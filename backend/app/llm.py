import asyncio
import json
import os
from collections.abc import AsyncIterator

import httpx2

# Short on purpose. Teaching behavior (ask before telling) is a later function.
SYSTEM_PROMPT = (
    "You are StudiousAI, a tutor. Answer the student directly, "
    "in plain language, in a short paragraph."
)

# This WSL instance has about 3.5 GB of RAM. Qwen3 1.7B Q4 fits.
# The 4B model does not, so it is not the default.
DEFAULT_OLLAMA_MODEL = "qwen3:1.7b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


class ModelUnavailable(Exception):
    """The language-model process did not answer."""


class FakeLanguageModel:
    """Streams a fixed reply. Tests use this so they never download a model."""

    def __init__(self, parts: list[str] | None = None):
        self.parts = parts if parts is not None else ["Alpha ", "Beta."]

    async def stream(self, text: str, cancel: asyncio.Event) -> AsyncIterator[str]:
        for part in self.parts:
            if cancel.is_set():
                return
            yield part


class HoldAfterFirstToken:
    """Yields one piece, then waits until cancel. Used to prove Stop works."""

    async def stream(self, text: str, cancel: asyncio.Event) -> AsyncIterator[str]:
        yield "Alpha "
        await cancel.wait()


def chat_payload(model: str, text: str) -> dict:
    return {
        "model": model,
        "stream": True,
        "think": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "options": {"num_ctx": 2048},
    }


class OllamaLanguageModel:
    """Streams tokens from a local Ollama server. The model stays replaceable."""

    def __init__(
        self,
        model: str = DEFAULT_OLLAMA_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def stream(self, text: str, cancel: asyncio.Event) -> AsyncIterator[str]:
        timeout = httpx2.Timeout(300.0, connect=3.0)
        try:
            async with httpx2.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=chat_payload(self.model, text),
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode(errors="replace")
                        raise ModelUnavailable(self._failure_text(detail))
                    async for line in response.aiter_lines():
                        if cancel.is_set():
                            return
                        piece = self._piece(line)
                        if piece:
                            yield piece
        except ModelUnavailable:
            raise
        except (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.TimeoutException):
            raise ModelUnavailable(
                f"The language model is not running. Start Ollama and load {self.model}."
            ) from None

    def _piece(self, line: str) -> str:
        if not line:
            return ""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return ""
        if data.get("error"):
            raise ModelUnavailable(self._failure_text(str(data["error"])))
        message = data.get("message") or {}
        content = message.get("content") or ""
        return content if isinstance(content, str) else ""

    def _failure_text(self, detail: str) -> str:
        lowered = detail.lower()
        if "not found" in lowered or "try pulling" in lowered:
            return (
                f"The model {self.model} is not downloaded. "
                f"Run: ollama pull {self.model}"
            )
        return f"The language model failed. Start Ollama and load {self.model}."


def build_model():
    """Fake when STUDIOUS_LLM=fake. Otherwise the local Ollama model."""
    if os.environ.get("STUDIOUS_LLM") == "fake":
        return FakeLanguageModel()
    return OllamaLanguageModel(
        model=os.environ.get("STUDIOUS_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        base_url=os.environ.get("STUDIOUS_OLLAMA_URL", DEFAULT_OLLAMA_URL),
    )

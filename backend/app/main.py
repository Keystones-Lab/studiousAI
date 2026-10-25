import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.llm import ModelUnavailable, build_model

# A study sentence, not a document. The window uses the same limit.
MAX_TEXT = 4000


class ClientGone(Exception):
    """The window closed while a reply was still streaming."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model = build_model()
    yield


app = FastAPI(title="StudiousAI", lifespan=lifespan)
app.state.model = build_model()

# Vite serves the React page on port 5173. This API listens on port 8000.
# A browser treats those as two different sites, so fetch is refused unless
# this server names the page's origin here. The WebSocket on /ws is a
# separate connection and does not use this list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


def classify(message: object) -> dict:
    """Decide what one client message is asking for.

    ping keeps the link alive. say starts a streamed reply. cancel stops
    the reply with that id. The server chooses every reply type.
    """
    if not isinstance(message, dict):
        return {"action": "error", "payload": {"type": "error", "text": "Expected an object."}}

    kind = message.get("type")
    if kind == "ping":
        return {
            "action": "pong",
            "payload": {"type": "pong", "sent_at": message.get("sent_at")},
        }

    if kind == "cancel":
        turn_id = message.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            return {"action": "error", "payload": {"type": "error", "text": "Missing id."}}
        return {"action": "cancel", "id": turn_id}

    if kind != "say":
        return {
            "action": "error",
            "payload": {"type": "error", "text": "Unknown message type."},
        }

    turn_id = message.get("id")
    if not isinstance(turn_id, str) or not turn_id:
        return {"action": "error", "payload": {"type": "error", "text": "Missing id."}}

    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return {
            "action": "error",
            "payload": {"type": "error", "id": turn_id, "text": "Say something first."},
        }

    text = text.strip()
    if len(text) > MAX_TEXT:
        return {
            "action": "error",
            "payload": {"type": "error", "id": turn_id, "text": "That message is too long."},
        }

    return {"action": "say", "id": turn_id, "text": text}


async def stream_reply(model, text: str, turn_id: str, cancel: asyncio.Event, closed: asyncio.Event, send, active: dict):
    status = "complete"
    try:
        async for piece in model.stream(text, cancel):
            if cancel.is_set() or closed.is_set():
                status = "cancelled"
                break
            if piece:
                await send({"type": "token", "id": turn_id, "text": piece})
        if cancel.is_set():
            status = "cancelled"
        if not closed.is_set():
            await send({"type": "done", "id": turn_id, "status": status})
    except ModelUnavailable as exc:
        if not closed.is_set():
            await send({"type": "error", "id": turn_id, "text": str(exc)})
            await send({"type": "done", "id": turn_id, "status": "error"})
    except ClientGone:
        return
    finally:
        if active.get(turn_id) is cancel:
            active.pop(turn_id, None)


@app.websocket("/ws")
async def websocket_session(websocket: WebSocket):
    """Read the window and stream a reply at the same time.

    A single receive loop cannot hear Stop while it is busy generating.
    Incoming messages go into a queue. The reply runs as its own task.
    """
    await websocket.accept()
    inbox: asyncio.Queue = asyncio.Queue()
    send_lock = asyncio.Lock()
    closed = asyncio.Event()
    active: dict[str, asyncio.Event] = {}
    tasks: set[asyncio.Task] = set()

    async def send(payload: dict):
        if closed.is_set():
            raise ClientGone()
        async with send_lock:
            if closed.is_set():
                raise ClientGone()
            try:
                await websocket.send_json(payload)
            except Exception as exc:
                closed.set()
                raise ClientGone() from exc

    async def reader():
        try:
            while True:
                await inbox.put(await websocket.receive_json())
        except Exception:
            await inbox.put(None)

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            message = await inbox.get()
            if message is None:
                break

            decision = classify(message)
            action = decision["action"]
            if action in {"pong", "error"}:
                await send(decision["payload"])
                continue

            if action == "cancel":
                event = active.get(decision["id"])
                if event is not None:
                    event.set()
                continue

            for event in active.values():
                event.set()
            cancel = asyncio.Event()
            active[decision["id"]] = cancel
            task = asyncio.create_task(
                stream_reply(
                    app.state.model,
                    decision["text"],
                    decision["id"],
                    cancel,
                    closed,
                    send,
                    active,
                )
            )
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    except ClientGone:
        return
    finally:
        closed.set()
        for event in active.values():
            event.set()
        reader_task.cancel()
        for task in tasks:
            task.cancel()

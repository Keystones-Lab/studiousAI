import { useEffect, useRef, useState } from "react";

const WS_URL = "ws://127.0.0.1:8000/ws";
const PING_MS = 1000;
const STALE_MS = 3000;
const MAX_TEXT = 4000;

export default function App() {
  const desktop = window.studious;
  const socketRef = useRef(null);
  const [status, setStatus] = useState("connecting");
  const [latency, setLatency] = useState(null);
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState([]);

  useEffect(() => {
    let cancelled = false;
    let socket = null;
    let pingTimer = null;
    let staleTimer = null;
    let reconnectTimer = null;

    function clearTimers() {
      clearInterval(pingTimer);
      clearTimeout(staleTimer);
      clearTimeout(reconnectTimer);
      pingTimer = null;
      staleTimer = null;
      reconnectTimer = null;
    }

    function markDisconnected() {
      setStatus("disconnected");
      setLatency(null);
      setTurns((current) =>
        current.map((turn) =>
          turn.role === "assistant" && turn.status === "streaming"
            ? { ...turn, status: "cancelled" }
            : turn,
        ),
      );
    }

    function armStaleTimer() {
      clearTimeout(staleTimer);
      staleTimer = setTimeout(() => {
        markDisconnected();
        if (socket && socket.readyState !== WebSocket.CLOSED) {
          socket.close();
        }
      }, STALE_MS);
    }

    function connect() {
      if (cancelled) {
        return;
      }

      socket = new WebSocket(WS_URL);
      socketRef.current = socket;

      socket.onopen = () => {
        if (cancelled) {
          return;
        }
        setStatus("connected");
        const sendPing = () => {
          if (!socket || socket.readyState !== WebSocket.OPEN) {
            return;
          }
          socket.send(JSON.stringify({ type: "ping", sent_at: Date.now() }));
        };
        sendPing();
        pingTimer = setInterval(sendPing, PING_MS);
        armStaleTimer();
      };

      socket.onmessage = (event) => {
        if (cancelled) {
          return;
        }
        let body;
        try {
          body = JSON.parse(event.data);
        } catch {
          return;
        }
        if (body.type === "pong" && typeof body.sent_at === "number") {
          setStatus("connected");
          setLatency(Date.now() - body.sent_at);
          armStaleTimer();
          return;
        }
        if (body.type === "token" && typeof body.id === "string" && typeof body.text === "string") {
          setTurns((current) =>
            current.map((turn) =>
              turn.role === "assistant" && turn.id === body.id
                ? { ...turn, text: turn.text + body.text, status: "streaming" }
                : turn,
            ),
          );
          return;
        }
        if (body.type === "done" && typeof body.id === "string") {
          const nextStatus =
            body.status === "cancelled" || body.status === "error" ? body.status : "complete";
          setTurns((current) =>
            current.map((turn) =>
              turn.role === "assistant" && turn.id === body.id
                ? { ...turn, status: nextStatus }
                : turn,
            ),
          );
          return;
        }
        if (body.type === "error" && typeof body.text === "string") {
          setTurns((current) => {
            if (typeof body.id === "string") {
              const index = current.findIndex(
                (turn) => turn.role === "assistant" && turn.id === body.id,
              );
              if (index !== -1) {
                return current.map((turn, i) =>
                  i === index
                    ? {
                        ...turn,
                        text: turn.text || body.text,
                        status: "error",
                      }
                    : turn,
                );
              }
            }
            return [
              ...current,
              {
                key: `error-${current.length}`,
                role: "error",
                text: body.text,
                status: "error",
              },
            ];
          });
        }
      };

      socket.onclose = () => {
        clearInterval(pingTimer);
        clearTimeout(staleTimer);
        pingTimer = null;
        staleTimer = null;
        if (socketRef.current === socket) {
          socketRef.current = null;
        }
        if (cancelled) {
          return;
        }
        markDisconnected();
        reconnectTimer = setTimeout(connect, 1000);
      };
    }

    connect();

    return () => {
      cancelled = true;
      clearTimers();
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        socket.close();
      }
    };
  }, []);

  function sendSentence(event) {
    event.preventDefault();
    const text = draft.trim();
    const socket = socketRef.current;
    if (!text || text.length > MAX_TEXT) {
      return;
    }
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    if (turns.some((turn) => turn.role === "assistant" && turn.status === "streaming")) {
      return;
    }

    const id = crypto.randomUUID();
    setTurns((current) => [
      ...current,
      { key: id, id, role: "you", text },
      { key: `${id}-reply`, id, role: "assistant", text: "", status: "streaming" },
    ]);
    socket.send(JSON.stringify({ type: "say", id, text }));
    setDraft("");
  }

  function stopReply() {
    const turn = turns.find((item) => item.role === "assistant" && item.status === "streaming");
    const socket = socketRef.current;
    if (!turn || !socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    socket.send(JSON.stringify({ type: "cancel", id: turn.id }));
  }

  const label =
    status === "connected"
      ? "Connected"
      : status === "connecting"
        ? "Connecting…"
        : "Disconnected";
  const streaming = turns.some((turn) => turn.role === "assistant" && turn.status === "streaming");
  const canSend = status === "connected" && draft.trim().length > 0 && !streaming;

  return (
    <main>
      <h1>StudiousAI</h1>
      <p className={`status ${status}`}>{label}</p>
      <p className="latency">{latency === null ? "—" : `${latency} ms`}</p>
      <p>
        {desktop
          ? `${desktop.appName} on ${desktop.platform} stays linked to the backend at ${WS_URL}.`
          : `This page stays linked to the backend at ${WS_URL}.`}{" "}
        Type a sentence and Send. The reply grows as words arrive. Stop cuts it off.
      </p>

      <ol className="transcript" aria-live="polite">
        {turns.map((turn) => (
          <li key={turn.key} className={`turn ${turn.role}`}>
            <span className="who">{who(turn)}</span>
            <span className="body">{bodyText(turn)}</span>
          </li>
        ))}
      </ol>

      <form className="composer" onSubmit={sendSentence}>
        <label className="visually-hidden" htmlFor="sentence">
          Sentence
        </label>
        <input
          id="sentence"
          value={draft}
          maxLength={MAX_TEXT}
          placeholder="Ask something"
          disabled={status !== "connected" || streaming}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={!canSend}>
          Send
        </button>
        {streaming ? (
          <button type="button" className="stop" onClick={stopReply}>
            Stop
          </button>
        ) : null}
      </form>
    </main>
  );
}

function who(turn) {
  if (turn.role === "you") {
    return "You";
  }
  if (turn.role === "error") {
    return "Error";
  }
  if (turn.status === "cancelled") {
    return "StudiousAI · stopped";
  }
  return "StudiousAI";
}

function bodyText(turn) {
  if (turn.text) {
    return turn.text;
  }
  if (turn.status === "streaming") {
    return "…";
  }
  if (turn.status === "cancelled") {
    return "Stopped before the first word.";
  }
  return "";
}

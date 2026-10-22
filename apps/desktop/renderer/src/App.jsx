import { useEffect, useState } from "react";

const API = "http://127.0.0.1:8000";

export default function App() {
  const desktop = window.studious;
  const [backend, setBackend] = useState("checking");

  useEffect(() => {
    let ignore = false;

    fetch(`${API}/health`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((body) => {
        if (!ignore) {
          setBackend(body.status === "ok" ? "connected" : "offline");
        }
      })
      .catch(() => {
        if (!ignore) {
          setBackend("offline");
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  const status =
    backend === "checking"
      ? "Checking the backend…"
      : backend === "connected"
        ? "Connected"
        : "Not connected";

  return (
    <main>
      <h1>StudiousAI</h1>
      <p className={backend === "connected" ? "status connected" : "status"}>
        {status}
      </p>
      <p>
        {desktop
          ? `${desktop.appName} is running on ${desktop.platform}. This screen is React. It calls ${API}/health, and that route runs in Ubuntu.`
          : `This screen is React. It calls ${API}/health when Electron opens the window.`}
      </p>
    </main>
  );
}

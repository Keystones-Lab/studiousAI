export default function App() {
  const desktop = window.studious;

  return (
    <main>
      <h1>StudiousAI</h1>
      <p>
        {desktop
          ? `${desktop.appName} is running on ${desktop.platform}. This screen is React. Electron opened the window, and the preload bridge passed the platform in.`
          : "This screen is React. Electron supplies the preload bridge when it opens the window."}
      </p>
    </main>
  );
}

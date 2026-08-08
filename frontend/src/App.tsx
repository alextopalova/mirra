import { useSession } from "./state/session";
import { StartScreen } from "./screens/StartScreen";
import { CaptureScreen } from "./screens/CaptureScreen";
// Screen imports are added here as each screen is built (see Task 1.4+).

export default function App() {
  const { screen } = useSession();
  switch (screen) {
    case "start": return <StartScreen />;
    case "capture": return <CaptureScreen />;
    default: return <div style={{ padding: 40 }}>TODO: {screen}</div>;
  }
}

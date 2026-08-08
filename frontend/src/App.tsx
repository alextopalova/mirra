import { useSession } from "./state/session";
import { StartScreen } from "./screens/StartScreen";
import { CaptureScreen } from "./screens/CaptureScreen";
import { MeasurementsScreen } from "./screens/MeasurementsScreen";
import { AnalyzingScreen } from "./screens/AnalyzingScreen";
import { ReportScreen } from "./screens/ReportScreen";
import { ShopScreen } from "./screens/ShopScreen";
// Screen imports are added here as each screen is built (see Task 1.4+).

export default function App() {
  const { screen } = useSession();
  switch (screen) {
    case "start": return <StartScreen />;
    case "capture": return <CaptureScreen />;
    case "measurements": return <MeasurementsScreen />;
    case "analyzing": return <AnalyzingScreen />;
    case "report": return <ReportScreen />;
    case "shop": return <ShopScreen />;
    default: return <div style={{ padding: 40 }}>TODO: {screen}</div>;
  }
}

import { useEffect, useRef } from "react";
import { useSession } from "./state/session";
import type { Screen } from "./api/types";
import { StartScreen } from "./screens/StartScreen";
import { CaptureScreen } from "./screens/CaptureScreen";
import { MeasurementsScreen } from "./screens/MeasurementsScreen";
import { AnalyzingScreen } from "./screens/AnalyzingScreen";
import { ReportScreen } from "./screens/ReportScreen";
import { ShopScreen } from "./screens/ShopScreen";
import { TryOnScreen } from "./screens/TryOnScreen";
import { GetItScreen } from "./screens/GetItScreen";
import { StartOverButton } from "./components/StartOverButton";
// Screen imports are added here as each screen is built (see Task 1.4+).

// Kiosk hygiene: with nobody touching it, an unattended screen should hand
// itself back to the walk-up state for the next shopper rather than sit on
// someone's half-finished session.
const IDLE_RESET_MS = 90_000;

// Screens where the idle timer must never fire:
// - "start" is already the reset target, so a timer there is meaningless.
// - "analyzing" / "tryon" legitimately sit still for tens of seconds while a
//   long async API call runs. Auto-resetting mid-generation would kill the
//   in-flight request and be a bad demo failure, even though there's no input.
const IDLE_RESET_EXCLUDED: ReadonlySet<Screen> = new Set(["start", "analyzing", "tryon"]);

/** Resets the session after IDLE_RESET_MS of no genuine pointer/touch/key activity. */
function useIdleReset(screen: Screen, reset: () => void) {
  // `reset` is a plain closure from context (not memoized), so it gets a new
  // identity on every session render. Route it through a ref instead of a
  // dependency so unrelated re-renders can't restart the timer — only an
  // actual screen change or a real interaction event may do that.
  const resetRef = useRef(reset);
  resetRef.current = reset;

  useEffect(() => {
    if (IDLE_RESET_EXCLUDED.has(screen)) return;

    let timer: ReturnType<typeof setTimeout>;
    const restart = () => {
      clearTimeout(timer);
      timer = setTimeout(() => resetRef.current(), IDLE_RESET_MS);
    };
    restart();

    const events = ["pointerdown", "touchstart", "keydown"] as const;
    events.forEach((e) => window.addEventListener(e, restart));

    return () => {
      clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, restart));
    };
  }, [screen]);
}

export default function App() {
  const { screen, reset } = useSession();
  useIdleReset(screen, reset);

  return (
    <>
      <StartOverButton />
      {(() => {
        switch (screen) {
          case "start": return <StartScreen />;
          case "capture": return <CaptureScreen />;
          case "measurements": return <MeasurementsScreen />;
          case "analyzing": return <AnalyzingScreen />;
          case "report": return <ReportScreen />;
          case "shop": return <ShopScreen />;
          case "tryon": return <TryOnScreen />;
          case "getit": return <GetItScreen />;
          default: return <div style={{ padding: 40 }}>TODO: {screen}</div>;
        }
      })()}
    </>
  );
}

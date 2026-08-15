import { useSession } from "../state/session";
import { House } from "lucide-react";
import "./StartOverButton.css";

/**
 * Discreet kiosk affordance shown on every screen except "start" so a shopper
 * (or a store associate) can bail out back to the walk-up screen at any time.
 * Deliberately small/quiet — must never compete with a screen's primary CTA.
 */
export function StartOverButton() {
  const { screen, reset } = useSession();
  if (screen === "start") return null;
  return (
    <button className="start-over-btn" onClick={reset} aria-label="Start over">
      <House size={24} />
    </button>
  );
}

import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import "./screen.css";

export function StartScreen() {
  const { go } = useSession();
  return (
    <div className="screen">
      <h1>Mirra</h1>
      <p>Your personal color, your body type, your perfect fit — in one scan.</p>
      <PrimaryButton label="Start your style scan" onClick={() => go("capture")} />
    </div>
  );
}

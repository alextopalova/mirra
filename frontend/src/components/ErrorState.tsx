import "../screens/screen.css";
import "./ErrorState.css";
import { PrimaryButton } from "./PrimaryButton";

export function ErrorState({ message, onRetry, onStartOver }: {
  message: string; onRetry: () => void; onStartOver: () => void;
}) {
  return (
    <div className="screen">
      <h2 className="error-state-heading">Something went wrong</h2>
      <p className="error-state-message">{message}</p>
      <div style={{ display: "flex", gap: 16 }}>
        <PrimaryButton label="Try again" onClick={onRetry} />
        <PrimaryButton label="Start over" variant="ghost" onClick={onStartOver} />
      </div>
    </div>
  );
}

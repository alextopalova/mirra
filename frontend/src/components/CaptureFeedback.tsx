import "./CaptureFeedback.css";

export type CaptureFeedbackKind = "success" | "turn";

/**
 * Large, from-a-distance overlay shown over the capture stage:
 *  - "success": a big green checkmark confirming a photo was captured.
 *  - "turn": a big rotation arrow + "Turn to your side" prompt, shown
 *    between the front and side captures.
 * Purely presentational — CaptureScreen owns all timing/state.
 */
export function CaptureFeedback({ kind, exiting }: { kind: CaptureFeedbackKind; exiting: boolean }) {
  return (
    <div
      className={`capture-feedback capture-feedback--${kind}${exiting ? " capture-feedback--exiting" : ""}`}
      aria-live="polite"
    >
      {kind === "success" ? (
        <>
          <svg className="capture-feedback-icon capture-feedback-check" viewBox="0 0 100 100" aria-hidden="true">
            <circle className="capture-feedback-ring" cx="50" cy="50" r="44" />
            <path className="capture-feedback-tick" d="M27 52 L43 68 L75 32" />
          </svg>
          <span className="capture-feedback-sr-only">Photo captured</span>
        </>
      ) : (
        <>
          <svg className="capture-feedback-icon capture-feedback-arrow" viewBox="0 0 100 100" aria-hidden="true">
            <path className="capture-feedback-arc" d="M 19.93,39.06 A 32 32 0 0 1 77.71,34.00" />
            <polygon className="capture-feedback-arrowhead" points="83.91,45.65 65.63,30.46 81.53,22.00" />
          </svg>
          <p className="capture-feedback-text">Turn to your side</p>
        </>
      )}
    </div>
  );
}

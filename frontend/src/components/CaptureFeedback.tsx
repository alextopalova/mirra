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
            {/* Mirrored on this inner group rather than on the <svg>: the
                element above already carries the nudge animation, and an
                animated transform replaces any transform set alongside it
                — the flip would simply be dropped every frame. */}
            <g className="capture-feedback-arrow-mirror">
              <path className="capture-feedback-arc" d="M 66.00,22.29 A 32,32 0 1 1 22.29,34.00" />
              <polygon className="capture-feedback-arrowhead" points="30.29,20.14 27.08,43.70 11.49,34.70" />
            </g>
          </svg>
          <p className="capture-feedback-text">Turn to your side</p>
        </>
      )}
    </div>
  );
}

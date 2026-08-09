import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { PoseGuide, type GuideState } from "../components/PoseGuide";
import { CaptureFeedback, type CaptureFeedbackKind } from "../components/CaptureFeedback";
import { DirectionArrow } from "../components/DirectionArrow";
import { Spinner } from "../components/Spinner";
import { useAutoCapture } from "../lib/useAutoCapture";
import { MIRROR_PREVIEW } from "../lib/poseFit";
import "./capture.css";
import "./screen.css";

// Hold times for the big distance-legible overlays: long enough to read and
// react to from several metres away, short enough to keep the flow moving.
const SUCCESS_HOLD_MS = 900;
const TURN_HOLD_MS = 2200;
const FEEDBACK_EXIT_MS = 220; // must match the CSS exit transition duration

export function CaptureScreen() {
  const { go, update } = useSession();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [step, setStep] = useState<"front" | "side">("front");
  const [count, setCount] = useState<number | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  // Bumped by the restart-scan button to genuinely re-request the camera
  // (not just hide the error) when that's what failed.
  const [cameraAttempt, setCameraAttempt] = useState(0);
  // Matches the live camera's own real aspect ratio once known. This only
  // sizes the INNER `.capture-video-area` (the letterboxed video rect) — the
  // outer `.capture-stage` footprint is fixed from the viewport alone (see
  // capture.css) and never depends on this, so swapping the guess for the
  // camera's true ratio never moves or resizes the stage itself, only how
  // much of it the video fills. Feeds the CSS `aspect-ratio` property
  // (w/h syntax) directly.
  const [stageAspect, setStageAspect] = useState("3 / 4");
  // True once the current stream's real dimensions are known (i.e.
  // onLoadedMetadata has fired) — drives the "Starting camera…" placeholder
  // shown inside the reserved stage while the camera spins up, so that
  // space reads as occupied rather than collapsing. Reset whenever a fresh
  // stream is requested (restart-scan bumps cameraAttempt).
  const [cameraReady, setCameraReady] = useState(false);
  const timerRef = useRef<number | null>(null);

  // Big "photo captured" / "turn to your side" overlays shown between
  // steps. `feedback` drives which one (if any) is on screen; `exiting`
  // triggers its fade-out just before the next phase begins.
  const [feedback, setFeedback] = useState<CaptureFeedbackKind | null>(null);
  const [feedbackExiting, setFeedbackExiting] = useState(false);
  const feedbackTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  // Torn down on unmount independently of the countdown timer above — this
  // is a chain of setTimeouts (hold, then exit-fade, then advance), not the
  // countdown interval, so it needs its own cleanup.
  useEffect(() => {
    return () => {
      if (feedbackTimerRef.current !== null) {
        window.clearTimeout(feedbackTimerRef.current);
        feedbackTimerRef.current = null;
      }
    };
  }, []);

  // Shows `kind` for `holdMs`, fades it out, then runs `after`. Fixed-length
  // and never waits on pose detection, so it can never deadlock the flow —
  // it always resolves and hands off to `after` (e.g. flipping to the side
  // step, which restarts the auto-capture hook's own 15s manual fallback).
  const showFeedback = (kind: CaptureFeedbackKind, holdMs: number, after: () => void) => {
    setFeedback(kind);
    setFeedbackExiting(false);
    feedbackTimerRef.current = window.setTimeout(() => {
      setFeedbackExiting(true);
      feedbackTimerRef.current = window.setTimeout(() => {
        setFeedback(null);
        setFeedbackExiting(false);
        feedbackTimerRef.current = null;
        after();
      }, FEEDBACK_EXIT_MS);
    }, holdMs);
  };

  useEffect(() => {
    let cancelled = false;
    let stream: MediaStream | undefined;
    setCameraReady(false);
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 1280 } } })
      .then((s) => {
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        if (videoRef.current) videoRef.current.srcObject = s;
      })
      .catch(() => {
        if (!cancelled) setCameraError("Camera access is unavailable. Please allow camera permission and reload.");
      });
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [cameraAttempt]);

  const handleLoadedMetadata = () => {
    const v = videoRef.current;
    if (v && v.videoWidth && v.videoHeight) {
      setStageAspect(`${v.videoWidth} / ${v.videoHeight}`);
    }
    setCameraReady(true);
  };

  const snap = (): string => {
    const v = videoRef.current!;
    const c = document.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    const ctx = c.getContext("2d")!;
    if (MIRROR_PREVIEW) {
      // The preview is shown mirrored — flip the canvas draw to match, so
      // the stored photo is what the shopper actually saw, not its opposite.
      ctx.translate(c.width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(v, 0, 0);
    return c.toDataURL("image/jpeg", 0.9);
  };

  const runCountdown = (after: () => void) => {
    if (timerRef.current !== null) return;
    let n = 3; setCount(n);
    const id = window.setInterval(() => {
      n -= 1;
      if (n === 0) {
        window.clearInterval(id);
        timerRef.current = null;
        setCount(null);
        after();
      } else setCount(n);
    }, 700);
    timerRef.current = id;
  };

  // Fires only from the auto-capture hook's onFit callback below — there is
  // no button that calls this. The guard protects against the hook somehow
  // signalling fit twice in a row (e.g. across a fast step transition).
  const capture = () => {
    if (timerRef.current !== null) return;
    runCountdown(() => {
      const img = snap();
      if (step === "front") {
        update({ frontPhoto: img });
        // Big checkmark, then a big "turn around" prompt, then the side
        // step begins — all from a fixed timer, never gated on detection.
        showFeedback("success", SUCCESS_HOLD_MS, () => {
          showFeedback("turn", TURN_HOLD_MS, () => setStep("side"));
        });
      } else {
        update({ sidePhoto: img });
        showFeedback("success", SUCCESS_HOLD_MS, () => go("measurements"));
      }
    });
  };

  // Pause detection during the countdown/step transition and while a
  // feedback overlay is on screen; the hook resets its stable-frame counter
  // and fallback timer whenever `step` changes (i.e. once the turn prompt
  // hands off to the side step).
  const autoActive = !cameraError && count === null && feedback === null;
  const auto = useAutoCapture(videoRef, autoActive, step, capture);

  let guideState: GuideState = "idle";
  if (!cameraError && feedback === null) {
    guideState = count !== null ? "fit" : auto.phase === "loading" ? "idle" : auto.fitStatus;
  }

  // The large movement arrow only makes sense while we're actively steering
  // the shopper toward a fit — not mid-countdown, mid-feedback overlay, or
  // once things have failed outright.
  const direction = !cameraError && feedback === null && count === null ? auto.direction : null;

  // There is no manual-capture path any more — this is purely a "something
  // genuinely failed, redo the auto-capture" affordance: camera denied,
  // pose detection failed to load, or no fit reached within the hook's
  // fallback window. The kiosk must never dead-end, so it's always reachable
  // (on top of the camera window) whenever one of those is true.
  const needsRestart = !!cameraError || auto.needsRestart;

  // Space inside the stage reads as occupied (not collapsed/blank) while the
  // camera is still starting. Suppressed once something has genuinely
  // failed — the restart overlay takes over that job then.
  const showCameraLoading = !cameraError && !cameraReady && !needsRestart;

  // Distinguish *why* the restart affordance is showing, since the remedy
  // differs: a blocked camera needs an OS/browser permission change, a
  // failed model load just needs a retry, and a no-fit timeout needs the
  // shopper to reposition. `auto.phase === "unavailable"` is set only when
  // the pose model itself failed to load (see useAutoCapture); any other
  // `needsRestart` cause is the no-fit fallback timeout.
  const restartTitle = cameraError
    ? "Camera blocked"
    : auto.phase === "unavailable"
    ? "Styling guide couldn't load"
    : "Couldn't get a clear view of you";
  const restartDetail =
    cameraError ??
    (auto.phase === "unavailable"
      ? "Restart the scan to try loading it again."
      : "Stand back so your whole body is visible, then restart the scan.");

  // Genuinely re-attempts detection, not just hiding the fallback UI: resets
  // the fit/stability state and fallback timer, re-initialises the pose
  // detector if that's what failed (see useAutoCapture's restart), and
  // re-requests the camera if that's what failed.
  const restartScan = () => {
    if (cameraError) {
      setCameraError(null);
      setCameraAttempt((n) => n + 1);
    } else {
      auto.restart();
    }
  };

  const heading =
    feedback === "success" ? "Captured!" :
    feedback === "turn" ? "Turn to your side" :
    step === "front" ? "Face the camera" : "Turn to your side";

  return (
    <div className="screen">
      <h2 className="capture-heading">{heading}</h2>
      <div className="capture-stage">
        {/* The camera's real aspect ratio only ever resizes THIS inner box,
            centred and letterboxed within the outer stage — the stage's own
            footprint (capture.css) is fixed from the viewport alone, so this
            never shifts or resizes the page around it. */}
        <div
          className="capture-video-area"
          style={{ "--capture-aspect": stageAspect } as CSSProperties}
        >
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            onLoadedMetadata={handleLoadedMetadata}
            className={MIRROR_PREVIEW ? "mirrored" : ""}
          />
          <PoseGuide variant={step} state={guideState} />
          <DirectionArrow direction={direction} />
        </div>
        {showCameraLoading && (
          <div className="capture-loading-overlay">
            <Spinner label="Starting camera…" />
          </div>
        )}
        {count !== null && <div className="capture-countdown">{count}</div>}
        {feedback !== null && <CaptureFeedback kind={feedback} exiting={feedbackExiting} />}
        {needsRestart && feedback === null && (
          <div className="capture-restart-overlay">
            <p className="capture-restart-title">{restartTitle}</p>
            <p className="capture-restart-message">{restartDetail}</p>
            <PrimaryButton label="Restart scan" variant="danger" onClick={restartScan} />
          </div>
        )}
      </div>
      {feedback === null && !needsRestart ? (
        <p className={`capture-hint${auto.fitStatus === "fit" ? " capture-hint-fit" : ""}`}>
          {count !== null ? "Hold still" : auto.hint}
        </p>
      ) : null}
    </div>
  );
}

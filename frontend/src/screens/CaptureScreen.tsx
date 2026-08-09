import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { PoseGuide, type GuideState } from "../components/PoseGuide";
import { useAutoCapture } from "../lib/useAutoCapture";
import { MIRROR_PREVIEW } from "../lib/poseFit";
import "./capture.css";
import "./screen.css";

export function CaptureScreen() {
  const { go, update } = useSession();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [step, setStep] = useState<"front" | "side">("front");
  const [count, setCount] = useState<number | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  // Matches the live camera's own aspect ratio once known, so the stage
  // isn't a mismatched tall box the shopper has to retreat far to fill.
  const [stageAspect, setStageAspect] = useState("3 / 4");
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let stream: MediaStream | undefined;
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
  }, []);

  const handleLoadedMetadata = () => {
    const v = videoRef.current;
    if (v && v.videoWidth && v.videoHeight) setStageAspect(`${v.videoWidth} / ${v.videoHeight}`);
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

  const capture = () => {
    if (timerRef.current !== null) return; // guards against double-fire (auto + manual, or double tap)
    runCountdown(() => {
      const img = snap();
      if (step === "front") { update({ frontPhoto: img }); setStep("side"); }
      else { update({ sidePhoto: img }); go("measurements"); }
    });
  };

  // Pause detection during the countdown/step transition; the hook resets
  // its stable-frame counter and fallback timer whenever `step` changes.
  const autoActive = !cameraError && count === null;
  const auto = useAutoCapture(videoRef, autoActive, step, capture);

  let guideState: GuideState = "idle";
  if (!cameraError) {
    guideState = count !== null ? "fit" : auto.phase === "loading" ? "idle" : auto.fitStatus;
  }

  // Manual capture is the safety net, not the default UI — it only appears
  // if the camera is denied, pose detection fails to load, or no fit is
  // reached within the hook's fallback window. The kiosk must never dead-end.
  const showManualButton = !!cameraError || auto.showManualFallback;

  return (
    <div className="screen">
      <h2>{step === "front" ? "Face the camera" : "Turn to your side"}</h2>
      <div className="capture-stage" style={{ "--capture-aspect": stageAspect } as CSSProperties}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          onLoadedMetadata={handleLoadedMetadata}
          className={MIRROR_PREVIEW ? "mirrored" : ""}
        />
        <PoseGuide variant={step} state={guideState} />
        {count !== null && <div className="capture-countdown">{count}</div>}
      </div>
      {cameraError ? (
        <p className="capture-hint capture-error">{cameraError}</p>
      ) : (
        <p className={`capture-hint${auto.fitStatus === "fit" ? " capture-hint-fit" : ""}`}>
          {count !== null ? "Hold still" : auto.hint}
        </p>
      )}
      <div className="actions">
        {showManualButton && (
          <PrimaryButton
            label={step === "front" ? "Capture front" : "Capture side"}
            onClick={capture}
            disabled={!!cameraError || count !== null}
          />
        )}
        {step === "side" && (
          <PrimaryButton label="Skip side" variant="ghost" onClick={() => go("measurements")} />
        )}
      </div>
    </div>
  );
}

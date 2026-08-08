import { useEffect, useRef, useState } from "react";
import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { PoseGuide } from "../components/PoseGuide";
import "./capture.css";
import "./screen.css";

export function CaptureScreen() {
  const { go, update } = useSession();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [step, setStep] = useState<"front" | "side">("front");
  const [count, setCount] = useState<number | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
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
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } }).then((s) => {
      if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
      stream = s;
      if (videoRef.current) videoRef.current.srcObject = s;
    }).catch(() => {
      if (!cancelled) setCameraError("Camera access is unavailable. Please allow camera permission and reload.");
    });
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const snap = (): string => {
    const v = videoRef.current!;
    const c = document.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
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
    if (timerRef.current !== null) return;
    runCountdown(() => {
      const img = snap();
      if (step === "front") { update({ frontPhoto: img }); setStep("side"); }
      else { update({ sidePhoto: img }); go("measurements"); }
    });
  };

  return (
    <div className="screen">
      <h2>{step === "front" ? "Face the camera" : "Turn to your side"}</h2>
      <div className="capture-stage">
        <video ref={videoRef} autoPlay playsInline muted />
        <PoseGuide variant={step} />
        {count !== null && <div className="capture-countdown">{count}</div>}
      </div>
      {cameraError ? (
        <p className="capture-hint capture-error">{cameraError}</p>
      ) : (
        <p className="capture-hint">Stand so your whole body fits the outline.</p>
      )}
      <div style={{ display: "flex", gap: 16 }}>
        <PrimaryButton label={step === "front" ? "Capture front" : "Capture side"} onClick={capture} disabled={!!cameraError || count !== null} />
        {step === "side" && (
          <PrimaryButton label="Skip side" variant="ghost" onClick={() => go("measurements")} />
        )}
      </div>
    </div>
  );
}

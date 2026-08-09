import { useEffect, useRef, useState, type RefObject } from "react";
import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";
import { evaluateFit, MIRROR_PREVIEW, type FitDirection, type FitStatus } from "./poseFit";

// Google's official model CDN — lite model, loaded at runtime (never bundled).
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";
// Matching WASM fileset for the installed @mediapipe/tasks-vision version
// (kept in lockstep with the "dependencies" entry in package.json).
const WASM_BASE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm";

const SAMPLE_INTERVAL_MS = 130; // ~7-8 fps sampling of the live preview
const STABLE_FRAMES_NEEDED = 6; // ~0.8s of consistently good framing before firing
const FALLBACK_TIMEOUT_MS = 15000; // never leave the kiosk stuck

export type AutoCapturePhase = "loading" | "tracking" | "unavailable";

export interface AutoCaptureState {
  phase: AutoCapturePhase;
  fitStatus: FitStatus;
  hint: string;
  direction: FitDirection;
  /** True once genuine detection has failed: model load error, or the
   * no-fit fallback timeout elapsed. Drives the "restart scan" affordance —
   * never a manual-capture button (there is no such path any more). */
  needsRestart: boolean;
  /** Re-attempts detection from scratch: resets the fit/stability state and
   * the fallback timer, and — if the model previously failed to load —
   * re-initialises the pose detector. Does not touch the camera stream;
   * that's the caller's responsibility if the camera itself is what failed. */
  restart: () => void;
}

const INITIAL_STATE: Omit<AutoCaptureState, "restart"> = {
  phase: "loading",
  fitStatus: "searching",
  hint: "Loading camera guide…",
  direction: null,
  needsRestart: false,
};

// Module-level singleton: the (multi-MB, CDN-fetched) model is loaded once
// and reused across the front/side steps instead of being re-fetched.
let landmarkerPromise: Promise<PoseLandmarker> | null = null;
function getLandmarker(): Promise<PoseLandmarker> {
  if (!landmarkerPromise) {
    landmarkerPromise = FilesetResolver.forVisionTasks(WASM_BASE).then((fileset) =>
      PoseLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
        runningMode: "VIDEO",
        numPoses: 1,
      })
    );
  }
  return landmarkerPromise;
}

/**
 * Runs mediapipe pose detection on the live preview and reports whether the
 * shopper fits the guide, for how the CaptureScreen should react — this
 * hook never sends landmarks anywhere, it's purely local framing guidance.
 */
export function useAutoCapture(
  videoRef: RefObject<HTMLVideoElement | null>,
  enabled: boolean,
  step: "front" | "side",
  onFit: () => void
): AutoCaptureState {
  const [state, setState] = useState<Omit<AutoCaptureState, "restart">>(INITIAL_STATE);
  const onFitRef = useRef(onFit);
  onFitRef.current = onFit;

  // Bumped by `restart()` to force the detection effect below to re-run even
  // when `enabled`/`step` haven't changed — e.g. the "restart scan" button
  // after a no-fit timeout or a failed model load.
  const [resetToken, setResetToken] = useState(0);
  const restart = () => setResetToken((n) => n + 1);

  // Detection loop: (re)started whenever enabled/step/resetToken changes,
  // torn down on cleanup. Does not touch the shared landmarker singleton's
  // lifecycle (that's the effect below), beyond clearing it on load failure
  // so a subsequent restart re-fetches instead of replaying the same error.
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let rafId: number | null = null;
    let lastSampleAt = 0;
    let consecutiveGood = 0;
    let fired = false;

    setState({ ...INITIAL_STATE });

    const fallbackTimer = window.setTimeout(() => {
      if (!cancelled) setState((s) => ({ ...s, needsRestart: true }));
    }, FALLBACK_TIMEOUT_MS);

    getLandmarker()
      .then((landmarker) => {
        if (cancelled) return;
        setState((s) => ({ ...s, phase: "tracking" }));

        const loop = (now: number) => {
          if (cancelled) return;
          const video = videoRef.current;
          if (video && video.readyState >= 2 && now - lastSampleAt >= SAMPLE_INTERVAL_MS) {
            lastSampleAt = now;
            const result = landmarker.detectForVideo(video, now);
            const landmarks = result.landmarks?.[0];
            const fit = evaluateFit(landmarks, MIRROR_PREVIEW);
            consecutiveGood = fit.status === "fit" ? consecutiveGood + 1 : 0;
            setState((s) => ({ ...s, fitStatus: fit.status, hint: fit.hint, direction: fit.direction }));
            if (consecutiveGood >= STABLE_FRAMES_NEEDED && !fired) {
              fired = true;
              onFitRef.current();
            }
          }
          rafId = requestAnimationFrame(loop);
        };
        rafId = requestAnimationFrame(loop);
      })
      .catch(() => {
        // Clear the cached (rejected) singleton promise so a later restart()
        // actually retries the fetch instead of replaying this same failure.
        landmarkerPromise = null;
        if (!cancelled) {
          setState({
            phase: "unavailable",
            fitStatus: "searching",
            hint: "Auto-capture couldn't start.",
            direction: null,
            needsRestart: true,
          });
        }
      });

    return () => {
      cancelled = true;
      window.clearTimeout(fallbackTimer);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [enabled, step, videoRef, resetToken]);

  // Final teardown of the shared detector — only on the CaptureScreen
  // unmounting entirely, not on every front/side step change.
  useEffect(() => {
    return () => {
      const promise = landmarkerPromise;
      landmarkerPromise = null;
      promise?.then((lm) => lm.close()).catch(() => {});
    };
  }, []);

  return { ...state, restart };
}

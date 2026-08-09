import { useEffect, useState } from "react";
import { useSession } from "../state/session";
import { analyzeBody, ApiError } from "../api/client";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import "./screen.css";

const GENERIC_ERROR = "We couldn't complete your scan.";

export function AnalyzingScreen() {
  const { data, update, go, reset } = useSession();
  const [error, setError] = useState<string | null>(null);
  // A 422 means the photo itself is the problem (e.g. "step back so your
  // shoulders, hips, and ankles are all in frame") -- retrying with the
  // identical photo would just fail the same way, so that case must send
  // the shopper back to retake it rather than re-POST.
  const [isPhotoIssue, setIsPhotoIssue] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    analyzeBody({
      frontPhoto: data.frontPhoto!, sidePhoto: data.sidePhoto,
      heightCm: data.heightCm!, weightKg: data.weightKg!,
    }).then(({ profile, palette }) => {
      if (cancelled) return;
      update({ profile, palette });
      go("report");
    }).catch((err: unknown) => {
      if (cancelled) return;
      if (err instanceof ApiError) {
        setError(err.detail || GENERIC_ERROR);
        setIsPhotoIssue(err.status === 422);
      } else {
        setError(GENERIC_ERROR);
        setIsPhotoIssue(false);
      }
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rerun only on explicit retry (attempt), not on every data/update/go identity change
  }, [attempt]);

  if (error) {
    return (
      <ErrorState
        message={error}
        retryLabel={isPhotoIssue ? "Retake photo" : "Try again"}
        onRetry={() => {
          if (isPhotoIssue) { go("capture"); return; }
          setError(null);
          setAttempt((a) => a + 1);
        }}
        onStartOver={reset}
      />
    );
  }

  return (
    <div className="screen">
      <Spinner label="Reading your colors and frame…" />
    </div>
  );
}

import { useEffect, useState } from "react";
import { useSession } from "../state/session";
import { analyzeBody } from "../api/client";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";

export function AnalyzingScreen() {
  const { data, update, go, reset } = useSession();
  const [error, setError] = useState<string | null>(null);
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
    }).catch(() => {
      if (cancelled) return;
      setError("We couldn't complete your scan.");
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rerun only on explicit retry (attempt), not on every data/update/go identity change
  }, [attempt]);

  if (error) {
    return (
      <ErrorState
        message={error}
        onRetry={() => { setError(null); setAttempt((a) => a + 1); }}
        onStartOver={reset}
      />
    );
  }

  return <Spinner label="Reading your colors and frame…" />;
}

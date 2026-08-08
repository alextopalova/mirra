import { useEffect, useState } from "react";
import { useSession } from "../state/session";
import { tryOn } from "../api/client";
import { PrimaryButton } from "../components/PrimaryButton";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import "./tryon.css";
import "./screen.css";

export function TryOnScreen() {
  const { data, go, reset } = useSession();
  const [img, setImg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setImg(null);
    setError(null);
    tryOn({ personPhoto: data.frontPhoto!, garmentId: data.selectedId! })
      .then((r) => {
        if (cancelled) return;
        setImg(r.image);
      })
      .catch(() => {
        if (cancelled) return;
        setError("We couldn't render your try-on.");
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rerun on selectedId or explicit retry, not on every data/go/reset identity change
  }, [data.selectedId, attempt]);

  if (error) {
    return (
      <ErrorState
        message={error}
        onRetry={() => setAttempt((a) => a + 1)}
        onStartOver={reset}
      />
    );
  }

  if (!img) return (
    <div className="screen">
      <Spinner label="Dressing you…" />
    </div>
  );

  return (
    <div className="screen">
      <h2>Here's you in it</h2>
      <img src={img} alt="Virtual try-on" className="tryon-image" />
      <div className="actions">
        <PrimaryButton label="Get it →" onClick={() => go("getit")} />
        <PrimaryButton label="Try another" variant="ghost" onClick={() => go("shop")} />
      </div>
    </div>
  );
}

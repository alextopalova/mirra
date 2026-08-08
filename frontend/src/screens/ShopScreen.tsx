import { useEffect, useState } from "react";
import { useSession } from "../state/session";
import { recommend } from "../api/client";
import { GarmentCard } from "../components/GarmentCard";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import type { Recommendation } from "../api/types";
import "./shop.css";
import "./screen.css";

const CATS = ["dress", "top", "pants"];
const OCCASIONS = ["everyday", "work", "date night", "wedding guest"];

export function ShopScreen() {
  const { data, update, go, reset } = useSession();
  const [category, setCategory] = useState("dress");
  const [occasion, setOccasion] = useState("everyday");
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    recommend({ profile: data.profile!, palette: data.palette!, category, occasion })
      .then((r) => {
        if (cancelled) return;
        setRecs(r);
        update({ recommendations: r });
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError("We couldn't load your matches.");
        setLoading(false);
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rerun on category/occasion/attempt, not on every data/update identity change
  }, [category, occasion, attempt]);

  if (error) {
    return (
      <ErrorState
        message={error}
        onRetry={() => setAttempt((a) => a + 1)}
        onStartOver={reset}
      />
    );
  }

  if (loading) return <Spinner label="Finding your matches…" />;

  return (
    <div className="screen">
      <h2>Your matches</h2>
      <div className="chips">
        {CATS.map((c) => (
          <button key={c} className={`chip ${c === category ? "active" : ""}`}
            onClick={() => setCategory(c)}>{c}</button>
        ))}
      </div>
      <div className="chips">
        {OCCASIONS.map((o) => (
          <button key={o} className={`chip ${o === occasion ? "active" : ""}`}
            onClick={() => setOccasion(o)}>{o}</button>
        ))}
      </div>
      <div className="grid">
        {recs.map((r) => (
          <GarmentCard key={r.garment.id} rec={r}
            onClick={() => { update({ selectedId: r.garment.id, category, occasion }); go("tryon"); }} />
        ))}
      </div>
    </div>
  );
}

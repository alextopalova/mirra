import { useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useSession } from "../state/session";
import { recommend, tryOn, ApiError } from "../api/client";
import { GarmentCard } from "../components/GarmentCard";
import { PrimaryButton } from "../components/PrimaryButton";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import type { Recommendation } from "../api/types";
import "./fitting.css";
import "./screen.css";

const CATEGORIES = [
  { key: "dress", label: "Dresses" },
  { key: "top", label: "Tops" },
  { key: "pants", label: "Trousers" },
];
const OCCASIONS = ["everyday", "work", "date night", "wedding guest"];


const TRY_ON_ERROR = "We couldn't render that try-on.";

/**
 * Browsing the rack and seeing a piece on yourself, on one screen.
 *
 * These used to be two screens, which meant every garment cost a
 * navigation, a re-fetch of the whole rack, and a trip back. Here the rack
 * and the filters stay mounted and only the preview changes, so comparing
 * four pieces is four taps instead of twelve.
 */
export function FittingRoomScreen() {
  const { data, update, go, reset } = useSession();
  const [category, setCategory] = useState(data.category ?? "dress");
  const [occasion, setOccasion] = useState(data.occasion ?? "everyday");
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const [selectedId, setSelectedId] = useState<string | undefined>(data.selectedId);
  // Try-on results live in the session (see SessionData.tryOns), not in
  // this component, so they survive a detour to the "Get it" screen and
  // back — which unmounts this screen.
  const tryOns = data.tryOns ?? {};
  const [tryOnBusy, setTryOnBusy] = useState(false);
  const [tryOnError, setTryOnError] = useState<string | null>(null);
  // Only the most recent try-on may write to the preview: a shopper who
  // switches garments mid-generation must not have the old result land on
  // the new selection.
  const tryOnRun = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    recommend({ profile: data.profile!, palette: data.palette!, category, occasion })
      .then((r) => {
        if (cancelled) return;
        setRecs(r);
        update({ recommendations: r, category, occasion });
        // Keep the shopper's pick across a filter change when it survives
        // the new filter; otherwise lead with the best match so the preview
        // is never empty.
        setSelectedId((prev) =>
          prev && r.some((x) => x.garment.id === prev) ? prev : r[0]?.garment.id
        );
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

  const selected = recs.find((r) => r.garment.id === selectedId);
  const preview = selectedId ? tryOns[selectedId] : undefined;
  const nearCount = recs.filter((r) => !r.exact).length;

  const select = (id: string) => {
    setSelectedId(id);
    setTryOnError(null);
    update({ selectedId: id });
  };

  const runTryOn = () => {
    if (!selected || tryOnBusy) return;
    const id = selected.garment.id;
    const run = ++tryOnRun.current;
    setTryOnBusy(true);
    setTryOnError(null);
    tryOn({ personPhoto: data.frontPhoto!, garmentId: id })
      .then((r) => {
        if (run !== tryOnRun.current) return;
        update({ tryOns: { ...(data.tryOns ?? {}), [id]: r.image } });
        setTryOnBusy(false);
      })
      .catch((err: unknown) => {
        if (run !== tryOnRun.current) return;
        setTryOnError(err instanceof ApiError && err.detail ? err.detail : TRY_ON_ERROR);
        setTryOnBusy(false);
      });
  };

  const buy = () => {
    if (!selected) return;
    update({ selectedId: selected.garment.id });
    go("getit");
  };

  return (
    <div className="screen screen-wide fitting">
      {/* The way back to the profile the rack was built from — a shopper who
          wants to re-read "why these pieces" shouldn't have to start over.
          It sits in the top-left corner opposite the fixed Home button, so
          the two corner controls read as a pair rather than as one stray
          button in the heading (see fitting.css). */}
      <button className="back-btn" onClick={() => go("report")} aria-label="Back">
        <ArrowLeft size={24} aria-hidden="true" />
      </button>
      <h1 className="fitting-title">Your fitting room</h1>

      <div className="fitting-body">
        {/* Preview. Shows the shopper's own scan until they ask to see a
            piece on it, so the panel is never an empty placeholder. */}
        <section className="card preview">
          <div className="preview-frame">
            {data.frontPhoto || preview ? (
              <img className="preview-img" src={preview ?? data.frontPhoto} alt={
                preview ? `${selected?.garment.name} shown on your scan` : "Your scan"
              } />
            ) : (
              <p className="preview-empty">Your scan will appear here.</p>
            )}
            {tryOnBusy && (
              <div className="preview-busy">
                <Spinner label="Dressing you…" />
              </div>
            )}
            <span className="preview-tag">{preview ? "Try-on" : "Your scan"}</span>
          </div>

          {/* Grouped so that on a portrait kiosk this column can sit
              beside the preview instead of under it (see fitting.css). */}
          <div className="preview-body">
            {selected && (
              <>
                <div className="preview-meta">
                  <p className="preview-name">{selected.garment.name}</p>
                  <p className="preview-price">€{selected.garment.price}</p>
                </div>
                <p className="preview-reason">{selected.reasons[0]}</p>
              </>
            )}
            {tryOnError && <p className="preview-error">{tryOnError}</p>}

            {/* Seeing the piece on yourself is what the mirror is for, so it
                carries the solid weight; buying is the step after that, not
                the one being asked for here. */}
            <div className="preview-actions">
              <PrimaryButton
                label={tryOnBusy ? "Dressing you…" : preview ? "Try again" : "Try it on"}
                disabled={!selected || tryOnBusy}
                onClick={runTryOn}
              />
              <PrimaryButton label="Buy" variant="ghost" disabled={!selected} onClick={buy} />
            </div>
          </div>

        </section>

        {/* The rack. Filters stay put; only this list re-fetches. */}
        <section className="rack">
          {/* Unlabelled, the two rows of pills read as decoration. Each row
              names what it filters, and the hint says out loud that the
              rack answers to a tap — a kiosk has no hover to discover it
              with. The visible label is the group's accessible name too
              (aria-labelledby), so there's no second, invisible wording to
              drift out of sync with it. */}
          <div className="filters">
            <p className="filters-hint">Tap to filter the rack</p>
            <div className="filter-row">
              <span className="filter-label" id="filter-category">Looking for</span>
              <div className="chips" role="group" aria-labelledby="filter-category">
                {CATEGORIES.map((c) => (
                  <button
                    key={c.key}
                    className={`chip${c.key === category ? " is-active" : ""}`}
                    aria-pressed={c.key === category}
                    onClick={() => setCategory(c.key)}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="filter-row">
              <span className="filter-label" id="filter-occasion">Wearing it to</span>
              <div className="chips" role="group" aria-labelledby="filter-occasion">
                {OCCASIONS.map((o) => (
                  <button
                    key={o}
                    className={`chip${o === occasion ? " is-active" : ""}`}
                    aria-pressed={o === occasion}
                    onClick={() => setOccasion(o)}
                  >
                    {o}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {loading ? (
            <Spinner label="Finding your matches…" />
          ) : recs.length === 0 ? (
            <p className="rack-empty">
              Nothing in this category right now. Try another filter.
            </p>
          ) : (
            <>
              {/* Said plainly rather than quietly padding the rack: these
                  pieces are in the category but outside the season or
                  occasion asked for. */}
              {nearCount > 0 && (
                <p className="rack-note">
                  {recs.length - nearCount === 0
                    ? "No exact matches here — showing the closest pieces."
                    : `${recs.length - nearCount} exact, ${nearCount} close.`}
                </p>
              )}
              <div className="rack-list">
                {recs.map((r) => (
                  <GarmentCard
                    key={r.garment.id}
                    rec={r}
                    selected={r.garment.id === selectedId}
                    onSelect={() => select(r.garment.id)}
                  />
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

import { useState } from "react";
import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { resolveImageUrl } from "../api/client";
import "./getit.css";
import "./screen.css";

/**
 * The handover: everything a shopper needs to walk away with the piece.
 *
 * Only three facts matter here — where it is, what sizes are on the rail,
 * and what it costs — so they're the only things on screen, at a size
 * that's readable while walking away from the mirror.
 */
export function GetItScreen() {
  const { data, go, reset } = useSession();
  const rec = data.recommendations?.find((r) => r.garment.id === data.selectedId);
  const g = rec?.garment;
  const [added, setAdded] = useState(false);

  return (
    <div className="screen getit">
      <h1 className="getit-name">{g?.name ?? "Your pick"}</h1>

      <div className="card getit-card">
        {g && (
          <img className="getit-img" src={resolveImageUrl(g.image_url)} alt="" />
        )}
        <dl className="getit-facts">
          <div className="getit-fact">
            <dt>Find it</dt>
            <dd>{g?.location ?? "Women's · Aisle 3"}</dd>
          </div>
          <div className="getit-fact">
            <dt>Sizes on the rail</dt>
            <dd className="getit-sizes">
              {(g?.sizes_in_stock ?? ["S", "M", "L"]).map((s) => (
                <span key={s} className="getit-size">{s}</span>
              ))}
            </dd>
          </div>
          {g && (
            <div className="getit-fact">
              <dt>Price</dt>
              <dd>€{g.price}</dd>
            </div>
          )}
        </dl>
      </div>

      {/* Confirmation replaces the instruction rather than sitting beside
          it, so there's never a screen showing both "add it" and "added". */}
      {added && <p className="getit-confirm">In your bag — pick it up at checkout.</p>}

      <div className="actions">
        <PrimaryButton
          label={added ? "Added ✓" : "Add to bag"}
          onClick={() => setAdded(true)}
          disabled={added}
        />
        <PrimaryButton label="Back to the rack" variant="ghost" onClick={() => go("fitting")} />
        <PrimaryButton label="Next customer" variant="ghost" onClick={reset} />
      </div>
    </div>
  );
}

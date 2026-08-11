import type { Recommendation } from "../api/types";
import { resolveImageUrl } from "../api/client";

/**
 * One garment on the rail.
 *
 * The image is the card: it fills the full width at 3:4 and everything else
 * is a two-line foot under it — name, price, and how well it matches. The
 * colour name and the styling reason moved to the preview panel, where they
 * describe the one garment the shopper is actually considering rather than
 * competing for room on all six.
 */
export function GarmentCard({ rec, selected, onSelect }: {
  rec: Recommendation;
  selected: boolean;
  onSelect: () => void;
}) {
  const { garment, score, exact } = rec;

  return (
    <button
      type="button"
      className={`rack-card${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span className="rack-card-frame">
        <img className="rack-card-img" src={resolveImageUrl(garment.image_url)} alt="" />
        {/* A backfilled piece is labelled on the card itself, so a shopper
            who never reads the note above the rack still knows this one is
            outside the filter they chose. */}
        {!exact && <span className="rack-card-near">Close</span>}
        <span className="rack-card-match">{Math.round(score * 100)}%</span>
      </span>
      <span className="rack-card-foot">
        <span className="rack-card-name">{garment.name}</span>
        <span className="rack-card-price">€{garment.price}</span>
      </span>
    </button>
  );
}

import {
  BONE_RULES,
  SHAPE_RULES,
  skipList,
  wearList,
  type Fruit,
  type Japanese,
} from "../lib/styleRules";
import "./BodyTypeDiagram.css";

// Designer-supplied illustrations, served from frontend/public/body-shapes.
// Filenames match the `fruit` values used throughout the app so the lookup
// is direct — no risk of a silently-wrong mapping.
const SHAPE_IMAGE: Record<Fruit, string> = {
  pear: "/body-shapes/pear.png",
  apple: "/body-shapes/apple.png",
  hourglass: "/body-shapes/hourglass.png",
  rectangle: "/body-shapes/rectangle.png",
  "inverted-triangle": "/body-shapes/inverted-triangle.png",
};

const BONE_ORDER: Japanese[] = ["straight", "wave", "natural"];

/** Describes the bone-type split in words: the model rarely returns a pure
 *  type, and "Mostly Wave, with some Straight" is both truer and more useful
 *  than a bare label. The fabric advice this implies lives in the WEAR/SKIP
 *  lists below — it must not be repeated here. */
function leanCaption(bone: Japanese, weights: Record<string, number>): string {
  const ranked = BONE_ORDER
    .map((k) => [k, weights[k] ?? 0] as const)
    .sort((a, b) => b[1] - a[1]);
  const second = ranked[1];
  const label = BONE_RULES[bone].label;
  return second && second[1] >= 0.25
    ? `Mostly ${label}, with some ${BONE_RULES[second[0]].label}`
    : `${label} through and through`;
}

/**
 * The shape card: what the scan found about your proportions, and the two
 * lists that follow from it.
 *
 * Self-contained on purpose. Cut advice (from the shape) and fabric advice
 * (from the bone type) both belong to the body, so both live here — not in
 * a shared band that reads as if it also applied to the colour card.
 */
export function BodyTypeDiagram({ fruit, bone, weights }: {
  fruit: Fruit; bone: Japanese; weights: Record<string, number>;
}) {
  const shape = SHAPE_RULES[fruit];
  const w = weights ?? {};

  return (
    <section className="card shape">
      <p className="eyebrow">Your shape</p>

      <div className="shape-head">
        <img
          src={SHAPE_IMAGE[fruit]}
          alt={`${shape.label} body shape illustration`}
          className="shape-illustration"
        />
        <div>
          <h2 className="shape-name">{shape.label}</h2>
          <p className="shape-line">{shape.line}</p>
        </div>
      </div>

      {/* Proportion shown as proportion: the segments are the model's own
          weights, so a 60/30/10 shopper sees a different bar from a
          40/35/25 one — and the dominant type is named, because that word
          is what the fabric line below is keyed to. */}
      <div className="shape-bone">
        <div className="shape-bone-bar">
          {BONE_ORDER.map((k) => (
            <span
              key={k}
              className={`shape-bone-seg${k === bone ? " is-dominant" : ""}`}
              style={{ flexGrow: Math.max(w[k] ?? 0, 0.02) }}
            />
          ))}
        </div>
        <p className="shape-bone-caption">{leanCaption(bone, w)}</p>
      </div>

      <div className="advice">
        <div>
          <p className="eyebrow advice-head advice-head--wear">Wear</p>
          <ul className="advice-list">
            {wearList(fruit, bone).map((item) => (
              <li key={item}>
                <span className="advice-mark advice-mark--wear" aria-hidden="true">✓</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div className="advice-skip">
          <p className="eyebrow advice-head">Skip</p>
          <ul className="advice-list">
            {skipList(fruit, bone).map((item) => (
              <li key={item}>
                <span className="advice-mark" aria-hidden="true">×</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

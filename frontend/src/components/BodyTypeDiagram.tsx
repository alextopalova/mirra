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

/** Whole percentages that add up to 100. The model rarely returns a pure
 *  type, so the split is the honest answer — but three numbers that visibly
 *  fail to make a whole read as a bug rather than as rounding, and the raw
 *  weights only sum to roughly 1. Normalise, then hand the rounding losses
 *  to the largest remainders. Whole percent is as fine as these weights
 *  deserve; a decimal would claim precision the model never had. */
function sharePercents(weights: Record<string, number>): Record<Japanese, number> {
  const raw = BONE_ORDER.map((k) => Math.max(weights[k] ?? 0, 0));
  const total = raw.reduce((a, b) => a + b, 0);
  // No signal at all (weights absent or all zero — the caller already
  // guards for a missing object). Splitting evenly is what the bar above
  // renders in that case via its own visibility floor, so the key has to
  // agree with it. Falling through instead would hand the remainder loop
  // 100 spare points to distribute over 3 items and print "1% 1% 1%".
  const exact = total > 0
    ? raw.map((v) => (v / total) * 100)
    : raw.map(() => 100 / BONE_ORDER.length);
  const shares = exact.map(Math.floor);
  let spare = 100 - shares.reduce((a, b) => a + b, 0);
  const byRemainder = exact
    .map((v, i) => [i, v - Math.floor(v)] as const)
    .sort((a, b) => b[1] - a[1]);
  for (const [i] of byRemainder) {
    if (spare <= 0) break;
    shares[i] += 1;
    spare -= 1;
  }
  return Object.fromEntries(
    BONE_ORDER.map((k, i) => [k, shares[i]]),
  ) as Record<Japanese, number>;
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
  const share = sharePercents(w);

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
          40/35/25 one. On its own that bar is three anonymous blocks, so the
          eyebrow says what is being measured and the key names every
          segment with its share — nothing here asks the shopper to guess
          which colour was which, and the dominant type stays the loudest
          because that word is what the fabric line below is keyed to. */}
      <div className="shape-bone">
        <p className="eyebrow">How your frame reads</p>
        {/* Decorative: the key underneath carries the same three names and
            numbers as text, so announcing the bar would only repeat it. */}
        <div className="shape-bone-bar" aria-hidden="true">
          {BONE_ORDER.map((k) => (
            <span
              key={k}
              className={`shape-bone-seg${k === bone ? " is-dominant" : ""}`}
              style={{ flexGrow: Math.max(w[k] ?? 0, 0.02) }}
            />
          ))}
        </div>
        <ul className="shape-bone-key">
          {BONE_ORDER.map((k) => (
            <li
              key={k}
              className={`shape-bone-key-item${k === bone ? " is-dominant" : ""}`}
            >
              <span className="shape-bone-key-dot" aria-hidden="true" />
              {BONE_RULES[k].label}
              <span className="shape-bone-key-share">{share[k]}%</span>
            </li>
          ))}
        </ul>
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

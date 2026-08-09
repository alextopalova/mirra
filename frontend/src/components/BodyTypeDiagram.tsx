import "./BodyTypeDiagram.css";

type Fruit = "pear" | "apple" | "hourglass" | "rectangle" | "inverted-triangle";
type Japanese = "straight" | "wave" | "natural";

// Designer-supplied illustrations, served from frontend/public/body-shapes.
// Filenames match the `fruit` values used throughout the app so the lookup
// below is direct — no risk of a silently-wrong mapping.
const SHAPE_IMAGE: Record<Fruit, string> = {
  pear: "/body-shapes/pear.png",
  apple: "/body-shapes/apple.png",
  hourglass: "/body-shapes/hourglass.png",
  rectangle: "/body-shapes/rectangle.png",
  "inverted-triangle": "/body-shapes/inverted-triangle.png",
};

const SHAPE_ALT: Record<Fruit, string> = {
  pear: "Pear body shape illustration",
  apple: "Apple body shape illustration",
  hourglass: "Hourglass body shape illustration",
  rectangle: "Rectangle body shape illustration",
  "inverted-triangle": "Inverted triangle body shape illustration",
};

const SILHOUETTE_GUIDANCE: Record<Fruit, string> = {
  pear: "Structured shoulders and A-line hems bring your frame into balance.",
  apple: "V-necks and empire waists draw the eye up and elongate your line.",
  hourglass: "Fitted waists and soft drape let your natural curve lead.",
  rectangle: "Peplums, belts and layered volume add definition at the waist.",
  "inverted-triangle": "Fuller skirts and hip detail soften a strong shoulder line.",
};

const FABRIC_GUIDANCE: Record<Japanese, string> = {
  straight: "Crisp, structured fabrics with clean lines suit your frame.",
  wave: "Soft, fluid fabrics — jersey, silk, gentle drape — move with you.",
  natural: "Relaxed, textured fabrics like linen and easy layers suit you best.",
};

const JAPANESE_ORDER: Japanese[] = ["straight", "wave", "natural"];

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function isFruit(f: string): f is Fruit {
  return Object.prototype.hasOwnProperty.call(SHAPE_IMAGE, f);
}

function isJapanese(j: string): j is Japanese {
  return Object.prototype.hasOwnProperty.call(FABRIC_GUIDANCE, j);
}

// Sorts the three bone-type weights (which sum to ~1) descending and turns
// them into a short, confident read like "Wave-leaning, with some Natural".
function rankWeights(weights: Record<string, number>): [Japanese, number][] {
  return JAPANESE_ORDER
    .map((k): [Japanese, number] => [k, weights[k] ?? 0])
    .sort((a, b) => b[1] - a[1]);
}

function leanCaption(ranked: [Japanese, number][]): string {
  const [topKey] = ranked[0];
  const second = ranked[1];
  if (second && second[1] >= 0.25) {
    return `${cap(topKey)}-leaning, with some ${cap(second[0])}`;
  }
  return `${cap(topKey)}-leaning`;
}

export function BodyTypeDiagram({ fruit, japanese, japaneseWeights }: {
  fruit: string; japanese: string; japaneseWeights: Record<string, number>;
}) {
  const shapeKey: Fruit = isFruit(fruit) ? fruit : "rectangle";
  const fabricKey: Japanese = isJapanese(japanese) ? japanese : "natural";
  const weights = japaneseWeights ?? {};
  const ranked = rankWeights(weights);
  const dominant = ranked[0][0];

  return (
    <div className="body-type-diagram" aria-label={`Body shape: ${cap(shapeKey)}`}>
      <p className="btd-label">Your silhouette</p>
      <div className="btd-figure">
        <div className="btd-illustration-surface">
          <img
            src={SHAPE_IMAGE[shapeKey]}
            alt={SHAPE_ALT[shapeKey]}
            className="btd-illustration"
          />
        </div>
      </div>

      <div className="btd-lean">
        <p className="btd-label">Bone type</p>
        <div className="btd-lean-bar">
          {JAPANESE_ORDER.map((k) => (
            <span
              key={k}
              className={`btd-lean-seg${k === dominant ? " is-dominant" : ""}`}
              style={{ flexGrow: Math.max(weights[k] ?? 0, 0.02) }}
            />
          ))}
        </div>
        <p className="btd-lean-caption">{leanCaption(ranked)}</p>
      </div>

      <div className="btd-guidance">
        <p className="btd-label">Styling notes</p>
        <p>{SILHOUETTE_GUIDANCE[shapeKey]}</p>
        <p>{FABRIC_GUIDANCE[fabricKey]}</p>
      </div>
    </div>
  );
}

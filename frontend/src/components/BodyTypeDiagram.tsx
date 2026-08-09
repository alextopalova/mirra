import "./BodyTypeDiagram.css";

// Static id is safe here: this component renders once per report screen.
const GRADIENT_ID = "btd-torso-fill";

type Fruit = "pear" | "apple" | "hourglass" | "rectangle" | "inverted-triangle";
type Japanese = "straight" | "wave" | "natural";

// Half-widths (in SVG units, from the vertical centerline) at six body
// levels: shoulder, bust, waist, hip, thigh, hem. This is the whole
// "recipe" for each silhouette — tune a shape by editing its six numbers.
const SHAPE_WIDTHS: Record<Fruit, number[]> = {
  pear: [24, 26, 22, 40, 34, 27],
  apple: [32, 38, 36, 28, 25, 21],
  hourglass: [32, 34, 20, 34, 28, 22],
  rectangle: [28, 28, 27, 28, 26, 22],
  "inverted-triangle": [38, 32, 24, 20, 19, 17],
};

const LEVELS_Y = [54, 86, 140, 186, 230, 298];
const CENTER_X = 80;

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
  return Object.prototype.hasOwnProperty.call(SHAPE_WIDTHS, f);
}

function isJapanese(j: string): j is Japanese {
  return Object.prototype.hasOwnProperty.call(FABRIC_GUIDANCE, j);
}

// Builds a single smooth, closed silhouette path from the six half-widths —
// a soft continuous contour rather than straight-line stick-figure segments.
function silhouettePath(widths: number[]): string {
  const pts = LEVELS_Y.map((y, i) => ({ y, w: widths[i] }));
  let d = `M ${CENTER_X + pts[0].w} ${pts[0].y}`;
  for (let i = 1; i < pts.length; i++) {
    const prev = pts[i - 1];
    const p = pts[i];
    const midY = (prev.y + p.y) / 2;
    d += ` C ${CENTER_X + prev.w} ${midY}, ${CENTER_X + p.w} ${midY}, ${CENTER_X + p.w} ${p.y}`;
  }
  const last = pts[pts.length - 1];
  d += ` Q ${CENTER_X} ${last.y + 16}, ${CENTER_X - last.w} ${last.y}`;
  for (let i = pts.length - 2; i >= 0; i--) {
    const p = pts[i];
    const next = pts[i + 1];
    const midY = (p.y + next.y) / 2;
    d += ` C ${CENTER_X - next.w} ${midY}, ${CENTER_X - p.w} ${midY}, ${CENTER_X - p.w} ${p.y}`;
  }
  d += ` Q ${CENTER_X} ${pts[0].y - 8}, ${CENTER_X + pts[0].w} ${pts[0].y} Z`;
  return d;
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
  const path = silhouettePath(SHAPE_WIDTHS[shapeKey]);
  const weights = japaneseWeights ?? {};
  const ranked = rankWeights(weights);
  const dominant = ranked[0][0];

  return (
    <div className="body-type-diagram" aria-label={`Body shape: ${cap(shapeKey)}`}>
      <div className="btd-figure">
        <svg viewBox="0 0 160 320" className="btd-svg" aria-hidden focusable="false">
          <defs>
            <linearGradient id={GRADIENT_ID} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: "var(--accent)", stopOpacity: 0.4 }} />
              <stop offset="100%" style={{ stopColor: "var(--accent)", stopOpacity: 0.08 }} />
            </linearGradient>
          </defs>
          <path d={path} className="btd-torso" fill={`url(#${GRADIENT_ID})`} />
          <rect x="72" y="36" width="16" height="20" rx="6" className="btd-neck" />
          <circle cx="80" cy="26" r="15" className="btd-head" />
        </svg>
      </div>

      <div className="btd-lean">
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
        <p>{SILHOUETTE_GUIDANCE[shapeKey]}</p>
        <p>{FABRIC_GUIDANCE[fabricKey]}</p>
      </div>
    </div>
  );
}

// The styling advice behind the profile screen.
//
// This is a rules table, not analysis: the API returns a shape, a bone type
// and a season, and standard styling practice says what each of those means
// for what to wear. Keeping it in one typed table (rather than scattered
// through JSX) is what lets the profile screen promise the same two
// things — WEAR and SKIP — for every shopper who stands in front of it.

export type Fruit = "pear" | "apple" | "hourglass" | "rectangle" | "inverted-triangle";
export type Japanese = "straight" | "wave" | "natural";

interface ShapeRule {
  label: string;
  /** One sentence naming what the analysis actually found in the shopper's
   *  proportions — the reason the advice below follows. */
  line: string;
  wear: string[];
  skip: string[];
}

export const SHAPE_RULES: Record<Fruit, ShapeRule> = {
  pear: {
    label: "Pear",
    line: "Your hips read wider than your shoulders, so the balance point is up top.",
    wear: [
      "Structured shoulders and boat necks",
      "A-line and bias-cut skirts",
      "Print, detail and colour above the waist",
      "Straight or bootcut trousers",
    ],
    skip: [
      "Skinny jeans under a cropped top",
      "Hip pockets and hip-height peplums",
      "Volume that starts at the hip",
    ],
  },
  apple: {
    label: "Apple",
    line: "You carry width through the middle, with legs and shoulders to lead with.",
    wear: [
      "V-necks and open collars",
      "Empire seams that sit under the bust",
      "Straight fabrics that skim the middle",
      "Cropped hems that show the ankle",
    ],
    skip: [
      "Belts that cinch at the waist",
      "Clingy jersey across the middle",
      "High, closed crew necks",
    ],
  },
  hourglass: {
    label: "Hourglass",
    line: "Your shoulders and hips balance around a clearly defined waist.",
    wear: [
      "Wrap dresses and waist-following seams",
      "Soft drape that skims the curve",
      "Fitted knits",
      "High-waisted trousers and skirts",
    ],
    skip: [
      "Boxy, straight-cut shifts",
      "Stiff volume that hides the waist",
      "Drop-waist silhouettes",
    ],
  },
  rectangle: {
    label: "Rectangle",
    line: "You have a straight, athletic line from shoulder to hip.",
    wear: [
      "Belted dresses and peplum tops",
      "Ruffles, pleats and texture",
      "Cropped jackets over high-waisted trousers",
      "Fit-and-flare skirts",
    ],
    skip: [
      "Straight column shifts",
      "Heavy shoulder padding",
      "Fully boxy tailoring",
    ],
  },
  "inverted-triangle": {
    label: "Inverted triangle",
    line: "Your shoulders read wider than your hips, so the balance point is below the waist.",
    wear: [
      "Full and pleated skirts",
      "Wide-leg and flared trousers",
      "V-necks and narrow lapels",
      "Print and detail below the waist",
    ],
    skip: [
      "Shoulder pads and puff sleeves",
      "Halter and wide boat necks",
      "Skinny trousers under a volume top",
    ],
  },
};

interface BoneRule {
  label: string;
  /** Bone type governs FABRIC, where shape governs CUT — so each rule
   *  contributes exactly one line to each list and the two never overlap. */
  wear: string;
  skip: string;
}

export const BONE_RULES: Record<Japanese, BoneRule> = {
  straight: {
    label: "Straight",
    wear: "Crisp, structured fabric with clean lines",
    skip: "Fussy ruffles and clingy jersey",
  },
  wave: {
    label: "Wave",
    wear: "Soft, fluid fabric — silk, jersey, gentle drape",
    skip: "Stiff canvas and bulky knits",
  },
  natural: {
    label: "Natural",
    wear: "Relaxed, textured fabric and easy layers",
    skip: "Tight, highly polished tailoring",
  },
};

interface SeasonRule {
  mood: string;
  note: string;
  /** Named so the shopper can recognise the colour on a tag, and hexed so
   *  the screen can show the thing itself rather than describe it. */
  skip: { name: string; hex: string }[];
  metals: string;
}

// The "Skip" swatches, and the two rules they have to obey.
//
// 1. MIRRORED in backend/app/reco/scorers.py (`SEASON_AVOID_HEXES`), which
//    ranks the rack against exactly these colours. This list used to live
//    only here, so the fitting room could put a shade the shopper had just
//    been warned off at the top of the rail with a match percentage next
//    to it. The backend's `test_scorers.py` reads this file and fails if
//    the two lists drift — change one, change the other.
//
// 2. No colour here may be close to one in the SAME season's palette
//    (backend/app/youcam/color.py `_SEASON_PALETTES`) — that would have the
//    profile screen showing a shade as "yours" and "skip" at once, side by
//    side. Two entries were reconciled for it: Spring's "Dusty mauve"
//    (#A98BA0) was a hair from the dusty pink in Spring's own palette —
//    near-identical swatches with near-identical names — and is now Taupe,
//    which carries the warning Spring actually needs (muted and drab over
//    clear); Autumn's icy pink and cool grey were too warm and too dark to
//    sit clear of Autumn's camel and moss, and are now genuinely icy and
//    genuinely cool.
const SEASON_RULES: Record<string, SeasonRule> = {
  spring: {
    mood: "Warm · Clear · Bright",
    note: "Warm colours with light in them keep you looking awake. Clear over dusty, every time.",
    skip: [
      { name: "Black", hex: "#111111" },
      { name: "Taupe", hex: "#8B7D6B" },
      { name: "Charcoal", hex: "#36393E" },
    ],
    metals: "Gold and warm brass",
  },
  summer: {
    mood: "Cool · Soft · Muted",
    note: "Muted, powdery colours on a cool base flatter you most. Soft contrast keeps you looking rested.",
    skip: [
      { name: "Orange", hex: "#E8703A" },
      { name: "Mustard", hex: "#C9A227" },
      { name: "Pure black", hex: "#111111" },
    ],
    metals: "Silver and white gold",
  },
  autumn: {
    mood: "Warm · Rich · Earthy",
    note: "Deep, warm, earthy colours give your skin its glow. Richness beats brightness on you.",
    skip: [
      { name: "Icy pink", hex: "#F2CBD5" },
      { name: "Cool grey", hex: "#B9C0C7" },
      { name: "Pure black", hex: "#111111" },
    ],
    metals: "Gold, bronze and copper",
  },
  winter: {
    mood: "Cool · Bold · Clear",
    note: "Cool, saturated colours and real contrast are yours. Muted shades wash you out.",
    skip: [
      { name: "Beige", hex: "#E8DCC0" },
      { name: "Camel", hex: "#C19A6B" },
      { name: "Olive", hex: "#6B7A3B" },
    ],
    metals: "Silver and platinum",
  },
};

const SEASON_FALLBACK: SeasonRule = {
  mood: "Curated for your undertone",
  note: "These shades sit closest to your skin's undertone.",
  skip: [],
  metals: "Silver and gold both work",
};

/** "Fall" is the same family as "Autumn" — mirrors `season_family` in the
 *  backend's scorers, which resolves it the same way. Without this the
 *  rack would be ranked against Autumn's skip list while this screen
 *  showed the shopper no skip list at all. */
const SEASON_ALIASES: Record<string, string> = { fall: "autumn" };

/** Matches on the season family so 12-season names ("Soft Summer", "Deep
 *  Autumn") resolve to the right advice instead of falling through. */
export function seasonRule(season: string): SeasonRule {
  const s = season.toLowerCase();
  const alias = Object.keys(SEASON_ALIASES).find((a) => s.includes(a));
  const key = alias ? SEASON_ALIASES[alias] : Object.keys(SEASON_RULES).find((k) => s.includes(k));
  return key ? SEASON_RULES[key] : SEASON_FALLBACK;
}

export function isFruit(f: string): f is Fruit {
  return Object.prototype.hasOwnProperty.call(SHAPE_RULES, f);
}

export function isJapanese(j: string): j is Japanese {
  return Object.prototype.hasOwnProperty.call(BONE_RULES, j);
}

/** Shape rules (cut) plus the bone-type rule (fabric), in that order — the
 *  silhouette decision comes before the material one. */
export function wearList(fruit: Fruit, bone: Japanese): string[] {
  return [...SHAPE_RULES[fruit].wear, BONE_RULES[bone].wear];
}

export function skipList(fruit: Fruit, bone: Japanese): string[] {
  return [...SHAPE_RULES[fruit].skip, BONE_RULES[bone].skip];
}

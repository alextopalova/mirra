// Turns the analysis's raw palette hexes into words a shopper can act on.
// "#AFC7E3" is not something you can look for on a rail; "powder blue" is.
//
// Naming is nearest-neighbour in CIELab (perceptual distance), not RGB —
// in RGB, a muted rose and a warm tan sit deceptively close together and
// the label lands on the wrong word.

interface NamedColor {
  name: string;
  hex: string;
}

/**
 * A boutique vocabulary rather than a web-colour list: every entry is a
 * word that appears on a garment tag, which is the whole point of naming
 * these at all. Spread evenly enough around the wheel that no palette
 * colour is more than a short hop from a name.
 */
const NAMED_COLORS: NamedColor[] = [
  { name: "White", hex: "#FFFFFF" },
  { name: "Ivory", hex: "#F5F0E1" },
  { name: "Cream", hex: "#F7EFD8" },
  { name: "Beige", hex: "#E8DCC0" },
  { name: "Sand", hex: "#E3D0B0" },
  { name: "Camel", hex: "#C19A6B" },
  { name: "Tan", hex: "#D2B48C" },
  { name: "Taupe", hex: "#8B7D6B" },
  { name: "Khaki", hex: "#A79A72" },
  { name: "Cocoa", hex: "#6B4F3A" },
  { name: "Chocolate", hex: "#4A3226" },
  { name: "Blush", hex: "#F1C6C2" },
  { name: "Soft rose", hex: "#E7A9A0" },
  { name: "Rose", hex: "#D77F86" },
  { name: "Dusty pink", hex: "#C48793" },
  { name: "Coral", hex: "#F27C5F" },
  { name: "Terracotta", hex: "#C56A4E" },
  { name: "Rust", hex: "#B7410E" },
  { name: "Red", hex: "#C1272D" },
  { name: "Wine", hex: "#722F37" },
  { name: "Burgundy", hex: "#6E1B2A" },
  { name: "Peach", hex: "#FFCBA4" },
  { name: "Apricot", hex: "#F4A261" },
  { name: "Orange", hex: "#E8703A" },
  { name: "Amber", hex: "#E9A23B" },
  { name: "Mustard", hex: "#C9A227" },
  { name: "Gold", hex: "#C9A54C" },
  { name: "Butter", hex: "#F3E5A0" },
  { name: "Yellow", hex: "#F2D64B" },
  { name: "Sage", hex: "#B2C2A5" },
  { name: "Moss", hex: "#7A8B58" },
  { name: "Olive", hex: "#6B7A3B" },
  { name: "Mint", hex: "#A9DCC4" },
  { name: "Jade", hex: "#4FA588" },
  { name: "Emerald", hex: "#1F7A5C" },
  { name: "Forest", hex: "#234F3B" },
  { name: "Teal", hex: "#2A7B7B" },
  { name: "Aqua", hex: "#7FD4D0" },
  { name: "Sky", hex: "#9DC7E8" },
  { name: "Powder blue", hex: "#AFC7E3" },
  { name: "Cornflower", hex: "#7A9CD8" },
  { name: "Denim", hex: "#4A6FA5" },
  { name: "Cobalt", hex: "#2C4FA1" },
  { name: "Navy", hex: "#24304F" },
  { name: "Midnight", hex: "#1B2436" },
  { name: "Lavender", hex: "#B7A9D9" },
  { name: "Lilac", hex: "#C9B6E4" },
  { name: "Orchid", hex: "#C08BC0" },
  { name: "Mauve", hex: "#A98BA0" },
  { name: "Violet", hex: "#7C5AA6" },
  { name: "Plum", hex: "#5E3A5C" },
  { name: "Pearl grey", hex: "#D9DCE0" },
  { name: "Silver", hex: "#C7CBD1" },
  { name: "Grey", hex: "#9AA0A8" },
  { name: "Slate", hex: "#5A6470" },
  { name: "Charcoal", hex: "#36393E" },
  { name: "Black", hex: "#111111" },
];

/** Parses "#RGB", "#RRGGBB" or the same without the hash. Returns null on
 * anything else so a malformed value degrades to showing no name rather
 * than throwing inside a render. */
function parseHex(hex: string): [number, number, number] | null {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

/** sRGB (0..255) -> CIELab, D65. Mirrors `hex_to_lab` in the backend's
 * catalog module, so a colour named here and a colour scored there are
 * measured in the same space. */
function rgbToLab(r: number, g: number, b: number): [number, number, number] {
  const lin = (c: number) => {
    const v = c / 255;
    return v > 0.04045 ? ((v + 0.055) / 1.055) ** 2.4 : v / 12.92;
  };
  const [rl, gl, bl] = [lin(r), lin(g), lin(b)];

  const x = (rl * 0.4124 + gl * 0.3576 + bl * 0.1805) / 0.95047;
  const y = (rl * 0.2126 + gl * 0.7152 + bl * 0.0722) / 1.0;
  const z = (rl * 0.0193 + gl * 0.1192 + bl * 0.9505) / 1.08883;

  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

const NAMED_LABS: [NamedColor, [number, number, number]][] = NAMED_COLORS.map((c) => {
  const rgb = parseHex(c.hex)!;
  return [c, rgbToLab(rgb[0], rgb[1], rgb[2])];
});

/**
 * The closest wearable name for a hex colour, or `null` if the input isn't
 * a colour at all. Callers render the swatch either way — the name is an
 * aid, and a missing one must never blank out the colour it describes.
 */
export function colorName(hex: string): string | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;

  const lab = rgbToLab(rgb[0], rgb[1], rgb[2]);
  let best = NAMED_LABS[0][0].name;
  let bestDist = Infinity;
  for (const [color, candidate] of NAMED_LABS) {
    const d =
      (lab[0] - candidate[0]) ** 2 +
      (lab[1] - candidate[1]) ** 2 +
      (lab[2] - candidate[2]) ** 2;
    if (d < bestDist) {
      bestDist = d;
      best = color.name;
    }
  }
  return best;
}

import type { BodyProfile, Palette, Recommendation } from "./types";
import { MOCK_CATALOG, type MockGarment } from "./mockCatalog";

export const mockProfile: BodyProfile = {
  fruit: "hourglass", japanese: "wave",
  japanese_weights: { straight: 0.2, wave: 0.6, natural: 0.2 },
  confidence: 0.78, summary: "Hourglass · Wave-leaning",
};
export const mockPalette: Palette = {
  season: "Autumn", colors: ["#8C5A3C", "#C08457", "#6B7F5B", "#B0463C", "#D9A05B", "#E3D0B0"],
};

/**
 * Stands in for the shopper's own scan. It's a catalog model shot — a real
 * person, photographed head to toe on white — so every screen downstream of
 * the capture behaves as though someone was actually scanned: the fitting
 * room preview shows a body, and the try-on has something to dress.
 *
 * Backend-relative like every other catalog path; callers resolve it through
 * `resolveImageUrl`.
 */
export const mockScanPhotoPath = "/garments/d9.jpg";

/** The catalog images ARE models wearing the garment, so returning the
 *  selected piece's own photo is a surprisingly faithful stand-in for a
 *  virtual try-on: the preview really does become "her, in that piece". */
export function mockTryOnPath(garmentId: string): string {
  const g = MOCK_CATALOG.find((x) => x.id === garmentId);
  return g?.image_url ?? mockScanPhotoPath;
}

/** The four season families every seasonal vocabulary reduces to, so "Soft
 *  Summer" matches a garment tagged plainly "summer" — the same rule the
 *  backend applies (see scorers.season_family). */
const FAMILIES = ["spring", "summer", "autumn", "winter"];
function family(season: string): string | undefined {
  const s = season.toLowerCase();
  if (s.includes("fall")) return "autumn";
  return FAMILIES.find((f) => s.includes(f));
}

function matchesSeason(g: MockGarment, season: string): boolean {
  const f = family(season);
  if (!f || g.season_tags.length === 0) return true;
  return g.season_tags.some((t) => family(t) === f);
}

/** Below this the rack is backfilled with near-matches, mirroring the
 *  backend's _MIN_RESULTS so mock mode shows the same "3 exact, 1 close"
 *  states the real thing does. */
const MIN_RESULTS = 4;

/**
 * A faithful-enough stand-in for POST /recommend: same filters (category,
 * season, occasion), same exact/near backfill, same response shape.
 *
 * The scores are positional rather than computed — mock mode is for working
 * on the screens, and reimplementing the four scorers here would create a
 * second ranking to keep in sync with the real one for no benefit.
 */
export function mockRecommend(input: {
  palette: Palette; category: string; occasion: string;
}): Recommendation[] {
  const inCategory = MOCK_CATALOG.filter((g) => g.category === input.category);
  const exact: MockGarment[] = [];
  const near: MockGarment[] = [];
  for (const g of inCategory) {
    const hit = matchesSeason(g, input.palette.season) && g.occasion_tags.includes(input.occasion);
    (hit ? exact : near).push(g);
  }

  const shortfall = Math.max(0, MIN_RESULTS - exact.length);
  const chosen = [
    ...exact.map((g) => ({ g, exact: true })),
    ...near.slice(0, shortfall).map((g) => ({ g, exact: false })),
  ];

  return chosen.map(({ g, exact: isExact }, i) => ({
    garment: g,
    score: Math.max(0.55, 0.94 - i * 0.05),
    exact: isExact,
    reasons: isExact
      ? [`${input.palette.season} palette match`, "Soft, flowing fabric suits Wave"]
      : ["Close on colour, outside your filter"],
  }));
}

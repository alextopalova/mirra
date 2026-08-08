import type { BodyProfile, Palette, Recommendation, Garment } from "./types";

export const mockProfile: BodyProfile = {
  fruit: "hourglass", japanese: "wave",
  japanese_weights: { straight: 0.2, wave: 0.6, natural: 0.2 },
  confidence: 0.78, summary: "Hourglass · Wave-leaning",
};
export const mockPalette: Palette = {
  season: "Autumn", colors: ["#8C5A3C", "#C08457", "#6B7F5B", "#B0463C", "#D9A05B"],
};
const g = (id: string, name: string, cat: string): Garment => ({
  id, name, category: cat, image_url: `https://picsum.photos/seed/${id}/400/560`,
  price: 1280, location: "Women's · Aisle 3", sizes_in_stock: ["S", "M", "L"], buy_url: "#",
});
export const mockRecs: Recommendation[] = [
  { garment: g("d1", "Wrap midi dress", "dress"), score: 0.92,
    reasons: ["Autumn palette match", "Defines the waist (Wave)"] },
  { garment: g("d2", "Fit-and-flare dress", "dress"), score: 0.88,
    reasons: ["Warm tone", "High-waist silhouette"] },
];
export const mockTryOn = { image: "https://picsum.photos/seed/tryon/600/840" };

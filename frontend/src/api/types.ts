// "fitting" is one screen doing what "shop" and "tryon" used to do
// separately: browsing the rack and seeing a piece on yourself happen side
// by side, so choosing another garment never costs a screen transition.
export type Screen =
  | "start" | "capture" | "measurements" | "analyzing"
  | "report" | "fitting" | "getit";

export interface Palette { season: string; colors: string[]; } // colors = hex
export interface BodyProfile {
  fruit: string;                 // "hourglass" | ...
  japanese: string;              // "wave" | "straight" | "natural"
  japanese_weights: Record<string, number>;
  confidence: number;            // 0..1
  summary: string;               // "Hourglass · Wave-leaning"
}
export interface Garment {
  id: string; name: string; category: string; image_url: string;
  price: number; location: string; sizes_in_stock: string[]; buy_url: string;
  // Sent by /recommend along with the rest of the catalog entry. Optional
  // because it's a scoring field the kiosk only borrows (to name the shade
  // on a card), not part of the contract every caller must satisfy.
  color_hex?: string;
}
export interface Recommendation {
  garment: Garment;
  score: number;
  reasons: string[];
  // False = shown only to fill a thin rack (right category, but outside the
  // requested season or occasion). The fitting room labels these instead of
  // presenting them as matches.
  exact: boolean;
}

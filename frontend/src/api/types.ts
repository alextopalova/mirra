export type Screen =
  | "start" | "capture" | "measurements" | "analyzing"
  | "report" | "shop" | "tryon" | "getit";

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
}
export interface Recommendation { garment: Garment; score: number; reasons: string[]; }

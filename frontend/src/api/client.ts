import type { BodyProfile, Palette, Recommendation } from "./types";
import * as M from "./mocks";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function analyzeBody(input: {
  frontPhoto: string; sidePhoto?: string; heightCm: number; weightKg: number;
}): Promise<{ profile: BodyProfile; palette: Palette }> {
  if (USE_MOCKS) { await wait(1400); return { profile: M.mockProfile, palette: M.mockPalette }; }
  const r = await fetch(`${BASE}/analyze-body`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(`analyze-body failed: ${r.status}`);
  return r.json();
}

export async function recommend(input: {
  profile: BodyProfile; palette: Palette; category: string; occasion: string;
}): Promise<Recommendation[]> {
  if (USE_MOCKS) { await wait(500); return M.mockRecs; }
  const r = await fetch(`${BASE}/recommend`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(`recommend failed: ${r.status}`);
  return r.json();
}

export async function tryOn(input: { personPhoto: string; garmentId: string }): Promise<{ image: string }> {
  if (USE_MOCKS) { await wait(1800); return M.mockTryOn; }
  const r = await fetch(`${BASE}/try-on`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(`try-on failed: ${r.status}`);
  return r.json();
}

import type { BodyProfile, Palette, Recommendation } from "./types";
import * as M from "./mocks";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/** Set VITE_USE_MOCKS=true to run the kiosk with no backend at all.
 *
 * Exported because it covers more than this module: the capture screen also
 * has to stand down (it can't mock a camera or a pose model, so it offers a
 * skip instead) or the flow dead-ends at the scan and mock mode looks
 * broken even though every API call is being served from mocks. */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Kiosk hygiene: "analyzing" and "tryon" are the two screens where the idle
// auto-reset is deliberately disabled (a generation must never be killed
// mid-flight -- see App.tsx). That means a request which never settles would
// otherwise leave an unattended kiosk spinning forever. Bound every call so
// a hang always surfaces as a normal, catchable error instead.
const ANALYZE_BODY_TIMEOUT_MS = 120_000;
const RECOMMEND_TIMEOUT_MS = 30_000;
const TRY_ON_TIMEOUT_MS = 120_000;

/** An API call that reached the server but got a non-OK response. Carries
 * the HTTP status and, when the server sent one, its `detail` message --
 * the backend deliberately returns actionable guidance (e.g. "step back so
 * your shoulders, hips, and ankles are all in frame") that shopper-facing
 * screens should show instead of a generic failure string. */
export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function toApiError(r: Response, label: string): Promise<ApiError> {
  let detail: string | undefined;
  try {
    const body = await r.json();
    if (body && typeof body.detail === "string" && body.detail.trim()) {
      detail = body.detail;
    }
  } catch {
    // Body wasn't JSON (or was empty) -- no server detail to surface.
  }
  return new ApiError(r.status, `${label} failed: ${r.status}`, detail);
}

export async function analyzeBody(input: {
  frontPhoto: string; sidePhoto?: string; heightCm: number; weightKg: number;
}): Promise<{ profile: BodyProfile; palette: Palette }> {
  if (USE_MOCKS) { await wait(1400); return { profile: M.mockProfile, palette: M.mockPalette }; }
  const r = await fetch(`${BASE}/analyze-body`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    signal: AbortSignal.timeout(ANALYZE_BODY_TIMEOUT_MS),
  });
  if (!r.ok) throw await toApiError(r, "analyze-body");
  return r.json();
}

export async function recommend(input: {
  profile: BodyProfile; palette: Palette; category: string; occasion: string;
}): Promise<Recommendation[]> {
  if (USE_MOCKS) { await wait(400); return M.mockRecommend(input); }
  const r = await fetch(`${BASE}/recommend`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    signal: AbortSignal.timeout(RECOMMEND_TIMEOUT_MS),
  });
  if (!r.ok) throw await toApiError(r, "recommend");
  return r.json();
}

/** Resolve a garment `image_url` to something the browser can load.
 *
 * Catalog entries store `image_url` as either a relative path served by
 * the backend's static mount (e.g. "/garments/d1.jpg" -- see
 * backend/app/main.py) or, for any not-yet-migrated entry, a
 * fully-qualified http(s) URL to a third party. Every screen that renders
 * a garment image should route through this single helper rather than
 * using `image_url` directly, so the resolution rule lives in one place.
 *
 * In mock mode the same paths are served by the FRONTEND, from
 * public/garments (mirrored there by backend/scripts/sync_mock_catalog.py),
 * so they must stay relative and resolve against this origin. Prefixing
 * them with the API base is what made a deployed mock build show a rack of
 * broken images: there is no backend behind a static deployment, so every
 * photo pointed at a host that wasn't answering. */
export function resolveImageUrl(imageUrl: string): string {
  if (/^https?:\/\//i.test(imageUrl)) return imageUrl;
  const path = imageUrl.startsWith("/") ? imageUrl : `/${imageUrl}`;
  return USE_MOCKS ? path : `${BASE}${path}`;
}

/** The stand-in "scan", already resolved to a loadable URL — the capture
 *  screen stores it directly as a photo, so it can't be a relative path. */
export function mockScanPhoto(): string {
  return resolveImageUrl(M.mockScanPhotoPath);
}

export async function tryOn(input: { personPhoto: string; garmentId: string }): Promise<{ image: string }> {
  if (USE_MOCKS) {
    await wait(1800);
    return { image: resolveImageUrl(M.mockTryOnPath(input.garmentId)) };
  }
  const r = await fetch(`${BASE}/try-on`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    signal: AbortSignal.timeout(TRY_ON_TIMEOUT_MS),
  });
  if (!r.ok) throw await toApiError(r, "try-on");
  return r.json();
}

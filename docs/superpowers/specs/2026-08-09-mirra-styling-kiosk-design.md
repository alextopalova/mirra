# Mirra — Design Spec

**Date:** 2026-08-09
**Hackathon:** YouCam API Skin AI & Apparel VTO Hackathon (Perfect Corp)
**Chosen topic:** Skin AI + Apparel VTO (both capabilities as one experience)
**Status:** Design approved, pending spec review

---

## 1. One-line pitch

**Mirra** is an in-store smart-mirror styling assistant that digitizes the Taiwanese/Japanese "total style diagnosis" — personal color + bone-structure + face type — from two photos, then does the one thing a salon can't: filters the store's inventory to what fits *your coloring and your frame*, and lets you try the top pick on your own body via Apparel VTO before you buy.

## 2. Why this wins (alignment with judging criteria)

- **Technological Implementation** — composes up to **3 YouCam APIs** (Facial Color Tones + Apparel VTO in the MVP; Face Attributes & Ratio completes the trio) plus a **custom computer-vision body classifier**. Not a wrapper around a single call.
- **Design** — a complete, coherent product: walk-up → diagnosis → matched rack → try-on → buy. Kiosk mode makes it feel like a real fixture.
- **Potential Impact** — targets Perfect Corp's *own* core market: in-store AR/AI for the 800+ brands they already serve. Crisp retail case: reduce fitting-room friction, drive conversion, upsell matched items.
- **Quality of Idea** — **body-typing is the uncontested lane**: of 43 gallery submissions, only one touches "body type" and only via *face shape*. Color-season is saturated; nobody does true silhouette typing, and nobody does an in-store fixture. Culturally authentic to the Taiwanese judges.

## 3. Positioning

- **Kiosk-first.** Primary experience is a **fullscreen web app** presented as an in-store smart mirror/monitor near the fitting rooms. Demoed on a laptop/tablet.
- **Consumer mode is a documented extension**, not a fork — same codebase, different catalog source and chrome. Not in MVP.
- **Catalog = the store's curated inventory** (a seeded `catalog.json` of clean flat-lay garments). This deliberately avoids arbitrary-URL scraping, which is brittle and produces model-worn images that degrade VTO quality.

## 4. Core user flow (kiosk)

1. **Walk-up / start screen** — big "Start your style scan" CTA; idle attract-loop.
2. **Capture** — front photo, side photo, height, weight. (Side photo recovers torso depth; height scales measurements; weight feeds the BMI signal for the Apple / firm-vs-soft axis; no self-report quiz.)
3. **Diagnosis** (parallel):
   - Selfie → **Facial Color Tones** → personal-color palette / season.
   - Selfie → **Face Attributes & Ratio** → face shape → neckline/collar preferences. *(First add-on; see scope.)*
   - Front+side photos + height/weight → **custom body classifier** → dual output: fruit shape + Japanese 3-type (weighted).
4. **Style report** — shows palette, body profile ("Hourglass · Wave-leaning"), and the styling rules derived from them.
5. **Shop** — user picks a category (top / dress / pants) and occasion; Mirra ranks store inventory on color × body fit.
6. **Try-on (virtual, first)** — user taps a pick → **Apparel VTO** renders it on their photo, right on the mirror. This is the kiosk's core value: try before you commit — no undressing, no fitting-room queue. Users can rapidly try several picks.
7. **Get it** — once they love one, the kiosk shows **where to find it on the floor** (in-store `location`/section) and offers **Add to bag / request my size / buy for delivery** (handoff, no real payment in MVP). Handles the "in a hurry / long queue / out of my size" cases.
8. **Reset** — "Next customer" clears session.

## 5. The hero: dual body classifier (custom, FastAPI backend)

Runs server-side in the **FastAPI backend** (Python: MediaPipe + OpenCV + NumPy) — the CV domain where the tooling is strongest, most testable, and upgradeable to SAM/SHAPY later. The frontend just uploads the two photos + height/weight and renders the result.

```
front photo ─┐
side photo  ─┤─► MediaPipe Pose (33 landmarks) + Selfie Segmentation
height+weight┘        │
                      ├─ front mask → horizontal widths @ shoulder / bust / waist / hip
                      ├─ side mask  → torso front-to-back DEPTH @ bust / waist
                      ├─ landmarks  → center-of-gravity (waist height, torso vs leg)
                      └─ height     → pixel→cm scale (display only; ratios need no calibration)
                              │
              ┌───────────────┴────────────────┐
     FRUIT classifier (ratio rules)     JAPANESE 3-TYPE classifier
   pear / apple / hourglass /          Straight / Wave / Natural
   rectangle / inverted-triangle       (weighted scores, allows mixed types)
        → WHERE to balance volume          → HOW it should feel (fabric/detail/fit)
```

**Fruit rules (ratios; BMI from height/weight assists Apple):**
- **Hourglass** — shoulder ≈ hip, clear waist definition (low waist-to-hip).
- **Triangle/Pear** — hip width > shoulder width.
- **Inverted triangle** — shoulder width > hip width.
- **Rectangle** — shoulder ≈ hip, little waist definition.
- **Apple** — midsection widest / waist ≥ hip; higher BMI supports.

**Japanese 3-type (ratios + torso depth + center-of-gravity + BMI proxy):**
- **Straight** — upper-heavy, high waist, thick torso depth, firmer build → structured, minimal, V-neck.
- **Wave** — lower-heavy, low waist, thin torso depth, defined waist, softer → soft fabrics, high-waist, fit-and-flare.
- **Natural** — balanced/elongated, broad frame, bony → oversized, textured/natural fabrics, relaxed.

Output is a **weighted profile with confidence**, not a hard label — honest, demoable, and mirrors the real system's recognition of mixed types.

## 6. Architecture

**Two services.** React (Vite + TypeScript) frontend on Vercel/Netlify; **FastAPI (Python)** backend on Render/Railway/Fly/HF Spaces (or run locally for a single-machine kiosk demo). Both give judges a public URL.

- **Frontend (React kiosk UI)**
  - Camera capture (front + side) + height/weight form.
  - Sends photos + inputs to the backend; renders the style report, matched rack, VTO result.
  - Kiosk chrome: fullscreen, large touch targets, walk-up start, "next customer" reset.
  - No CV in the browser — the frontend stays thin.
- **Backend (FastAPI)**
  - **`/analyze-body`** — MediaPipe Pose + segmentation + OpenCV/NumPy → measurements → dual classifier (fruit + Japanese 3-type, weighted). The hero, and unit-testable against image fixtures.
  - **`/recommend`** — runs the scorer pipeline over the catalog given the diagnosis + user selections.
  - **YouCam proxy** — holds the API key server-side; implements the async upload → task → poll flow for Facial Color Tones, Apparel VTO, (optional) Face Attributes. Key never reaches the client.
  - CORS configured for the frontend origin.
- **Data**
  - `catalog.json` — ~40 curated garments with clean flat-lay images (+ `location`, `sizes_in_stock`).
  - Recommendation engine — a **pluggable scorer pipeline** (Python).

## 7. Recommendation engine (extensible by design)

A ranked pipeline of independent scorers over the catalog, given the diagnosis + user selections:

- `colorScorer` — CIELab distance from garment color to user palette.
- `bodyScorer` — fruit balance rules × Japanese fabric/detail/fit rules → compatibility score.
- `occasionScorer` — occasion tag match (MVP; occasion selector is in the core flow).
- `necklineScorer` — face-shape → neckline match (soft weight; first add-on, ships with Face Attributes).
- *(future)* `weatherScorer`, `inventoryScorer`, etc. — drop in without touching the core.

Final rank = weighted sum; top N shown; #1 offered for VTO try-on.

## 8. Catalog item schema (draft)

```json
{
  "id": "top_012",
  "name": "Structured cotton shirt",
  "category": "top",
  "image_url": "/catalog/top_012.png",   // clean flat-lay for VTO
  "price": 1280,
  "color_lab": [72.1, 4.3, 18.9],
  "season_tags": ["autumn", "spring"],
  "silhouette": { "structured": true, "fabric": "crisp", "neckline": "v", "waist": "regular" },
  "occasion_tags": ["work", "smart-casual"],
  "location": "Women's · Aisle 3 · Shirts",   // in-store shelf/section for the "Get it" step
  "sizes_in_stock": ["S", "M", "L"],
  "buy_url": "https://..."
}
```

## 9. YouCam API integration

| Pillar | YouCam API | Role | MVP? |
|---|---|---|---|
| 個人色彩 color | **Facial Color Tones Analyzer** | selfie → palette/season → color scoring | ✅ MVP |
| try-on / buy | **Apparel VTO (Clothes Changer)** | render top pick on user photo → Buy | ✅ MVP |
| 顏分析 face | **Face Attributes & Ratio Analyzer** | face shape → neckline preferences; unlocks the 3-API story | First add-on |

**Notes / to validate in the API Playground during build:**
- Confirm whether Facial Color Tones returns a discrete season label or raw tone/undertone values we bucket into seasons ourselves (assume the latter; build the mapping).
- Confirm auth (key vs key+secret) and the exact async task/poll contract.
- Watch the free API-unit budget (1,000 units) — cache results per session, avoid redundant calls.

## 10. Scope

**MVP (the demo-able spine):**
1. Kiosk-mode two-photo + height/weight capture.
2. Custom dual body classifier (fruit + Japanese 3-type). ← hero
3. Facial Color Tones → palette.
4. Catalog match (color × body) with category + occasion selectors.
5. Apparel VTO virtual try-on of picks, then a "Get it" step (in-store location + add to bag / buy handoff).
6. Deployed public URL.

**First add-ons (clean seams, once spine works):**
- Face Attributes → necklines (unlocks 3-API integration story).
- Shareable "style report card."
- Weather scorer.
- Real-cm measurements & side-depth refinement.
- Consumer web mode (non-kiosk chrome, alternate catalog source).

**Out of scope (explicitly):**
- Arbitrary online-catalog URL scraping.
- Skin AI dermatology scores (out of the styling narrative).
- Kibbe 13-type (subjective, no Taiwanese footprint).
- User accounts / persistence beyond a session.
- Real payment processing (Buy is a link/handoff).

## 11. Key risks & mitigations

| Risk | Mitigation |
|---|---|
| Body measurement noisy on real photos | Use ratios (no calibration needed); constrain capture with on-screen pose guide; output weighted confidence, not hard labels. |
| YouCam async/latency stalls the demo | Show progress states; pre-warm; cache per session; have a recorded fallback in the video. |
| Free API-unit budget exhaustion | Cache per session; mock responses in dev; only call live during real runs. |
| VTO quality on messy garment images | Curated flat-lay catalog only (a benefit of kiosk framing). |
| Two-service deploy: CORS / backend cold-start on free tiers | Configure CORS early; keep a container image; for the demo run the FastAPI backend locally alongside the kiosk, or pre-warm the host before recording. |
| Scope creep | MVP spine is fixed; everything else is an add-on behind clean seams. |

## 12. Success criteria

- A judge can walk up to the fullscreen app, scan, and within ~1–2 minutes see: a personal-color palette, a dual body-type read, a matched rack from store inventory, and themselves wearing the top pick via VTO — end to end, live.
- Demonstrably uses ≥2 (target 3) YouCam APIs meaningfully.
- 1–3 min demo video shows the full walk-up→try-on loop on-device.

## 13. Demo script (for the video)

1. Walk up to the "mirror," tap Start.
2. Snap front + side, enter height + weight. (Narrate: "no measuring tape, no quiz.")
3. Reveal: "Autumn palette · Hourglass, Wave-leaning."
4. Pick "dress · date night" → matched rack appears, explain *why* each fits (color + shape).
5. Tap a pick → VTO renders it on the shopper, right on the mirror ("no queue, no undressing"); try a second pick.
6. Love one → "Get it": kiosk shows where it is on the floor + add to bag / my size.
7. One line on the retail impact (fitting-room friction → conversion) + the YouCam APIs used.

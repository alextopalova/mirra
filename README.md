# Mirra — the in-store styling mirror

**YouCam API Skin AI & Apparel VTO Hackathon · Track: Skin AI + Apparel VTO**

Mirra is a smart-mirror kiosk for clothing stores. A shopper walks up, takes two photos, and in about a
minute gets a personal style diagnosis — their **personal-colour palette** and their **body type** — then
sees the store's own garments filtered to what actually suits them, **tries the pick on virtually right on
the mirror**, and is told where to find it on the shop floor.

It digitises the "total style diagnosis" (個人色彩 personal colour + 骨架分析 bone structure) that image
consultants in Taiwan and Japan sell as a paid service — and then does the thing a salon can't: closes the
loop straight into what's on the rack.

---

## Why this, and why it's not a wrapper

A real salon hands you a PDF and sends you off to guess. Mirra ends at a garment you can try on and buy.

The body-type diagnosis is **our own computer-vision pipeline**, not an API call — no YouCam endpoint (and,
as far as we found, no competitor in this hackathon) does true silhouette typing from a body photo.

**Dual body typing.** Mirra reads the body two ways at once, because they answer different questions:

| Lens | Output | Answers |
|---|---|---|
| Western "fruit" shapes | pear / apple / hourglass / rectangle / inverted-triangle | **where** to balance volume |
| Japanese 骨格診断 | Straight (直筒) / Wave (波浪) / Natural (自然), as weighted scores | **how** a garment should feel — fabric, structure, waist |

Together they drive the recommendation: *"Adds interest up top to balance hips"* (fruit) plus
*"Soft, flowing fabric suits Wave"* (bone structure).

## YouCam APIs used

| API | Role in the product |
|---|---|
| **Apparel VTO — AI Clothes (`task/cloth`)** | The centrepiece. Renders the recommended garment on the shopper's own photo, on the mirror. No fitting-room queue, no undressing. |
| **AI Skin Tone / Facial Color Tones (`task/skin-tone-analysis`)** | Reads skin tone and undertone from the shopper's face; Mirra derives a seasonal palette from it, which drives colour matching against the catalogue in CIELab space. |

*(`task/face-analyzer` was evaluated for neckline advice but returns 404 on the current API — dropped.)*

## How it works

```
front photo ─┐
side photo  ─┤─► MediaPipe Pose + segmentation ─► silhouette widths @ shoulder/bust/waist/hip
height+weight┘                                          │
                                    ┌───────────────────┴────────────────┐
                            FRUIT shape                        JAPANESE 3-type
                                    └───────────────────┬────────────────┘
face crop ──► YouCam Skin Tone ──► undertone + depth ──► seasonal palette
                                                        │
                        category + occasion ────────────┤
                                                        ▼
              scorers: colour (CIELab ΔE) × body-fit rules × occasion  ──► ranked rack
                                                        ▼
                        YouCam Apparel VTO ──► "here's you in it" ──► where to find it in store
```

**Measuring from the silhouette, not the landmarks, is the thing that makes it work.** MediaPipe's hip
landmarks are hip *joint centres*, far narrower than the widest hip — using them directly produced a waist
wider than the hips (anatomically impossible) and classified our test subject as inverted-triangle. Measuring
widths across the segmentation silhouette at landmark-derived heights fixed it. The pipeline refuses to emit
an impossible measurement rather than returning a confidently wrong diagnosis.

## Repository layout

```
backend/          FastAPI (Python 3.12)
  app/cv/         measurement + dual classifier   ← the hero, thoroughly unit-tested (incl. the pure band-width math)
  app/reco/       catalogue, scorers, ranking engine
  app/youcam/     YouCam API client, VTO, colour   (CONTRACT.md = live-verified API contract)
  app/routers/    /analyze-body, /recommend, /try-on
frontend/         React 19 + TypeScript + Vite — the kiosk UI
docs/superpowers/ design spec + implementation plan
```

## Running it

**Backend**
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./scripts_setup_model.sh            # downloads the MediaPipe models (~9MB, not committed)
cp .env.example .env                # then add YOUCAM_API_KEY
uvicorn app.main:app --reload       # http://localhost:8000
```

**Frontend**
```bash
cd frontend
npm install
cp .env.example .env                # VITE_API_BASE=http://localhost:8000
npm run dev                         # http://localhost:5173
```

Set `USE_MOCKS=false` (backend) and `VITE_USE_MOCKS=false` (frontend) to call the real YouCam APIs.
Mocks are **on by default** so development doesn't burn API credits.

**Tests**
```bash
cd backend && . .venv/bin/activate && pytest -q     # 162 tests
```

## Design notes

- **Kiosk-first.** Grey/blue liquid-glass UI, ≥72px touch targets, an on-screen numeric keypad (kiosks have
  no keyboard), a pose-guide overlay telling the shopper where to stand, and a 90s idle reset for the next
  customer — deliberately suspended during analysis and try-on so a generation is never interrupted.
- **The style report is a stopover, not a destination.** One dominant CTA pushes to try-on; the mirror is
  the point.
- **Nothing blocks the scan.** A failed colour read, an unusable side photo, or a YouCam outage all degrade
  gracefully — the shopper still gets a body diagnosis and a rack.
- **Extensible by design.** Recommendations are a pluggable scorer pipeline (colour × body × occasion);
  weather or loyalty-data scorers drop in without touching the core.

## Limitations (honest)

- The catalogue is a seeded 15-garment stand-in for a store's real inventory feed.
- Body-type thresholds are tuned against anatomical reasoning and a small number of photos, not a labelled
  dataset.
- Colour analysis needs a forward-facing face; when the API can't read one it falls back to a default
  palette rather than failing the scan.
- "Add to bag" is a handoff — there's no real payment integration.

## License

MIT

# Mirra - Smart Try-on

**YouCam API Skin AI & Apparel VTO Hackathon. Track: Skin AI + Apparel VTO**

Mirra is a styling assistant for clothing stores. A shopper takes two photos and, in about a minute, gets a
personal style diagnosis - their **personal-colour palette** and their **body type**. The customer then sees the store's
own garments filtered to what suits them, **tries a pick on virtually**, and is told where to find it on the
shop floor.

It digitizes the "total style diagnosis" (個人色彩 personal colour + 骨架分析 bone structure) that image
consultants sell as a paid service, and connects it directly to what's on the rack.

Mirra is meant to work with **any store clothing catalog** and is a web app, so it runs on **any device with a browser**. The interface adapts to
the screen it's on, whether it's a self-service kiosk, a shop-floor tablet, a laptop, or the shopper's own phone.

---

## Contents

- [YouCam APIs used](#youcam-apis-used)
- [Body typing](#body-typing)
- [How it works](#how-it-works)
- [Running it](#running-it)
- [Repository layout](#repository-layout)
- [Design notes](#design-notes)
- [License](#license)

---

## YouCam APIs used

| API | Role in the product |
|---|---|
| **Apparel VTO - AI Clothes (`task/cloth`)** | Renders the recommended garment on the shopper's own photo. No fitting-room queue, no undressing. |
| **AI Skin Tone / Facial Color Tones (`task/skin-tone-analysis`)** | Reads skin tone and undertone from the shopper's face; Mirra derives a seasonal palette from it, which drives colour matching against the catalogue in CIELab space. |

## Body typing

The body-type diagnosis is a **self-developed computer-vision pipeline**.

Mirra reads the body two ways at once, because they answer different questions:

| Lens                            | Output | Answers |
|---------------------------------|---|---|
| Western "fruit" shapes          | pear / apple / hourglass / rectangle / inverted-triangle | **where** to balance volume |
| 3-type body classification <br/>骨格診断 | Straight (直筒) / Wave (波浪) / Natural (自然), as weighted scores | **how** a garment should feel - fabric, structure, waist |

Together they drive the recommendation: *"Adds interest up top to balance hips"* (fruit) plus
*"Soft, flowing fabric suits Wave"* (bone structure).

## How it works

```
front photo ─┐
side photo  ─┤─► MediaPipe Pose + segmentation ─► silhouette widths at shoulder/bust/waist/hip
height+weight┘                                          │
                                    ┌───────────────────┴────────────────┐
                            FRUIT shape                                3-type
                                    └───────────────────┬────────────────┘
face crop ──► YouCam Skin Tone ──► undertone + depth ──► seasonal palette
                                                        │
                        category + occasion ────────────┤
                                                        ▼
        scorers: colour (CIELab ΔE) × body fit × season × occasion  ──► ranked rack
                                                        ▼
                        YouCam Apparel VTO ──► "here's you in it" ──► where to find it in store
```

**Measuring from the silhouette, not the landmarks, is the thing that makes it work.**

### Filtering and scoring

Category is a hard filter - ask for dresses, get dresses. **Season and occasion filter too**, rather than
just nudging the order: a shopper who picks "work" is asking to see work clothes, and a rack that merely
reshuffles the same items reads as broken. Garments matching both are *exact*; if there are fewer than four,
the best remaining pieces in the category fill the rail and are flagged so the screen can label them.

Everything that survives the filter is scored on four weighted facets:

| Facet | Weight | Measures |
|---|---|---|
| **Body fit** | 35% | silhouette rules keyed to the fruit shape *and* the 3-type result |
| **Colour** | 30% | perceptual distance (CIELab ΔE) from the garment to the shopper's palette |
| **Season** | 25% | agreement with the diagnosed colour season |
| **Occasion** | 10% | what they came in to shop for |

A shade the shopper's palette told them to skip takes a flat deduction off that total - a yes/no verdict
deserves a flat price, not a fifth sliding facet. It stays a penalty rather than a filter, so an off-palette
piece keeps its body and occasion credit and can still surface when the store has nothing better, which is
the honest answer when it doesn't.

Each garment carries up to two plain-language reasons. The "palette match" line is only claimed when the
colour match is genuinely on-season, so the rack never sells a garment on a compliment it can't back up. The
rail is then sorted purely by the percentage printed on the card.

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
cd backend && . .venv/bin/activate && pytest -q     # 248 tests
```

**Deploying.** The frontend is deployed on Vercel and the backend runs as a Render service.

## Repository layout

```
backend/            FastAPI (Python 3.12)
  app/cv/           measurement + dual classifier   ← the hero, thoroughly unit-tested
  app/reco/         catalogue, scorers, ranking engine
  app/youcam/       YouCam API client, VTO, colour   (CONTRACT.md = live-verified API contract)
  app/routers/      /analyze-body, /recommend, /try-on
  data/             catalog.json + garments/ (70 self-hosted garment photos)
  models/           MediaPipe weights, downloaded by scripts_setup_model.sh (not committed)
  scripts/          catalogue build/retag and colour-calibration tooling
  tests/            248 tests
frontend/           React 19 + TypeScript + Vite
  src/screens/      start → capture → measurements → analyzing → report → fitting room → get it
  src/components/   pose guide, numeric keypad, body-type diagram, palette swatches, glass panels
  src/lib/          pose fit, auto-capture, colour naming, style rules
  src/api/          typed client for the backend
docs/superpowers/   design spec + implementation plan
render.yaml         backend deployment blueprint
```

## Design notes

- **Built for a kiosk first, comfortable everywhere.** Grey/blue liquid-glass UI, ≥72px touch targets, an
  on-screen numeric keypad (kiosks have no keyboard), a pose-guide overlay telling the shopper where to
  stand, and a 90s idle reset for the next customer - deliberately suspended during analysis and try-on so a
  generation is never interrupted.
- **The style report is a stopover, not a destination.** One dominant CTA pushes to try-on; the mirror is
  the point.
- **Nothing blocks the scan.** A failed colour read, an unusable side photo, or a YouCam outage all degrade
  gracefully - the shopper still gets a body diagnosis and a rack.
- **Extensible by design.** Recommendations are a pluggable scorer pipeline (colour × body × occasion ×
  season); weather or loyalty-data scorers drop in without touching the core.

## License

Released under the **MIT License** - see [LICENSE](LICENSE).

You are free to use, copy, modify, merge, publish, distribute, sublicense and sell this software, including
commercially, for any purpose. The only condition is that the copyright notice and permission notice are
included in copies. The software is provided as-is, without warranty of any kind.

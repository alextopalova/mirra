"""Mirror the catalog into the frontend, so mock mode can run with no backend.

Mock mode is what every deployed build runs: the kiosk frontend deploys to
static hosting on its own, and there is no Python service behind it. So the
two things it serves — the catalog data and the garment photos — have to
ship with the frontend, and both are copies of files that live under
`backend/`. This script makes those copies:

    frontend/src/api/mockCatalog.ts   <- backend/data/catalog.json
    frontend/public/garments/*.jpg    <- backend/data/garments/*.jpg

Copies drift, and this pair has form. `mockCatalog.ts` was hand-maintained,
documented as "regenerate after editing the catalog", and duly went stale
when the catalog was re-sourced: same ids, so the new photos kept loading
while the old names and prices stayed. A green knit tank dress was labelled
"Brown Animal Print Dress" at EUR 1650 — the price still in rupees from the
dataset the first catalog came from. Nothing looked broken; it just lied.

So neither copy is made by hand any more:

    python3 scripts/sync_mock_catalog.py            # write both
    python3 scripts/sync_mock_catalog.py --check    # fail if either is stale

`--check` exits non-zero when the frontend no longer matches the backend, so
CI or a pre-commit hook can refuse the edit that leaves it behind rather
than relying on anyone remembering.

Why copy the images rather than build them in: Vercel's "root directory"
setting excludes everything outside it from the build, so a project rooted
at `frontend/` cannot read `../backend/data/garments` at build time. The
files have to be inside `frontend/` to be deployed at all.

Only the fields `/recommend` actually returns are emitted into the TS — the
scoring fields (`color_lab`, `silhouette`) stay server-side, with the
scoring.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
CATALOG = BACKEND / "data" / "catalog.json"
IMAGES = BACKEND / "data" / "garments"
SNAPSHOT = BACKEND.parent / "frontend" / "src" / "api" / "mockCatalog.ts"
PUBLIC_IMAGES = BACKEND.parent / "frontend" / "public" / "garments"

# Exactly the Garment fields the API returns, plus the two tag arrays the
# fitting room's filters run against. Order is the emitted key order.
FIELDS = ("id", "name", "category", "image_url", "price", "location",
          "sizes_in_stock", "buy_url", "color_hex")
TAG_FIELDS = ("season_tags", "occasion_tags")

HEADER = '''import type { Garment } from "./types";

/**
 * A snapshot of the store's real catalog (backend/data/catalog.json), used
 * only by mock mode.
 *
 * Mock mode exists so the kiosk's screens can be worked on without the
 * backend or the ML pipeline — but a rack of invented placeholder garments
 * makes the fitting room useless for exactly the design questions mock mode
 * is meant to answer (do real product photos crop well, do real names fit
 * on a card, does a real catalog leave the filters looking empty). So these
 * are the actual garments, with the real season and occasion tags the
 * filters run against.
 *
 * GENERATED — do not hand-edit. Regenerate after any catalog change:
 *
 *     cd backend && python3 scripts/sync_mock_catalog.py
 *
 * Hand-editing is what let this file go stale once already: the catalog was
 * re-sourced, this snapshot wasn't, and mock mode showed the previous
 * catalog's names and prices against the new photos.
 *
 * `image_url` stays a backend-relative path, exactly as the API returns it,
 * so `resolveImageUrl` handles it identically in both modes.
 */
export interface MockGarment extends Garment {
  season_tags: string[];
  occasion_tags: string[];
}

export const MOCK_CATALOG: MockGarment[] = [
'''


def ts_value(value) -> str:
    """A JSON scalar/array as the TypeScript literal for it."""
    return json.dumps(value, ensure_ascii=False)


def render(catalog: list[dict]) -> str:
    lines = [HEADER]
    for garment in catalog:
        missing = [f for f in FIELDS if f not in garment]
        if missing:
            raise SystemExit(
                f"{garment.get('id', '?')} is missing {', '.join(missing)} — "
                f"the snapshot must carry every field /recommend returns."
            )
        head = ", ".join(f"{f}: {ts_value(garment[f])}" for f in FIELDS[:5])
        tail = ", ".join(f"{f}: {ts_value(garment[f])}" for f in FIELDS[5:])
        tags = ", ".join(f"{f}: {ts_value(garment.get(f, []))}" for f in TAG_FIELDS)
        lines.append(f"  {{ {head},\n    {tail},\n    {tags} }},\n")
    lines.append("];\n")
    return "".join(lines)


def image_diff() -> tuple[list[str], list[str]]:
    """(missing-or-different, extra) image filenames, frontend vs backend.

    Compared by content, not just by name: re-exporting a photo under the
    same filename is exactly the kind of change that would otherwise leave
    the deployed build serving the old one.
    """
    source = {p.name: p for p in sorted(IMAGES.glob("*.jpg"))}
    shipped = {p.name for p in PUBLIC_IMAGES.glob("*.jpg")} if PUBLIC_IMAGES.exists() else set()
    stale = [
        name for name, path in source.items()
        if name not in shipped or not filecmp.cmp(path, PUBLIC_IMAGES / name, shallow=False)
    ]
    return stale, sorted(shipped - set(source))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the frontend copies are out of date, and write nothing")
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text())
    generated = render(catalog)
    current = SNAPSHOT.read_text() if SNAPSHOT.exists() else ""
    stale_images, extra_images = image_diff()

    if args.check:
        problems = []
        if generated != current:
            problems.append(f"{SNAPSHOT.relative_to(BACKEND.parent)} does not match "
                            f"{CATALOG.relative_to(BACKEND.parent)}")
        if stale_images:
            problems.append(f"{len(stale_images)} image(s) missing or changed: "
                            f"{', '.join(stale_images[:6])}"
                            f"{'…' if len(stale_images) > 6 else ''}")
        if extra_images:
            problems.append(f"{len(extra_images)} image(s) no longer in the catalog: "
                            f"{', '.join(extra_images[:6])}"
                            f"{'…' if len(extra_images) > 6 else ''}")
        if problems:
            print("STALE:\n  " + "\n  ".join(problems)
                  + "\nRun: cd backend && python3 scripts/sync_mock_catalog.py", file=sys.stderr)
            sys.exit(1)
        print(f"up to date — {len(catalog)} garments, "
              f"{len(list(PUBLIC_IMAGES.glob('*.jpg')))} images")
        return

    SNAPSHOT.write_text(generated)
    PUBLIC_IMAGES.mkdir(parents=True, exist_ok=True)
    for name in stale_images:
        shutil.copy2(IMAGES / name, PUBLIC_IMAGES / name)
    # Removed from the catalog, so it must not keep shipping: a deployed
    # build serving a garment the store no longer stocks is worse than one
    # missing a photo.
    for name in extra_images:
        (PUBLIC_IMAGES / name).unlink()

    prices = [g["price"] for g in catalog]
    print(f"wrote {SNAPSHOT.relative_to(BACKEND.parent)}: {len(catalog)} garments, "
          f"prices {min(prices)}–{max(prices)}")
    print(f"synced {PUBLIC_IMAGES.relative_to(BACKEND.parent)}: "
          f"{len(stale_images)} copied, {len(extra_images)} removed, "
          f"{len(list(PUBLIC_IMAGES.glob('*.jpg')))} total")


if __name__ == "__main__":
    main()

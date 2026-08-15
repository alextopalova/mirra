"""Re-derive every garment's `season_tags` and `occasion_tags` in place.

Both fields drive hard filters on the kiosk's fitting-room screen, so both
have to be true of all 40 garments rather than of the handful that happened
to be tagged by hand. Before this script, 35 of 40 items were tagged
"everyday", nothing at all was tagged "work", and season tags were sparse —
so picking "work" changed the rack not at all.

Run from the backend directory:

    python3 scripts/retag_catalog.py            # rewrite data/catalog.json
    python3 scripts/retag_catalog.py --dry-run  # print the tag counts only

The rules below are deterministic functions of data already in the catalog
(CIELab colour, silhouette, category, price), so re-running is idempotent
and a catalog edit can always be re-tagged without hand-maintaining a
parallel spreadsheet of tags.
"""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "data" / "catalog.json"

# A garment usually belongs to one season, but plenty sit honestly between
# two (a soft mid-blue reads Summer or Winter). Anything scoring within this
# margin of the winner is kept as a second tag — which also keeps each
# season's rack populated enough to filter against.
SECOND_SEASON_MARGIN = 0.18


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def season_tags(lab: list[float]) -> list[str]:
    """Seasonal colour analysis, expressed as the three axes it actually uses.

    Warm/cool comes from b* (yellow positive, blue negative), light/deep from
    L*, and clear/muted from chroma. Each season is the pairing of those
    axes that defines it: Spring warm+bright, Autumn warm+deep/muted, Summer
    cool+light/muted, Winter cool+deep/clear.
    """
    L, a, b = lab
    chroma = math.hypot(a, b)

    # Zeroed at b* = -6 rather than at neutral: a dark brown or olive sits
    # barely on the warm side of neutral in Lab, and a threshold at 0 filed
    # every one of them as a cool colour — which left the Autumn rack empty
    # in a catalog full of browns.
    warmth = _clamp01((b + 6) / 22)
    coolness = 1 - warmth
    lightness = _clamp01((L - 30) / 55)
    depth = 1 - lightness
    clarity = _clamp01((chroma - 8) / 35)
    mutedness = 1 - clarity

    # Depth/lightness is weighted above clarity for the two cool seasons:
    # black and charcoal have no chroma at all, and scoring them on the
    # clear/muted axis alone would file them as Summer pastels.
    scores = {
        "spring": warmth * (0.5 * lightness + 0.5 * clarity),
        "autumn": warmth * (0.5 * depth + 0.5 * mutedness),
        "summer": coolness * (0.6 * lightness + 0.4 * mutedness),
        "winter": coolness * (0.6 * depth + 0.4 * clarity),
    }

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    tags = [ranked[0][0]]
    if ranked[1][1] >= ranked[0][1] - SECOND_SEASON_MARGIN:
        tags.append(ranked[1][0])
    return tags


def occasion_tags(g: dict) -> list[str]:
    """Where a shopper could actually wear the piece.

    Read off the same signals a person would use standing at the rail:
    whether it's cut with structure, what the fabric does, how loud the
    colour is, and what it costs. Every garment ends up with at least
    "everyday" so no filter combination can strand an item with no home.
    """
    name = g["name"].lower()
    cat = g["category"]
    sil = g.get("silhouette", {})
    fabric = sil.get("fabric", "")
    structured = bool(sil.get("structured"))
    L, a, b = g["color_lab"]
    chroma = math.hypot(a, b)
    price = g.get("price", 0)

    tags: list[str] = []

    # Work: needs to hold a line. Structure or a crisp/smooth fabric, in a
    # colour that isn't shouting, and nothing that reads as gymwear.
    is_gym = any(w in name for w in ("legging", "track", "jogger", "sweat"))
    if not is_gym and (structured or fabric in {"crisp", "smooth", "structured"}) and chroma < 45:
        tags.append("work")

    # Date night: deep or saturated colour, in something that moves. Dresses
    # and tops carry the look; trousers come along only if they're dressy.
    if cat in {"dress", "top"} and (chroma > 24 or L < 30) and fabric in {"soft", "smooth", "draping"}:
        tags.append("date night")

    # Wedding guest: dresses only, and only the ones that read as an
    # occasion — pale and delicate, or genuinely colourful, at a price that
    # isn't a t-shirt's. The threshold is in EUR (the currency the kiosk
    # prints); it was 1200 when the catalog carried its source dataset's
    # Indian-rupee prices, which no EUR-priced garment could ever clear.
    if cat == "dress" and price >= 50 and (L > 78 or chroma > 30):
        tags.append("wedding guest")

    # Everyday is the floor, not a leftover: anything wearable to the shops
    # belongs here, which is nearly everything that isn't strictly formal.
    if "wedding guest" not in tags or chroma < 40:
        tags.append("everyday")

    return tags


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print counts without writing")
    args = ap.parse_args()

    catalog = json.loads(CATALOG.read_text())
    seasons: Counter[str] = Counter()
    occasions: Counter[str] = Counter()
    pairs: Counter[tuple[str, str, str]] = Counter()

    for g in catalog:
        g["season_tags"] = season_tags(g["color_lab"])
        g["occasion_tags"] = occasion_tags(g)
        seasons.update(g["season_tags"])
        occasions.update(g["occasion_tags"])
        for s in g["season_tags"]:
            for o in g["occasion_tags"]:
                pairs[(g["category"], s, o)] += 1

    print("seasons  ", dict(seasons))
    print("occasions", dict(occasions))
    empty = [
        (c, s, o)
        for c in ("dress", "top", "pants")
        for s in ("spring", "summer", "autumn", "winter")
        for o in ("everyday", "work", "date night", "wedding guest")
        if pairs[(c, s, o)] == 0
    ]
    print(f"filter combinations with no exact match: {len(empty)}/48")

    if args.dry_run:
        return
    CATALOG.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"wrote {CATALOG}")


if __name__ == "__main__":
    main()

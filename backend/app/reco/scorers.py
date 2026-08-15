"""Pure scoring functions for the recommendation engine.

Each function scores one facet of "why this garment suits this shopper":
color harmony against their palette, body-shape flattery, and occasion
fit. `body_score`'s `reasons` are shown directly to the shopper on the
kiosk screen (e.g. "Defines the waist"), so they read as short, confident
styling advice -- not internal jargon or raw field names.
"""

import math

from app.reco.catalog import Garment, hex_to_lab
from app.schemas import BodyProfile


def _dE(a: list[float], b: list[float]) -> float:
    """CIE76 (Euclidean) distance between two Lab colors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# How close (CIE76) a garment has to sit to a colour the shopper was told to
# skip before it *is*, to their eye, that colour on the rail. Calibrated
# against the naming vocabulary the profile screen already uses
# (frontend/src/lib/colorNames.ts): coral->orange is 15, gold->mustard 14,
# ivory->beige 10, tan->camel 11 -- all the same shade to a shopper, all
# caught. Navy->black is 26, emerald->olive 30, white->beige 19 -- clearly
# different colours that a Summer/Winter shopper may absolutely wear, all
# left alone. 18 is the gap between those two groups.
AVOID_SAME_SHADE_DE = 18.0


def is_avoided_color(
    garment_lab: list[float],
    palette_labs: list[list[float]],
    avoid_labs: list[list[float]] | None,
) -> bool:
    """Whether this garment reads as a colour the shopper was told to skip.

    Two conditions, both required:

    1. It sits within `AVOID_SAME_SHADE_DE` of an avoided colour -- close
       enough to be that shade rather than merely adjacent to it.
    2. It isn't closer to one of the shopper's own palette colours. The
       palette is what we *promised* them on the profile screen, so it wins
       any tie. This is what makes a season that somehow both recommends
       and warns against the same shade harmless to the shopper rather than
       actively punishing: the recommendation is honoured. (The season data
       itself is kept free of that contradiction -- see SEASON_AVOID_HEXES
       -- but `palette_labs` arrives from the client on every /recommend
       call, so it can't be assumed clean.)
    """
    if not avoid_labs:
        return False
    nearest_avoid = min(_dE(garment_lab, a) for a in avoid_labs)
    if nearest_avoid > AVOID_SAME_SHADE_DE:
        return False
    if palette_labs and min(_dE(garment_lab, p) for p in palette_labs) <= nearest_avoid:
        return False
    return True


def color_score(garment_lab: list[float], palette_labs: list[list[float]]) -> float:
    """How well a garment's color matches the shopper's flattering palette.

    Returns 0.5 (neutral -- neither reward nor punish) when the palette is
    empty, since we have nothing to compare against. Otherwise the closest
    palette color wins, and the result is always clamped to [0, 1].

    Deliberately says nothing about the colours the shopper's season tells
    them to skip: that's a yes/no verdict (`is_avoided_color`), not a
    sliding scale, and folding it in here would make its cost proportional
    to the palette credit the garment was going to lose anyway -- smallest
    for exactly the off-palette pieces the advice is aimed at. `rank()`
    prices it separately.
    """
    if not palette_labs:
        return 0.5
    best = min(_dE(garment_lab, p) for p in palette_labs)  # CIE76 distance
    return round(min(1.0, max(0.0, 1.0 - best / 60.0)), 3)  # 60 ~= "very different"


# Japanese-type ("Kibbe-adjacent") styling preferences: which fabric/
# structure/neckline traits flatter each type, and the user-facing copy
# explaining the match.
_JP_RULES = {
    "straight": {
        "structured": True,
        "fabric": {"crisp", "structured", "smooth"},
        "fabric_note": "Clean, structured lines suit Straight",
        "neckline": {"v"},
        "neckline_note": "A V-neck sharpens your line",
    },
    "wave": {
        "structured": False,
        "fabric": {"soft", "draping", "light"},
        "fabric_note": "Soft, flowing fabric suits Wave",
        "neckline": set(),  # no single neckline is distinctly "Wave"
        "neckline_note": "",
    },
    "natural": {
        "structured": False,
        "fabric": {"textured", "natural", "chunky"},
        "fabric_note": "Relaxed, textured pieces suit Natural",
        "neckline": set(),  # no single neckline is distinctly "Natural"
        "neckline_note": "",
    },
}

# Fruit-shape balance: where each shape benefits from added interest, and
# the fallback line shown when no sharper reason applies.
_FRUIT_NOTE = {
    "pear": "Adds interest up top to balance hips",
    "apple": "Skims the midsection and elongates",
    "hourglass": "Defines your waist",
    "rectangle": "Creates curve and waist definition",
    "inverted-triangle": "Adds volume below to balance shoulders",
}
_DEFAULT_FALLBACK_REASON = "Flatters your shape"

# Fruit shapes (plus the Wave japanese-type, which specifically favors a
# defined/high waist) that benefit from a waist-defining garment.
_WAIST_LOVING_FRUITS = {"hourglass", "rectangle"}
_WAIST_DEFINING_VALUES = {"defined", "high"}


def body_score(g: Garment, profile: BodyProfile) -> tuple[float, list[str]]:
    """Score + user-facing reasons for how well a garment flatters this body.

    `reasons` is guaranteed non-empty: every recommendation shown to the
    shopper must be able to explain itself, even when none of the specific
    styling rules fire (in which case a fruit-shape fallback line is used).
    """
    reasons: list[str] = []
    score = 0.4
    silhouette = g.silhouette
    # `profile` is deserialized straight from the /recommend request body, so
    # `profile.japanese` is not guaranteed to be one of the three keys this
    # dict knows about (a client could send anything). Fall back to
    # "straight" rather than raising KeyError on an unrecognised value.
    rule = _JP_RULES.get(profile.japanese, _JP_RULES["straight"])

    if silhouette.get("structured") == rule["structured"]:
        score += 0.25

    if silhouette.get("fabric") in rule["fabric"]:
        score += 0.2
        reasons.append(rule["fabric_note"])

    # Neckline preference only applies when the garment actually has one.
    # Pants use "n/a" for this field -- that must stay neutral (no reward,
    # no penalty) rather than being silently treated as "no match" for the
    # wrong reason. Made explicit here rather than relying on "n/a" simply
    # never appearing in a preferred-neckline set.
    neckline = silhouette.get("neckline")
    has_neckline = neckline is not None and neckline != "n/a"
    if has_neckline and neckline in rule["neckline"]:
        score += 0.1
        reasons.append(rule["neckline_note"])

    waist_benefits_shopper = profile.japanese == "wave" or profile.fruit in _WAIST_LOVING_FRUITS
    if waist_benefits_shopper and silhouette.get("waist") in _WAIST_DEFINING_VALUES:
        score += 0.15
        reasons.append(f"Defines the waist ({profile.japanese.title()})")

    if not reasons:
        reasons.append(_FRUIT_NOTE.get(profile.fruit, _DEFAULT_FALLBACK_REASON))

    return round(min(score, 1.0), 3), reasons


def occasion_score(g: Garment, occasion: str) -> float:
    """1.0 for an exact occasion-tag match, 0.6 otherwise (still wearable)."""
    return 1.0 if occasion in g.occasion_tags else 0.6


# season_score outcomes. Exposed so `engine.rank()` can tell an explicit
# off-season penalty apart from "we had no season signal" without
# re-deriving the match logic itself.
SEASON_MATCH = 1.0
SEASON_NEUTRAL = 0.5  # mirrors color_score's "nothing to compare" neutral
SEASON_OFF_SEASON_PENALTY = 0.15


# The four season families every seasonal-analysis vocabulary reduces to.
# The colour analysis may return a 12-season name ("Soft Summer", "Deep
# Autumn"), while catalog tags are always the plain family -- comparing the
# two strings directly filed every 12-season shopper as off-season for the
# entire catalog.
_SEASON_FAMILIES = ("spring", "summer", "autumn", "winter")
_SEASON_ALIASES = {"fall": "autumn"}


def season_family(season: str | None) -> str | None:
    """The plain season family inside a season name, or None if there isn't one.

    "Soft Summer" -> "summer", "Fall" -> "autumn", "Deep Winter" -> "winter".
    Returns None for an unrecognised value so callers can treat it as "no
    season signal" rather than as a mismatch.
    """
    if not season:
        return None
    s = season.strip().lower()
    for alias, family in _SEASON_ALIASES.items():
        if alias in s:
            return family
    for family in _SEASON_FAMILIES:
        if family in s:
            return family
    return None


def season_matches(g: Garment, season: str | None) -> bool:
    """Whether a garment belongs to the shopper's season family.

    An untagged garment matches everyone: the tag's absence means "this
    piece isn't seasonal", not "this piece is wrong for you".
    """
    family = season_family(season)
    if family is None or not g.season_tags:
        return True
    return any(season_family(t) == family for t in g.season_tags)


def season_score(g: Garment, season: str | None) -> float:
    """How well a garment's season fits the shopper's seasonal palette.

    A shopper's colour "season" (Autumn/Winter/Spring/Summer) is a proxy
    for which garments were designed to sit near their skin-tone palette --
    `color_score` alone can't tell a genuine palette match from a raw
    CIELab coincidence (a winter garment can happen to sit near an autumn
    palette color). This term makes the seasonal tag itself count.

    - Any overlap between `g.season_tags` and `season` (case-insensitive)
      is a full match -- a garment can legitimately belong to more than
      one season.
    - Returns SEASON_NEUTRAL (not a penalty) when there's nothing to
      compare: no `season` given, or the garment carries no season tags
      at all (an untagged/cross-season piece). A kiosk whose colour
      analysis failed and fell back to a default season, or a neutral
      item that genuinely suits any palette, must not be punished for it.
    - Otherwise it's a soft, decisive penalty (SEASON_OFF_SEASON_PENALTY)
      rather than a hard filter/zero: a 15-garment rack must never go
      empty, and some pieces (dark neutrals, blacks, greys) can still be
      the best available option outside their "main" season.
    """
    if not season or not g.season_tags:
        return SEASON_NEUTRAL
    if season_family(season) is None:
        # A season we can't place at all carries no signal either way.
        return SEASON_NEUTRAL
    return SEASON_MATCH if season_matches(g, season) else SEASON_OFF_SEASON_PENALTY


# ---------------------------------------------------------------------------
# The colours each season's advice tells the shopper to skip
# ---------------------------------------------------------------------------
#
# The profile screen prints these under a "Skip" heading, next to the
# shopper's palette. Until now they lived only in the frontend, so the rack
# on the very next screen could -- and did -- put a colour the shopper had
# just been warned off at the top of the rail with a match percentage
# beside it. Ranking has to read the same advice the shopper read.
#
# MIRRORED in frontend/src/lib/styleRules.ts (`SEASON_RULES[*].skip`), which
# is where the shopper-facing name and swatch for each of these live. The
# names/hexes must stay identical in both places -- `test_scorers.py`
# asserts it against that file so the two can't drift apart silently.
#
# Invariant, enforced by test: no colour here may sit within
# 2 * AVOID_SAME_SHADE_DE of any colour in its OWN season's recommended
# palette (app/youcam/color.py `_SEASON_PALETTES`). A season that both
# recommends and warns against the same shade contradicts itself on one
# screen, and doubling the shade radius leaves clear air on both sides:
# by the triangle inequality no garment can then read as both. Two entries
# were reconciled to satisfy it:
#   - Spring's "Dusty mauve" (#A98BA0) sat 25.7 from the dusty pink
#     (#F49CBB) in Spring's own palette -- near-identical swatches with
#     near-identical names, one labelled "yours", one "skip". Replaced with
#     Taupe, which carries the same warning Spring actually needs (muted
#     and drab over clear) without colliding.
#   - Autumn's "Cool grey" (#9AA0A8) and "Icy pink" (#F1C6C2) were 30.0 and
#     34.8 from Autumn's moss and camel. Both moved to genuinely cooler,
#     lighter values -- which also makes them look like their own names.
SEASON_AVOID_HEXES: dict[str, list[str]] = {
    "spring": ["#111111", "#8B7D6B", "#36393E"],  # Black, Taupe, Charcoal
    "summer": ["#E8703A", "#C9A227", "#111111"],  # Orange, Mustard, Pure black
    "autumn": ["#F2CBD5", "#B9C0C7", "#111111"],  # Icy pink, Cool grey, Pure black
    "winter": ["#E8DCC0", "#C19A6B", "#6B7A3B"],  # Beige, Camel, Olive
}

# Converted once at import: `rank()` needs these for every garment in the
# catalog, on every request.
_SEASON_AVOID_LABS: dict[str, list[list[float]]] = {
    family: [hex_to_lab(h) for h in hexes] for family, hexes in SEASON_AVOID_HEXES.items()
}


def season_avoid_labs(season: str | None) -> list[list[float]]:
    """The Lab colours this shopper's season tells them to skip.

    Empty for no season, or a season name we can't place -- the same
    "no signal, so no penalty" stance `season_score` takes. We only ever
    penalise a shopper for a colour we're confident we told them to avoid.
    """
    family = season_family(season)
    if family is None:
        return []
    return _SEASON_AVOID_LABS.get(family, [])

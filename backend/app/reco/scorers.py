"""Pure scoring functions for the recommendation engine.

Each function scores one facet of "why this garment suits this shopper":
color harmony against their palette, body-shape flattery, and occasion
fit. `body_score`'s `reasons` are shown directly to the shopper on the
kiosk screen (e.g. "Defines the waist"), so they read as short, confident
styling advice -- not internal jargon or raw field names.
"""

import math

from app.reco.catalog import Garment
from app.schemas import BodyProfile


def _dE(a: list[float], b: list[float]) -> float:
    """CIE76 (Euclidean) distance between two Lab colors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def color_score(garment_lab: list[float], palette_labs: list[list[float]]) -> float:
    """How well a garment's color matches the shopper's flattering palette.

    Returns 0.5 (neutral -- neither reward nor punish) when the palette is
    empty, since we have nothing to compare against. Otherwise the closest
    palette color wins, and the result is always clamped to [0, 1].
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
    rule = _JP_RULES[profile.japanese]

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

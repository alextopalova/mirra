"""Recommendation engine: turns a shopper's diagnosis into a ranked rack.

Combines the four scorers (color, body, occasion, season) into a single
weighted score per garment, filtered to the requested category and sorted
descending -- the exact order the kiosk shows on the shop screen.
"""

from app.reco.catalog import Garment
from app.reco.scorers import (
    SEASON_OFF_SEASON_PENALTY,
    body_score,
    color_score,
    occasion_score,
    season_score,
)
from app.schemas import BodyProfile

# Re-balanced to give season a real, decisive voice (previously 0 -- see
# the season_tags bug this fixes) without letting it swamp body fit, which
# still matters most for whether a garment actually flatters the shopper.
_COLOR_WEIGHT = 0.30
_BODY_WEIGHT = 0.35
_OCCASION_WEIGHT = 0.10
_SEASON_WEIGHT = 0.25

_MAX_REASONS = 2
# Final safety net: body_score already guarantees at least one reason, but
# this keeps the kiosk from ever rendering an empty reasons list if that
# contract is ever loosened.
_FALLBACK_REASON = "A strong match for you"


def _color_match_reason(season: str | None) -> str:
    return f"{season} palette match" if season else "Your palette match"


def rank(
    profile: BodyProfile,
    palette_labs: list[list[float]],
    category: str,
    occasion: str,
    catalog: list[Garment],
    season: str | None = None,
) -> list[dict]:
    """Score and rank the catalog's garments in `category` for this shopper.

    Returns a list of `{"garment": Garment, "score": float, "reasons":
    list[str]}` dicts, sorted by score descending. A `category` that
    matches nothing in the catalog yields an empty list rather than an
    error -- callers (the /recommend route) rely on this to return 200
    with an empty array instead of failing.
    """
    out = []
    for g in catalog:
        if g.category != category:
            continue

        cs = color_score(g.color_lab, palette_labs)
        bs, body_reasons = body_score(g, profile)
        os_ = occasion_score(g, occasion)
        ss = season_score(g, season)
        score = round(
            _COLOR_WEIGHT * cs
            + _BODY_WEIGHT * bs
            + _OCCASION_WEIGHT * os_
            + _SEASON_WEIGHT * ss,
            3,
        )

        # A raw CIELab color match can be a coincidence -- a winter garment
        # can happen to sit near an autumn palette color. Only credit the
        # shopper-facing "palette match" line when we're not positively
        # off-season for their color season; otherwise it would be an
        # honest-sounding claim the garment doesn't actually back up.
        is_off_season = ss == SEASON_OFF_SEASON_PENALTY
        reasons = list(body_reasons)
        if cs > 0.7 and not is_off_season:
            reasons.insert(0, _color_match_reason(season))
        reasons = reasons[:_MAX_REASONS] or [_FALLBACK_REASON]

        out.append({"garment": g, "score": score, "reasons": reasons})

    out.sort(key=lambda r: r["score"], reverse=True)
    return out

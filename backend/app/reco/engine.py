"""Recommendation engine: turns a shopper's diagnosis into a ranked rack.

Combines the four scorers (color, body, occasion, season) into a single
weighted score per garment, docks the garments whose colour the shopper's
season told them to skip, filters to the requested category and sorts
descending -- the exact order, and the exact percentages, the kiosk shows
on the shop screen.
"""

from app.reco.catalog import Garment
from app.reco.scorers import (
    SEASON_OFF_SEASON_PENALTY,
    body_score,
    color_score,
    is_avoided_color,
    occasion_score,
    season_avoid_labs,
    season_matches,
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

# Charged to a garment in a colour the shopper's season told them to skip
# (see scorers.SEASON_AVOID_HEXES). A flat deduction off the weighted total
# rather than a fifth weighted facet, for two reasons:
#
#  - The four facets each answer "how well does this suit you?" on a
#    sliding scale. This one answers "did the profile screen already tell
#    you not to wear this?" -- a yes/no verdict, and a flat price is the
#    honest shape for it.
#  - Its cost must not shrink for the pieces the advice actually targets.
#    An avoided colour is off-palette by construction, so it was scoring
#    near-zero on colour anyway; anything folded into the colour facet
#    would have cost it almost nothing.
#
# 0.30 is a shade more than the off-season penalty costs (0.25 * 0.85 =
# 0.21), because an explicit "skip this shade" line the shopper read is
# stronger evidence than a season tag on a garment. It stays a penalty and
# not a filter: an avoided piece keeps its body/occasion/season credit,
# stays on the rack, and can still be shown -- and can still come first if
# the store has nothing better, which is the honest answer when it doesn't.
_AVOIDED_COLOR_PENALTY = 0.30

_MAX_REASONS = 2
# Final safety net: body_score already guarantees at least one reason, but
# this keeps the kiosk from ever rendering an empty reasons list if that
# contract is ever loosened.
_FALLBACK_REASON = "A strong match for you"

# How many garments the fitting room should always have to show. Four fills
# the rail beside the try-on preview without scrolling; below that the
# screen looks like the recommendation failed rather than like the store is
# genuinely thin on, say, Autumn wedding-guest dresses.
_MIN_RESULTS = 4


def _color_match_reason(season: str | None) -> str:
    return f"{season} palette match" if season else "Your palette match"


def rank(
    profile: BodyProfile,
    palette_labs: list[list[float]],
    category: str,
    occasion: str,
    catalog: list[Garment],
    season: str | None = None,
    min_results: int = _MIN_RESULTS,
) -> list[dict]:
    """Score and rank the catalog's garments in `category` for this shopper.

    Season and occasion are FILTERS, not just scoring terms: a shopper who
    picks "work" is asking to see work clothes, and a rack that merely
    reorders the same 13 items reads as broken. Each result carries
    `"exact": True` when the garment matches both, so the kiosk can label
    the near-matches it falls back to.

    That fallback is the other half of the contract: with 40 garments split
    across 3 categories, 4 seasons and 4 occasions, some combinations have
    only one or two exact matches. Rather than show an empty rail, the best
    remaining garments in the category fill up to `min_results`, flagged
    `"exact": False` so the screen can say so plainly.

    Returns `{"garment": Garment, "score": float, "reasons": list[str],
    "exact": bool}` dicts, sorted by score descending -- the single order
    the rack is displayed in (see the sort at the bottom). A `category`
    matching nothing yields an empty list rather than an error -- callers
    (the /recommend route) rely on this to return 200 with an empty array
    instead of failing.
    """
    # The shades this shopper's season told them to skip, on the profile
    # screen they saw two screens ago. Ranking has to read the same advice
    # the shopper read, or the rack contradicts it.
    avoid_labs = season_avoid_labs(season)

    exact: list[dict] = []
    near: list[dict] = []
    for g in catalog:
        if g.category != category:
            continue

        cs = color_score(g.color_lab, palette_labs)
        bs, body_reasons = body_score(g, profile)
        os_ = occasion_score(g, occasion)
        ss = season_score(g, season)
        avoided = is_avoided_color(g.color_lab, palette_labs, avoid_labs)
        score = round(
            max(
                0.0,
                _COLOR_WEIGHT * cs
                + _BODY_WEIGHT * bs
                + _OCCASION_WEIGHT * os_
                + _SEASON_WEIGHT * ss
                - (_AVOIDED_COLOR_PENALTY if avoided else 0.0),
            ),
            3,
        )

        # A raw CIELab color match can be a coincidence -- a winter garment
        # can happen to sit near an autumn palette color. Only credit the
        # shopper-facing "palette match" line when we're not positively
        # off-season for their color season; otherwise it would be an
        # honest-sounding claim the garment doesn't actually back up.
        #
        # `avoided` is the same principle applied to the colour itself: a
        # garment we are marking down *for its colour* must never be sold to
        # the shopper on the strength of that colour. (Under the season
        # palettes we ship this can't fire -- an avoided colour is too far
        # from the palette to clear 0.7 -- but `palette_labs` comes off the
        # request body, so the claim is guarded rather than assumed.)
        is_off_season = ss == SEASON_OFF_SEASON_PENALTY
        reasons = list(body_reasons)
        if cs > 0.7 and not is_off_season and not avoided:
            reasons.insert(0, _color_match_reason(season))
        reasons = reasons[:_MAX_REASONS] or [_FALLBACK_REASON]

        is_exact = season_matches(g, season) and occasion in g.occasion_tags
        rec = {"garment": g, "score": score, "reasons": reasons, "exact": is_exact}
        (exact if is_exact else near).append(rec)

    exact.sort(key=lambda r: r["score"], reverse=True)
    near.sort(key=lambda r: r["score"], reverse=True)

    # Grouping and ordering are two different jobs, and conflating them was
    # the bug. The exact/near split decides WHICH garments make the rack:
    # every exact match, plus the best near-matches needed to fill it to
    # `min_results` -- so a thin filter combination still returns something
    # and the backfill is still the best of what's left.
    shortfall = max(0, min_results - len(exact))
    results = exact + near[:shortfall]

    # ...but the ORDER is one descending run over the score printed on the
    # card. Returning the groups back to back put a 71% exact match above an
    # 89% near-match, and a rail that isn't sorted by its own visible
    # percentages reads as broken -- shoppers see both numbers at once.
    # Nothing is lost by re-sorting: the exact/near distinction survives on
    # each result's `exact` flag, which the kiosk renders as a per-card
    # "Close" badge rather than as position. Python's sort is stable, so
    # equal scores keep exact matches ahead of the near-matches they tie
    # with, which is the only place the distinction can still break a tie.
    results.sort(key=lambda r: r["score"], reverse=True)
    return results

import itertools
import math
import re
from pathlib import Path

import pytest

from app.reco.catalog import Garment, hex_to_lab
from app.reco.scorers import (
    AVOID_SAME_SHADE_DE,
    SEASON_AVOID_HEXES,
    SEASON_MATCH,
    SEASON_NEUTRAL,
    SEASON_OFF_SEASON_PENALTY,
    body_score,
    color_score,
    is_avoided_color,
    occasion_score,
    season_avoid_labs,
    season_score,
)
from app.schemas import BodyProfile
from app.youcam.color import _SEASON_PALETTES


def _g(**kw):
    base = dict(
        id="x", name="x", category="dress", image_url="", price=0,
        color_hex="#000000", color_lab=[45, 12, 22], season_tags=["autumn"],
        silhouette={"waist": "defined", "fabric": "soft", "structured": False, "neckline": "v"},
        occasion_tags=["date night"], location="", sizes_in_stock=["M"], buy_url="#",
    )
    base.update(kw)
    return Garment(**base)


def _profile(japanese="wave", fruit="hourglass"):
    return BodyProfile(
        fruit=fruit, japanese=japanese,
        japanese_weights={"straight": 0.2, "wave": 0.6, "natural": 0.2},
        confidence=0.6, summary="x",
    )


# --- brief's four required tests, verbatim ---

def test_color_score_high_for_near_color():
    assert color_score([45, 12, 22], [[46, 11, 23]]) > 0.9


def test_color_score_low_for_far_color():
    assert color_score([45, 12, 22], [[80, -20, -30]]) < 0.5


def test_body_score_rewards_wave_friendly_garment():
    s, reasons = body_score(
        _g(silhouette={"waist": "defined", "fabric": "soft", "structured": False, "neckline": "round"}),
        _profile("wave"),
    )
    assert s > 0.5 and any("waist" in r.lower() for r in reasons)


def test_occasion_score_matches_tag():
    assert occasion_score(_g(occasion_tags=["work"]), "work") == 1.0
    assert occasion_score(_g(occasion_tags=["work"]), "date night") < 1.0


def test_body_score_falls_back_safely_for_unknown_japanese_value():
    # `profile.japanese` is a plain str deserialised straight from the
    # /recommend request body -- a client can send anything. This must not
    # KeyError; it should behave like the "straight" fallback rule instead.
    profile = _profile(japanese="banana")
    score, reasons = body_score(_g(), profile)
    assert 0.0 <= score <= 1.0
    assert len(reasons) >= 1


# --- color_score: robustness (clamping, empty palette, closest-match) ---

def test_color_score_identical_color_is_exactly_one():
    assert color_score([50, 10, 10], [[50, 10, 10]]) == 1.0


def test_color_score_empty_palette_is_neutral():
    # No skin-tone palette to compare against -> neither reward nor punish.
    assert color_score([45, 12, 22], []) == 0.5


def test_color_score_clamps_to_zero_for_extremely_far_color():
    s = color_score([0, -100, -100], [[100, 100, 100]])
    assert s == 0.0


def test_color_score_always_within_unit_interval():
    # Sweep a range of distances and make sure nothing ever escapes [0, 1].
    garment = [45, 12, 22]
    palettes = [
        [[45, 12, 22]],
        [[46, 11, 23]],
        [[80, -20, -30]],
        [[0, -100, -100]],
        [[100, 100, 100]],
        [],
    ]
    for p in palettes:
        s = color_score(garment, p)
        assert 0.0 <= s <= 1.0


def test_color_score_picks_closest_palette_entry():
    # A far color plus a near-identical one should score high: the best
    # (minimum-distance) match wins, not an average or the first entry.
    assert color_score([45, 12, 22], [[80, -20, -30], [46, 11, 23]]) > 0.9


# --- body_score: pants / neckline "n/a" must be neutral, not penalised ---

def test_body_score_neckline_na_is_neutral_for_pants():
    # fruit="pear" deliberately does NOT trigger the waist-definition bonus,
    # so the only thing separating these two garments' scores is the
    # neckline -- keeping both scores well under the 1.0 cap.
    profile = _profile(japanese="straight", fruit="pear")
    pants = _g(
        category="pants",
        silhouette={"waist": "defined", "fabric": "structured", "structured": True, "neckline": "n/a"},
    )
    top_with_matching_neckline = _g(
        category="top",
        silhouette={"waist": "defined", "fabric": "structured", "structured": True, "neckline": "v"},
    )
    s_pants, r_pants = body_score(pants, profile)
    s_top, r_top = body_score(top_with_matching_neckline, profile)

    # The v-neck earns an extra styling point that "n/a" cannot possibly
    # earn or lose -- pants aren't docked for lacking a neckline.
    assert s_top > s_pants
    assert s_pants > 0.5
    assert not any("neckline" in r.lower() or "v-neck" in r.lower() for r in r_pants)


def test_body_score_neckline_na_does_not_crash_for_any_japanese_type():
    pants = _g(
        category="pants",
        silhouette={"waist": "relaxed", "fabric": "light", "structured": False, "neckline": "n/a"},
    )
    for jp in ("straight", "wave", "natural"):
        s, reasons = body_score(pants, _profile(japanese=jp))
        assert 0.0 <= s <= 1.0
        assert len(reasons) >= 1


# --- reasons: user-facing copy, never empty, across every combination ---

# Fabrics deliberately chosen to NOT belong to the japanese type under test
# (per the styling rules: straight <- crisp/structured/smooth,
# wave <- soft/draping/light, natural <- textured/natural/chunky), and
# structured/waist/neckline chosen so no bonus condition fires either --
# this forces the fallback path on every iteration.
_MISMATCHED_FABRIC = {"straight": "chunky", "wave": "structured", "natural": "smooth"}
_MISMATCHED_STRUCTURED = {"straight": False, "wave": True, "natural": True}
_JAPANESE_TYPES = ("straight", "wave", "natural")
_FRUITS = ("pear", "apple", "hourglass", "rectangle", "inverted-triangle")


@pytest.mark.parametrize("japanese,fruit", list(itertools.product(_JAPANESE_TYPES, _FRUITS)))
def test_reasons_never_empty_across_every_combination(japanese, fruit):
    garment = _g(
        silhouette={
            "waist": "regular",  # avoids the waist-definition bonus entirely
            "fabric": _MISMATCHED_FABRIC[japanese],
            "structured": _MISMATCHED_STRUCTURED[japanese],
            "neckline": "boat",  # doesn't match any type's preferred neckline
        }
    )
    score, reasons = body_score(garment, _profile(japanese=japanese, fruit=fruit))
    assert isinstance(reasons, list)
    assert len(reasons) >= 1
    assert all(isinstance(r, str) and r.strip() for r in reasons)


def test_reasons_are_never_empty_for_pants_fallback_either():
    pants = _g(
        category="pants",
        silhouette={"waist": "regular", "fabric": "chunky", "structured": False, "neckline": "n/a"},
    )
    for japanese, fruit in itertools.product(_JAPANESE_TYPES, _FRUITS):
        _, reasons = body_score(pants, _profile(japanese=japanese, fruit=fruit))
        assert len(reasons) >= 1


# --- season_score: the bug fix (season_tags were never scored) ---------


def test_season_score_matches_is_full_score():
    assert season_score(_g(season_tags=["autumn"]), "Autumn") == SEASON_MATCH


def test_season_score_matches_case_insensitively():
    assert season_score(_g(season_tags=["Autumn"]), "autumn") == SEASON_MATCH
    assert season_score(_g(season_tags=["autumn"]), "AUTUMN") == SEASON_MATCH


def test_season_score_mismatch_is_a_soft_penalty_not_zero():
    s = season_score(_g(season_tags=["winter"]), "Autumn")
    assert s == SEASON_OFF_SEASON_PENALTY
    assert 0.0 < s < SEASON_NEUTRAL, "off-season must be discouraged, not disqualifying"


def test_season_score_any_tag_match_counts_as_in_season():
    # A garment can legitimately belong to more than one season -- only one
    # of its tags needs to match the shopper's season.
    assert season_score(_g(season_tags=["winter", "autumn"]), "Autumn") == SEASON_MATCH


def test_season_score_no_season_given_is_neutral_not_punitive():
    # The kiosk's colour analysis can fail and fall back to no/default
    # season -- that must not tank every garment's score.
    assert season_score(_g(season_tags=["winter"]), None) == SEASON_NEUTRAL
    assert season_score(_g(season_tags=["winter"]), "") == SEASON_NEUTRAL


def test_season_score_no_season_tags_on_garment_is_neutral():
    # An untagged/cross-season garment (e.g. a neutral basic) shouldn't be
    # penalised just because it carries no season_tags at all.
    assert season_score(_g(season_tags=[]), "Autumn") == SEASON_NEUTRAL


def test_season_score_always_within_unit_interval():
    for tags in ([], ["autumn"], ["winter"], ["spring", "summer"]):
        for season in (None, "", "Autumn", "Winter", "banana"):
            s = season_score(_g(season_tags=tags), season)
            assert 0.0 <= s <= 1.0


# --- avoided colours: the shades the profile screen says to skip -------


def test_season_avoid_labs_resolves_the_season_family():
    assert season_avoid_labs("Summer") == season_avoid_labs("Soft Summer")
    assert season_avoid_labs("Fall") == season_avoid_labs("autumn")
    assert len(season_avoid_labs("Winter")) == len(SEASON_AVOID_HEXES["winter"])


def test_season_avoid_labs_is_empty_without_a_season_we_can_place():
    # Same stance season_score takes: no signal, so no penalty. We only
    # dock a shopper for a colour we're sure we told them to avoid.
    for season in (None, "", "banana"):
        assert season_avoid_labs(season) == []


def test_is_avoided_color_catches_the_same_shade_by_another_name():
    # Gold sits ~14 from the mustard a Summer is told to skip -- the same
    # colour on a rail, under a different word on the tag.
    avoid = season_avoid_labs("Summer")
    assert is_avoided_color(hex_to_lab("#C9A54C"), [], avoid) is True


def test_is_avoided_color_leaves_a_merely_adjacent_colour_alone():
    # Navy is ~26 from black: not the shade Summer was warned off, and a
    # colour that season genuinely wears. A radius that swallowed it would
    # be a filter on half the store rather than an honest warning.
    avoid = season_avoid_labs("Summer")
    assert is_avoided_color(hex_to_lab("#24304F"), [], avoid) is False


def test_is_avoided_color_defers_to_the_shoppers_own_palette():
    # If the palette we showed the shopper contains the shade, that promise
    # wins -- we never punish someone for wearing what we recommended.
    avoid = season_avoid_labs("Summer")
    mustard = hex_to_lab("#C9A227")
    assert is_avoided_color(mustard, [], avoid) is True
    assert is_avoided_color(mustard, [mustard], avoid) is False


def test_is_avoided_color_is_false_without_an_avoid_list():
    assert is_avoided_color([45, 12, 22], [[45, 12, 22]], []) is False
    assert is_avoided_color([45, 12, 22], [[45, 12, 22]], None) is False


def test_color_score_ignores_avoidance_and_stays_a_pure_palette_distance():
    # The avoid verdict is priced by `rank()`, deliberately not folded in
    # here (see color_score's docstring) -- this pins that split so a future
    # change has to be a decision rather than an accident.
    mustard = hex_to_lab("#C9A227")
    assert color_score(mustard, [mustard]) == 1.0


def test_no_season_both_recommends_and_warns_against_the_same_shade():
    # The self-contradiction this table was fixed to remove: a season whose
    # palette contains (near enough) a colour its own "Skip" list warns
    # against argues with itself on one screen, and leaves `rank()` unable
    # to tell which of the two promises to keep.
    #
    # The bar is twice the same-shade radius: with that much clear air
    # between a recommended colour and a warned one, the triangle
    # inequality says no garment can read as both.
    min_separation = 2 * AVOID_SAME_SHADE_DE
    for season, palette in _SEASON_PALETTES.items():
        family = season.lower()
        palette_labs = [hex_to_lab(h) for h in palette]
        for avoid_hex in SEASON_AVOID_HEXES[family]:
            avoid_lab = hex_to_lab(avoid_hex)
            nearest = min(math.dist(avoid_lab, p) for p in palette_labs)
            assert nearest >= min_separation, (
                f"{season} tells the shopper to skip {avoid_hex} while "
                f"recommending a colour {nearest:.1f} away from it"
            )


def test_no_garment_can_be_both_a_palette_colour_and_an_avoided_one():
    # The consequence of the invariant above, stated the way `rank()`
    # experiences it, over the palettes the kiosk actually serves.
    for season, palette in _SEASON_PALETTES.items():
        palette_labs = [hex_to_lab(h) for h in palette]
        avoid_labs = season_avoid_labs(season)
        for lab in palette_labs:
            assert is_avoided_color(lab, palette_labs, avoid_labs) is False


_STYLE_RULES_TS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "styleRules.ts"
)


def _frontend_skip_hexes() -> dict[str, list[str]]:
    """The `SEASON_RULES[*].skip` hexes, read out of the frontend source."""
    src = _STYLE_RULES_TS.read_text()
    table = src.split("const SEASON_RULES", 1)[1]
    out: dict[str, list[str]] = {}
    for season, block in re.findall(
        r"^  (\w+): \{(.*?)^  \},", table, re.S | re.M
    ):
        skip = re.search(r"skip: \[(.*?)\]", block, re.S)
        out[season] = [h.upper() for h in re.findall(r'hex: "(#[0-9a-fA-F]{6})"', skip.group(1))]
    return out


def test_frontend_skip_list_mirrors_the_backend_avoid_table():
    # The shopper reads these colours off the profile screen (frontend) and
    # the rack is ranked against them (backend). Two copies of one piece of
    # advice is a contradiction waiting to happen, so the copies are pinned
    # to each other here -- a swatch changed on one side without the other
    # fails this test rather than quietly recommending what it warns about.
    if not _STYLE_RULES_TS.exists():
        pytest.skip("frontend checkout not present")
    frontend = _frontend_skip_hexes()
    backend = {k: [h.upper() for h in v] for k, v in SEASON_AVOID_HEXES.items()}
    assert frontend == backend


def test_reasons_read_as_short_user_facing_copy():
    # Shown directly on the kiosk screen: no debug text, no raw field
    # names/underscores, no trailing periods, reasonably short.
    _, reasons = body_score(
        _g(silhouette={"waist": "defined", "fabric": "soft", "structured": False, "neckline": "round"}),
        _profile("wave"),
    )
    for r in reasons:
        assert not r.endswith(".")
        assert "_" not in r
        assert len(r) <= 60

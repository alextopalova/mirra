import itertools

import pytest

from app.reco.catalog import Garment
from app.reco.scorers import body_score, color_score, occasion_score
from app.schemas import BodyProfile


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

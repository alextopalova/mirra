import itertools

from app.reco.catalog import Garment, hex_to_lab, load_catalog
from app.reco.engine import rank
from app.reco.scorers import SEASON_AVOID_HEXES, is_avoided_color, season_avoid_labs
from app.schemas import BodyProfile

# The four seasons' palettes as the kiosk actually serves them, so the
# rack-level guarantees below are checked against what a real shopper gets
# rather than a synthetic palette. Imported rather than copied so a palette
# tweak can't quietly stop being covered.
from app.youcam.color import _SEASON_PALETTES

_CATEGORIES = ("dress", "top", "pants")
_OCCASIONS = ("everyday", "work", "date night", "wedding guest")


def _p(fruit="hourglass", japanese="wave"):
    return BodyProfile(
        fruit=fruit, japanese=japanese,
        japanese_weights={"straight": 0.2, "wave": 0.6, "natural": 0.2},
        confidence=0.6, summary="x",
    )


def _g(id_, color_hex="#8C5A3C", **kw):
    """A synthetic garment.

    Used wherever a test needs two garments that differ in exactly one
    respect. The store catalog is real inventory that changes underneath
    these tests, so anything asserting a precise ordering builds its own
    two-item rack instead of hunting for a convenient pair in it.
    """
    base = dict(
        id=id_, name=id_, category="dress", image_url="", price=0,
        color_hex=color_hex, color_lab=hex_to_lab(color_hex),
        season_tags=["autumn"],
        silhouette={"waist": "defined", "fabric": "soft", "structured": False, "neckline": "v"},
        occasion_tags=["everyday"], location="", sizes_in_stock=["M"], buy_url="#",
    )
    base.update(kw)
    return Garment(**base)


# --- brief's test (verbatim contract) ---------------------------------

def test_rank_filters_category_and_sorts():
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "dress", "date night", cat)
    assert all(r["garment"].category == "dress" for r in recs)
    scores = [r["score"] for r in recs]
    assert scores == sorted(scores, reverse=True)


# --- additional behavioral coverage ------------------------------------

def test_rank_unknown_category_returns_empty_list():
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "shoes", "date night", cat)
    assert recs == []


def test_rank_scores_within_unit_interval():
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "top", "everyday", cat)
    assert recs, "expected some tops in the seed catalog"
    for r in recs:
        assert 0.0 <= r["score"] <= 1.0


def test_rank_reasons_never_empty_and_capped_at_two():
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "pants", "work", cat)
    assert recs, "expected some pants in the seed catalog"
    for r in recs:
        assert 1 <= len(r["reasons"]) <= 2


def test_rank_season_prefixed_reason_for_strong_color_match():
    cat = load_catalog()
    # A garment's actual color_lab, passed back in as the sole palette
    # entry, guarantees a near-perfect (>0.7) color_score for that garment.
    dresses = [g for g in cat if g.category == "dress"]
    target = dresses[0]
    recs = rank(_p(), [target.color_lab], "dress", "date night", cat, season="Autumn")
    match = next(r for r in recs if r["garment"].id == target.id)
    assert "Autumn" in match["reasons"][0]
    assert "palette match" in match["reasons"][0].lower()


def test_rank_without_season_falls_back_to_generic_color_reason():
    cat = load_catalog()
    dresses = [g for g in cat if g.category == "dress"]
    target = dresses[0]
    recs = rank(_p(), [target.color_lab], "dress", "date night", cat)
    match = next(r for r in recs if r["garment"].id == target.id)
    assert any("palette match" in r.lower() for r in match["reasons"])


# --- season-aware ranking (the bug fix: season_tags were never scored) --


def test_rank_in_season_garment_outranks_off_season_on_raw_color_alone():
    # Two identical dresses but for their season tag. Handing the winter
    # one's *own* colour back in as the sole palette entry gives it a
    # perfect color_score (1.0) while the in-season one only gets a partial
    # one -- yet the season term must still stop the off-season garment
    # from winning on colour alone.
    #
    # Both colours are deliberately mid-palette Autumn shades, well clear of
    # anything Autumn is told to skip: this test is about the season term,
    # and the avoided-colour penalty is a large enough deduction to mask it
    # if the two effects are allowed to land on the same garment.
    in_season = _g("in", color_hex="#8C5A3C", season_tags=["autumn"])
    off_season = _g("off", color_hex="#B0463C", season_tags=["winter"])
    recs = rank(
        _p(), [off_season.color_lab], "dress", "everyday",
        [in_season, off_season], season="Autumn",
    )
    by_id = {r["garment"].id: r for r in recs}
    assert by_id["off"]["score"] < by_id["in"]["score"]


def test_rank_does_not_claim_palette_match_for_off_season_item():
    # Even when an off-season garment's raw color is a near-perfect match
    # (color_score > 0.7), the kiosk must not tell the shopper it's a
    # palette match for their season -- that would be a false claim.
    #
    # Built from two synthetic dresses rather than picked out of the store
    # catalog. This used to name a known winter dress and rely on the
    # Autumn/everyday/dress cell staying thin enough for `rank` to backfill
    # that dress into the rack. Restocking the catalog filled the cell, the
    # dress was correctly filtered out, and the test failed for a reason
    # that had nothing to do with the claim it checks.
    off_season = _g("off", color_hex="#B0463C", season_tags=["winter"])
    in_season = _g("in", color_hex="#8C5A3C", season_tags=["autumn"])
    recs = rank(
        _p(), [off_season.color_lab], "dress", "everyday",
        [in_season, off_season], season="Autumn",
    )
    match = next(r for r in recs if r["garment"].id == "off")
    assert not any("palette match" in r.lower() for r in match["reasons"])


def test_rank_unknown_season_does_not_penalize_any_garment():
    # No season signal (e.g. color analysis fell back to a default) must
    # be neutral, not punitive -- scores should match the no-season-term
    # ordering rather than collapsing everything toward the off-season
    # penalty.
    cat = load_catalog()
    with_season = rank(_p(), [[45, 12, 22]], "dress", "everyday", cat, season=None)
    without_season = rank(_p(), [[45, 12, 22]], "dress", "everyday", cat)
    assert [r["garment"].id for r in with_season] == [
        r["garment"].id for r in without_season
    ]
    assert [r["score"] for r in with_season] == [r["score"] for r in without_season]


def test_rank_season_changes_the_ordering():
    # If the season term were too weak, switching the shopper's season
    # would barely move the ranking. Autumn and Winter shoppers should get
    # a meaningfully different top pick for the same catalog/profile.
    cat = load_catalog()
    palette = [[45, 12, 22]]  # a neutral-ish mid brown, no strong bias
    autumn_top = rank(_p(), palette, "dress", "everyday", cat, season="Autumn")[0]
    winter_top = rank(_p(), palette, "dress", "everyday", cat, season="Winter")[0]
    assert autumn_top["garment"].id != winter_top["garment"].id
    assert "autumn" in [t.lower() for t in autumn_top["garment"].season_tags]
    assert "winter" in [t.lower() for t in winter_top["garment"].season_tags]


def test_rank_filters_to_the_shoppers_season_and_occasion():
    # Season and occasion are hard filters now: an Autumn shopper asking for
    # everyday dresses must not be shown Winter-only pieces as if they
    # matched. Anything that survives is either a genuine match or is
    # explicitly flagged as a near-match (see the next test).
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "dress", "everyday", cat, season="Autumn")
    for r in recs:
        if not r["exact"]:
            continue
        g = r["garment"]
        assert not g.season_tags or "autumn" in [t.lower() for t in g.season_tags]
        assert "everyday" in g.occasion_tags


# --- ordering: one descending run over the score on the card -----------
#
# Replaces an earlier test that asserted exact matches came before
# near-matches as a *group*. That grouping is what put a 71% exact match
# above an 89% near-match on screen, next to both percentages -- the rack
# visibly wasn't sorted by its own numbers. The exact/near distinction now
# lives entirely on each result's `exact` flag (rendered as a per-card
# "Close" badge), never on position.


def test_rank_orders_the_whole_rack_by_the_score_on_the_card():
    cat = load_catalog()
    for category, occasion, season in itertools.product(
        _CATEGORIES, _OCCASIONS, (None, "Autumn", "Summer", "Soft Winter")
    ):
        recs = rank(_p(), [[45, 12, 22]], category, occasion, cat, season=season)
        scores = [r["score"] for r in recs]
        assert scores == sorted(scores, reverse=True), (category, occasion, season)


def test_rank_puts_a_higher_scoring_near_match_above_a_lower_scoring_exact_match():
    # The bug in its purest form. `near` is a worse fit for the occasion
    # (so it's flagged as a near-match) but a far better fit for the body,
    # which the weights say matters more -- so it scores higher and must be
    # shown higher, while still carrying `exact: False` for its badge.
    exact = _g(
        "exact",
        occasion_tags=["work"],
        silhouette={"waist": "regular", "fabric": "chunky", "structured": True, "neckline": "crew"},
    )
    near = _g(
        "near",
        occasion_tags=["everyday"],
        silhouette={"waist": "defined", "fabric": "soft", "structured": False, "neckline": "v"},
    )
    recs = rank(_p(), [[45, 12, 22]], "dress", "work", [exact, near], season="Autumn")

    assert [r["garment"].id for r in recs] == ["near", "exact"]
    assert recs[0]["score"] > recs[1]["score"]
    assert recs[0]["exact"] is False and recs[1]["exact"] is True


def test_rank_still_flags_and_backfills_near_matches_after_the_re_sort():
    # Sorting the whole rack by score must not cost the near-matches their
    # flag or their place on a thin rack -- that flag is the only thing the
    # kiosk has left to draw the "Close" badge from.
    exact = _g("exact", occasion_tags=["work"])
    near = _g("near", occasion_tags=["everyday"], season_tags=["winter"])
    recs = rank(_p(), [[45, 12, 22]], "dress", "work", [exact, near], season="Autumn")

    by_id = {r["garment"].id: r for r in recs}
    assert set(by_id) == {"exact", "near"}
    assert by_id["exact"]["exact"] is True
    assert by_id["near"]["exact"] is False


def test_rank_backfills_a_thin_rack_rather_than_returning_almost_nothing():
    # "Wedding guest" + a season is the thinnest realistic combination in a
    # 40-piece catalog. The shopper must still get a rack to look at, and
    # every backfilled piece must be labelled as a near-match rather than
    # passed off as a hit.
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "dress", "wedding guest", cat, season="Autumn")
    dresses = [g for g in cat if g.category == "dress"]
    assert len(recs) >= min(4, len(dresses))
    exact_ids = {r["garment"].id for r in recs if r["exact"]}
    for r in recs:
        if r["garment"].id not in exact_ids:
            assert r["exact"] is False


def test_rank_matches_a_twelve_season_name_against_plain_catalog_tags():
    # The colour analysis returns names like "Soft Summer"; catalog tags are
    # always the plain family. Comparing the two strings directly filed
    # every 12-season shopper as off-season for the entire catalog.
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "dress", "everyday", cat, season="Soft Summer")
    assert any(r["exact"] for r in recs)
    for r in recs:
        if r["exact"] and r["garment"].season_tags:
            assert "summer" in [t.lower() for t in r["garment"].season_tags]


# --- avoided colours: the rack must not contradict the profile screen ---
#
# The "Skip" list on the profile screen used to be frontend-only, so the
# very next screen could put one of those shades at the top of the rail
# with a match percentage beside it.


def _real_shopper_racks():
    """Every (season, category, occasion) rack a shopper can actually get.

    Yields `(season, palette_labs, avoid_labs, recs)`. Uses the shipped
    season palettes and the live catalog, so these assertions are about
    what the kiosk really shows, not a contrived palette.
    """
    cat = load_catalog()
    for season, hexes in _SEASON_PALETTES.items():
        palette_labs = [hex_to_lab(h) for h in hexes]
        avoid_labs = season_avoid_labs(season)
        for category, occasion in itertools.product(_CATEGORIES, _OCCASIONS):
            recs = rank(_p(), palette_labs, category, occasion, cat, season=season)
            yield season, palette_labs, avoid_labs, recs


def test_rank_does_not_top_the_rack_with_a_colour_the_shopper_was_told_to_avoid():
    # The guarantee. Softened exactly where honesty requires it: if the
    # store has nothing in this category that isn't on the skip list, the
    # best of a bad rail is still the right answer -- showing an empty rack
    # would be worse and would break the never-empty contract.
    for season, palette_labs, avoid_labs, recs in _real_shopper_racks():
        if not recs:
            continue
        avoided = [
            r for r in recs
            if is_avoided_color(r["garment"].color_lab, palette_labs, avoid_labs)
        ]
        if len(avoided) == len(recs):
            continue  # nothing else to offer
        top = recs[0]["garment"]
        assert not is_avoided_color(top.color_lab, palette_labs, avoid_labs), (
            f"{season}: rack led with {top.name} ({top.color_hex}), a shade the "
            f"profile screen told this shopper to skip"
        )


def test_rank_never_claims_a_palette_match_for_a_colour_it_is_docking():
    # The reasons are shopper-facing copy. "Autumn palette match" on a
    # garment we are marking down for being off-palette is the app arguing
    # with itself in two places on the same card.
    for _season, palette_labs, avoid_labs, recs in _real_shopper_racks():
        for r in recs:
            if is_avoided_color(r["garment"].color_lab, palette_labs, avoid_labs):
                assert not any("palette match" in x.lower() for x in r["reasons"])


def test_rank_docks_an_avoided_colour_below_the_same_garment_in_a_good_colour():
    # Two identical dresses, one in a shade this season's advice skips.
    # Isolates the penalty from every other term.
    season = "Summer"
    avoided_hex = SEASON_AVOID_HEXES["summer"][0]
    good_hex = _SEASON_PALETTES[season][0]
    palette_labs = [hex_to_lab(h) for h in _SEASON_PALETTES[season]]
    catalog = [
        _g("avoided", color_hex=avoided_hex, season_tags=["summer"]),
        _g("good", color_hex=good_hex, season_tags=["summer"]),
    ]
    recs = rank(_p(), palette_labs, "dress", "everyday", catalog, season=season)

    assert [r["garment"].id for r in recs] == ["good", "avoided"]
    assert recs[1]["score"] < recs[0]["score"]


def test_rank_still_shows_an_avoided_colour_rather_than_emptying_the_rack():
    # A penalty, not a filter: a rail of nothing but skip-list colours still
    # comes back scored and ordered, with usable percentages on the cards.
    season = "Summer"
    catalog = [
        _g(f"a{i}", color_hex=h, season_tags=["summer"])
        for i, h in enumerate(SEASON_AVOID_HEXES["summer"])
    ]
    palette_labs = [hex_to_lab(h) for h in _SEASON_PALETTES[season]]
    recs = rank(_p(), palette_labs, "dress", "everyday", catalog, season=season)

    assert len(recs) == len(catalog)
    for r in recs:
        assert 0.0 <= r["score"] <= 1.0
        assert r["reasons"]


def test_rank_does_not_dock_a_colour_the_shoppers_own_palette_contains():
    # A palette arrives on the request body, so it can contradict the season
    # advice however the client likes. When it does, the colour we promised
    # the shopper wins: they must never be penalised for wearing a shade we
    # showed them as theirs.
    contradicting_hex = SEASON_AVOID_HEXES["summer"][1]  # in the palette below
    ordinary_hex = _SEASON_PALETTES["Summer"][0]
    palette_labs = [hex_to_lab(contradicting_hex), hex_to_lab(ordinary_hex)]
    catalog = [
        _g("contradicting", color_hex=contradicting_hex, season_tags=["summer"]),
        _g("ordinary", color_hex=ordinary_hex, season_tags=["summer"]),
    ]
    recs = rank(_p(), palette_labs, "dress", "everyday", catalog, season="Summer")

    # Both are exact palette colours for this shopper, so both are perfect
    # colour matches and nothing else separates them: identical scores.
    assert recs[0]["score"] == recs[1]["score"]

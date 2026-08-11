from app.reco.catalog import load_catalog
from app.reco.engine import rank
from app.schemas import BodyProfile


def _p(fruit="hourglass", japanese="wave"):
    return BodyProfile(
        fruit=fruit, japanese=japanese,
        japanese_weights={"straight": 0.2, "wave": 0.6, "natural": 0.2},
        confidence=0.6, summary="x",
    )


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
    # d1 "Wrap midi dress" is tagged autumn; d2 "Tailored shift dress" is
    # tagged winter. Handing the winter garment's *own* color back in as
    # the sole palette entry gives it a perfect color_score (1.0) while
    # the in-season garment only gets a partial one -- yet the season term
    # must still stop the off-season garment from winning on color alone.
    cat = load_catalog()
    dresses = {g.id: g for g in cat if g.category == "dress"}
    winter_dress = dresses["d2"]
    recs = rank(
        _p(), [winter_dress.color_lab], "dress", "everyday", cat, season="Autumn"
    )
    by_id = {r["garment"].id: r for r in recs}
    assert by_id["d2"]["score"] < by_id["d1"]["score"]


def test_rank_does_not_claim_palette_match_for_off_season_item():
    # Even when an off-season garment's raw color is a near-perfect match
    # (color_score > 0.7), the kiosk must not tell the shopper it's a
    # palette match for their season -- that would be a false claim.
    cat = load_catalog()
    dresses = {g.id: g for g in cat if g.category == "dress"}
    winter_dress = dresses["d2"]  # tagged winter, not autumn
    recs = rank(
        _p(), [winter_dress.color_lab], "dress", "everyday", cat, season="Autumn"
    )
    match = next(r for r in recs if r["garment"].id == "d2")
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


def test_rank_exact_matches_come_before_near_matches():
    cat = load_catalog()
    recs = rank(_p(), [[45, 12, 22]], "dress", "everyday", cat, season="Autumn")
    flags = [r["exact"] for r in recs]
    assert flags == sorted(flags, reverse=True)


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

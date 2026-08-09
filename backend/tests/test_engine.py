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
    assert any("colour match" in r.lower() for r in match["reasons"])

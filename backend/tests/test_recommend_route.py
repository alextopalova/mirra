import itertools

from fastapi.testclient import TestClient

from app.main import app
from app.reco.catalog import hex_to_lab
from app.reco.scorers import is_avoided_color, season_avoid_labs
from app.youcam.color import _SEASON_PALETTES

client = TestClient(app)

_BODY = {
    "profile": {
        "fruit": "hourglass", "japanese": "wave",
        "japanese_weights": {"straight": 0.2, "wave": 0.6, "natural": 0.2},
        "confidence": 0.6, "summary": "x",
    },
    "palette": {"season": "Autumn", "colors": ["#8C5A3C"]},
    "category": "dress", "occasion": "date night",
}


# --- brief's test (verbatim contract) -----------------------------------

def test_recommend_route_returns_sorted_dresses():
    r = client.post("/recommend", json=_BODY)
    assert r.status_code == 200
    data = r.json()
    assert all(x["garment"]["category"] == "dress" for x in data)
    scores = [x["score"] for x in data]
    assert scores == sorted(scores, reverse=True)


# --- additional behavioral coverage --------------------------------------

def test_recommend_route_unknown_category_returns_empty_array_not_500():
    body = {**_BODY, "category": "shoes"}
    r = client.post("/recommend", json=body)
    assert r.status_code == 200
    assert r.json() == []


def test_recommend_route_empty_category_returns_empty_array():
    body = {**_BODY, "category": ""}
    r = client.post("/recommend", json=body)
    assert r.status_code == 200
    assert r.json() == []


def test_recommend_route_orders_every_rack_by_the_score_it_returns():
    # End to end, over the season/occasion combinations thin enough to need
    # backfilling: the array the fitting room renders top to bottom must be
    # in descending order of the percentage it prints on each card. Sorting
    # exact matches ahead of near ones as a group used to break this.
    for season, colors in _SEASON_PALETTES.items():
        for category, occasion in itertools.product(
            ("dress", "top", "pants"),
            ("everyday", "work", "date night", "wedding guest"),
        ):
            body = {
                **_BODY,
                "palette": {"season": season, "colors": colors},
                "category": category,
                "occasion": occasion,
            }
            data = client.post("/recommend", json=body).json()
            scores = [x["score"] for x in data]
            assert scores == sorted(scores, reverse=True), (season, category, occasion)


def test_recommend_route_does_not_lead_with_a_colour_the_profile_said_to_skip():
    # The same guarantee the engine tests make, asserted on the payload the
    # kiosk actually receives -- the skip list reaching the ranking depends
    # on the route passing the season through.
    for season, colors in _SEASON_PALETTES.items():
        palette_labs = [hex_to_lab(c) for c in colors]
        avoid_labs = season_avoid_labs(season)
        for category in ("dress", "top", "pants"):
            body = {
                **_BODY,
                "palette": {"season": season, "colors": colors},
                "category": category,
                "occasion": "everyday",
            }
            data = client.post("/recommend", json=body).json()
            if not data:
                continue
            labs = [hex_to_lab(x["garment"]["color_hex"]) for x in data]
            if all(is_avoided_color(lab, palette_labs, avoid_labs) for lab in labs):
                continue  # the store has nothing better in this category
            assert not is_avoided_color(labs[0], palette_labs, avoid_labs), (
                season, category, data[0]["garment"]["name"]
            )


def test_recommend_route_response_shape_matches_frontend_contract():
    r = client.post("/recommend", json=_BODY)
    data = r.json()
    assert data, "expected some dress recommendations"
    for item in data:
        assert set(item.keys()) == {"garment", "score", "reasons", "exact"}
        assert isinstance(item["exact"], bool)
        assert isinstance(item["score"], (int, float))
        assert 0.0 <= item["score"] <= 1.0
        assert isinstance(item["reasons"], list)
        assert 1 <= len(item["reasons"]) <= 2
        g = item["garment"]
        for field in ("id", "name", "category", "image_url", "price",
                      "location", "sizes_in_stock", "buy_url"):
            assert field in g

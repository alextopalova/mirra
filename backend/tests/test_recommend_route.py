from fastapi.testclient import TestClient

from app.main import app

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

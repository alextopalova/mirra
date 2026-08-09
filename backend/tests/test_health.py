from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_garments_static_route_is_mounted():
    # Self-hosted garment images (backend/data/garments/<id>.jpg) are served
    # under this prefix -- see app/main.py.
    assert "/garments" in [r.path for r in app.routes]


def test_missing_garment_image_returns_clean_404():
    # A nonexistent file under the static mount is a plain 404, not a
    # crash -- and this doesn't touch/create anything under
    # backend/data/garments/, it's a read of a name that doesn't exist.
    r = client.get("/garments/definitely-not-a-real-garment-id-xyz.jpg")
    assert r.status_code == 404

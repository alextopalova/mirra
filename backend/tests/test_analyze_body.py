import base64
import os

from fastapi.testclient import TestClient

from app.main import app
from app.routers import body as body_router

client = TestClient(app)
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "person_front.jpg")


def _dataurl(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def test_analyze_body_returns_profile_and_palette():
    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX), "heightCm": 170, "weightKg": 62,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["fruit"]
    assert isinstance(body["palette"]["colors"], list)


def test_analyze_body_accepts_bare_base64_with_whitespace():
    # No "data:image/...;base64," prefix, and the payload has embedded
    # newlines (as a naive line-wrapped base64 blob might) -- both must be
    # tolerated, not just the clean dataURL form the frontend normally sends.
    with open(FIX, "rb") as f:
        raw_b64 = base64.b64encode(f.read()).decode()
    wrapped = "\n".join(raw_b64[i : i + 76] for i in range(0, len(raw_b64), 76))
    r = client.post("/analyze-body", json={
        "frontPhoto": wrapped, "heightCm": 170, "weightKg": 62,
    })
    assert r.status_code == 200
    assert r.json()["profile"]["fruit"]


def test_analyze_body_returns_422_not_500_on_measurement_validation_error(monkeypatch):
    # measure_from_images raises ValueError for recoverable, user-facing
    # problems (no person / body cropped / degenerate measurement). The
    # route must surface that as a helpful 422, not a bare 500.
    def _boom(*args, **kwargs):
        raise ValueError("full body not visible. Step back and retake the photo.")

    monkeypatch.setattr(body_router, "measure_from_images", _boom)
    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX), "heightCm": 170, "weightKg": 62,
    })
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail
    assert "full body not visible" in detail


def test_analyze_body_422_on_undecodable_image():
    # Valid base64, but the decoded bytes aren't a real image -- cv2.imdecode
    # returns None for this, which must not propagate into a 500.
    bogus = base64.b64encode(b"not an image, just some bytes").decode()
    r = client.post("/analyze-body", json={
        "frontPhoto": bogus, "heightCm": 170, "weightKg": 62,
    })
    assert r.status_code == 422
    assert r.json()["detail"]


def test_analyze_body_422_on_malformed_base64():
    r = client.post("/analyze-body", json={
        "frontPhoto": "data:image/jpeg;base64,not-valid-base64!!!",
        "heightCm": 170, "weightKg": 62,
    })
    assert r.status_code == 422
    assert r.json()["detail"]


def test_analyze_body_200_on_undecodable_side_photo():
    # sidePhoto is optional by product spec (kiosk has a "Skip side"
    # button, and the measurement code accepts side_bgr=None). An unusable
    # side photo must degrade to front-only analysis, not fail the scan.
    bogus = base64.b64encode(b"still not an image").decode()
    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX), "sidePhoto": bogus,
        "heightCm": 170, "weightKg": 62,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["fruit"]
    assert isinstance(body["palette"]["colors"], list)


def test_analyze_body_200_on_malformed_base64_side_photo():
    # Malformed base64 in sidePhoto is the other undecodable case (as
    # opposed to valid base64 that isn't a real image); it must also
    # degrade gracefully rather than 422.
    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX),
        "sidePhoto": "data:image/jpeg;base64,not-valid-base64!!!",
        "heightCm": 170, "weightKg": 62,
    })
    assert r.status_code == 200
    assert r.json()["profile"]["fruit"]


def test_analyze_body_front_only_path_still_used_when_side_photo_unusable(monkeypatch):
    # Confirm the analysis genuinely proceeds front-only (side_bgr=None),
    # not that some empty/short-circuited response is returned.
    seen = {}
    real_measure = body_router.measure_from_images

    def _spy(front_bgr, side_bgr, height_cm, weight_kg):
        seen["side_bgr"] = side_bgr
        return real_measure(front_bgr, side_bgr, height_cm, weight_kg)

    monkeypatch.setattr(body_router, "measure_from_images", _spy)

    bogus = base64.b64encode(b"still not an image").decode()
    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX), "sidePhoto": bogus,
        "heightCm": 170, "weightKg": 62,
    })

    assert r.status_code == 200
    assert seen["side_bgr"] is None
    assert r.json()["profile"]["fruit"]

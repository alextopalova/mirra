"""POST /analyze-body — real-mode Facial Color Tones wiring.

Mock mode's placeholder-palette behaviour is already covered by
tests/test_analyze_body.py. These tests cover the real-mode (use_mocks =
False) path: the endpoint must call app.youcam.color.analyze_color and
weave its result into the response, and colour-analysis failures must
never break the body scan (still 200, still a valid profile + palette).

No live network calls: app.youcam.color.YouCamClient is monkeypatched to a
client built on httpx.MockTransport, same pattern as test_tryon_route.py.
"""

import base64
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.youcam import color as color_mod
from app.youcam.client import YouCamClient

client = TestClient(app)
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "person_front.jpg")


def _dataurl(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


@pytest.fixture(autouse=True)
def _real_mode(monkeypatch):
    monkeypatch.setattr(settings, "use_mocks", False)
    monkeypatch.setattr(settings, "youcam_api_key", "sk-test-key")


def _mock_transport_client_factory(handler):
    return lambda: YouCamClient(transport=httpx.MockTransport(handler))


def _full_flow_handler(poll_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/skin-tone-analysis":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "files": [
                            {
                                "file_id": "face-file-1",
                                "requests": [
                                    {"method": "PUT", "url": "https://s3.example.com/put", "headers": {}}
                                ],
                            }
                        ]
                    }
                },
            )
        if request.method == "PUT" and str(request.url) == "https://s3.example.com/put":
            return httpx.Response(200)
        if request.method == "POST" and request.url.path == "/s2s/v2.0/task/skin-tone-analysis":
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        if request.method == "GET" and request.url.path == "/s2s/v2.0/task/skin-tone-analysis/task-1":
            return httpx.Response(200, json={"data": {"task_status": "success", **poll_payload}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def test_analyze_body_real_mode_uses_derived_palette(monkeypatch):
    handler = _full_flow_handler({"results": {"undertone": "warm", "depth": "light"}})
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX), "heightCm": 170, "weightKg": 62,
    })

    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["fruit"]
    assert body["palette"]["season"] == "Spring"
    assert isinstance(body["palette"]["colors"], list) and body["palette"]["colors"]


def test_analyze_body_real_mode_still_200_when_color_task_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/skin-tone-analysis":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "files": [
                            {
                                "file_id": "f1",
                                "requests": [{"method": "PUT", "url": "https://s3.example.com/put", "headers": {}}],
                            }
                        ]
                    }
                },
            )
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "POST" and request.url.path == "/s2s/v2.0/task/skin-tone-analysis":
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        return httpx.Response(
            200,
            json={"data": {"error": "error_face_not_forward_facing", "results": None, "task_status": "error"}},
        )

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX), "heightCm": 170, "weightKg": 62,
    })

    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["fruit"]
    assert isinstance(body["palette"]["colors"], list) and body["palette"]["colors"]


def test_analyze_body_real_mode_still_200_when_youcam_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/analyze-body", json={
        "frontPhoto": _dataurl(FIX), "heightCm": 170, "weightKg": 62,
    })

    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["fruit"]
    assert isinstance(body["palette"]["colors"], list) and body["palette"]["colors"]

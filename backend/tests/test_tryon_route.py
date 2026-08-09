"""POST /try-on — mock mode, real mode, and error-mapping tests.

No live network calls: app.youcam.vto.YouCamClient is monkeypatched to a
client built on httpx.MockTransport for every "real mode" test.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.youcam.client import YouCamClient

client = TestClient(app)

PERSON_DATAURL = "data:image/jpeg;base64,ZmFrZS1wZXJzb24tcGhvdG8tYnl0ZXM="


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    # Every test controls use_mocks explicitly; default to real mode being
    # opt-in per test so a forgotten flag doesn't silently hit mock mode.
    monkeypatch.setattr(settings, "youcam_api_key", "sk-test-key")


def _mock_transport_client_factory(handler):
    return lambda: YouCamClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------

def test_try_on_mock_mode_returns_placeholder_without_network(monkeypatch):
    monkeypatch.setattr(settings, "use_mocks", True)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"mock mode must not touch the network, got: {request.url}")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "d1"})

    assert r.status_code == 200
    assert r.json()["image"].startswith("http")


def test_try_on_unknown_garment_id_returns_placeholder_without_network(monkeypatch):
    # Real mode, but the garmentId doesn't exist in the catalog: documented
    # choice is to degrade to the placeholder rather than a hard 4xx, so a
    # kiosk shopper never sees a bare error for a stale/mistyped id.
    monkeypatch.setattr(settings, "use_mocks", False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unknown garmentId must not touch the network, got: {request.url}")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "does-not-exist"})

    assert r.status_code == 200
    assert r.json()["image"].startswith("http")


# ---------------------------------------------------------------------------
# Real mode — happy paths
# ---------------------------------------------------------------------------

def _full_flow_handler(results_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "files": [
                            {
                                "file_id": "person-file-1",
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
        if request.method == "POST" and request.url.path == "/s2s/v2.0/task/cloth":
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        if request.method == "GET" and request.url.path == "/s2s/v2.0/task/cloth/task-1":
            return httpx.Response(200, json={"data": {"status": "success", **results_payload}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def test_try_on_real_mode_object_shaped_results(monkeypatch):
    monkeypatch.setattr(settings, "use_mocks", False)
    handler = _full_flow_handler({"results": {"url": "https://result.example.com/obj.jpg"}})
    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "d1"})

    assert r.status_code == 200
    assert r.json() == {"image": "https://result.example.com/obj.jpg"}


def test_try_on_real_mode_list_shaped_results(monkeypatch):
    monkeypatch.setattr(settings, "use_mocks", False)
    handler = _full_flow_handler({"results": [{"url": "https://result.example.com/list.jpg"}]})
    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "p1"})

    assert r.status_code == 200
    assert r.json() == {"image": "https://result.example.com/list.jpg"}


# ---------------------------------------------------------------------------
# Real mode — error mapping
# ---------------------------------------------------------------------------

def test_try_on_task_failure_maps_to_503_with_shopper_message(monkeypatch):
    monkeypatch.setattr(settings, "use_mocks", False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                200,
                json={"data": {"files": [{"file_id": "f1", "requests": [{"method": "PUT", "url": "https://s3.example.com/put", "headers": {}}]}]}},
            )
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "POST" and request.url.path == "/s2s/v2.0/task/cloth":
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        return httpx.Response(
            200, json={"data": {"status": "error", "error": "SECRET-DEBUG-INFO sk-should-not-leak"}}
        )

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "d1"})

    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "try another item" in detail.lower() or "try again" in detail.lower()
    # Never leak the raw API error / API key into the shopper-facing response.
    assert "SECRET-DEBUG-INFO" not in detail
    assert "sk-" not in detail


def test_try_on_timeout_maps_to_503_with_shopper_message(monkeypatch):
    monkeypatch.setattr(settings, "use_mocks", False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                200,
                json={"data": {"files": [{"file_id": "f1", "requests": [{"method": "PUT", "url": "https://s3.example.com/put", "headers": {}}]}]}},
            )
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "POST" and request.url.path == "/s2s/v2.0/task/cloth":
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        return httpx.Response(200, json={"data": {"status": "running"}})

    def make_client():
        return YouCamClient(transport=httpx.MockTransport(handler))

    # Patch poll's defaults indirectly by monkeypatching YouCamClient.poll to
    # time out fast instead of the real 60-try/2.5s defaults (would make the
    # test take minutes otherwise). Capture the original unbound method
    # first so the replacement doesn't recurse into itself.
    _original_poll = YouCamClient.poll

    async def _fast_poll(self, task, task_id, interval=2.5, max_tries=60):
        return await _original_poll(self, task, task_id, interval=0, max_tries=2)

    monkeypatch.setattr("app.youcam.vto.YouCamClient", make_client)
    monkeypatch.setattr(YouCamClient, "poll", _fast_poll)

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "d1"})

    assert r.status_code == 503
    assert r.json()["detail"]


# ---------------------------------------------------------------------------
# Real mode — malformed photo
# ---------------------------------------------------------------------------

def test_try_on_malformed_person_photo_returns_422(monkeypatch):
    monkeypatch.setattr(settings, "use_mocks", False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not reach the network with undecodable photo data")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post(
        "/try-on",
        json={"personPhoto": "data:image/jpeg;base64,not-valid-base64!!!", "garmentId": "d1"},
    )

    assert r.status_code == 422

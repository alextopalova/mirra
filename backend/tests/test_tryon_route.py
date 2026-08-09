"""POST /try-on — mock mode, real mode, and error-mapping tests.

No live network calls: app.youcam.vto.YouCamClient is monkeypatched to a
client built on httpx.MockTransport for every "real mode" test.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.reco.catalog import Garment
from app.youcam.client import YouCamClient

client = TestClient(app)


def _fake_garment(**overrides) -> Garment:
    fields = {
        "id": "fake-1",
        "name": "Fake Garment",
        "category": "top",
        "image_url": "/garments/fake-1.jpg",
        "price": 100.0,
        "location": "Test · Aisle 1",
        "sizes_in_stock": ["S", "M"],
        "buy_url": "#",
        "color_hex": "#000000",
        "color_lab": [0.0, 0.0, 0.0],
        "season_tags": ["all"],
        "silhouette": {},
        "occasion_tags": ["everyday"],
    }
    fields.update(overrides)
    return Garment(**fields)

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


def test_try_on_unknown_garment_id_logs_warning_naming_the_id(monkeypatch, caplog):
    # A stale/mistyped frontend garmentId should be distinguishable from
    # mock mode in the logs, even though the shopper-facing behaviour
    # (placeholder) is unchanged.
    monkeypatch.setattr(settings, "use_mocks", False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("unknown garmentId must not touch the network")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    with caplog.at_level("WARNING", logger="app.routers.youcam"):
        r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "does-not-exist"})

    assert r.status_code == 200
    assert any(
        record.levelname == "WARNING" and "does-not-exist" in record.getMessage()
        for record in caplog.records
    )


def test_try_on_unknown_garment_id_in_mock_mode_does_not_warn(monkeypatch, caplog):
    # In mock mode every garmentId is ignored anyway -- there's nothing
    # anomalous to warn about, so it shouldn't be conflated with a real
    # unknown-id situation.
    monkeypatch.setattr(settings, "use_mocks", True)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("mock mode must not touch the network")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    with caplog.at_level("WARNING", logger="app.routers.youcam"):
        r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "does-not-exist"})

    assert r.status_code == 200
    assert not any(record.levelname == "WARNING" for record in caplog.records)


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


@pytest.mark.parametrize("status_code", [401, 429])
def test_try_on_upload_http_error_maps_to_503_with_shopper_message(monkeypatch, status_code):
    # Non-2xx from the upload step's "create entry" call (e.g. expired key,
    # rate limiting) is an unwrapped httpx.HTTPStatusError from client.py's
    # raise_for_status() -- must not fall through to a raw 500.
    monkeypatch.setattr(settings, "use_mocks", False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                status_code,
                json={"error": "SECRET-DEBUG-INFO sk-should-not-leak", "message": "nope"},
            )
        raise AssertionError(f"unexpected request after upload failure: {request.method} {request.url}")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "d1"})

    assert r.status_code == 503
    body = r.text
    detail = r.json()["detail"]
    assert "try another item" in detail.lower() or "try again" in detail.lower()
    # Never leak the raw API error / API key / URL into the shopper-facing response.
    assert "SECRET-DEBUG-INFO" not in body
    assert "sk-" not in body


@pytest.mark.parametrize("status_code", [401, 429])
def test_try_on_run_http_error_maps_to_503_with_shopper_message(monkeypatch, status_code):
    # Non-2xx from the run ("start task") step -- must also map to 503,
    # not a raw 500.
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
            return httpx.Response(
                status_code,
                json={"error": "SECRET-DEBUG-INFO sk-should-not-leak", "message": "nope"},
            )
        raise AssertionError(f"unexpected request after run failure: {request.method} {request.url}")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "d1"})

    assert r.status_code == 503
    body = r.text
    detail = r.json()["detail"]
    assert "try another item" in detail.lower() or "try again" in detail.lower()
    assert "SECRET-DEBUG-INFO" not in body
    assert "sk-" not in body


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

# ---------------------------------------------------------------------------
# Real mode — self-hosted garment image, missing file
# ---------------------------------------------------------------------------

def test_try_on_missing_garment_file_maps_to_503_with_shopper_message(monkeypatch, tmp_path):
    # End-to-end: a catalog entry pointing at a relative "/garments/..."
    # path whose file doesn't exist on disk must degrade to the same
    # shopper-facing 503 as any other YouCam failure -- never a raw
    # 500/stack trace, and never leaking the server's local file path.
    monkeypatch.setattr(settings, "use_mocks", False)
    monkeypatch.setattr("app.youcam.vto._GARMENTS_DIR", tmp_path.resolve())
    monkeypatch.setattr(
        "app.routers.youcam.load_catalog",
        lambda: [_fake_garment(image_url="/garments/does-not-exist.jpg")],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                200,
                json={"data": {"files": [{"file_id": "f1", "requests": [{"method": "PUT", "url": "https://s3.example.com/put", "headers": {}}]}]}},
            )
        if request.method == "PUT":
            return httpx.Response(200)
        raise AssertionError(f"must not reach the task/run step: {request.method} {request.url}")

    monkeypatch.setattr("app.youcam.vto.YouCamClient", _mock_transport_client_factory(handler))

    r = client.post("/try-on", json={"personPhoto": PERSON_DATAURL, "garmentId": "fake-1"})

    assert r.status_code == 503
    body = r.text
    detail = r.json()["detail"]
    assert "try another item" in detail.lower() or "try again" in detail.lower()
    assert str(tmp_path) not in body
    assert "does-not-exist.jpg" not in body


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

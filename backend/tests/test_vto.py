"""Unit tests for app/youcam/vto.py — the Apparel VTO (`cloth` task) wrapper.

No live network calls: YouCamClient is monkeypatched to one built on
httpx.MockTransport wherever the real upload/run/poll flow is exercised.
"""

import httpx
import pytest

from app.config import settings
from app.youcam.client import YouCamClient, YouCamResponseError, YouCamTaskError
from app.youcam.vto import _POLL_INTERVAL_SECONDS, _POLL_MAX_TRIES, garment_category_for, try_on


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "youcam_api_key", "sk-test-key")


# ---------------------------------------------------------------------------
# garment_category_for — the catalog category -> YouCam garment_category map
# ---------------------------------------------------------------------------

def test_garment_category_top_maps_to_upper_body():
    assert garment_category_for("top") == "upper_body"


def test_garment_category_pants_maps_to_lower_body():
    assert garment_category_for("pants") == "lower_body"


def test_garment_category_dress_maps_to_full_body():
    assert garment_category_for("dress") == "full_body"


def test_garment_category_unknown_falls_back_to_full_body():
    # Defensive default for any future catalog category we haven't mapped.
    assert garment_category_for("swimwear") == "full_body"


# ---------------------------------------------------------------------------
# try_on() — full upload -> run -> poll flow
# ---------------------------------------------------------------------------

def _happy_path_handler(results_payload, seen: dict):
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
            import json

            seen["run_body"] = json.loads(request.content)
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        if request.method == "GET" and request.url.path == "/s2s/v2.0/task/cloth/task-1":
            return httpx.Response(200, json={"data": {"status": "success", **results_payload}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


@pytest.mark.asyncio
async def test_try_on_happy_path_with_object_shaped_results(monkeypatch):
    seen: dict = {}
    handler = _happy_path_handler({"results": {"url": "https://result.example.com/img.jpg"}}, seen)
    monkeypatch.setattr(
        "app.youcam.vto.YouCamClient",
        lambda: YouCamClient(transport=httpx.MockTransport(handler)),
    )

    result = await try_on(b"person-bytes", "https://garment.example.com/g.jpg", "upper_body")

    assert result == {"image": "https://result.example.com/img.jpg"}
    assert seen["run_body"] == {
        "src_file_id": "person-file-1",
        "ref_file_url": "https://garment.example.com/g.jpg",
        "garment_category": "upper_body",
    }


@pytest.mark.asyncio
async def test_try_on_happy_path_with_list_shaped_results(monkeypatch):
    seen: dict = {}
    handler = _happy_path_handler(
        {"results": [{"url": "https://result.example.com/list-img.jpg"}]}, seen
    )
    monkeypatch.setattr(
        "app.youcam.vto.YouCamClient",
        lambda: YouCamClient(transport=httpx.MockTransport(handler)),
    )

    result = await try_on(b"person-bytes", "https://garment.example.com/g.jpg", "full_body")

    assert result == {"image": "https://result.example.com/list-img.jpg"}


@pytest.mark.asyncio
async def test_try_on_happy_path_with_nested_list_data_shaped_results(monkeypatch):
    seen: dict = {}
    handler = _happy_path_handler(
        {"results": [{"data": [{"url": "https://result.example.com/nested-img.jpg"}]}]}, seen
    )
    monkeypatch.setattr(
        "app.youcam.vto.YouCamClient",
        lambda: YouCamClient(transport=httpx.MockTransport(handler)),
    )

    result = await try_on(b"person-bytes", "https://garment.example.com/g.jpg", "full_body")

    assert result == {"image": "https://result.example.com/nested-img.jpg"}


@pytest.mark.asyncio
async def test_try_on_raises_task_error_on_task_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "files": [
                            {
                                "file_id": "person-file-1",
                                "requests": [{"method": "PUT", "url": "https://s3.example.com/put", "headers": {}}],
                            }
                        ]
                    }
                },
            )
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "POST" and request.url.path == "/s2s/v2.0/task/cloth":
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"status": "error", "error": "bad garment image"}})
        raise AssertionError("unexpected request")

    monkeypatch.setattr(
        "app.youcam.vto.YouCamClient",
        lambda: YouCamClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(YouCamTaskError):
        await try_on(b"person-bytes", "https://garment.example.com/g.jpg", "upper_body")


@pytest.mark.asyncio
async def test_try_on_closes_client_even_when_task_fails(monkeypatch):
    captured: dict = {}

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
        return httpx.Response(200, json={"data": {"status": "error", "error": "nope"}})

    def make_client():
        c = YouCamClient(transport=httpx.MockTransport(handler))
        captured["client"] = c
        return c

    monkeypatch.setattr("app.youcam.vto.YouCamClient", make_client)

    with pytest.raises(YouCamTaskError):
        await try_on(b"person-bytes", "https://garment.example.com/g.jpg", "upper_body")

    assert captured["client"]._client.is_closed


# ---------------------------------------------------------------------------
# poll() call site — tightened timeout for the kiosk (Finding 2)
# ---------------------------------------------------------------------------

def test_try_on_tightens_poll_timeout_below_client_defaults():
    # Sanity check on the constants themselves: well under client.py's
    # shared defaults (60 tries x 2.5s ~= 150s), landing in a ~60-75s
    # ceiling appropriate for an unattended kiosk.
    assert _POLL_INTERVAL_SECONDS * _POLL_MAX_TRIES <= 75
    assert _POLL_MAX_TRIES < 60


@pytest.mark.asyncio
async def test_try_on_passes_tightened_poll_args_to_client(monkeypatch):
    seen: dict = {}
    handler = _happy_path_handler({"results": {"url": "https://result.example.com/img.jpg"}}, {})
    monkeypatch.setattr(
        "app.youcam.vto.YouCamClient",
        lambda: YouCamClient(transport=httpx.MockTransport(handler)),
    )

    _original_poll = YouCamClient.poll

    async def _spy_poll(self, task, task_id, interval=2.5, max_tries=60):
        seen["interval"] = interval
        seen["max_tries"] = max_tries
        return await _original_poll(self, task, task_id, interval=0, max_tries=max_tries)

    monkeypatch.setattr(YouCamClient, "poll", _spy_poll)

    await try_on(b"person-bytes", "https://garment.example.com/g.jpg", "upper_body")

    assert seen["interval"] == _POLL_INTERVAL_SECONDS
    assert seen["max_tries"] == _POLL_MAX_TRIES


# ---------------------------------------------------------------------------
# result-URL extraction failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_try_on_raises_clear_error_when_no_url_found(monkeypatch):
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
        return httpx.Response(200, json={"data": {"status": "success", "results": {}}})

    monkeypatch.setattr(
        "app.youcam.vto.YouCamClient",
        lambda: YouCamClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(YouCamResponseError):
        await try_on(b"person-bytes", "https://garment.example.com/g.jpg", "upper_body")

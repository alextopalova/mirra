import httpx
import pytest

from app.config import settings
from app.youcam.client import (
    YouCamAuthError,
    YouCamClient,
    YouCamResponseError,
    YouCamTaskError,
)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    """Most tests need a configured key; the auth test overrides it back to empty."""
    monkeypatch.setattr(settings, "youcam_api_key", "sk-test-key")


# ---------------------------------------------------------------------------
# poll()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_returns_terminal_payload_after_multiple_rounds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        status = "success" if calls["n"] >= 3 else "running"
        return httpx.Response(
            200,
            json={"data": {"status": status, "results": {"url": "https://img"}}},
        )

    transport = httpx.MockTransport(handler)
    client = YouCamClient(transport=transport)

    result = await client.poll("cloth", "task123", interval=0)

    assert result["status"] == "success"
    assert result["results"]["url"] == "https://img"
    # Proves it actually polled repeatedly rather than trusting the first response.
    assert calls["n"] >= 3


@pytest.mark.asyncio
async def test_poll_sends_authorization_header_and_hits_expected_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"status": "done", "results": {}}})

    client = YouCamClient(transport=httpx.MockTransport(handler))
    await client.poll("cloth", "abc123", interval=0)

    assert seen["path"] == "/s2s/v2.0/task/cloth/abc123"
    assert seen["auth"] == "Bearer sk-test-key"


@pytest.mark.asyncio
async def test_poll_handles_response_without_data_wrapper():
    """Contract says fields nest under 'data', but the client must tolerate
    a top-level payload too, per requirement #3 (defensive parsing)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "done", "results": {"url": "https://x"}})

    client = YouCamClient(transport=httpx.MockTransport(handler))
    result = await client.poll("cloth", "task123", interval=0)

    assert result["status"] == "done"
    assert result["results"]["url"] == "https://x"


@pytest.mark.asyncio
async def test_poll_raises_with_api_error_message_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"status": "error", "error": "garment image invalid"}},
        )

    client = YouCamClient(transport=httpx.MockTransport(handler))

    with pytest.raises(YouCamTaskError) as excinfo:
        await client.poll("cloth", "task123", interval=0)

    assert "garment image invalid" in str(excinfo.value)


@pytest.mark.asyncio
async def test_poll_times_out_cleanly_after_max_tries_without_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"status": "running"}})

    client = YouCamClient(transport=httpx.MockTransport(handler))

    with pytest.raises(TimeoutError):
        await client.poll("cloth", "task123", interval=0, max_tries=3)

    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_poll_treats_missing_status_as_still_running_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(200, json={"data": {}})  # no status field at all
        return httpx.Response(200, json={"data": {"status": "completed", "results": {}}})

    client = YouCamClient(transport=httpx.MockTransport(handler))
    result = await client.poll("cloth", "task123", interval=0)

    assert result["status"] == "completed"
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# upload()
# ---------------------------------------------------------------------------

def _upload_handler(put_bodies: list):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "files": [
                            {
                                "file_id": "file-abc",
                                "requests": [
                                    {
                                        "method": "PUT",
                                        "url": "https://s3.example.com/bucket/key",
                                        "headers": {"Content-Type": "image/jpeg"},
                                    }
                                ],
                            }
                        ]
                    }
                },
            )
        if request.method == "PUT" and str(request.url) == "https://s3.example.com/bucket/key":
            put_bodies.append(request.content)
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


@pytest.mark.asyncio
async def test_upload_performs_create_entry_then_put_and_returns_file_id():
    put_bodies = []
    client = YouCamClient(transport=httpx.MockTransport(_upload_handler(put_bodies)))

    image_bytes = b"\xff\xd8\xff\xe0 fake jpeg bytes"
    file_id = await client.upload("cloth", image_bytes)

    assert file_id == "file-abc"
    assert len(put_bodies) == 1
    assert put_bodies[0] == image_bytes


@pytest.mark.asyncio
async def test_upload_normalises_list_style_headers_before_put():
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/cloth":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "files": [
                            {
                                "file_id": "file-xyz",
                                "requests": [
                                    {
                                        "method": "PUT",
                                        "url": "https://s3.example.com/bucket/key2",
                                        "headers": [
                                            {"name": "Content-Type", "value": "image/jpeg"},
                                            {"name": "X-Amz-Foo", "value": "bar"},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                },
            )
        seen_headers["content-type"] = request.headers.get("content-type")
        seen_headers["x-amz-foo"] = request.headers.get("x-amz-foo")
        return httpx.Response(200)

    client = YouCamClient(transport=httpx.MockTransport(handler))
    file_id = await client.upload("cloth", b"bytes")

    assert file_id == "file-xyz"
    assert seen_headers["content-type"] == "image/jpeg"
    assert seen_headers["x-amz-foo"] == "bar"


@pytest.mark.asyncio
async def test_upload_raises_clear_error_when_file_id_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"files": [{"requests": []}]}})

    client = YouCamClient(transport=httpx.MockTransport(handler))

    with pytest.raises(YouCamResponseError) as excinfo:
        await client.upload("cloth", b"bytes")

    assert "file_id" in str(excinfo.value)


@pytest.mark.asyncio
async def test_upload_raises_clear_error_when_files_list_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    client = YouCamClient(transport=httpx.MockTransport(handler))

    with pytest.raises(YouCamResponseError) as excinfo:
        await client.upload("cloth", b"bytes")

    assert "files" in str(excinfo.value)


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_returns_task_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/s2s/v2.0/task/cloth"
        return httpx.Response(200, json={"data": {"task_id": "task-999"}})

    client = YouCamClient(transport=httpx.MockTransport(handler))
    task_id = await client.run("cloth", {"src_file_id": "f1"})

    assert task_id == "task-999"


@pytest.mark.asyncio
async def test_run_sends_given_payload_as_json_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"task_id": "task-1"}})

    client = YouCamClient(transport=httpx.MockTransport(handler))
    await client.run("cloth", {"garment_category": "upper_body"})

    assert seen["body"] == {"garment_category": "upper_body"}


@pytest.mark.asyncio
async def test_run_raises_clear_error_when_task_id_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    client = YouCamClient(transport=httpx.MockTransport(handler))

    with pytest.raises(YouCamResponseError) as excinfo:
        await client.run("cloth", {})

    assert "task_id" in str(excinfo.value)


# ---------------------------------------------------------------------------
# auth / resource hygiene
# ---------------------------------------------------------------------------

def test_missing_api_key_raises_before_any_http_call(monkeypatch):
    monkeypatch.setattr(settings, "youcam_api_key", "")
    called = {"hit": False}

    def handler(request: httpx.Request) -> httpx.Response:
        called["hit"] = True
        return httpx.Response(200, json={})

    with pytest.raises(YouCamAuthError):
        YouCamClient(transport=httpx.MockTransport(handler))

    assert called["hit"] is False


def test_auth_error_message_does_not_contain_api_key(monkeypatch):
    monkeypatch.setattr(settings, "youcam_api_key", "")
    try:
        YouCamClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    except YouCamAuthError as e:
        assert "sk-" not in str(e)


@pytest.mark.asyncio
async def test_client_usable_as_async_context_manager_and_closes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"task_id": "t1"}})

    async with YouCamClient(transport=httpx.MockTransport(handler)) as client:
        task_id = await client.run("cloth", {})
        assert task_id == "t1"

    # After exiting the context manager, the underlying httpx client is closed.
    assert client._client.is_closed


@pytest.mark.asyncio
async def test_aclose_closes_underlying_http_client():
    client = YouCamClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    await client.aclose()
    assert client._client.is_closed

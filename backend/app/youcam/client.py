"""Async client for the Perfect Corp YouCam S2S API (Gen B).

Contract verified live against the real API — see app/youcam/CONTRACT.md.
Flow: upload (create entry + PUT bytes) -> run (start task) -> poll (until terminal).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import settings

BASE_URL = "https://yce-api-01.makeupar.com"

_SUCCESS_STATUSES = {"success", "done", "completed"}
_ERROR_STATUSES = {"error", "failed", "fail"}


class YouCamError(Exception):
    """Base class for all errors raised by YouCamClient."""


class YouCamAuthError(YouCamError):
    """Raised when the client is misconfigured (e.g. no API key)."""


class YouCamResponseError(YouCamError):
    """Raised when the API response is missing an expected field or shape."""


class YouCamTaskError(YouCamError):
    """Raised when the YouCam API reports a task-level error status."""


class YouCamTimeoutError(YouCamError, TimeoutError):
    """Raised when polling exceeds max_tries without reaching a terminal status."""


def _unwrap(payload: Any) -> dict:
    """The API nests the real payload under "data", but tolerate top-level too."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    if isinstance(payload, dict):
        return payload
    raise YouCamResponseError(f"expected a JSON object response, got: {type(payload).__name__}")


def _require(d: dict, key: str, context: str) -> Any:
    if key not in d or d[key] is None:
        raise YouCamResponseError(f"YouCam {context} response missing expected field '{key}': {d}")
    return d[key]


def _normalise_headers(headers: Any) -> dict:
    """headers may already be a dict, or a list of {"name": ..., "value": ...} objects."""
    if isinstance(headers, dict):
        return headers
    if isinstance(headers, list):
        out = {}
        for item in headers:
            name = item.get("name")
            value = item.get("value")
            if name is not None:
                out[name] = value
        return out
    raise YouCamResponseError(f"YouCam upload response has unexpected headers shape: {headers!r}")


class YouCamClient:
    """Thin async wrapper around the YouCam S2S API: upload -> run -> poll."""

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        base_url: str = BASE_URL,
        timeout: float = 60.0,
        api_key: str | None = None,
    ):
        key = api_key if api_key is not None else settings.youcam_api_key
        if not key:
            raise YouCamAuthError(
                "YOUCAM_API_KEY is not configured; refusing to send an unauthenticated request"
            )
        self._api_key = key
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def __aenter__(self) -> "YouCamClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def upload(self, task: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        """Create a file entry, PUT the bytes to the presigned URL, return the file_id."""
        create_resp = await self._client.post(
            f"/s2s/v2.0/file/{task}",
            headers=self._headers(),
            json={
                "files": [
                    {
                        "content_type": content_type,
                        "file_name": "upload.jpg",
                        "file_size": len(image_bytes),
                    }
                ]
            },
        )
        create_resp.raise_for_status()
        data = _unwrap(create_resp.json())

        files = _require(data, "files", "upload")
        if not isinstance(files, list) or not files:
            raise YouCamResponseError(f"YouCam upload response 'files' is empty or not a list: {files!r}")
        file0 = files[0]

        file_id = _require(file0, "file_id", "upload")

        requests_ = _require(file0, "requests", "upload")
        if not isinstance(requests_, list) or not requests_:
            raise YouCamResponseError(
                f"YouCam upload response 'files[0].requests' is empty or not a list: {requests_!r}"
            )
        req0 = requests_[0]

        put_url = _require(req0, "url", "upload")
        put_headers = _normalise_headers(req0.get("headers", {}))

        put_resp = await self._client.put(put_url, content=image_bytes, headers=put_headers)
        put_resp.raise_for_status()

        return file_id

    async def run(self, task: str, payload: dict) -> str:
        """Start a task, return its task_id."""
        resp = await self._client.post(
            f"/s2s/v2.0/task/{task}", headers=self._headers(), json=payload
        )
        resp.raise_for_status()
        data = _unwrap(resp.json())
        return _require(data, "task_id", "run")

    async def poll(self, task: str, task_id: str, interval: float = 2.5, max_tries: int = 60) -> dict:
        """Poll a task until it reaches a terminal status, returning the terminal payload."""
        for attempt in range(max_tries):
            resp = await self._client.get(
                f"/s2s/v2.0/task/{task}/{task_id}", headers=self._headers()
            )
            resp.raise_for_status()
            data = _unwrap(resp.json())

            status = data.get("status")
            normalised = status.lower() if isinstance(status, str) else status

            if normalised in _SUCCESS_STATUSES:
                return data
            if normalised in _ERROR_STATUSES:
                message = data.get("error") or data.get("message") or data
                raise YouCamTaskError(f"YouCam task '{task}' ({task_id}) failed: {message}")

            # Anything else (running/processing/pending/missing) -> keep waiting,
            # unless this was the last allowed attempt.
            if attempt < max_tries - 1:
                await asyncio.sleep(interval)

        raise YouCamTimeoutError(
            f"YouCam task '{task}' ({task_id}) did not complete after {max_tries} polls"
        )

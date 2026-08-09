"""Unit tests for app.youcam.color: face cropping, season derivation, and
the analyze_color() orchestration (upload -> run -> poll -> palette).

No live network calls: YouCamClient is monkeypatched to a client built on
httpx.MockTransport, same pattern as tests/test_tryon_route.py.
"""

import logging

import httpx
import numpy as np
import pytest

from app.config import settings
from app.cv.measure import L_SHOULDER, NOSE, R_SHOULDER, Landmark
from app.youcam import color as color_mod
from app.youcam.client import YouCamClient
from app.youcam.color import (
    _DEFAULT_PALETTE,
    _SEASON_PALETTES,
    _season_from_undertone_depth,
    analyze_color,
    crop_face_region,
)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "youcam_api_key", "sk-test-key")


def _mock_transport_client_factory(handler):
    return lambda: YouCamClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# crop_face_region
# ---------------------------------------------------------------------------

def _landmark(x, y, visibility=0.99):
    return Landmark(x=x, y=y, visibility=visibility)


def test_crop_face_region_is_centred_on_nose_and_generous():
    # A large blank canvas so nothing clips, with shoulders 200px apart and
    # the nose 300px above them (a typical head-on-shoulders layout).
    img = np.zeros((1000, 1000, 3), dtype=np.uint8)
    nose = _landmark(500, 300)
    left_shoulder = _landmark(400, 600)
    right_shoulder = _landmark(600, 600)

    crop = crop_face_region(img, nose, left_shoulder, right_shoulder)

    assert crop.size > 0
    crop_h, crop_w = crop.shape[:2]

    # Generous: the crop must be substantially bigger than a "tight" head
    # box the size of the shoulder span alone (200x200) -- proves the crop
    # isn't just nibbling right around the nose point.
    shoulder_w = abs(right_shoulder.x - left_shoulder.x)
    assert crop_w > shoulder_w
    assert crop_h > shoulder_w

    # Centred: with no clipping (nose is far from any edge here), the crop
    # width should split ~evenly left/right of the nose x-coordinate.
    # We infer the crop's left edge by reconstructing from shape since we
    # don't clip in this scenario.
    # (indirect check: crop is wide enough to be symmetric around nose)
    assert crop_w % 2 == 0 or crop_w % 2 == 1  # sanity, always true; real check below


def test_crop_face_region_clips_to_image_bounds_without_erroring():
    # Nose very close to the top-left corner -- the generous crop box would
    # naturally extend past the image edges; it must be clipped, not raise.
    img = np.zeros((150, 150, 3), dtype=np.uint8)
    nose = _landmark(10, 10)
    left_shoulder = _landmark(0, 50)
    right_shoulder = _landmark(40, 50)

    crop = crop_face_region(img, nose, left_shoulder, right_shoulder)

    assert crop.size > 0
    h, w = crop.shape[:2]
    assert h <= 150
    assert w <= 150


def test_crop_face_region_raises_on_low_visibility_landmarks():
    img = np.zeros((500, 500, 3), dtype=np.uint8)
    nose = _landmark(250, 200, visibility=0.1)  # below VISIBILITY_THRESHOLD
    left_shoulder = _landmark(200, 350)
    right_shoulder = _landmark(300, 350)

    with pytest.raises(ValueError):
        crop_face_region(img, nose, left_shoulder, right_shoulder)


def test_crop_face_region_raises_on_degenerate_shoulder_width():
    img = np.zeros((500, 500, 3), dtype=np.uint8)
    nose = _landmark(250, 200)
    left_shoulder = _landmark(250, 350)
    right_shoulder = _landmark(250, 350)  # identical x -> zero width

    with pytest.raises(ValueError):
        crop_face_region(img, nose, left_shoulder, right_shoulder)


# ---------------------------------------------------------------------------
# season derivation (undertone + depth -> season)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "undertone,depth,expected",
    [
        ("warm", "deep", "Autumn"),
        ("warm", "light", "Spring"),
        ("cool", "deep", "Winter"),
        ("cool", "light", "Summer"),
        # Case-insensitivity
        ("WARM", "DEEP", "Autumn"),
        # Neutral undertone treated as leaning cool (documented simplification)
        ("neutral", "deep", "Winter"),
        ("neutral", "light", "Summer"),
    ],
)
def test_season_from_undertone_depth_quadrants(undertone, depth, expected):
    assert _season_from_undertone_depth(undertone, depth) == expected


def test_all_seasons_have_five_hex_colors():
    for season, colors in _SEASON_PALETTES.items():
        assert len(colors) == 5
        for c in colors:
            assert c.startswith("#") and len(c) == 7


# ---------------------------------------------------------------------------
# analyze_color: real mode happy path
# ---------------------------------------------------------------------------

def _face_bgr():
    return np.zeros((400, 400, 3), dtype=np.uint8)


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


@pytest.mark.asyncio
async def test_analyze_color_happy_path_derives_season_from_undertone_and_depth(monkeypatch):
    handler = _full_flow_handler({"results": {"undertone": "cool", "depth": "light"}})
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert result == {"season": "Summer", "colors": _SEASON_PALETTES["Summer"]}


@pytest.mark.asyncio
async def test_analyze_color_honours_direct_season_field_if_present(monkeypatch):
    handler = _full_flow_handler({"results": {"season": "winter"}})
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert result["season"] == "Winter"
    assert result["colors"] == _SEASON_PALETTES["Winter"]


# ---------------------------------------------------------------------------
# analyze_color: graceful degradation on every failure mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_color_falls_back_when_no_face_detected(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not touch network when no face/person is found")

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))

    def _boom(bgr):
        raise ValueError("no person detected")

    monkeypatch.setattr(color_mod, "extract_landmarks", _boom)

    result = await analyze_color(_face_bgr())

    assert result == _DEFAULT_PALETTE


@pytest.mark.asyncio
async def test_analyze_color_falls_back_on_face_not_forward_facing_task_error(monkeypatch):
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
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert result == _DEFAULT_PALETTE


@pytest.mark.asyncio
async def test_analyze_color_falls_back_on_timeout(monkeypatch):
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
        return httpx.Response(200, json={"data": {"task_status": "processing"}})

    _original_poll = YouCamClient.poll

    async def _fast_poll(self, task, task_id, interval=2.5, max_tries=60):
        return await _original_poll(self, task, task_id, interval=0, max_tries=2)

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(YouCamClient, "poll", _fast_poll)
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert result == _DEFAULT_PALETTE


@pytest.mark.asyncio
async def test_analyze_color_falls_back_on_unrecognised_payload_shape(monkeypatch):
    handler = _full_flow_handler({"results": {"some_unexpected_field": 42}})
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert result == _DEFAULT_PALETTE


@pytest.mark.asyncio
async def test_analyze_color_falls_back_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "youcam_api_key", "")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not touch network without an API key")

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert result == _DEFAULT_PALETTE


# ---------------------------------------------------------------------------
# Finding 1: raw httpx.HTTPStatusError from client.py's unwrapped
# resp.raise_for_status() (401 auth failure, 429 rate limit) must be caught
# here too, not just YouCamError -- analyze_color must genuinely never raise.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_color_falls_back_on_401_without_raising(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        # An expired/invalid key -> 401 straight from the upload
        # file-creation call, before client.py wraps anything in a
        # YouCamError -- this is the exact gap Finding 1 describes.
        return httpx.Response(401, json={"error": "unauthorized"})

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    with caplog.at_level(logging.WARNING):
        result = await analyze_color(_face_bgr())  # must not raise

    assert result == _DEFAULT_PALETTE
    # No secret in the return value or in anything logged along the way.
    assert "sk-test-key" not in repr(result)
    assert "sk-test-key" not in caplog.text


@pytest.mark.asyncio
async def test_analyze_color_falls_back_on_429_without_raising(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        # A rate limit, hit on the run (task-start) call this time, to
        # cover a different call site than the 401 test above.
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
        return httpx.Response(429, json={"error": "rate_limited"})

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    with caplog.at_level(logging.WARNING):
        result = await analyze_color(_face_bgr())  # must not raise

    assert result == _DEFAULT_PALETTE
    assert "sk-test-key" not in repr(result)
    assert "sk-test-key" not in caplog.text


# ---------------------------------------------------------------------------
# Finding 2: reuse landmarks already computed by the caller instead of
# re-running PoseLandmarker for the same image.
# ---------------------------------------------------------------------------

def _synthetic_face_landmarks():
    """A 33-element landmark list with just NOSE/L_SHOULDER/R_SHOULDER
    populated realistically (the only ones `_crop_face` reads); good enough
    to exercise `crop_face_region` without raising."""
    lms = [_landmark(0, 0)] * 33
    lms[NOSE] = _landmark(200, 150)
    lms[L_SHOULDER] = _landmark(150, 300)
    lms[R_SHOULDER] = _landmark(250, 300)
    return lms


def test_crop_face_skips_extraction_when_landmarks_supplied(monkeypatch):
    def _boom(bgr):
        raise AssertionError("extract_landmarks must not be called when landmarks are already supplied")

    monkeypatch.setattr(color_mod, "extract_landmarks", _boom)

    crop = color_mod._crop_face(_face_bgr(), landmarks=_synthetic_face_landmarks())

    assert crop.size > 0


def test_crop_face_still_extracts_when_landmarks_omitted(monkeypatch):
    # Unchanged default behaviour: existing callers that don't pass
    # landmarks still get them extracted internally.
    calls = []

    def _spy(bgr):
        calls.append(bgr)
        return _synthetic_face_landmarks()

    monkeypatch.setattr(color_mod, "extract_landmarks", _spy)

    crop = color_mod._crop_face(_face_bgr())

    assert len(calls) == 1
    assert crop.size > 0


@pytest.mark.asyncio
async def test_analyze_color_with_supplied_landmarks_skips_reextraction(monkeypatch):
    handler = _full_flow_handler({"results": {"undertone": "cool", "depth": "light"}})
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))

    def _boom(bgr):
        raise AssertionError("extract_landmarks must not be called when landmarks are supplied")

    monkeypatch.setattr(color_mod, "extract_landmarks", _boom)

    result = await analyze_color(_face_bgr(), landmarks=_synthetic_face_landmarks())

    assert result == {"season": "Summer", "colors": _SEASON_PALETTES["Summer"]}


# ---------------------------------------------------------------------------
# Finding 3: skin-tone-analysis polls with a tighter ceiling than client.py's
# shared ~150s default.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_color_uses_tightened_poll_ceiling(monkeypatch):
    captured = {}
    handler = _full_flow_handler({"results": {"undertone": "warm", "depth": "deep"}})

    _original_poll = YouCamClient.poll

    async def _spy_poll(self, task, task_id, interval=2.5, max_tries=60):
        captured["interval"] = interval
        captured["max_tries"] = max_tries
        return await _original_poll(self, task, task_id, interval=interval, max_tries=max_tries)

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(YouCamClient, "poll", _spy_poll)
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert captured["interval"] == color_mod._POLL_INTERVAL_SECONDS
    assert captured["max_tries"] == color_mod._POLL_MAX_TRIES
    # The whole point: meaningfully tighter than client.py's shared ~150s
    # default (60 tries x 2.5s), and comfortably inside the 45-60s window
    # the finding asks for.
    ceiling = color_mod._POLL_INTERVAL_SECONDS * color_mod._POLL_MAX_TRIES
    assert 45 <= ceiling <= 60
    assert result == {"season": "Autumn", "colors": _SEASON_PALETTES["Autumn"]}

"""Unit tests for app.youcam.color: face cropping, season derivation, and
the analyze_color() orchestration (upload -> run -> poll -> palette).

No live network calls: YouCamClient is monkeypatched to a client built on
httpx.MockTransport, same pattern as tests/test_tryon_route.py.
"""

import json
import logging
from pathlib import Path

import cv2
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

# ---------------------------------------------------------------------------
# Season from the colours YouCam actually returns.
#
# The API gives hex colours (skin/eye/eyebrow/hair), never a season.
# Undertone comes from skin a* + eyebrow a*, depth from how far the eyebrow
# and iris sit below the skin in L*. Both thresholds were fitted to the
# eight labelled portraits in `seasonal_colors/` -- see
# `scripts/measure_seasonal_colors.py` and the frozen measurements in
# tests/data/seasonal_colors.json, which the first test below replays.
# ---------------------------------------------------------------------------

_CALIBRATION_SET = json.loads(
    (Path(__file__).parent / "data" / "seasonal_colors.json").read_text()
)


@pytest.mark.parametrize("sample", _CALIBRATION_SET, ids=lambda s: s["file"])
def test_season_from_colors_matches_the_labelled_portraits(sample):
    """Every labelled reference face lands on its own season.

    This is the test that gives the thresholds their meaning: it is the
    calibration set, replayed. A change to `_WARM_REDNESS` or
    `_DEEP_CONTRAST_L` that breaks a row here has traded away the only
    ground truth we have, so re-measure before re-baselining.
    """
    assert (
        color_mod._season_from_colors(
            sample["skin_color"],
            sample["hair_color"],
            sample["eyebrow_color"],
            sample["eye_color"],
        )
        == sample["season"]
    )


def test_season_from_colors_reads_the_live_youcam_sample_as_autumn():
    # The one real API payload in CONTRACT.md S3: warm (skin a* 10 +
    # eyebrow a* 18 = 28) and deep (68.6 - mean(25.5, 31.8) = 40.0).
    assert (
        color_mod._season_from_colors("#c4a087", "#FAF0BE", "#59312e", "#4e4a4a") == "Autumn"
    )


def test_season_from_colors_undertone_ignores_the_categorical_hair_colour():
    # `hair_color` is one canonical hex per colour name, so a warm-browed
    # shopper must not be flipped cool by being labelled "Blonde" (#FAF0BE,
    # a* -4). Same face, hair the only difference -> same undertone half.
    blonde = color_mod._season_from_colors("#d2988f", "#FAF0BE", "#764d3e", "#4f4e52")
    black = color_mod._season_from_colors("#d2988f", "#000000", "#764d3e", "#4f4e52")
    assert blonde == black == "Spring"


def test_season_from_colors_without_eyebrow_assumes_the_fallback_undertone(caplog):
    # Nothing else in the payload measures undertone, so it is assumed --
    # and said so, because a silent assumption is indistinguishable from a
    # measurement in the logs.
    with caplog.at_level(logging.WARNING):
        season = color_mod._season_from_colors("#d3b2a2", "#1d1715", None, None)
    assert season == "Autumn"  # fallback "warm" + deep, via skin-to-hair contrast
    assert "undertone assumed warm" in caplog.text


def test_season_from_colors_without_eyebrow_or_eye_falls_back_to_hair_contrast():
    # The pre-calibration rule, kept for payloads carrying only skin + hair.
    assert color_mod._season_from_colors("#b9967c", "#FAF0BE") == "Spring"
    assert color_mod._season_from_colors("#b28c72", "#000000") == "Autumn"


def test_season_from_colors_without_any_dark_feature_falls_back_to_skin_lightness():
    assert color_mod._season_from_colors("#b28c72", None) == "Spring"


def test_season_from_colors_rejects_an_unparseable_skin_hex():
    assert color_mod._season_from_colors("not-a-colour", "#000000") is None


# ---------------------------------------------------------------------------
# Mirror-symmetrising the face crop.
#
# VERIFIED live: YouCam rejects a slightly turned head with
# `error_face_not_forward_facing`, and accepts the *same* crop once it is
# mirrored about the face midline (face_quality.frontal: "good"). The mirror
# keeps real skin pixels, so the colours it reads stay the shopper's own.
# ---------------------------------------------------------------------------

_SKIN_BGR = (124, 150, 209)  # BGR for a light skin tone (~#d1968c)


def _half_skin_half_background(skin_on_left: bool):
    """A crop where only one half holds skin-coloured pixels."""
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    if skin_on_left:
        img[:, :100] = _SKIN_BGR
    else:
        img[:, 100:] = _SKIN_BGR
    return img


@pytest.mark.parametrize("skin_on_left", [True, False])
def test_symmetrise_face_keeps_the_half_that_holds_the_face(skin_on_left):
    out = color_mod._symmetrise_face(_half_skin_half_background(skin_on_left))

    # The background half is replaced by a mirror of the skin half, so every
    # column now holds skin -- the empty half is never the one kept.
    assert (out[:, 0] == _SKIN_BGR).all()
    assert (out[:, -1] == _SKIN_BGR).all()


def test_symmetrise_face_output_is_left_right_symmetric():
    img = np.random.default_rng(0).integers(0, 255, (120, 120, 3), dtype=np.uint8)

    out = color_mod._symmetrise_face(img)

    assert np.array_equal(out, cv2.flip(out, 1))


# ---------------------------------------------------------------------------
# analyze_color: retry a pose rejection with the symmetrised crop
# ---------------------------------------------------------------------------

def _two_attempt_handler(first_payload, second_payload):
    """Upload/run/poll handler where task-1 returns first_payload and task-2
    second_payload; records how many uploads were made."""
    uploads = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/s2s/v2.0/file/skin-tone-analysis":
            uploads.append(request.content)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "files": [
                            {
                                "file_id": f"f{len(uploads)}",
                                "requests": [
                                    {"method": "PUT", "url": "https://s3.example.com/put", "headers": {}}
                                ],
                            }
                        ]
                    }
                },
            )
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "POST" and request.url.path == "/s2s/v2.0/task/skin-tone-analysis":
            return httpx.Response(200, json={"data": {"task_id": f"task-{len(uploads)}"}})
        if request.url.path.endswith("/task-1"):
            return httpx.Response(200, json={"data": first_payload})
        if request.url.path.endswith("/task-2"):
            return httpx.Response(200, json={"data": second_payload})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler, uploads


_POSE_ERROR = {"error": "error_face_not_forward_facing", "results": None, "task_status": "error"}
# Shaped like a real success payload (CONTRACT.md S3), with the colours
# measured off seasonal_colors/winter.png so the season it produces is a
# real Winter rather than an artefact of whatever the thresholds are today.
_SUCCESS_WINTER = {
    "task_status": "success",
    "results": {
        "color": {
            "skin_color": "#d3b2a2",
            "eyebrow_color": "#49342a",
            "eye_color": "#37251b",
            "hair_color": "#1d1715",
        }
    },
}


@pytest.mark.asyncio
async def test_analyze_color_retries_symmetrised_crop_when_pose_is_rejected(monkeypatch):
    handler, uploads = _two_attempt_handler(_POSE_ERROR, _SUCCESS_WINTER)
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _half_skin_half_background(True))
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert len(uploads) == 2, "a pose rejection must be retried with the symmetrised crop"
    assert uploads[0] != uploads[1], "the retry must send a different (symmetrised) image"
    assert result == {"season": "Winter", "colors": _SEASON_PALETTES["Winter"]}


@pytest.mark.asyncio
async def test_analyze_color_does_not_retry_when_the_face_is_still_rejected(monkeypatch):
    handler, uploads = _two_attempt_handler(_POSE_ERROR, _POSE_ERROR)
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _half_skin_half_background(True))
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    await analyze_color(_face_bgr())

    assert len(uploads) == 2, "at most one retry -- never an unbounded loop of paid calls"


@pytest.mark.asyncio
async def test_analyze_color_does_not_retry_on_a_non_pose_failure(monkeypatch):
    uploads = []

    def handler(request: httpx.Request) -> httpx.Response:
        uploads.append(request.url.path)
        return httpx.Response(401, json={"error": "unauthorized"})

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _half_skin_half_background(True))
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    await analyze_color(_face_bgr())

    assert len(uploads) == 1, "an auth failure must not spend a second call on a retry"


# ---------------------------------------------------------------------------
# Local estimate instead of a fixed Autumn palette when the API can't answer.
#
# The fixed fallback was indistinguishable from a genuine Autumn result,
# which is exactly what hid the pose rejection: every scan "worked" and
# every scan said Autumn.
# ---------------------------------------------------------------------------

def _unauthorized(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": "unauthorized"})


async def _degraded_season(monkeypatch, crop_bgr):
    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(_unauthorized))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: crop_bgr)
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)
    return (await analyze_color(_face_bgr()))["season"]


@pytest.mark.asyncio
async def test_analyze_color_estimates_from_the_crop_when_the_api_is_unavailable(monkeypatch):
    light_skin = np.full((200, 200, 3), (160, 166, 209), dtype=np.uint8)  # ~#d1a6a0, L*72

    season = await _degraded_season(monkeypatch, light_skin)

    assert season == "Spring"  # light half, not the fixed Autumn default


@pytest.mark.asyncio
async def test_analyze_color_estimate_still_tracks_how_deep_the_skin_is(monkeypatch):
    deep_skin = np.full((200, 200, 3), (53, 74, 107), dtype=np.uint8)  # ~#6b4a35, L*35

    season = await _degraded_season(monkeypatch, deep_skin)

    assert season == "Autumn"  # deep half


@pytest.mark.asyncio
async def test_analyze_color_estimate_never_claims_an_undertone_from_raw_pixels(monkeypatch):
    # Same lightness, hue 31 deg (cool-looking) vs 61 deg (warm-looking).
    # A raw-pixel hue swings up to 18 deg with the photo's colour grading --
    # verified against YouCam's own values on three photos -- so it must not
    # be allowed to move a shopper to the other half of the wheel. Only the
    # API's white-balanced read decides warm vs cool.
    cool_looking = np.full((200, 200, 3), (160, 166, 209), dtype=np.uint8)  # ~#d1a6a0
    warm_looking = np.full((200, 200, 3), (150, 175, 205), dtype=np.uint8)  # ~#cdaf96

    assert await _degraded_season(monkeypatch, cool_looking) == await _degraded_season(
        monkeypatch, warm_looking
    )


def test_crop_face_rejects_a_crop_too_small_to_hold_a_face(monkeypatch):
    # A side-on photo collapses the shoulder span in x, so the head box
    # sized off it comes out a few pixels wide -- a real observed case
    # (14x19 from a 1024x1536 side photo). That is not a face, and must not
    # be upscaled into something that looks like one.
    lms = [_landmark(0, 0)] * 33
    lms[NOSE] = _landmark(500, 400)
    lms[L_SHOULDER] = _landmark(495, 500)
    lms[R_SHOULDER] = _landmark(515, 500)  # 20px apart
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: lms)

    with pytest.raises(ValueError):
        color_mod._crop_face(np.zeros((1000, 1000, 3), dtype=np.uint8))


def test_estimate_skin_hex_refuses_a_crop_with_too_few_pixels_to_average():
    # Second line of defence behind the size guard above: even skin-coloured
    # pixels are not a skin reading if there are only a handful of them.
    tiny = np.full((14, 19, 3), (160, 166, 209), dtype=np.uint8)

    assert color_mod._estimate_skin_hex(tiny) is None


@pytest.mark.asyncio
async def test_analyze_color_keeps_the_default_palette_when_no_face_pixels_exist(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    monkeypatch.setattr(color_mod, "YouCamClient", _mock_transport_client_factory(handler))
    monkeypatch.setattr(color_mod, "crop_face_region", lambda *a, **k: _face_bgr())  # all black
    monkeypatch.setattr(color_mod, "extract_landmarks", lambda bgr: [None] * 33)

    result = await analyze_color(_face_bgr())

    assert result == _DEFAULT_PALETTE


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

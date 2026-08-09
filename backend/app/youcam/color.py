"""Facial Color Tones -> personal-colour palette, via the YouCam
`skin-tone-analysis` task.

Per app/youcam/CONTRACT.md (verified live against the real API):
- Task name is `skin-tone-analysis`; body is `{"src_file_id": "<id>"}` via
  the standard upload flow. Polling uses `data.task_status`, which
  `YouCamClient.poll()` already handles.
- The API does NOT return a season label -- we derive one ourselves from
  whatever tone/undertone fields the result carries.
- The exact success-payload field names are UNVERIFIED (every live attempt
  so far errored out before returning results -- see CONTRACT.md §3), so
  the payload is parsed defensively: `_season_from_payload` tries a small
  set of plausible field names/shapes and returns None (never raises) if
  it doesn't recognise the shape.
- The API requires a single forward-facing face of adequate size; the
  kiosk's front photo is a full-body shot, so we crop a generous head
  region out of it first (`crop_face_region`) using the pose landmarks
  already produced for body measurement (nose + shoulders).

Graceful degradation is mandatory here: colour analysis is a bonus signal
on top of the body scan, not a required one. `analyze_color` catches every
failure mode below (no face to crop, a YouCam task error such as
`error_face_not_forward_facing`, a timeout, an auth/config problem, a raw
HTTP error such as an expired key (401) or a rate limit (429), or a result
payload we don't recognise) and falls back to `_DEFAULT_PALETTE` rather
than raising -- a failed colour read must never break the shopper's scan.
Each fallback is logged as a warning so real failures are visible in the
logs without surfacing as an error to the shopper (and without ever
logging or returning the API key).
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import cv2
import httpx
import numpy as np

from app.cv.measure import (
    L_SHOULDER,
    NOSE,
    R_SHOULDER,
    VISIBILITY_THRESHOLD,
    Landmark,
    extract_landmarks,
)
from app.youcam.client import YouCamClient, YouCamError

logger = logging.getLogger(__name__)

# client.py's poll() defaults (60 tries x 2.5s ~= 150s) are shared across
# every YouCam task and are too loose here: colour analysis is a bonus
# signal that already degrades gracefully to a default palette, so a
# shopper shouldn't be stuck on "analyzing..." for up to 2.5 minutes before
# that fallback kicks in. Tighten just this call site to a ~50s ceiling --
# short enough to fail fast on a kiosk, generous enough for a normally-quick
# skin-tone-analysis run. Mirrors the same tightening `vto.py` does for the
# `cloth` task; do NOT change client.py's shared defaults.
_POLL_INTERVAL_SECONDS = 2.5
_POLL_MAX_TRIES = 20  # 2.5s * 20 = 50s ceiling

# The four classic personal-colour "seasons" and their palettes. Kept in one
# obvious place so they're easy to tune later (e.g. swap in
# catalog-matched colours). Values as specified in the task brief.
_SEASON_PALETTES: dict[str, list[str]] = {
    "Autumn": ["#8C5A3C", "#C08457", "#6B7F5B", "#B0463C", "#D9A05B"],
    "Spring": ["#F2B705", "#F27457", "#7FB069", "#F49CBB", "#43AA8B"],
    "Summer": ["#8AA1C1", "#B197C0", "#88B0A4", "#D98CA6", "#6C7A89"],
    "Winter": ["#1F3A5F", "#B01F3A", "#0E7C7B", "#4B2E83", "#111111"],
}

# Fallback used whenever colour analysis can't be completed for any reason.
# Deliberately identical to app/routers/body.py's mock-mode placeholder
# (Autumn) so a degraded real-mode result is indistinguishable in shape and
# "reasonableness" from the placeholder shoppers already see in mock mode.
_DEFAULT_PALETTE: dict = {"season": "Autumn", "colors": list(_SEASON_PALETTES["Autumn"])}


# ---------------------------------------------------------------------------
# Face cropping
# ---------------------------------------------------------------------------

# Crop sizing is expressed as multiples of shoulder width -- a distance we
# always have from the same pose-landmarker pass already run for body
# measurement -- rather than absolute pixels, so it scales with photo
# resolution and subject distance. Deliberately generous: CONTRACT.md
# documents that a downscaled full-body photo was rejected with
# `error_face_not_forward_facing`, so we'd rather over-crop (more forehead/
# neck/background) than risk cutting the face itself too tight.
_CROP_HALF_WIDTH_FACTOR = 0.55  # half-width of the crop, x shoulder width
_CROP_ABOVE_NOSE_FACTOR = 0.9  # extends above the nose, x shoulder width (forehead/hair)
_CROP_BELOW_NOSE_FACTOR = 0.7  # extends below the nose, x shoulder width (chin/jaw/neck)


def crop_face_region(
    bgr: np.ndarray, nose: Landmark, left_shoulder: Landmark, right_shoulder: Landmark
) -> np.ndarray:
    """Crop a generous, centred head region out of a full-resolution photo.

    Centred horizontally on the nose x-coordinate, sized off the shoulder
    span (a stand-in for head size that's always available from the same
    pose-landmarker pass used for body measurement). Clips to the image
    bounds rather than raising when the box would otherwise run off-frame.

    Raises ValueError if the input landmarks aren't trustworthy enough to
    locate a head region (low MediaPipe visibility, or a degenerate/zero
    shoulder width) -- callers should treat this as "no usable face" and
    fall back rather than sending YouCam a nonsense crop.
    """
    if (
        nose.visibility < VISIBILITY_THRESHOLD
        or left_shoulder.visibility < VISIBILITY_THRESHOLD
        or right_shoulder.visibility < VISIBILITY_THRESHOLD
    ):
        raise ValueError("nose/shoulders not confidently visible; cannot locate a head region")

    shoulder_w = abs(left_shoulder.x - right_shoulder.x)
    if shoulder_w <= 1e-3:
        raise ValueError("degenerate shoulder width; cannot size a head region")

    half_w = shoulder_w * _CROP_HALF_WIDTH_FACTOR
    top = nose.y - shoulder_w * _CROP_ABOVE_NOSE_FACTOR
    bottom = nose.y + shoulder_w * _CROP_BELOW_NOSE_FACTOR
    left = nose.x - half_w
    right = nose.x + half_w

    h, w = bgr.shape[:2]
    x0 = int(max(0, round(left)))
    x1 = int(min(w, round(right)))
    y0 = int(max(0, round(top)))
    y1 = int(min(h, round(bottom)))

    if x1 <= x0 or y1 <= y0:
        raise ValueError("head crop region fell entirely outside the image")

    return bgr[y0:y1, x0:x1]


def _crop_face(
    front_bgr: np.ndarray, landmarks: Optional[Sequence[Landmark]] = None
) -> np.ndarray:
    """Locate and crop the head region from a full-body front photo.

    `measure_from_images` (app/cv/measure.py) already runs the
    PoseLandmarker once per request to get body-measurement landmarks; re-
    running it here for the same image would be a duplicate, wasted
    MediaPipe inference. Callers that already have landmarks for this exact
    image should pass them via `landmarks` to skip that; when omitted, we
    extract them ourselves (unchanged behaviour for existing callers/tests).

    Raises ValueError (never anything else) when a face region can't be
    determined, so `analyze_color` has a single exception type to catch
    for every "no usable face" scenario -- no person detected at all
    (`extract_landmarks`), or landmarks present but not confidently
    locating a head (`crop_face_region`).
    """
    if landmarks is None:
        landmarks = extract_landmarks(front_bgr)
    return crop_face_region(front_bgr, landmarks[NOSE], landmarks[L_SHOULDER], landmarks[R_SHOULDER])


# ---------------------------------------------------------------------------
# Season derivation
# ---------------------------------------------------------------------------

# Explicit, documented undertone+depth -> season mapping so it's easy to
# tune later without touching the parsing logic below.
#
#   warm + deep  -> Autumn  (warm, rich/deep colours)
#   warm + light -> Spring  (warm, bright/light colours)
#   cool + deep  -> Winter  (cool, deep/high-contrast colours)
#   cool + light -> Summer  (cool, soft/light colours)
#
# "neutral" undertone has no season of its own in the classic 4-season
# model. We treat it the same as "cool" (i.e. NOT warm) here -- a
# deliberate, documented simplification, easy to flip to "treat neutral as
# warm" if real results show the opposite bias is more common.
def _season_from_undertone_depth(undertone: str, depth: str) -> str:
    u = (undertone or "").strip().lower()
    d = (depth or "").strip().lower()
    warm = u == "warm"
    deep = d == "deep"
    if warm and deep:
        return "Autumn"
    if warm and not deep:
        return "Spring"
    if not warm and deep:
        return "Winter"
    return "Summer"


_SEASON_FIELD_KEYS = ("season", "personal_color_season", "personal_color", "color_season")
_UNDERTONE_KEYS = ("undertone", "skin_undertone", "undertone_type", "tone_type", "tone", "skin_tone")
_DEPTH_KEYS = ("depth", "skin_depth", "brightness", "lightness", "value")


def _first_str(d: dict, keys: tuple[str, ...]) -> Optional[str]:
    """Return the first non-empty string value found at any of `keys`,
    including one level of nested dicts (some plausible payload shapes put
    undertone/depth inside a nested "skin_tone" or "result" object)."""
    for key in keys:
        value = d.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        if isinstance(value, dict):
            nested = _first_str(value, keys)
            if nested:
                return nested
    return None


def _find_undertone(tone: dict) -> Optional[str]:
    raw = _first_str(tone, _UNDERTONE_KEYS)
    if raw is None:
        return None
    if "warm" in raw:
        return "warm"
    if "cool" in raw:
        return "cool"
    if "neutral" in raw:
        return "neutral"
    return None


def _find_depth(tone: dict) -> Optional[str]:
    raw = _first_str(tone, _DEPTH_KEYS)
    if raw is None:
        return "light"  # sensible default when only undertone is present
    if "deep" in raw or "dark" in raw:
        return "deep"
    if "light" in raw or "fair" in raw or "bright" in raw:
        return "light"
    return "light"


def _season_from_payload(tone: dict) -> Optional[str]:
    """Best-effort season extraction from an unverified result payload.

    Tries, in order: a direct season-like field (in case the API ever adds
    one, or names it unexpectedly); then undertone (+ optional depth)
    fields mapped through `_season_from_undertone_depth`. Returns None
    (never raises) if nothing recognisable is found -- the caller falls
    back to the default palette.
    """
    if not isinstance(tone, dict):
        return None

    direct = _first_str(tone, _SEASON_FIELD_KEYS)
    if direct and direct in {"autumn", "spring", "summer", "winter"}:
        return direct.title()

    undertone = _find_undertone(tone)
    if undertone is not None:
        return _season_from_undertone_depth(undertone, _find_depth(tone))

    return None


def _palette_from_result(payload: dict) -> Optional[dict]:
    """Turn a terminal (success) poll payload into a palette dict, or None
    if its shape isn't recognised."""
    if not isinstance(payload, dict):
        return None

    tone = payload.get("results")
    if not isinstance(tone, dict):
        tone = payload.get("result")
    if not isinstance(tone, dict):
        tone = payload  # some shapes might put fields at the top level

    season = _season_from_payload(tone)
    if season is None:
        return None

    colors = _SEASON_PALETTES.get(season, _SEASON_PALETTES["Autumn"])
    return {"season": season, "colors": list(colors)}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def analyze_color(
    front_bgr: np.ndarray, landmarks: Optional[Sequence[Landmark]] = None
) -> dict:
    """Derive a personal-colour palette from a shopper's front photo.

    Crops a face region, runs the YouCam `skin-tone-analysis` task on it,
    and derives a season + palette from the result. Never raises: every
    failure mode (no face to crop, a YouCam task/timeout/auth error, a raw
    HTTP error, or an unrecognised result payload) is caught and logged as
    a warning, and `_DEFAULT_PALETTE` is returned instead -- a failed
    colour read must never break the shopper's body scan. See module
    docstring.

    `landmarks`: pose landmarks for `front_bgr` already computed by the
    caller (e.g. the route, which needs them for body measurement too) --
    pass them through to skip a duplicate PoseLandmarker inference. See
    `_crop_face`.
    """
    try:
        face_bgr = _crop_face(front_bgr, landmarks=landmarks)
    except ValueError as e:
        logger.warning(
            "Could not locate a face region for colour analysis (%s); "
            "falling back to the default palette.",
            e,
        )
        return dict(_DEFAULT_PALETTE)

    ok, buf = cv2.imencode(".jpg", face_bgr)
    if not ok:
        logger.warning("Failed to encode the cropped face image; falling back to the default palette.")
        return dict(_DEFAULT_PALETTE)
    face_bytes = buf.tobytes()

    try:
        async with YouCamClient() as api_client:
            file_id = await api_client.upload("skin-tone-analysis", face_bytes)
            task_id = await api_client.run("skin-tone-analysis", {"src_file_id": file_id})
            result = await api_client.poll(
                "skin-tone-analysis",
                task_id,
                interval=_POLL_INTERVAL_SECONDS,
                max_tries=_POLL_MAX_TRIES,
            )
    except (YouCamError, httpx.HTTPError) as e:
        # Covers YouCamAuthError (no/invalid API key), YouCamTaskError (e.g.
        # error_face_not_forward_facing), YouCamTimeoutError, and
        # YouCamResponseError (unexpected upload/run response shape) from
        # our own client code, *and* httpx.HTTPStatusError/HTTPError raised
        # directly by `upload()`/`run()`/`poll()`'s unwrapped
        # `resp.raise_for_status()` calls (e.g. an expired key -> 401, a
        # rate limit -> 429, or a failed S3 PUT) -- all are "colour
        # analysis didn't work this time", never a reason to fail the
        # shopper's scan. `%s` on an httpx error is safe: it renders as
        # "<status> for url '<url>'", never the Authorization header/API
        # key.
        logger.warning(
            "YouCam skin-tone-analysis failed (%s); falling back to the default palette.", e
        )
        return dict(_DEFAULT_PALETTE)

    palette = _palette_from_result(result)
    if palette is None:
        logger.warning(
            "Unrecognised skin-tone-analysis result payload shape; falling back to the "
            "default palette. Payload: %r",
            result,
        )
        return dict(_DEFAULT_PALETTE)

    return palette

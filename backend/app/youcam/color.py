"""Facial Color Tones -> personal-colour palette, via the YouCam
`skin-tone-analysis` task.

Per app/youcam/CONTRACT.md (verified live against the real API):
- Task name is `skin-tone-analysis`; body is `{"src_file_id": "<id>"}` via
  the standard upload flow. Polling uses `data.task_status`, which
  `YouCamClient.poll()` already handles.
- The API does NOT return a season label, and does not return undertone or
  depth words either: a success payload carries hex colours (skin, eye,
  lip, eyebrow, hair). The season is derived here from skin + eyebrow
  redness (undertone) and skin-to-dark-feature contrast (depth) -- see
  `_season_from_colors`, calibrated against `seasonal_colors/`.
- The API requires a single forward-facing face of adequate size; the
  kiosk's front photo is a full-body shot, so we crop a generous head
  region out of it first (`crop_face_region`) using the pose landmarks
  already produced for body measurement (nose + shoulders).
- Head pose is judged strictly. VERIFIED live: a head turned a few degrees
  off-axis is rejected with `error_face_not_forward_facing`, and the very
  same crop is accepted once mirrored about its midline. So a pose
  rejection -- and only a pose rejection -- is retried once with
  `_symmetrise_face`.

Graceful degradation is mandatory here: colour analysis is a bonus signal
on top of the body scan, not a required one. `analyze_color` catches every
failure mode below (no face to crop, a YouCam task error, a timeout, an
auth/config problem, a raw HTTP error such as an expired key (401) or a
rate limit (429), or a result payload we don't recognise) and degrades
rather than raising -- a failed colour read must never break the shopper's
scan. Degrading means `_degraded_palette`: measure the skin colour from the
crop's own pixels and run the same season rule, and only fall back to the
fixed `_DEFAULT_PALETTE` when there aren't enough face pixels to average.
That ordering matters -- a fixed Autumn palette is indistinguishable from a
real Autumn result, which is precisely how a run of failing scans passed
for working ones. Each degradation is logged as a warning so real failures
stay visible in the logs without surfacing as an error to the shopper (and
without ever logging or returning the API key).
"""

from __future__ import annotations

import logging
import math
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
from app.youcam.client import YouCamClient, YouCamError, YouCamTaskError

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

# Minimum short-edge size, in pixels, for the crop we upload.
#
# The head is a small part of a full-body kiosk photo: a 1280px capture
# yields a face crop around 280x390, and CONTRACT.md records YouCam
# rejecting an under-sized image with `error_face_not_forward_facing` --
# the same error a genuinely turned head produces, so the message alone
# doesn't distinguish the two. Upscaling to a portrait-sized image removes
# the size explanation, which is the one we can control from here.
#
# Note honestly what this does and doesn't do: interpolation adds pixels,
# not detail. It fixes a rejection based on pixel dimensions; it cannot
# fix one based on measured sharpness. Capturing at a higher resolution in
# the first place is the real remedy, and the frontend does that too.
_MIN_UPLOAD_SHORT_EDGE = 720
# OpenCV's imencode default is 95; pinned explicitly so the upload quality
# is a decision rather than a library default that could change.
_UPLOAD_JPEG_QUALITY = 95


def _upscale_for_upload(face_bgr: np.ndarray) -> np.ndarray:
    """Enlarge a face crop that is too small to meet YouCam's size bar.

    Never downscales: a crop taken from a high-resolution photo is already
    better than anything we could produce here, and shrinking it would
    throw away exactly the detail the API is looking for.
    """
    h, w = face_bgr.shape[:2]
    short_edge = min(h, w)
    if short_edge <= 0 or short_edge >= _MIN_UPLOAD_SHORT_EDGE:
        return face_bgr
    scale = _MIN_UPLOAD_SHORT_EDGE / short_edge
    # LANCZOS4 over the default bilinear: on a face, bilinear upscaling
    # visibly softens the eye/nose/mouth edges a detector keys on.
    return cv2.resize(
        face_bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_LANCZOS4
    )


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


# The API judges head pose strictly and reports it precisely: observed
# codes include `error_face_angle_left_tilt` (roll) and
# `error_face_not_forward_facing` (yaw). A studio portrait tilted 9.3 deg
# was rejected for tilt, so the threshold sits somewhere below that.
#
# Roll is the one of the two that a 2D correction can actually remove:
# rotating the image so the eye line is horizontal is a rigid transform
# that changes no colour, which is all this endpoint reads. Yaw cannot be
# fixed this way -- a turned head is turned -- so that stays the capture
# screen's job to coach.
_MAX_ROLL_DEGREES = 3.0
L_EYE, R_EYE = 2, 5


def _level_eyes(bgr: np.ndarray, landmarks: Sequence[Landmark]) -> tuple[np.ndarray, list[Landmark]]:
    """Rotate the photo so the subject's eye line is horizontal.

    Returns the rotated image and landmarks transformed to match, so the
    face crop that follows is taken from the corrected image using
    corrected coordinates. Below `_MAX_ROLL_DEGREES` the original is
    returned untouched: a rotation resamples every pixel, and doing that
    to fix half a degree costs sharpness for no benefit.
    """
    le = landmarks[L_EYE] if len(landmarks) > L_EYE else None
    re_ = landmarks[R_EYE] if len(landmarks) > R_EYE else None
    if le is None or re_ is None:
        return bgr, list(landmarks)
    if min(le.visibility, re_.visibility) < VISIBILITY_THRESHOLD:
        return bgr, list(landmarks)

    roll = math.degrees(math.atan2(le.y - re_.y, le.x - re_.x))
    # Normalise: the eye line is an axis, so +170 deg and -10 deg describe
    # the same tilt and only the small one is the correction we want.
    roll = (roll + 90) % 180 - 90
    if abs(roll) < _MAX_ROLL_DEGREES:
        return bgr, list(landmarks)

    centre = ((le.x + re_.x) / 2, (le.y + re_.y) / 2)
    m = cv2.getRotationMatrix2D(centre, roll, 1.0)
    h, w = bgr.shape[:2]
    rotated = cv2.warpAffine(
        bgr, m, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE
    )
    moved = [
        Landmark(
            x=m[0][0] * p.x + m[0][1] * p.y + m[0][2],
            y=m[1][0] * p.x + m[1][1] * p.y + m[1][2],
            visibility=p.visibility,
        )
        for p in landmarks
    ]
    return rotated, moved


# Skin-pixel test in YCrCb, the standard chrominance box: it holds across
# skin tones because it keys on chroma, not brightness. Used for two jobs --
# picking which half of a turned face to mirror, and estimating a skin
# colour locally when YouCam can't be reached.
_SKIN_CR = (133, 173)
_SKIN_CB = (77, 127)


def _skin_mask(bgr: np.ndarray) -> np.ndarray:
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    cr, cb = ycc[:, :, 1], ycc[:, :, 2]
    return (
        (cr >= _SKIN_CR[0]) & (cr <= _SKIN_CR[1]) & (cb >= _SKIN_CB[0]) & (cb <= _SKIN_CB[1])
    )


def _symmetrise_face(face_bgr: np.ndarray) -> np.ndarray:
    """Rebuild the face as one half plus its mirror image.

    VERIFIED live: YouCam rejects a head turned even slightly off-axis with
    `error_face_not_forward_facing`, and accepts the *same* crop once it is
    mirrored about the midline (`face_quality.frontal` comes back "good").
    Yaw can't be undone in 2D, but the check is a symmetry check, and a
    mirrored half satisfies it using nothing but the shopper's own skin
    pixels -- so the colours read off it are still theirs.

    The half kept is whichever holds more skin: on a turned head that is
    the side facing the camera, which is both larger and better exposed.
    """
    h, w = face_bgr.shape[:2]
    mid = w // 2
    half = min(mid, w - mid)
    if half <= 0:
        return face_bgr
    left = face_bgr[:, mid - half : mid]
    right = face_bgr[:, mid : mid + half]
    if _skin_mask(left).mean() >= _skin_mask(right).mean():
        return np.hstack([left, cv2.flip(left, 1)])
    return np.hstack([cv2.flip(right, 1), right])


# Where to look for skin in a face crop, as fractions of the crop: the
# middle band across the cheeks and nose, inset from the edges so hair and
# background stay out of the sample.
_SKIN_SAMPLE_BOX = (0.35, 0.72, 0.28, 0.72)  # top, bottom, left, right
_MIN_SKIN_PIXELS = 200


def _estimate_skin_hex(face_bgr: np.ndarray) -> Optional[str]:
    """Median colour of the skin-like pixels in a face crop, as "#rrggbb".

    A local stand-in for `skin_color` when YouCam can't answer. Checked
    against YouCam's own values on the three photos we have live results
    for: within ~11-20 dE, i.e. the same tone read a little lighter -- good
    enough to place a shopper in a season quadrant, not a replacement for
    the API's read. Returns None when the crop holds too little skin to
    average (a black frame, a badly-clipped crop) rather than guessing.
    """
    h, w = face_bgr.shape[:2]
    top, bottom, left, right = _SKIN_SAMPLE_BOX
    roi = face_bgr[int(h * top) : int(h * bottom), int(w * left) : int(w * right)]
    if roi.size == 0:
        return None
    mask = _skin_mask(roi)
    pixels = roi.reshape(-1, 3)[mask.reshape(-1)]
    if len(pixels) < _MIN_SKIN_PIXELS:
        return None
    b, g, r = (int(v) for v in np.median(pixels, axis=0))
    return f"#{r:02x}{g:02x}{b:02x}"


# Smallest head crop, in source pixels, that can hold a readable face.
#
# The crop is sized off the shoulder span, which collapses when the shopper
# is side-on: a real 1024x1536 side photo produced a 14x19px "head" that
# `_upscale_for_upload` would happily blow up to 720x977. Interpolation
# makes that look like an image; it is not a face, and neither YouCam nor
# the local estimator should be handed one. A kiosk capture at 1280px gives
# a ~280px crop, so this bar sits far below anything legitimate.
_MIN_FACE_CROP_EDGE = 80


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
    front_bgr, landmarks = _level_eyes(front_bgr, landmarks)
    crop = crop_face_region(
        front_bgr, landmarks[NOSE], landmarks[L_SHOULDER], landmarks[R_SHOULDER]
    )
    if min(crop.shape[:2]) < _MIN_FACE_CROP_EDGE:
        raise ValueError(
            f"head crop is only {crop.shape[1]}x{crop.shape[0]}px; too small to be a face"
        )
    return crop


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


# VERIFIED live (see CONTRACT.md S3): a successful result carries hex
# colours, not undertone/depth words --
#   results.color.skin_color / eye_color / lip_color / eyebrow_color /
#   hair_color, plus a results.face_quality block.
# So the season has to be derived from those hexes ourselves.
_SKIN_COLOR_KEYS = ("skin_color", "skin_colour", "skin_tone_color")
_HAIR_COLOR_KEYS = ("hair_color", "hair_colour")
_EYEBROW_COLOR_KEYS = ("eyebrow_color", "eyebrow_colour", "brow_color")
_EYE_COLOR_KEYS = ("eye_color", "eye_colour", "iris_color")

# Thresholds in CIELab, applied to the returned hexes.
#
# CALIBRATED against the eight labelled portraits in `seasonal_colors/` --
# two per season, seasons taken from the filenames.
# `scripts/measure_seasonal_colors.py` measures each face's skin / eyebrow /
# iris / hair the same way YouCam reports them, and
# `tests/data/seasonal_colors.json` freezes those
# measurements so the rule stays pinned to them. All eight land on their
# labelled season; the previous skin-hue + hair-contrast rule scored one.
#
#   redness  skin a* + eyebrow a*  -- the total red (pheomelanin +
#     haemoglobin) load. Warm on the labelled set scored 20-36, cool 10-17.
#     Skin *hue* was the old undertone signal and is worse than a coin
#     flip: it separates nothing on this set (the Summers measured the most
#     "golden" of all eight) because it tracks the photo's white balance
#     more than the shopper. Eyebrow pigment is the honest read -- it is
#     rarely dyed, never made up, and its warm/cool split is what personal-
#     colour analysis has always keyed on.
#
#   contrast  skin L* - mean(eyebrow L*, iris L*)  -- how far the shopper's
#     dark features sit below their skin. Deep on the labelled set scored
#     41-55, light 23-37. Hair L* is a poorer version of the same idea:
#     `hair_color` is categorical (see below), and a mid-blonde on a deep
#     colouring reads "light" from hair while the brows read it correctly.
#
# The margins are 3.0 and 4.1 units wide on eight faces, so these are
# calibrated, not settled. Re-run the script above with more labelled
# photos before trusting them further; the numbers to move are here and
# nowhere else.
_WARM_REDNESS = 18.5
_DEEP_CONTRAST_L = 39.0

# Used only when neither eyebrow nor eye colour is available. Kept from the
# previous rule (skin-to-hair contrast, then bare skin lightness) so a
# payload missing the newer fields degrades to the old behaviour rather
# than to nothing. `hair_color` is a *categorical* read -- YouCam returns a
# canonical hex per colour name (#FAF0BE "Blonde", #000000 "Black"), not a
# measured pixel value -- which is why it is the fallback and not the
# primary depth signal.
_HAIR_DEEP_CONTRAST_L = 35.0
_LIGHT_SKIN_L = 60.0

# Undertone assumed whenever it cannot be measured, i.e. whenever there is
# no eyebrow colour to read (the local degraded path, or an unexpected
# payload shape).
#
# MEASURED: YouCam's `skin_color` is white-balance normalised -- the same
# face shot with a green-warm and a blue-cool grade came back 62.1 deg and
# 63.4 deg, 1.3 deg apart. A raw-pixel hue off the same crops lands 65, 45
# and 74 deg against the API's 62, 63 and 65: up to 18 deg of error that
# tracks the photo's colour cast, not the shopper. Skin alone cannot carry
# undertone even when it *is* normalised -- see `_WARM_REDNESS` above -- so
# rather than guess from it we assume this and say so in the logs.
#
# "warm" rather than "cool" because every skin_color the API has returned
# to us reads warm, so it is the assumption least likely to contradict a
# real read.
_FALLBACK_UNDERTONE = "warm"


def _lab_from_hex(hex_color: Optional[str]) -> Optional[tuple[float, float, float]]:
    """CIELab (L*, a*, b*) for a "#rrggbb" string, or None if unparseable."""
    if not isinstance(hex_color, str):
        return None
    h = hex_color.strip().lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        return None
    rgb = np.uint8([[[int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)]]])  # BGR
    lab = cv2.cvtColor(rgb, cv2.COLOR_BGR2LAB)[0][0]
    # OpenCV packs 8-bit Lab as L*255/100 and a/b offset by 128.
    return float(lab[0]) * 100.0 / 255.0, float(lab[1]) - 128.0, float(lab[2]) - 128.0


def _season_from_colors(
    skin_hex: str,
    hair_hex: Optional[str] = None,
    eyebrow_hex: Optional[str] = None,
    eye_hex: Optional[str] = None,
) -> Optional[str]:
    """Map the colours YouCam returns to a season.

    Undertone is the combined redness of skin and eyebrow; depth is how far
    the shopper's dark features (eyebrow, iris) sit below their skin in L*.
    See the `_WARM_REDNESS` / `_DEEP_CONTRAST_L` block above for what these
    were calibrated on and how wide the margins are.

    Every input but `skin_hex` is optional and each is used only if it
    parses, so a payload carrying fewer fields degrades a step at a time
    rather than failing: without an eyebrow the undertone is *assumed*
    (`_FALLBACK_UNDERTONE`, logged) because nothing else in the payload
    measures it; without eyebrow or iris the depth falls back to the older
    skin-to-hair contrast, and then to bare skin lightness.
    """
    skin = _lab_from_hex(skin_hex)
    if skin is None:
        return None
    skin_l, skin_a, _ = skin
    brow = _lab_from_hex(eyebrow_hex)
    eye = _lab_from_hex(eye_hex)
    hair = _lab_from_hex(hair_hex)

    if brow is not None:
        undertone = "warm" if (skin_a + brow[1]) >= _WARM_REDNESS else "cool"
    else:
        undertone = _FALLBACK_UNDERTONE
        logger.warning(
            "No eyebrow colour in the skin-tone-analysis result; undertone assumed %s "
            "(skin hue alone does not measure it -- see _WARM_REDNESS).",
            _FALLBACK_UNDERTONE,
        )

    dark_l = [feature[0] for feature in (brow, eye) if feature is not None]
    if dark_l:
        contrast = skin_l - sum(dark_l) / len(dark_l)
        depth = "deep" if contrast >= _DEEP_CONTRAST_L else "light"
    elif hair is not None:
        depth = "deep" if (skin_l - hair[0]) >= _HAIR_DEEP_CONTRAST_L else "light"
    else:
        depth = "light" if skin_l >= _LIGHT_SKIN_L else "deep"
    return _season_from_undertone_depth(undertone, depth)


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

    # The verified live shape: colours nested under `color`, or flattened.
    colour_block = tone.get("color") if isinstance(tone.get("color"), dict) else tone
    skin_hex = _first_str(colour_block, _SKIN_COLOR_KEYS)
    if skin_hex:
        hair_hex = _first_str(colour_block, _HAIR_COLOR_KEYS)
        eyebrow_hex = _first_str(colour_block, _EYEBROW_COLOR_KEYS)
        eye_hex = _first_str(colour_block, _EYE_COLOR_KEYS)
        season = _season_from_colors(skin_hex, hair_hex, eyebrow_hex, eye_hex)
        # Logged because the season is DERIVED here, not returned by the
        # API: without the input hexes a surprising season is impossible to
        # tell apart from a bad threshold. These are what any future
        # calibration needs.
        logger.info(
            "skin-tone-analysis returned skin %s / eyebrow %s / eye %s / hair %s -> season %s",
            skin_hex,
            eyebrow_hex,
            eye_hex,
            hair_hex,
            season,
        )
        return season

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


# Error codes that mean "the head is not square to the camera" rather than
# "the request was wrong". VERIFIED live: `error_face_not_forward_facing`
# (yaw) and `error_face_angle_left_tilt` (roll). Only these are worth a
# second, symmetrised attempt -- retrying an auth failure or a rate limit
# would just spend another credit to fail the same way.
_POSE_ERROR_MARKERS = ("not_forward_facing", "face_angle", "not_frontal")


def _is_pose_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _POSE_ERROR_MARKERS)


def _encode_jpeg(face_bgr: np.ndarray) -> Optional[bytes]:
    ok, buf = cv2.imencode(
        ".jpg", face_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), _UPLOAD_JPEG_QUALITY]
    )
    return buf.tobytes() if ok else None


async def _run_analysis(api_client: YouCamClient, face_bytes: bytes) -> dict:
    file_id = await api_client.upload("skin-tone-analysis", face_bytes)
    task_id = await api_client.run("skin-tone-analysis", {"src_file_id": file_id})
    return await api_client.poll(
        "skin-tone-analysis",
        task_id,
        interval=_POLL_INTERVAL_SECONDS,
        max_tries=_POLL_MAX_TRIES,
    )


def _degraded_palette(face_bgr: Optional[np.ndarray] = None) -> dict:
    """The palette to return when YouCam couldn't give us one.

    Measures the skin lightness from the crop's own pixels where possible,
    so a degraded read is still a read of *this* shopper, and pairs it with
    `_FALLBACK_UNDERTONE` (see above -- raw pixels cannot be trusted for
    undertone). `_DEFAULT_PALETTE` is the last resort, for when there
    aren't enough face pixels to average -- it was previously the only
    fallback, and being a plausible-looking Autumn is exactly what let a
    run of failed scans pass for working ones.
    """
    if face_bgr is not None:
        skin_hex = _estimate_skin_hex(face_bgr)
        skin = _lab_from_hex(skin_hex)
        if skin is not None:
            depth = "light" if skin[0] >= _LIGHT_SKIN_L else "deep"
            season = _season_from_undertone_depth(_FALLBACK_UNDERTONE, depth)
            logger.warning(
                "Estimated skin %s locally from the crop -> %s (no YouCam result; "
                "undertone assumed %s, only lightness is measured here).",
                skin_hex,
                season,
                _FALLBACK_UNDERTONE,
            )
            return {"season": season, "colors": list(_SEASON_PALETTES[season])}
    return dict(_DEFAULT_PALETTE)


async def analyze_color(
    front_bgr: np.ndarray, landmarks: Optional[Sequence[Landmark]] = None
) -> dict:
    """Derive a personal-colour palette from a shopper's front photo.

    Crops a face region, runs the YouCam `skin-tone-analysis` task on it
    (retrying once with a mirror-symmetrised crop if the head pose is
    rejected), and derives a season + palette from the result. Never
    raises: every failure mode (no face to crop, a YouCam
    task/timeout/auth error, a raw HTTP error, or an unrecognised result
    payload) is caught and logged as a warning, and a palette estimated
    from the crop's own pixels is returned instead -- a failed colour read
    must never break the shopper's body scan. See module docstring.

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

    face_bgr = _upscale_for_upload(face_bgr)
    face_bytes = _encode_jpeg(face_bgr)
    if face_bytes is None:
        logger.warning("Failed to encode the cropped face image; estimating the palette locally.")
        return _degraded_palette(face_bgr)
    logger.info(
        "Uploading %dx%d face crop (%.0f kB) for skin-tone-analysis.",
        face_bgr.shape[1],
        face_bgr.shape[0],
        len(face_bytes) / 1024,
    )

    try:
        async with YouCamClient() as api_client:
            try:
                result = await _run_analysis(api_client, face_bytes)
            except YouCamTaskError as e:
                # A turned head is the one rejection we can do something
                # about: mirroring the crop satisfies the API's symmetry
                # check without inventing any pixels. One retry only.
                if not _is_pose_rejection(e):
                    raise
                retry_bytes = _encode_jpeg(_symmetrise_face(face_bgr))
                if retry_bytes is None:
                    raise
                logger.warning(
                    "YouCam rejected the crop for head pose (%s); retrying once with a "
                    "mirror-symmetrised crop.",
                    e,
                )
                result = await _run_analysis(api_client, retry_bytes)
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
            "YouCam skin-tone-analysis failed (%s); estimating the palette from the crop instead.",
            e,
        )
        return _degraded_palette(face_bgr)

    palette = _palette_from_result(result)
    if palette is None:
        logger.warning(
            "Unrecognised skin-tone-analysis result payload shape; estimating the palette "
            "from the crop instead. Payload: %r",
            result,
        )
        return _degraded_palette(face_bgr)

    return palette

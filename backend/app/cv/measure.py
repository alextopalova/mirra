"""Body measurement extraction from photos, via MediaPipe's Pose Landmarker
and Image Segmenter.

Environment notes (verified for mediapipe==0.10.35 on macOS ARM / Python
3.12):

- The legacy `mp.solutions.pose` API is NOT present in this build -- only
  `mediapipe.tasks.python.vision.PoseLandmarker` (the newer Tasks API) is
  available. That API needs a model file on disk (see MODEL_PATH below)
  and returns landmarks normalized to 0..1, each carrying an x, y and a
  `visibility` confidence score.
- `PoseLandmarkerOptions(output_segmentation_masks=True)` CRASHES the
  process (SIGABRT) on this build -- do not use it to get a person mask.
  `vision.ImageSegmenter` with the `selfie_segmenter.tflite` model works
  fine and is what we use instead (see SEGMENTER_MODEL_PATH).
- The segmenter's `category_mask` polarity (which of the two label values,
  0 or 255, means "person") is NOT a stable convention we can hardcode --
  it must be resolved per-image by sampling the mask at pixel positions
  we independently know, from the pose landmarks, to be on the body (see
  `_resolve_person_label`).

Why silhouette widths instead of landmark-to-landmark distances: BlazePose's
hip landmarks (23/24) are the hip *joint centers* -- a narrow pelvis pivot
point, not the widest point of the hips/pelvis silhouette. Measuring
shoulder-to-hip and using a fixed cinch factor for the waist (the original
approach) can produce a "waist" wider than the "hips", which is anatomically
impossible and silently misclassifies body shape. Measuring actual
horizontal silhouette width at landmark-derived heights fixes that.

Design: the module is split into layers so the measurement math is
unit-testable without a camera or a photo:

- `extract_landmarks`          -- runs PoseLandmarker, returns pixel-space landmarks.
- `extract_silhouette_widths`  -- runs ImageSegmenter + polarity resolution
                                   + band-width math -> SilhouetteWidths.
- `measurements_from_landmarks` -- pure math over landmarks + widths -> BodyMeasurements.
- `measure_from_images`        -- public entry point; composes the above.
  Task 2.3 (the API route) calls this one.
"""

from __future__ import annotations

import os

# Quiet native TFLite/GL/absl logging *before* mediapipe's C extension is
# imported and initializes its logging backend. These are informational
# native stderr lines (e.g. "Created TensorFlow Lite XNNPACK delegate",
# GL context info) emitted on first model load -- not Python warnings, and
# not indicative of a problem. Setting these here keeps `pytest -v` output
# pristine even if a test module imports this file for the first time
# outside of pytest's own fd-level capture (e.g. `pytest -s`).
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

from app.schemas import BodyMeasurements

logging.getLogger("absl").setLevel(logging.ERROR)

# Resolve relative to this package, not the process CWD, so the API server
# can be launched from anywhere. measure.py -> app/cv -> app -> backend.
_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_PATH = _MODELS_DIR / "pose_landmarker.task"
SEGMENTER_MODEL_PATH = _MODELS_DIR / "selfie_segmenter.tflite"

# BlazePose 33-point topology, same indices as the legacy mp.solutions.pose
# PoseLandmark enum.
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_HIP, R_HIP = 23, 24
L_ANKLE, R_ANKLE = 27, 28

# A landmark is only trusted once MediaPipe's own visibility score clears
# this bar. 0.5 is the threshold MediaPipe's own documentation/examples use
# to mean "confidently visible" (as opposed to occluded or extrapolated);
# below it the model is essentially guessing where the point is -- exactly
# what happens when a limb is cropped out of the frame. For a kiosk flow we
# would much rather over-reject (ask the shopper to step back) than
# silently emit a bogus leg length, so we don't try to be lenient here.
VISIBILITY_THRESHOLD = 0.5

# Landmarks required for a usable full-body front measurement: without
# these, shoulder/hip width and leg length are meaningless.
_KEY_LANDMARKS = {
    "left shoulder": L_SHOULDER,
    "right shoulder": R_SHOULDER,
    "left hip": L_HIP,
    "right hip": R_HIP,
    "left ankle": L_ANKLE,
    "right ankle": R_ANKLE,
}

# Vertical bands used to sample silhouette width, expressed as a fraction
# of torso_span (shoulder-line y=0.0 to hip-line y=1.0). Derived empirically
# against tests/fixtures/person_front.jpg and sanity-checked against typical
# body proportions:
#   - shoulder width is read right at the shoulder line;
#   - bust is the widest point in the upper torso (chest/underarm region);
#   - waist is the *narrowest* point between bust and hip -- the natural
#     waist is always at or below the midpoint, never above it;
#   - hip is the *widest* point around/just below the hip joint landmarks
#     (true hip/pelvis width sits slightly below the joint center).
_SHOULDER_BAND_HALF_FRAC = 0.06
_BUST_BAND_FRAC = (0.05, 0.50)
_WAIST_BAND_FRAC = (0.50, 1.00)
_HIP_BAND_FRAC = (0.95, 1.20)
_BAND_SAMPLES = 25


@dataclass(frozen=True)
class Landmark:
    """A single pose landmark in pixel coordinates."""

    x: float
    y: float
    visibility: float


@dataclass(frozen=True)
class SilhouetteWidths:
    """Horizontal silhouette widths (pixels), measured at landmark-derived
    heights. Kept as its own type (rather than passing four loose floats)
    so callers can't accidentally swap arguments, and so
    `measurements_from_landmarks` can be unit tested with synthetic
    instances -- no image or mask required."""

    shoulder_w: float
    bust_w: float
    waist_w: float
    hip_w: float


_landmarker_singleton: Optional[vision.PoseLandmarker] = None
_segmenter_singleton: Optional[vision.ImageSegmenter] = None


def _get_landmarker() -> vision.PoseLandmarker:
    """Lazily create (and cache) the PoseLandmarker.

    Model load is the expensive part (~seconds), so we build it once per
    process rather than per call.
    """
    global _landmarker_singleton
    if _landmarker_singleton is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Pose landmarker model not found at {MODEL_PATH}. "
                "Run `backend/scripts_setup_model.sh` to download it."
            )
        opts = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
        )
        _landmarker_singleton = vision.PoseLandmarker.create_from_options(opts)
    return _landmarker_singleton


def _get_segmenter() -> vision.ImageSegmenter:
    """Lazily create (and cache) the ImageSegmenter (selfie segmentation
    model), used to get a person-vs-background mask for silhouette widths.

    NOTE: `PoseLandmarkerOptions(output_segmentation_masks=True)` crashes
    the process (SIGABRT) on this Apple Silicon mediapipe build -- do not
    use that path for a mask. This ImageSegmenter + selfie_segmenter model
    combination is the one verified to work.
    """
    global _segmenter_singleton
    if _segmenter_singleton is None:
        if not SEGMENTER_MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Selfie segmenter model not found at {SEGMENTER_MODEL_PATH}. "
                "Run `backend/scripts_setup_model.sh` to download it."
            )
        opts = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(SEGMENTER_MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
            output_category_mask=True,
        )
        _segmenter_singleton = vision.ImageSegmenter.create_from_options(opts)
    return _segmenter_singleton


def extract_landmarks(bgr) -> list[Landmark]:
    """Run PoseLandmarker on a BGR (OpenCV-convention) image array.

    Returns the 33 landmarks in pixel coordinates (normalized x/y scaled by
    the image's width/height). Raises ValueError if no person is detected.
    """
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = _get_landmarker().detect(mp_image)
    if not result.pose_landmarks:
        raise ValueError("no person detected")
    raw = result.pose_landmarks[0]
    return [Landmark(x=lm.x * w, y=lm.y * h, visibility=lm.visibility) for lm in raw]


def _validate_full_body_visible(lms: Sequence[Landmark]) -> None:
    low_confidence = [
        name
        for name, idx in _KEY_LANDMARKS.items()
        if idx >= len(lms) or lms[idx].visibility < VISIBILITY_THRESHOLD
    ]
    if low_confidence:
        raise ValueError(
            "full body not visible (low-confidence: "
            + ", ".join(low_confidence)
            + "). Step back so your shoulders, hips, and ankles are all in frame."
        )


def _pick_more_visible(lms: Sequence[Landmark], left_idx: int, right_idx: int) -> int:
    """A profile photo only clearly shows one side of the body; use whichever
    of the mirrored landmark pair MediaPipe is more confident about."""
    return left_idx if lms[left_idx].visibility >= lms[right_idx].visibility else right_idx


# ---------------------------------------------------------------------------
# Silhouette mask: segmentation, polarity resolution, band-width math.
# All pure/testable except `_segment_person_mask` (the one MediaPipe call).
# ---------------------------------------------------------------------------


def _segment_person_mask(bgr) -> np.ndarray:
    """Run the selfie segmenter; return the raw category mask.

    The returned array's two label values are an implementation detail of
    the model/runtime and are NOT guaranteed to consistently mean "person"
    -- callers must resolve which value is the person via
    `_resolve_person_label` rather than assuming a fixed value.
    """
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = _get_segmenter().segment(mp_image)
    return np.squeeze(result.category_mask.numpy_view())


def _sample_points_on_body(front_lms: Sequence[Landmark]) -> list[tuple[float, float]]:
    """A handful of pixel positions we know, from the pose landmarks, are
    solidly inside the body silhouette (not near an edge): the nose, the
    shoulder midpoint, the hip midpoint, and the chest/belly midpoint
    between those two. Used to resolve mask polarity deterministically."""
    nose = front_lms[NOSE]
    sh_mid = (
        (front_lms[L_SHOULDER].x + front_lms[R_SHOULDER].x) / 2,
        (front_lms[L_SHOULDER].y + front_lms[R_SHOULDER].y) / 2,
    )
    hip_mid = (
        (front_lms[L_HIP].x + front_lms[R_HIP].x) / 2,
        (front_lms[L_HIP].y + front_lms[R_HIP].y) / 2,
    )
    chest_mid = ((sh_mid[0] + hip_mid[0]) / 2, (sh_mid[1] + hip_mid[1]) / 2)
    return [(nose.x, nose.y), sh_mid, hip_mid, chest_mid]


def _resolve_person_label(
    mask: np.ndarray, sample_points: Sequence[tuple[float, float]]
) -> int:
    """Determine which mask label value (typically 0 or 255) means "person",
    by sampling the mask at points known to be on the body and taking the
    majority label among the in-bounds samples. Pure function of the mask
    and sample points -- deterministic and unit-testable, and correct
    regardless of which polarity convention the model happens to emit."""
    h, w = mask.shape
    labels = []
    for x, y in sample_points:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < w and 0 <= yi < h:
            labels.append(int(mask[yi, xi]))
    if not labels:
        raise ValueError(
            "could not resolve silhouette mask polarity: no landmark sample "
            "points fell inside the image bounds"
        )
    # Tie-break (e.g. a 2-2 split among the 4 sample points) is intentional
    # and deterministic, not incidental: np.unique returns `vals` sorted
    # ascending, and np.argmax returns the *first* index attaining the max
    # count, so a tie always resolves to the lower label value. We don't
    # have a principled reason to prefer the lower label on a genuine tie
    # (it's an arbitrary but stable choice) -- the point is that it's
    # reproducible rather than order- or hash-dependent.
    vals, counts = np.unique(labels, return_counts=True)
    return int(vals[np.argmax(counts)])


def _row_contiguous_width(mask: np.ndarray, label: int, y: float, cx: float) -> float:
    """Width, in pixels, of the contiguous run of `label` pixels on row `y`
    that contains column `cx`.

    Using the contiguous run through the body centerline (rather than the
    full min-to-max span of `label` pixels in the row) matters in practice:
    a real photo with arms hanging by the sides or hands on hips puts
    person-label pixels well outside the torso at waist/hip height, which
    would otherwise inflate "torso" width to "torso + arm" width. Where the
    silhouette has any gap between the arm and the torso (typical unless
    the arm is pressed flat against the body), starting from the center and
    expanding outward until the first background pixel isolates the torso.
    """
    h, w = mask.shape
    yi = int(round(y))
    if not (0 <= yi < h):
        return 0.0
    row = mask[yi]
    cxi = int(round(cx))
    if not (0 <= cxi < w) or row[cxi] != label:
        return 0.0
    left = cxi
    while left - 1 >= 0 and row[left - 1] == label:
        left -= 1
    right = cxi
    while right + 1 < w and row[right + 1] == label:
        right += 1
    return float(right - left + 1)


def _band_extreme(
    mask: np.ndarray,
    label: int,
    y0: float,
    y1: float,
    cx_at,
    mode: str,
    n_samples: int = _BAND_SAMPLES,
) -> float:
    """Max or min contiguous silhouette width sampled across rows y0..y1
    (inclusive, order-independent). Rows with no on-body pixel at the
    expected centerline (e.g. band strays outside the image) are skipped
    rather than counted as zero-width, so a partially out-of-frame band
    doesn't spuriously win a `min` search. Returns 0.0 if no row in the
    band yielded a usable sample -- callers treat that as degenerate."""
    lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
    widths = []
    for y in np.linspace(lo, hi, n_samples):
        wpx = _row_contiguous_width(mask, label, y, cx_at(y))
        if wpx > 0:
            widths.append(wpx)
    if not widths:
        return 0.0
    return max(widths) if mode == "max" else min(widths)


def _measure_silhouette_widths(
    mask: np.ndarray, label: int, front_lms: Sequence[Landmark]
) -> SilhouetteWidths:
    """Pure math: mask + resolved person label + landmarks -> band widths.
    No MediaPipe calls here -- safe to unit test with a synthetic mask."""
    sh_mid_x = (front_lms[L_SHOULDER].x + front_lms[R_SHOULDER].x) / 2
    hip_mid_x = (front_lms[L_HIP].x + front_lms[R_HIP].x) / 2
    shoulder_y = (front_lms[L_SHOULDER].y + front_lms[R_SHOULDER].y) / 2
    hip_y = (front_lms[L_HIP].y + front_lms[R_HIP].y) / 2
    torso_span = (hip_y - shoulder_y) or 1e-6

    def y_at(frac: float) -> float:
        return shoulder_y + frac * torso_span

    def cx_at(y: float) -> float:
        # Body centerline, linearly interpolated between the shoulder and
        # hip midpoints so a slightly leaning torso is still tracked.
        frac = (y - shoulder_y) / torso_span
        return sh_mid_x + frac * (hip_mid_x - sh_mid_x)

    shoulder_w = _band_extreme(
        mask, label, y_at(-_SHOULDER_BAND_HALF_FRAC), y_at(_SHOULDER_BAND_HALF_FRAC), cx_at, "max"
    )
    bust_w = _band_extreme(mask, label, y_at(_BUST_BAND_FRAC[0]), y_at(_BUST_BAND_FRAC[1]), cx_at, "max")
    waist_w = _band_extreme(mask, label, y_at(_WAIST_BAND_FRAC[0]), y_at(_WAIST_BAND_FRAC[1]), cx_at, "min")
    hip_w = _band_extreme(mask, label, y_at(_HIP_BAND_FRAC[0]), y_at(_HIP_BAND_FRAC[1]), cx_at, "max")

    return SilhouetteWidths(shoulder_w=shoulder_w, bust_w=bust_w, waist_w=waist_w, hip_w=hip_w)


def extract_silhouette_widths(bgr, front_lms: Sequence[Landmark]) -> SilhouetteWidths:
    """Run the segmenter and turn it into SilhouetteWidths for this photo.
    The one function in this section that actually calls MediaPipe;
    everything it composes (`_resolve_person_label`, `_measure_silhouette_widths`)
    is pure and independently unit tested."""
    mask = _segment_person_mask(bgr)
    label = _resolve_person_label(mask, _sample_points_on_body(front_lms))
    return _measure_silhouette_widths(mask, label, front_lms)


def _validate_widths_sane(widths: SilhouetteWidths) -> None:
    """A waist wider than the hips, or any zero/degenerate width, means the
    mask or the sampling bands were bad (e.g. segmentation failed, subject
    was partly out of frame, or lighting/background confused the model) --
    not that the person's actual shape is implausible. Refuse to emit a
    confidently wrong diagnosis; surface it as a retake request instead."""
    if min(widths.shoulder_w, widths.bust_w, widths.waist_w, widths.hip_w) <= 0:
        raise ValueError(
            "couldn't read your shape clearly -- got a degenerate body "
            "measurement. Please step back and retake the photo with your "
            "full body in frame and even lighting."
        )
    if widths.waist_w >= widths.hip_w:
        raise ValueError(
            "couldn't read your shape clearly -- measured waist wider than "
            "hips, which isn't physically plausible. Please step back and "
            "retake the photo, standing straight with arms slightly away "
            "from your sides."
        )


def measurements_from_landmarks(
    front_lms: Sequence[Landmark],
    widths: SilhouetteWidths,
    side_lms: Optional[Sequence[Landmark]] = None,
    height_cm: Optional[float] = None,
    weight_kg: Optional[float] = None,
) -> BodyMeasurements:
    """Pure math: landmark pixel coordinates + silhouette widths ->
    BodyMeasurements. No MediaPipe calls happen in this function -- it's
    safe (and intended) to unit test with synthetic Landmark lists and a
    synthetic SilhouetteWidths.
    """
    _validate_full_body_visible(front_lms)
    _validate_widths_sane(widths)

    shoulder_y = (front_lms[L_SHOULDER].y + front_lms[R_SHOULDER].y) / 2
    hip_y = (front_lms[L_HIP].y + front_lms[R_HIP].y) / 2
    ankle_y = (front_lms[L_ANKLE].y + front_lms[R_ANKLE].y) / 2
    torso_len = abs(hip_y - shoulder_y)
    leg_len = abs(ankle_y - hip_y)

    bmi = 22.0
    if height_cm and weight_kg:
        m2 = (height_cm / 100.0) ** 2
        bmi = round(weight_kg / m2, 1)

    torso_depth = None
    has_side = False
    if side_lms is not None:
        shoulder_idx = _pick_more_visible(side_lms, L_SHOULDER, R_SHOULDER)
        hip_idx = _pick_more_visible(side_lms, L_HIP, R_HIP)
        # Side data is supplementary: if it's too low-confidence to trust
        # (e.g. the person wasn't actually in profile, or wasn't in frame),
        # we silently skip the depth estimate rather than raising -- the
        # front measurement alone is still perfectly usable.
        if (
            side_lms[shoulder_idx].visibility >= VISIBILITY_THRESHOLD
            and side_lms[hip_idx].visibility >= VISIBILITY_THRESHOLD
        ):
            # Torso "depth" proxy: in a side-view photo, the horizontal (x)
            # span between the hip and shoulder landmarks correlates with
            # front-to-back torso thickness/lean, normalized by the
            # vertical torso height in the same image so it's roughly
            # scale-invariant. Pose has no true depth/thickness landmark;
            # this is a coarse 2D stand-in, only computed when a side photo
            # is supplied, per MVP scope.
            depth_px = abs(side_lms[hip_idx].x - side_lms[shoulder_idx].x)
            side_torso = abs(side_lms[hip_idx].y - side_lms[shoulder_idx].y) or 1.0
            torso_depth = round(min(depth_px / side_torso, 1.0), 3)
            has_side = True

    return BodyMeasurements(
        shoulder_w=widths.shoulder_w,
        bust_w=widths.bust_w,
        waist_w=widths.waist_w,
        hip_w=widths.hip_w,
        torso_len=torso_len,
        leg_len=leg_len,
        bmi=bmi,
        has_side=has_side,
        torso_depth=torso_depth,
    )


def measure_from_images(
    front_bgr,
    side_bgr=None,
    height_cm: Optional[float] = None,
    weight_kg: Optional[float] = None,
) -> BodyMeasurements:
    """Public entry point: photos in, BodyMeasurements out.

    Raises ValueError if no person is detected in the front photo, if the
    front photo doesn't show the full body (see VISIBILITY_THRESHOLD), or
    if the silhouette measurement comes out anatomically implausible (see
    `_validate_widths_sane`) -- in all cases the caller should ask the
    shopper to step back and retake the photo. A side photo is optional and
    best-effort: if no person is found in it, it's silently ignored rather
    than failing the whole measurement.
    """
    front_lms = extract_landmarks(front_bgr)
    _validate_full_body_visible(front_lms)
    widths = extract_silhouette_widths(front_bgr, front_lms)

    side_lms = None
    if side_bgr is not None:
        try:
            side_lms = extract_landmarks(side_bgr)
        except ValueError:
            side_lms = None

    return measurements_from_landmarks(
        front_lms, widths, side_lms=side_lms, height_cm=height_cm, weight_kg=weight_kg
    )

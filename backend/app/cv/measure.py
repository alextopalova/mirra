"""Body measurement extraction from photos, via MediaPipe's Pose Landmarker.

Environment note (verified for mediapipe==0.10.35 on macOS ARM / Python
3.12): the legacy `mp.solutions.pose` API is NOT present in this build --
only `mediapipe.tasks.python.vision.PoseLandmarker` (the newer Tasks API)
is available. That API needs a model file on disk (see MODEL_PATH below)
and returns landmarks normalized to 0..1, each carrying an x, y and a
`visibility` confidence score.

Design: the module is split into three layers so the measurement math is
unit-testable without a camera or a photo:

- `extract_landmarks`      -- runs MediaPipe, returns pixel-space landmarks.
- `measurements_from_landmarks` -- pure math over landmarks -> BodyMeasurements.
- `measure_from_images`    -- public entry point; composes the two above.
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
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

from app.schemas import BodyMeasurements

logging.getLogger("absl").setLevel(logging.ERROR)

# Resolve relative to this package, not the process CWD, so the API server
# can be launched from anywhere. measure.py -> app/cv -> app -> backend.
MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "pose_landmarker.task"

# BlazePose 33-point topology, same indices as the legacy mp.solutions.pose
# PoseLandmark enum.
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


@dataclass(frozen=True)
class Landmark:
    """A single pose landmark in pixel coordinates."""

    x: float
    y: float
    visibility: float


_landmarker_singleton: Optional[vision.PoseLandmarker] = None


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


def measurements_from_landmarks(
    front_lms: Sequence[Landmark],
    side_lms: Optional[Sequence[Landmark]] = None,
    height_cm: Optional[float] = None,
    weight_kg: Optional[float] = None,
) -> BodyMeasurements:
    """Pure math: turn landmark pixel coordinates into BodyMeasurements.

    No MediaPipe calls happen in this function -- it's safe (and intended)
    to unit test with synthetic Landmark lists.
    """
    _validate_full_body_visible(front_lms)

    def dx(a: int, b: int) -> float:
        return abs(front_lms[a].x - front_lms[b].x)

    shoulder_w = dx(L_SHOULDER, R_SHOULDER)
    hip_w = dx(L_HIP, R_HIP)

    # Pose has no waist or bust landmark, so both are approximated from the
    # spans we do have. These are intentional MVP heuristics, not
    # anthropometric measurements -- refine later with a segmentation mask
    # (e.g. MediaPipe Selfie Segmentation) at the waist y-level if time
    # allows:
    #   - bust sits slightly narrower than the shoulder line -> 0.92x shoulder width.
    #   - waist is approximated as the shoulder/hip midpoint span, cinched
    #     in by a fixed factor (0.82) to account for the torso narrowing
    #     inward rather than staying a straight line between shoulder and hip.
    bust_w = shoulder_w * 0.92
    waist_w = (shoulder_w + hip_w) / 2 * 0.82

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
        shoulder_w=shoulder_w,
        bust_w=bust_w,
        waist_w=waist_w,
        hip_w=hip_w,
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

    Raises ValueError if no person is detected in the front photo, or if
    the front photo doesn't show the full body (see VISIBILITY_THRESHOLD).
    A side photo is optional and best-effort: if no person is found in it,
    it's silently ignored rather than failing the whole measurement.
    """
    front_lms = extract_landmarks(front_bgr)

    side_lms = None
    if side_bgr is not None:
        try:
            side_lms = extract_landmarks(side_bgr)
        except ValueError:
            side_lms = None

    return measurements_from_landmarks(
        front_lms, side_lms=side_lms, height_cm=height_cm, weight_kg=weight_kg
    )

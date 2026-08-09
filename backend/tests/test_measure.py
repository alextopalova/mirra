from pathlib import Path

import pytest

from app.cv.classify import classify
from app.cv.measure import (
    Landmark,
    VISIBILITY_THRESHOLD,
    measure_from_images,
    measurements_from_landmarks,
)

FIXTURE = Path(__file__).parent / "fixtures" / "person_front.jpg"


def _lm(x, y, visibility=0.99):
    return Landmark(x=x, y=y, visibility=visibility)


def _front_landmarks(shoulder_w=90, hip_w=100, torso_len=55, leg_len=95, cx=200, top_y=100):
    """Build a plausible 33-point synthetic front-view pose.

    Only the indices measure.py actually reads (shoulders 11/12, hips
    23/24, ankles 27/28) are given meaningful values; every other index is
    filled with a harmless, fully-visible placeholder so list look-ups
    never go out of range.
    """
    lms = [_lm(cx, top_y, 0.99) for _ in range(33)]
    shoulder_y = top_y + 40
    hip_y = shoulder_y + torso_len
    ankle_y = hip_y + leg_len
    lms[11] = _lm(cx - shoulder_w / 2, shoulder_y)  # left shoulder
    lms[12] = _lm(cx + shoulder_w / 2, shoulder_y)  # right shoulder
    lms[23] = _lm(cx - hip_w / 2, hip_y)            # left hip
    lms[24] = _lm(cx + hip_w / 2, hip_y)            # right hip
    lms[27] = _lm(cx - 10, ankle_y)                 # left ankle
    lms[28] = _lm(cx + 10, ankle_y)                 # right ankle
    return lms


def _side_landmarks(shoulder_x=150, hip_x=175, shoulder_y=140, hip_y=195):
    """Profile pose: only the person's near (left) side is clearly visible."""
    lms = [_lm(150, 100, 0.99) for _ in range(33)]
    lms[11] = _lm(shoulder_x, shoulder_y, 0.95)  # left shoulder (near side, visible)
    lms[12] = _lm(shoulder_x, shoulder_y, 0.15)  # right shoulder (occluded in profile)
    lms[23] = _lm(hip_x, hip_y, 0.95)            # left hip (near side, visible)
    lms[24] = _lm(hip_x, hip_y, 0.15)            # right hip (occluded in profile)
    return lms


# ---------------------------------------------------------------------------
# measurements_from_landmarks: pure math, no MediaPipe involved
# ---------------------------------------------------------------------------

def test_widths_and_ratios_are_plausible():
    m = measurements_from_landmarks(_front_landmarks(shoulder_w=90, hip_w=100), height_cm=170, weight_kg=62)
    assert m.shoulder_w > 0 and m.hip_w > 0
    assert 0.5 < (m.shoulder_w / m.hip_w) < 2.0
    # bust/waist approximations should stay positive and smaller than the
    # spans they're derived from (they are cinch/narrowing factors).
    assert 0 < m.bust_w < m.shoulder_w
    assert 0 < m.waist_w < max(m.shoulder_w, m.hip_w)


def test_bmi_computed_from_height_and_weight():
    m = measurements_from_landmarks(_front_landmarks(), height_cm=170, weight_kg=62)
    expected = round(62 / (1.70 ** 2), 1)
    assert m.bmi == expected
    assert 20 < m.bmi < 25


def test_bmi_defaults_when_height_or_weight_missing():
    m = measurements_from_landmarks(_front_landmarks())
    assert m.bmi == 22.0


def test_torso_and_leg_length_match_landmark_geometry():
    m = measurements_from_landmarks(_front_landmarks(torso_len=55, leg_len=95))
    assert m.torso_len == pytest.approx(55, abs=1e-6)
    assert m.leg_len == pytest.approx(95, abs=1e-6)


def test_torso_depth_present_with_side_view():
    m = measurements_from_landmarks(_front_landmarks(), side_lms=_side_landmarks())
    assert m.has_side is True
    assert m.torso_depth is not None
    assert 0 < m.torso_depth <= 1.0


def test_no_side_view_leaves_depth_unset():
    m = measurements_from_landmarks(_front_landmarks())
    assert m.has_side is False
    assert m.torso_depth is None


def test_low_visibility_side_view_skips_depth_without_raising():
    poor_side = [_lm(100, 100, 0.1) for _ in range(33)]  # nothing confidently visible
    m = measurements_from_landmarks(_front_landmarks(), side_lms=poor_side)
    assert m.has_side is False
    assert m.torso_depth is None


def test_result_feeds_classifier_without_error():
    m = measurements_from_landmarks(_front_landmarks(), height_cm=170, weight_kg=62)
    p = classify(m)
    assert p.fruit in {"hourglass", "pear", "apple", "rectangle", "inverted-triangle"}


# ---------------------------------------------------------------------------
# Visibility validation
# ---------------------------------------------------------------------------

def test_raises_when_ankles_not_visible_cropped_frame():
    lms = _front_landmarks()
    lms[27] = _lm(lms[27].x, lms[27].y, visibility=0.1)  # ankle cropped out of frame
    lms[28] = _lm(lms[28].x, lms[28].y, visibility=0.1)
    with pytest.raises(ValueError, match="full body not visible"):
        measurements_from_landmarks(lms)


def test_raises_when_shoulder_not_visible():
    lms = _front_landmarks()
    lms[11] = _lm(lms[11].x, lms[11].y, visibility=0.05)
    with pytest.raises(ValueError, match="full body not visible"):
        measurements_from_landmarks(lms)


def test_raises_when_hip_not_visible():
    lms = _front_landmarks()
    lms[23] = _lm(lms[23].x, lms[23].y, visibility=0.2)
    lms[24] = _lm(lms[24].x, lms[24].y, visibility=0.2)
    with pytest.raises(ValueError, match="full body not visible"):
        measurements_from_landmarks(lms)


def test_visibility_right_at_threshold_is_accepted():
    lms = _front_landmarks()
    for idx in (11, 12, 23, 24, 27, 28):
        lms[idx] = _lm(lms[idx].x, lms[idx].y, visibility=VISIBILITY_THRESHOLD)
    m = measurements_from_landmarks(lms)  # should not raise
    assert m.shoulder_w > 0


# ---------------------------------------------------------------------------
# measure_from_images: the public entry point (Task 2.3 calls this directly)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FIXTURE.exists(), reason=(
    "backend/tests/fixtures/person_front.jpg not present locally; "
    "see backend/tests/fixtures/README.md for requirements"
))
def test_measure_from_images_returns_plausible_and_classifiable():
    import cv2

    img = cv2.imread(str(FIXTURE))
    assert img is not None
    m = measure_from_images(img, height_cm=170, weight_kg=62)
    assert m.shoulder_w > 0 and m.hip_w > 0
    assert 0.5 < (m.shoulder_w / m.hip_w) < 2.0
    assert 20 < m.bmi < 25
    p = classify(m)
    assert p.fruit in {"hourglass", "pear", "apple", "rectangle", "inverted-triangle"}


def test_measure_from_images_raises_on_missing_model(monkeypatch, tmp_path):
    from app.cv import measure as measure_mod

    monkeypatch.setattr(measure_mod, "MODEL_PATH", tmp_path / "does_not_exist.task")
    monkeypatch.setattr(measure_mod, "_landmarker_singleton", None)
    with pytest.raises(FileNotFoundError, match="scripts_setup_model.sh"):
        measure_mod._get_landmarker()

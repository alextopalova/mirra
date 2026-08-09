from pathlib import Path

import numpy as np
import pytest

from app.cv.classify import classify
from app.cv.measure import (
    Landmark,
    SilhouetteWidths,
    VISIBILITY_THRESHOLD,
    _measure_silhouette_widths,
    _resolve_person_label,
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


def _widths(shoulder_w=90, bust_w=85, waist_w=60, hip_w=100):
    """A plausible SilhouetteWidths for tests that don't care about the
    exact band math -- just need something that passes the sanity clamp."""
    return SilhouetteWidths(shoulder_w=shoulder_w, bust_w=bust_w, waist_w=waist_w, hip_w=hip_w)


# ---------------------------------------------------------------------------
# measurements_from_landmarks: pure math, no MediaPipe involved
# ---------------------------------------------------------------------------

def test_widths_pass_through_and_ratios_are_plausible():
    widths = _widths(shoulder_w=90, bust_w=85, waist_w=60, hip_w=100)
    m = measurements_from_landmarks(_front_landmarks(), widths, height_cm=170, weight_kg=62)
    # The silhouette widths flow straight through into BodyMeasurements --
    # measurements_from_landmarks does no width math of its own anymore.
    assert m.shoulder_w == widths.shoulder_w
    assert m.bust_w == widths.bust_w
    assert m.waist_w == widths.waist_w
    assert m.hip_w == widths.hip_w
    assert 0.5 < (m.shoulder_w / m.hip_w) < 2.0
    assert m.waist_w < m.hip_w


def test_bmi_computed_from_height_and_weight():
    m = measurements_from_landmarks(_front_landmarks(), _widths(), height_cm=170, weight_kg=62)
    expected = round(62 / (1.70 ** 2), 1)
    assert m.bmi == expected
    assert 20 < m.bmi < 25


def test_bmi_defaults_when_height_or_weight_missing():
    m = measurements_from_landmarks(_front_landmarks(), _widths())
    assert m.bmi == 22.0


def test_torso_and_leg_length_match_landmark_geometry():
    m = measurements_from_landmarks(_front_landmarks(torso_len=55, leg_len=95), _widths())
    assert m.torso_len == pytest.approx(55, abs=1e-6)
    assert m.leg_len == pytest.approx(95, abs=1e-6)


def test_torso_depth_present_with_side_view():
    m = measurements_from_landmarks(_front_landmarks(), _widths(), side_lms=_side_landmarks())
    assert m.has_side is True
    assert m.torso_depth is not None
    assert 0 < m.torso_depth <= 1.0


def test_no_side_view_leaves_depth_unset():
    m = measurements_from_landmarks(_front_landmarks(), _widths())
    assert m.has_side is False
    assert m.torso_depth is None


def test_low_visibility_side_view_skips_depth_without_raising():
    poor_side = [_lm(100, 100, 0.1) for _ in range(33)]  # nothing confidently visible
    m = measurements_from_landmarks(_front_landmarks(), _widths(), side_lms=poor_side)
    assert m.has_side is False
    assert m.torso_depth is None


def test_result_feeds_classifier_without_error():
    m = measurements_from_landmarks(_front_landmarks(), _widths(), height_cm=170, weight_kg=62)
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
        measurements_from_landmarks(lms, _widths())


def test_raises_when_shoulder_not_visible():
    lms = _front_landmarks()
    lms[11] = _lm(lms[11].x, lms[11].y, visibility=0.05)
    with pytest.raises(ValueError, match="full body not visible"):
        measurements_from_landmarks(lms, _widths())


def test_raises_when_hip_not_visible():
    lms = _front_landmarks()
    lms[23] = _lm(lms[23].x, lms[23].y, visibility=0.2)
    lms[24] = _lm(lms[24].x, lms[24].y, visibility=0.2)
    with pytest.raises(ValueError, match="full body not visible"):
        measurements_from_landmarks(lms, _widths())


def test_visibility_right_at_threshold_is_accepted():
    lms = _front_landmarks()
    for idx in (11, 12, 23, 24, 27, 28):
        lms[idx] = _lm(lms[idx].x, lms[idx].y, visibility=VISIBILITY_THRESHOLD)
    m = measurements_from_landmarks(lms, _widths())  # should not raise
    assert m.shoulder_w > 0


# ---------------------------------------------------------------------------
# Sanity clamp: a bad silhouette measurement must not produce a confidently
# wrong diagnosis -- it must raise instead.
# ---------------------------------------------------------------------------

def test_raises_when_waist_wider_than_hip():
    bad_widths = _widths(shoulder_w=90, bust_w=95, waist_w=110, hip_w=100)
    with pytest.raises(ValueError, match="waist wider than hips"):
        measurements_from_landmarks(_front_landmarks(), bad_widths)


def test_raises_on_degenerate_zero_width():
    bad_widths = _widths(hip_w=0)
    with pytest.raises(ValueError, match="degenerate"):
        measurements_from_landmarks(_front_landmarks(), bad_widths)


# ---------------------------------------------------------------------------
# Silhouette polarity resolution: pure function of a mask + sample points,
# no MediaPipe involved. Must work regardless of which of the two label
# values the segmenter happens to use for "person" on a given run.
# ---------------------------------------------------------------------------

def test_resolve_person_label_handles_both_mask_polarities():
    # A 100x100 mask with a solid "body" rectangle from row 20-79, col
    # 30-69. All sample points sit well inside it.
    sample_points = [(50, 50), (50, 30), (50, 70), (50, 40)]  # (x, y)
    for body_label, bg_label in [(255, 0), (0, 255)]:
        mask = np.full((100, 100), bg_label, dtype=np.uint8)
        mask[20:80, 30:70] = body_label
        assert _resolve_person_label(mask, sample_points) == body_label


def test_resolve_person_label_raises_when_no_sample_points_in_bounds():
    mask = np.zeros((10, 10), dtype=np.uint8)
    with pytest.raises(ValueError, match="polarity"):
        _resolve_person_label(mask, [(-5, -5), (50, 50)])


# ---------------------------------------------------------------------------
# Silhouette band-width math: pure function of a mask + label + landmarks.
# Uses a synthetic mask with a distinct, known width in each vertical band
# (shoulder / bust / waist / hip) to verify the max/min band logic picks
# the right value from each, and that waist correctly comes out as the
# narrowest of the four.
# ---------------------------------------------------------------------------

def _stepped_width(y: int) -> int:
    """Piecewise silhouette width (px) by absolute row y, for a synthetic
    torso spanning shoulder_y=50 to hip_y=200 (torso_span=150).

    Chosen so each band constant defined in measure.py samples a distinct,
    unambiguous value:
      - shoulder band  y in [41, 59]   -> 80  (only value present there)
      - bust band      y in [57.5,125] -> max is 90 (80 briefly, then 90)
      - waist band     y in [125, 200] -> min is 40
      - hip band       y in [192.5,230]-> max is 100
    """
    if y < 41:
        return 60
    if y < 60:
        return 80
    if y < 125:
        return 90
    if y < 200:
        return 40
    if y <= 230:
        return 100
    return 50


def _make_banded_mask(person_label=255, bg_label=0, h=300, w=300, cx=150):
    mask = np.full((h, w), bg_label, dtype=np.uint8)
    for y in range(h):
        half = _stepped_width(y) // 2
        mask[y, cx - half : cx + half] = person_label
    return mask


def test_measure_silhouette_widths_finds_bust_waist_hip_bands():
    mask = _make_banded_mask()
    # shoulder_y=50, hip_y=200 (torso_len=150), centerline x=150 throughout.
    front_lms = _front_landmarks(shoulder_w=80, hip_w=100, torso_len=150, leg_len=90, cx=150, top_y=10)
    widths = _measure_silhouette_widths(mask, 255, front_lms)
    assert widths.shoulder_w == pytest.approx(80)
    assert widths.bust_w == pytest.approx(90)
    assert widths.waist_w == pytest.approx(40)
    assert widths.hip_w == pytest.approx(100)
    assert widths.waist_w < widths.hip_w  # narrowest point, as expected


# ---------------------------------------------------------------------------
# measure_from_images: the public entry point (Task 2.3 calls this directly)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FIXTURE.exists(), reason=(
    "backend/tests/fixtures/person_front.jpg not present locally; "
    "see backend/tests/fixtures/README.md for requirements"
))
def test_measure_from_images_returns_anatomically_sane_result():
    import cv2

    img = cv2.imread(str(FIXTURE))
    assert img is not None
    m = measure_from_images(img, height_cm=170, weight_kg=62)
    assert m.shoulder_w > 0 and m.hip_w > 0
    # A real body: shoulders and hips are in the same ballpark, and the
    # waist is narrower than the hips. The old landmark-distance approach
    # violated both of these on this exact photo (shoulder/hip=1.73,
    # waist/hip=1.12) and misclassified it as inverted-triangle.
    assert 0.6 < (m.shoulder_w / m.hip_w) < 1.4
    assert m.waist_w < m.hip_w
    assert 20 < m.bmi < 25
    p = classify(m)
    assert p.fruit != "inverted-triangle"
    assert p.fruit in {"hourglass", "pear", "apple", "rectangle"}


def test_measure_from_images_raises_on_missing_model(monkeypatch, tmp_path):
    from app.cv import measure as measure_mod

    monkeypatch.setattr(measure_mod, "MODEL_PATH", tmp_path / "does_not_exist.task")
    monkeypatch.setattr(measure_mod, "_landmarker_singleton", None)
    with pytest.raises(FileNotFoundError, match="scripts_setup_model.sh"):
        measure_mod._get_landmarker()


def test_get_segmenter_raises_on_missing_model(monkeypatch, tmp_path):
    from app.cv import measure as measure_mod

    monkeypatch.setattr(measure_mod, "SEGMENTER_MODEL_PATH", tmp_path / "does_not_exist.tflite")
    monkeypatch.setattr(measure_mod, "_segmenter_singleton", None)
    with pytest.raises(FileNotFoundError, match="scripts_setup_model.sh"):
        measure_mod._get_segmenter()

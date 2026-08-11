from pathlib import Path

import numpy as np
import pytest

from app.cv.classify import classify
from app.cv.measure import (
    Landmark,
    SilhouetteWidths,
    VISIBILITY_THRESHOLD,
    _BAND_SAMPLES,
    _HIP_BAND_FRAC,
    _measure_silhouette_widths,
    _resolve_person_label,
    _row_contiguous_width,
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


def test_raises_when_waist_equals_hip():
    # Spec requires waist >= hip to raise, not just strict waist > hip: a
    # waist exactly as wide as the hips is still anatomically implausible
    # (real waists are narrower) and should be treated as a bad
    # measurement, not silently accepted.
    bad_widths = _widths(shoulder_w=90, bust_w=95, waist_w=100, hip_w=100)
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


def test_resolve_person_label_tie_break_favors_lower_label_value():
    # A 2-2 split among the 4 sample points (e.g. an unusual pose or a mask
    # straddling an edge) has no true majority. The tie-break is documented
    # in measure.py as intentional and deterministic: it favors the lower
    # label value. Pin that here so a refactor (e.g. swapping np.unique for
    # collections.Counter, whose ordering is insertion-based, not sorted)
    # doesn't silently change which label wins ties.
    mask = np.zeros((10, 10), dtype=np.uint8)
    mask[0, 0] = 10
    mask[0, 1] = 10
    mask[0, 2] = 200
    mask[0, 3] = 200
    sample_points = [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert _resolve_person_label(mask, sample_points) == 10
    # And confirm it's genuinely a tie, not one label just happening to be
    # first in the list -- swapping which coordinates carry which label
    # still favors the lower value.
    mask2 = np.zeros((10, 10), dtype=np.uint8)
    mask2[0, 0] = 200
    mask2[0, 1] = 10
    mask2[0, 2] = 10
    mask2[0, 3] = 200
    assert _resolve_person_label(mask2, sample_points) == 10


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


def test_row_contiguous_width_excludes_detached_arm_blob():
    # A row with a torso column centered on cx, PLUS a separate arm/hand
    # blob a few pixels to the side with a background gap between them --
    # the shape that a real "hands on hips" or "arm hanging by the side"
    # photo produces at waist/hip height. This is the case the whole
    # accuracy fix (contiguous-run-through-centerline, not full row span)
    # exists to handle; the stepped-rectangle band test elsewhere has no
    # such appendage and would pass even if this logic regressed to a
    # naive min/max span.
    h, w = 20, 100
    mask = np.zeros((h, w), dtype=np.uint8)
    label = 255
    y = 10
    # Torso: cols 40..59 inclusive (width 20), centered around cx=49.
    mask[y, 40:60] = label
    # Background gap: cols 60..74 (untouched, stays 0) -- separates the arm
    # from the torso.
    # Arm/hand blob: cols 75..84 inclusive (width 10), same label as torso,
    # same row -- exactly what a naive min/max span over the row would
    # (wrongly) fold into "torso" width.
    mask[y, 75:85] = label

    torso_width = _row_contiguous_width(mask, label, y=y, cx=49)
    assert torso_width == pytest.approx(20)

    # Sanity-check the test's own premise: a naive full-row bounding span
    # (leftmost to rightmost label pixel, ignoring the background gap)
    # WOULD have swallowed the arm blob. If `_row_contiguous_width` ever
    # regressed to that logic, this assertion is what would catch it.
    cols_with_label = np.where(mask[y] == label)[0]
    naive_span = float(cols_with_label.max() - cols_with_label.min() + 1)
    assert naive_span == pytest.approx(45)
    assert naive_span != torso_width


def test_measure_silhouette_widths_rejects_hand_rejoin_artefact_in_hip_band():
    # Regression test for the shipped bug: for a subject standing with arms
    # at their sides (the common kiosk pose), the hands/wrists rejoin the
    # torso silhouette near the bottom of the hip band, merging into the
    # same contiguous centerline run and producing a single row far wider
    # than the true hip width -- the exact mechanism in the bug report
    # (frac +1.05 spiked to w=327 on the real fixture while frac +1.00 was
    # still w=271, a 109px single-row collapse either side of it). A raw
    # max over the band would pick up that one row; the percentile-based
    # `_band_extreme` should not.
    h, w = 400, 400
    label = 255
    cx = 200
    mask = np.zeros((h, w), dtype=np.uint8)
    for y in range(h):
        half = 50  # true torso/hip half-width everywhere -> width 100
        mask[y, cx - half : cx + half] = label
    # Hand/arm reconnection artefact: right at the bottom edge of the hip
    # band, the hands/wrists merge into the torso's contiguous run for this
    # one row, tripling the apparent width.
    shoulder_y, hip_y = 100, 300
    torso_span = hip_y - shoulder_y
    artefact_y = round(shoulder_y + _HIP_BAND_FRAC[1] * torso_span)  # bottom of the hip band
    mask[artefact_y, cx - 150 : cx + 150] = label

    front_lms = _front_landmarks(
        shoulder_w=100, hip_w=100, torso_len=torso_span, leg_len=90, cx=cx, top_y=60
    )
    widths = _measure_silhouette_widths(mask, label, front_lms)
    # The measured hip width reflects the true torso, not the blob.
    assert widths.hip_w == pytest.approx(100)

    # Sanity-check the test's own premise: a naive raw-max-over-the-band
    # approach (what `_band_extreme` did before the percentile fix) WOULD
    # have picked up the artefact row and returned the inflated width. If
    # `_band_extreme` ever regressed to plain max/min, this is what would
    # catch it.
    y0 = shoulder_y + _HIP_BAND_FRAC[0] * torso_span
    y1 = shoulder_y + _HIP_BAND_FRAC[1] * torso_span
    naive_samples = [
        _row_contiguous_width(mask, label, y, cx) for y in np.linspace(y0, y1, _BAND_SAMPLES)
    ]
    naive_max = max(naive_samples)
    assert naive_max == pytest.approx(300)
    assert naive_max != widths.hip_w


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
    #
    # This range is intentionally tight (not just "wide enough to pass"):
    # a too-wide hip band used to make the hand/arm silhouette rejoin the
    # torso and get picked up as "hip" width, inflating hip_w by ~17% and
    # dragging shoulder/hip down to 0.766 -- comfortably inside a loose
    # 0.6-1.4 bound, so that bound didn't catch the bug. 0.85-1.20 is
    # anatomically realistic for a front-view adult body and would have
    # failed on the inflated 0.766.
    assert 0.85 < (m.shoulder_w / m.hip_w) < 1.20
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


# ---------------------------------------------------------------------------
# Arm contamination: a hands-on-hips pose fuses the forearm into the torso
# ---------------------------------------------------------------------------

def _arm_landmarks(base, side, elbow, wrist, index):
    """Attach one arm chain (elbow/wrist/fingertip) to a synthetic pose."""
    e, w, i = (13, 15, 19) if side == "left" else (14, 16, 20)
    base[e], base[w], base[i] = _lm(*elbow), _lm(*wrist), _lm(*index)
    return base


def test_arm_x_at_interpolates_along_the_chain_and_stops_at_the_fingertips():
    from app.cv.measure import _arm_x_at

    lms = _front_landmarks(shoulder_w=90, cx=200)
    shoulder_y = lms[11].y
    # Left arm hanging straight down and slightly outward.
    lms = _arm_landmarks(lms, "left", (150, shoulder_y + 40), (140, shoulder_y + 80),
                         (138, shoulder_y + 90))

    # Midway between shoulder (x=155) and elbow (x=150).
    assert _arm_x_at(lms, shoulder_y + 20, "left") == pytest.approx(152.5, abs=0.6)
    # Above the shoulder and below the fingertips there is no arm to hit.
    assert _arm_x_at(lms, shoulder_y - 10, "left") is None
    assert _arm_x_at(lms, shoulder_y + 200, "left") is None


def test_row_with_a_hand_resting_on_the_hip_is_rejected_as_arm_contaminated():
    from app.cv.measure import _row_is_arm_contaminated

    lms = _front_landmarks(shoulder_w=90, hip_w=100, cx=200)
    hip_y = lms[23].y
    # Hand sitting on the hip: the fingertip chain passes right through
    # hip height, well outside the torso.
    lms = _arm_landmarks(lms, "left", (170, hip_y - 60), (160, hip_y - 5), (158, hip_y + 20))

    # The arm sits at x~159, left of the body centerline (cx=200).
    # A run whose left edge stops short of it is a clean torso reading...
    assert _row_is_arm_contaminated(175, 245, 200, hip_y, lms) is False
    # ...but one that reaches past the arm's centerline has swallowed it.
    assert _row_is_arm_contaminated(155, 245, 200, hip_y, lms) is True


def test_band_extreme_skips_rows_where_an_arm_is_fused_to_the_torso():
    """The regression this guards: on a hands-on-hips photo every row in the
    hip band read torso+forearm+hand, measuring the hips ~50% too wide and
    turning a defined waist into a pear."""
    from app.cv.measure import _band_extreme

    # Torso 60px wide, plus a 40px "arm" fused onto its right at every row.
    mask = np.zeros((60, 300), dtype=np.uint8)
    mask[:, 100:160] = 1          # torso
    mask[20:40, 160:200] = 1      # arm fused to the torso, rows 20-39

    lms = _front_landmarks(cx=130)
    lms[11], lms[12] = _lm(100, 0), _lm(160, 0)
    lms[23], lms[24] = _lm(100, 59), _lm(160, 59)
    # One arm chain running down the fused region's centerline (x=180); the
    # other hangs clear on the opposite side so it constrains nothing.
    lms = _arm_landmarks(lms, "left", (180, 10), (180, 35), (180, 45))
    lms = _arm_landmarks(lms, "right", (80, 10), (80, 35), (80, 45))

    def cx_at(_y):
        return 130.0

    # Band spans both fused (20-39) and clean rows, as a real hip band does.
    # Without the pose, the fused rows win the "max" and inflate the width.
    assert _band_extreme(mask, 1, 0, 59, cx_at, "max") == pytest.approx(100, abs=1)
    # With it, those rows are dropped and only the true torso is measured.
    assert _band_extreme(mask, 1, 0, 59, cx_at, "max", lms=lms) == pytest.approx(60, abs=1)

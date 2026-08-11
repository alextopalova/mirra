from app.schemas import BodyMeasurements
from app.cv.classify import classify


def m(**kw):
    base = dict(shoulder_w=100, bust_w=95, waist_w=75, hip_w=100,
                torso_len=60, leg_len=90, bmi=22.0)
    base.update(kw)
    return BodyMeasurements(**base)


def test_hourglass_when_balanced_with_defined_waist():
    p = classify(m(shoulder_w=100, hip_w=100, waist_w=72))
    assert p.fruit == "hourglass"


def test_pear_when_hips_wider():
    p = classify(m(shoulder_w=88, hip_w=104, waist_w=78))
    assert p.fruit == "pear"


def test_inverted_triangle_when_shoulders_wider():
    p = classify(m(shoulder_w=108, hip_w=90, waist_w=88))
    assert p.fruit == "inverted-triangle"


def test_rectangle_when_balanced_no_waist():
    p = classify(m(shoulder_w=100, hip_w=100, waist_w=94))
    assert p.fruit == "rectangle"


def test_apple_when_waist_widest_high_bmi():
    p = classify(m(shoulder_w=96, hip_w=94, waist_w=100, bmi=29))
    assert p.fruit == "apple"


def test_japanese_weights_sum_to_one_and_summary_present():
    p = classify(m())
    assert abs(sum(p.japanese_weights.values()) - 1.0) < 1e-6
    assert p.japanese in {"straight", "wave", "natural"}
    assert p.summary


def test_marked_waist_outranks_a_moderate_shoulder_hip_imbalance():
    """A strongly defined waist is the dominant signal: shoulders ~10% wider
    than the hips used to file this as an inverted triangle, because the
    shoulder/hip gate ran before the waist was ever considered."""
    p = classify(m(shoulder_w=110, hip_w=100, waist_w=67))
    assert p.fruit == "hourglass"
    # ...and symmetrically for hips wider than shoulders.
    assert classify(m(shoulder_w=90, hip_w=100, waist_w=67)).fruit == "hourglass"


def test_marked_waist_does_not_override_a_large_shoulder_hip_imbalance():
    """Past ~15% the imbalance is the shape, however defined the waist."""
    assert classify(m(shoulder_w=125, hip_w=100, waist_w=65)).fruit == "inverted-triangle"
    assert classify(m(shoulder_w=80, hip_w=100, waist_w=65)).fruit == "pear"


def test_a_merely_defined_waist_still_defers_to_the_shoulder_hip_gates():
    """0.71-0.80 is a defined waist but not a marked one, so it decides
    hourglass-vs-rectangle only once shoulders and hips are balanced."""
    assert classify(m(shoulder_w=110, hip_w=100, waist_w=78)).fruit == "inverted-triangle"
    assert classify(m(shoulder_w=100, hip_w=100, waist_w=78)).fruit == "hourglass"

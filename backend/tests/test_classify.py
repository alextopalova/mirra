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

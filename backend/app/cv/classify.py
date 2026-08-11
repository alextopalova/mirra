from app.schemas import BodyMeasurements, BodyProfile

# Waist definition is graded, not binary:
#   <= 0.80  a defined waist -- enough to separate hourglass from rectangle
#            once shoulders and hips are already known to be balanced.
#   <= 0.70  a *markedly* defined waist. Standard body-shape rulesets treat
#            a waist this much narrower than the hips as the dominant
#            signal, outranking a moderate shoulder-hip imbalance -- so it
#            is checked before the shoulder/hip gates rather than after
#            them, which is where a strongly-waisted body used to be filed
#            as an inverted triangle purely because the shoulders measured
#            ~10% wider.
# A rule that overrides another rule has to clear a higher bar than the one
# it overrides; that is why this threshold is stricter than 0.80 rather
# than equal to it.
_DEFINED_WAIST_RATIO = 0.80
_MARKED_WAIST_RATIO = 0.70
# ...and only while the imbalance really is moderate. Past +/-15% the
# shoulder-hip difference is the shape, however defined the waist is.
_BALANCED_SHOULDER_HIP = (0.85, 1.15)


def _fruit(m: BodyMeasurements) -> str:
    shoulder, waist, hip, bust = m.shoulder_w, m.waist_w, m.hip_w, m.bust_w
    whr = waist / hip if hip else 1.0
    sh_hip = shoulder / hip if hip else 1.0
    defined_waist = whr <= _DEFINED_WAIST_RATIO

    # Apple: midsection is the widest point (often with higher BMI). Stays
    # first -- a waist that IS the widest point can't also be a marked one.
    if waist >= hip and waist >= bust and m.bmi >= 26:
        return "apple"

    # A markedly defined waist on a moderately balanced frame is an
    # hourglass regardless of which of shoulders/hips is the wider.
    if whr <= _MARKED_WAIST_RATIO and (
        _BALANCED_SHOULDER_HIP[0] <= sh_hip <= _BALANCED_SHOULDER_HIP[1]
    ):
        return "hourglass"

    if sh_hip >= 1.07:
        return "inverted-triangle"
    if sh_hip <= 0.93:
        return "pear"
    # shoulders ≈ hips → hourglass vs rectangle depends on waist definition
    return "hourglass" if defined_waist else "rectangle"


def _japanese_weights(m: BodyMeasurements) -> dict[str, float]:
    """Heuristic scores for the 骨格診断 (Straight / Wave / Natural) types.

    Each signal nudges one or two of the three scores; the result is
    normalized so the scores sum to 1.0. Signals used, and the direction
    each pushes:

    - Center of gravity (torso_len vs leg_len): a torso that is long
      relative to the legs reads as upper-body-heavy, a classic Straight
      trait. Relatively longer legs read as lower-body-heavy, a Wave trait.
    - Waist-to-hip ratio: a straighter torso line (high waist/hip ratio,
      little taper) is typical of Straight; a more defined, curved waist
      (low ratio) is typical of Wave.
    - BMI: Straight types tend to read as firmer/denser; Wave types
      softer/leaner. This is a coarse proxy, not a judgment on body size.
    - Shoulder-to-hip ratio: broad shoulders relative to hips, and long
      limbs relative to the torso, read as an angular, bony Natural frame.
    - torso_depth (front-to-back thickness, only when has_side is true):
      a thicker torso supports Straight (three-dimensional build); a
      flatter torso supports Wave.
    """
    torso_leg_ratio = m.torso_len / m.leg_len if m.leg_len else 1.0
    whr = m.waist_w / m.hip_w if m.hip_w else 1.0
    sh_hip = m.shoulder_w / m.hip_w if m.hip_w else 1.0
    depth = m.torso_depth if (m.has_side and m.torso_depth is not None) else None

    # Small equal baseline so no score can hit zero (keeps normalization stable).
    straight = 1.0
    wave = 1.0
    natural = 1.0

    # Center of gravity.
    if torso_leg_ratio >= 0.68:
        straight += 1.0
    else:
        wave += 1.0

    # Waist definition.
    if whr >= 0.78:
        straight += 0.8
    else:
        wave += 0.8

    # Build firmness.
    if m.bmi >= 23:
        straight += 0.6
    else:
        wave += 0.6

    # Frame breadth (shoulders vs hips) and limb length (legs vs torso).
    if sh_hip >= 1.02:
        natural += 1.2
    if m.leg_len >= m.torso_len * 1.4:
        natural += 0.8

    # Torso depth, only available with a side-view capture.
    if depth is not None:
        if depth >= 0.45:
            straight += 1.0
        else:
            wave += 1.0

    scores = {"straight": straight, "wave": wave, "natural": natural}
    total = sum(scores.values())
    # No rounding here: dividing by the exact total keeps the values summing
    # to 1.0 to within floating-point epsilon, which the tests rely on.
    return {k: v / total for k, v in scores.items()}


_LEAN = {"straight": "Straight", "wave": "Wave", "natural": "Natural"}


def classify(m: BodyMeasurements) -> BodyProfile:
    fruit = _fruit(m)
    weights = _japanese_weights(m)
    japanese = max(weights, key=weights.get)
    confidence = round(weights[japanese], 3)
    summary = f"{fruit.replace('-', ' ').title()} · {_LEAN[japanese]}-leaning"
    return BodyProfile(
        fruit=fruit,
        japanese=japanese,
        japanese_weights=weights,
        confidence=confidence,
        summary=summary,
    )

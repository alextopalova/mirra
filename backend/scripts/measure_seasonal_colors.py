"""Measure skin / eyebrow / iris / hair colour off labelled portraits, locally.

The companion to `calibrate_undertone.py`, which measures the same thing by
calling YouCam (~16 credits a photo). This one spends nothing: it reads the
pixels directly, which is what makes it usable on a folder of reference
faces whose seasons are already known.

    python3 scripts/measure_seasonal_colors.py                  # ../seasonal_colors
    python3 scripts/measure_seasonal_colors.py path/to/photos
    python3 scripts/measure_seasonal_colors.py --write          # refresh the test fixture

The season label comes from the filename -- `summer_2.png` -> Summer -- so a
folder is labelled just by naming its files. Output is one row per photo
plus, for each axis the season rule uses, how cleanly the labelled groups
separate on it and where the boundary between them sits.

WHY THESE FOUR REGIONS: they are exactly the fields YouCam's
skin-tone-analysis returns (`skin_color`, `eyebrow_color`, `eye_color`,
`hair_color`), so a threshold fitted here is comparable with the number
`color.py` compares against at runtime. Two caveats worth keeping in mind:

- These are raw pixel medians. YouCam's `skin_color` is white-balance
  normalised and its `hair_color` is categorical (one canonical hex per
  colour name), so the two scales are close but not identical. The axes
  `color.py` uses are differences (skin a* + eyebrow a*, skin L* - dark
  feature L*), which survive a shared cast far better than absolute hue --
  that is the point of picking them.
- The one live YouCam eyebrow sample we have (#59312e, a* 18) is redder
  than any measured here (max a* 15). One sample is not an offset, but it
  is a reason to re-check `_WARM_REDNESS` against live results when there
  are enough of them.

Regions are found with MediaPipe FaceLandmarker (468+iris landmarks) and
the selfie multiclass segmenter, downloaded on first run into `models/`.
Both are calibration-only -- the app itself never loads them.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import mediapipe as mp  # noqa: E402
from mediapipe.tasks import python as mp_python  # noqa: E402
from mediapipe.tasks.python import vision  # noqa: E402

from app.youcam.color import _lab_from_hex, _season_from_colors  # noqa: E402

MODELS = BACKEND / "models"
DEFAULT_PHOTOS = BACKEND.parent / "seasonal_colors"
FIXTURE = BACKEND / "tests" / "data" / "seasonal_colors.json"

_DOWNLOADS = {
    "face_landmarker.task":
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task",
    "selfie_multiclass.tflite":
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite",
}

# selfie_multiclass_256x256 category ids.
SEG_HAIR, SEG_FACE_SKIN = 1, 3

# FaceLandmarker indices.
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397,
             365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58,
             132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
# Cheeks, forehead and jaw: skin on every face, clear of brows, eyes, lips,
# nostrils and the specular ridge down the nose.
SKIN_PATCHES = [50, 101, 118, 117, 205, 280, 330, 347, 346, 425,
                108, 151, 337, 9, 172, 397, 135, 364]
IRISES = ([468, 469, 470, 471, 472], [473, 474, 475, 476, 477])
BROWS = ([70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
         [300, 293, 334, 296, 336, 285, 295, 282, 283, 276])

SEASONS = ("Autumn", "Spring", "Summer", "Winter")
WARM_SEASONS = {"Autumn", "Spring"}
DEEP_SEASONS = {"Autumn", "Winter"}


def ensure_models() -> None:
    MODELS.mkdir(exist_ok=True)
    for name, url in _DOWNLOADS.items():
        dest = MODELS / name
        if dest.exists():
            continue
        print(f"downloading {name} (calibration only) ...", file=sys.stderr)
        urllib.request.urlretrieve(url, dest)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _median_hex(pixels: np.ndarray) -> str:
    b, g, r = (int(v) for v in np.median(pixels.reshape(-1, 3), axis=0))
    return f"#{r:02x}{g:02x}{b:02x}"


def _keep_midtones(pixels: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Drop the darkest and lightest pixels of a region before averaging.

    Every region here is lit unevenly: a catchlight on the hair or a
    specular highlight on the cheek is brighter than anything the region is
    actually made of, and the shadow under it is darker. Both pull a plain
    median, so the reported colour is the middle band's median instead.
    """
    if len(pixels) < 40:
        return pixels
    lab = cv2.cvtColor(pixels.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2LAB)
    light = lab.reshape(-1, 3)[:, 0].astype(np.float64)
    low, high = np.percentile(light, [lo, hi])
    keep = (light >= low) & (light <= high)
    return pixels[keep] if keep.sum() >= 40 else pixels


def _filled(shape: tuple, points: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(points.astype(np.int32)), 255)
    return mask.astype(bool)


def _make_landmarker() -> vision.FaceLandmarker:
    return vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=str(MODELS / "face_landmarker.task")),
        num_faces=1,
    ))


def _make_segmenter() -> vision.ImageSegmenter:
    return vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=str(MODELS / "selfie_multiclass.tflite")),
        output_category_mask=True,
    ))


def measure(path: Path, landmarker: vision.FaceLandmarker,
            segmenter: vision.ImageSegmenter) -> dict | None:
    """Skin / eyebrow / eye / hair hexes for one portrait.

    Both MediaPipe sessions are passed in and reused across photos on
    purpose: creating and tearing one down per image made the segmenter
    return an empty mask on roughly half the calls, so `hair_color` came
    back None at random. Reused, every measurement here is reproducible.
    """
    bgr = cv2.imread(str(path))
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    image = mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    detected = landmarker.detect(image)
    if not detected.face_landmarks:
        return None
    landmarks = np.array([[p.x * w, p.y * h] for p in detected.face_landmarks[0]])
    segments = np.squeeze(segmenter.segment(image).category_mask.numpy_view())

    # Skin: discs on the cheeks, forehead and jaw. Landmarks only, no
    # segmenter -- the segmenter's boundary shifts by a few pixels between
    # identical runs, which moved the measured skin hex by ~3 units of L*
    # and made the calibration irreproducible. The discs sit well inside the
    # face, so there is nothing for a person mask to add here.
    face_width = float(np.ptp(landmarks[FACE_OVAL, 0]))
    discs = np.zeros((h, w), np.uint8)
    for index in SKIN_PATCHES:
        cv2.circle(discs, (int(landmarks[index, 0]), int(landmarks[index, 1])),
                   max(2, int(face_width * 0.035)), 255, -1)
    skin = _keep_midtones(bgr[discs.astype(bool)], 25, 85)

    # Hair: the segmenter's hair class near the head only, eroded so the
    # halo where it straddles the background isn't read as hair colour.
    oval = landmarks[FACE_OVAL]
    x0, y0, x1, y1 = oval[:, 0].min(), oval[:, 1].min(), oval[:, 0].max(), oval[:, 1].max()
    fw, fh = x1 - x0, y1 - y0
    near_head = np.zeros((h, w), bool)
    near_head[int(max(0, y0 - fh * 0.6)):int(min(h, y0 + fh)),
              int(max(0, x0 - fw * 0.7)):int(min(w, x1 + fw * 0.7))] = True
    hair_mask = cv2.erode((near_head & (segments == SEG_HAIR)).astype(np.uint8),
                          np.ones((5, 5), np.uint8)).astype(bool)
    hair = _keep_midtones(bgr[hair_mask], 20, 80)

    # Iris: an annulus between pupil and limbus, so the pupil doesn't drag
    # every eye colour toward black.
    iris_mask = np.zeros((h, w), bool)
    for iris in IRISES:
        centre = landmarks[iris].mean(axis=0)
        radius = np.linalg.norm(landmarks[iris][1:] - centre, axis=1).max()
        ring = np.zeros((h, w), np.uint8)
        cv2.circle(ring, (int(centre[0]), int(centre[1])), int(max(2, radius * 0.90)), 255, -1)
        cv2.circle(ring, (int(centre[0]), int(centre[1])), int(max(1, radius * 0.50)), 0, -1)
        iris_mask |= ring > 0
    eye = _keep_midtones(bgr[iris_mask], 25, 75)

    brow_mask = np.zeros((h, w), bool)
    for brow in BROWS:
        brow_mask |= _filled(bgr.shape, landmarks[brow])
    # Skin shows between the hairs, so a brow's darkest pixels are the ones
    # that are actually brow.
    eyebrow = _keep_midtones(bgr[brow_mask], 5, 45)

    row = {"file": path.name, "season": path.stem.split("_")[0].title()}
    for pixels, name in ((skin, "skin"), (eyebrow, "eyebrow"), (eye, "eye"), (hair, "hair")):
        row[f"{name}_color"] = _median_hex(pixels) if len(pixels) >= 20 else None
    return row


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _axes(row: dict) -> dict:
    """The two numbers `_season_from_colors` actually thresholds."""
    skin = _lab_from_hex(row["skin_color"])
    brow = _lab_from_hex(row["eyebrow_color"])
    eye = _lab_from_hex(row["eye_color"])
    dark = [f[0] for f in (brow, eye) if f is not None]
    return {
        "redness": skin[1] + brow[1] if brow else float("nan"),
        "contrast": skin[0] - sum(dark) / len(dark) if dark else float("nan"),
    }


def _separation(rows: list[dict], axis: str, positive: set[str]) -> str:
    """How cleanly the labelled groups split on one axis."""
    hi = sorted(_axes(r)[axis] for r in rows if r["season"] in positive)
    lo = sorted(_axes(r)[axis] for r in rows if r["season"] not in positive)
    if not hi or not lo:
        return "no data"
    if min(hi) > max(lo):
        return (f"clean: <= {max(lo):.1f} vs >= {min(hi):.1f} "
                f"(gap {min(hi) - max(lo):.1f}, boundary {(max(lo) + min(hi)) / 2:.1f})")
    return f"OVERLAP: {min(hi):.1f}..{max(hi):.1f} vs {min(lo):.1f}..{max(lo):.1f}"


def report(rows: list[dict]) -> int:
    header = ("season", "file", "skin", "eyebrow", "eye", "hair",
              "redness", "contrast", "predicted")
    print(" ".join(f"{h:>12}" for h in header))
    correct = 0
    for row in rows:
        axes = _axes(row)
        predicted = _season_from_colors(row["skin_color"], row["hair_color"],
                                        row["eyebrow_color"], row["eye_color"])
        correct += predicted == row["season"]
        print(" ".join(f"{v:>12}" for v in (
            row["season"], row["file"], str(row["skin_color"]), str(row["eyebrow_color"]),
            str(row["eye_color"]), str(row["hair_color"]),
            f"{axes['redness']:.1f}", f"{axes['contrast']:.1f}",
            f"{predicted}{'' if predicted == row['season'] else '  <-- MISS'}")))

    print(f"\n{correct}/{len(rows)} photos land on their labelled season")
    print(f"  warm vs cool, on skin a* + eyebrow a*      {_separation(rows, 'redness', WARM_SEASONS)}")
    print(f"  deep vs light, on skin L* - dark L*        {_separation(rows, 'contrast', DEEP_SEASONS)}")
    print("\nA clean split means the boundary above is the midpoint of the widest gap;"
          "\nwith this few photos treat it as calibrated, not settled.")
    return correct


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("photos", nargs="?", type=Path, default=DEFAULT_PHOTOS,
                        help=f"folder of labelled portraits (default: {DEFAULT_PHOTOS})")
    parser.add_argument("--write", action="store_true",
                        help=f"also write the measurements to {FIXTURE.relative_to(BACKEND)}")
    args = parser.parse_args()

    if not args.photos.is_dir():
        parser.error(f"{args.photos} is not a directory")
    paths = sorted(p for p in args.photos.iterdir()
                   if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    unlabelled = [p.name for p in paths if p.stem.split("_")[0].title() not in SEASONS]
    if unlabelled:
        parser.error("filenames must start with a season name "
                     f"({', '.join(SEASONS)}); these do not: {', '.join(unlabelled)}")

    ensure_models()
    rows = []
    with _make_landmarker() as landmarker, _make_segmenter() as segmenter:
        for path in paths:
            row = measure(path, landmarker, segmenter)
            if row is None:
                print(f"{path.name}: no face found, skipped", file=sys.stderr)
                continue
            rows.append(row)
    rows.sort(key=lambda r: (r["season"], r["file"]))

    report(rows)
    if args.write:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(rows, indent=2) + "\n")
        print(f"\nwrote {len(rows)} measurements to {FIXTURE}")


if __name__ == "__main__":
    main()

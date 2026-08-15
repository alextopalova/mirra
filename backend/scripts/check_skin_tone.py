"""Run the colour-analysis leg on one photo, in isolation.

Reaching /analyze-body through the kiosk means a full scan, and every
attempt spends YouCam credits. This runs exactly the same crop -> upscale
-> upload -> poll path against a single image so a change can be tested for
one call instead of a whole flow.

    # free: writes the exact JPEG that would be uploaded, calls nothing
    python3 scripts/check_skin_tone.py ../example_picture_3.png --dry-run

    # SPENDS ONE YOUCAM CALL
    python3 scripts/check_skin_tone.py ../example_picture_3.png

`analyze_color` never raises, so a failure shows up as a warning on stderr
naming the YouCam error code, followed by a palette estimated from the
crop's own pixels (or the fixed default when there aren't enough face
pixels to average). Read the log lines, not just the season:

    "skin-tone-analysis returned skin ... -> season ..."   a real API read
    "retrying once with a mirror-symmetrised crop"          pose rejection, retried
    "Estimated skin ... locally"                            API unavailable
    "falling back to the default palette"                   nothing readable at all

The dry-run's saved crop is the thing to look at first on a failure: if the
face is small, cut off, or turned away, the API's complaint is about the
image rather than about the request.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cv.measure import extract_landmarks  # noqa: E402
from app.youcam.color import (  # noqa: E402
    _UPLOAD_JPEG_QUALITY,
    _crop_face,
    _symmetrise_face,
    _upscale_for_upload,
    analyze_color,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", help="path to a full-body front photo")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="save the crop that would be uploaded and exit without calling YouCam",
    )
    ap.add_argument("--out", default="face_upload.jpg", help="where --dry-run writes the crop")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    bgr = cv2.imread(args.image)
    if bgr is None:
        sys.exit(f"could not read image: {args.image}")
    print(f"source           {bgr.shape[1]}x{bgr.shape[0]}")

    landmarks = extract_landmarks(bgr)
    # Exactly what analyze_color uploads: eye-levelled, size-guarded, upscaled.
    try:
        crop = _crop_face(bgr, landmarks=landmarks)
    except ValueError as e:
        sys.exit(f"no usable face region: {e}")
    upscaled = _upscale_for_upload(crop)
    ok, buf = cv2.imencode(".jpg", upscaled, [int(cv2.IMWRITE_JPEG_QUALITY), _UPLOAD_JPEG_QUALITY])
    print(f"face crop        {crop.shape[1]}x{crop.shape[0]}")
    print(f"uploaded as      {upscaled.shape[1]}x{upscaled.shape[0]}  "
          f"({len(buf.tobytes()) / 1024:.0f} kB)" if ok else "encode FAILED")

    if args.dry_run:
        cv2.imwrite(args.out, upscaled)
        retry_path = args.out.replace(".jpg", "_symmetrised.jpg")
        cv2.imwrite(retry_path, _symmetrise_face(upscaled))
        print(f"\nwrote {args.out} — no API call made. Open it: is the face large,")
        print("fully in frame, and looking straight at the camera?")
        print(f"wrote {retry_path} — the mirrored crop sent if YouCam rejects the pose.")
        return

    print("\ncalling YouCam skin-tone-analysis (spends one call)...")
    result = asyncio.run(analyze_color(bgr, landmarks=landmarks))
    print(f"\nseason  {result['season']}")
    print(f"colors  {' '.join(result['colors'])}")
    print("\nCheck the log lines above to see where that season came from — a real")
    print("API read, a symmetrised retry, a local estimate, or the fixed default.")


if __name__ == "__main__":
    main()

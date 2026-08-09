"""POST /analyze-body: photos + height/weight -> body profile + palette.

The palette comes from the real YouCam Facial Color Tones integration
(`app.youcam.color.analyze_color`) in real mode, and a fixed placeholder in
mock mode (`settings.use_mocks`, see app/config.py) -- mock mode never
touches the network, to protect the YouCam credit budget during
development (see app/youcam/CONTRACT.md).

`analyze_color` is designed to never raise -- every colour-analysis
failure mode (no face to crop, a YouCam task/timeout/auth error, an
unrecognised result payload) is caught internally and degrades to a
default palette. The `try/except Exception` around its call below is a
deliberate extra safety net on top of that, not the primary mechanism: a
failed colour read must never turn the shopper's otherwise-successful
body scan into a 500.

Error mapping (why 422, not 500): `measure_from_images` raises `ValueError`
for problems the *shopper* can fix by retaking a photo (no person detected,
body cropped out of frame, an anatomically implausible measurement). A bare
500 here would leave the kiosk showing a generic error with no guidance, so
those are caught and turned into a 422 with a shopper-facing `detail`
message. The same treatment applies to a `frontPhoto` payload that isn't
decodable at all (corrupt bytes, not an image, malformed base64) -- that's
also a retake-able problem, not a server bug.

`sidePhoto` is different: it's optional by product spec (the kiosk capture
screen has a "Skip side" button, and `measure_from_images` accepts
`side_bgr=None` and just skips the torso-depth refinement). Failing an
entire scan because the *optional* side photo was corrupt would block a
shopper from a scan that could otherwise succeed, so an undecodable
`sidePhoto` degrades gracefully: it's treated as absent (logged, not
raised) and the analysis proceeds front-only.
"""

import base64
import binascii
import logging
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.cv.classify import classify
from app.cv.measure import extract_landmarks, measure_from_images
from app.youcam.color import analyze_color

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalyzeIn(BaseModel):
    frontPhoto: str
    sidePhoto: Optional[str] = None
    heightCm: float
    weightKg: float


# Palette used in mock mode, and as the final fallback if real-mode colour
# analysis fails for any reason (see analyze_body below).
_PLACEHOLDER_PALETTE = {
    "season": "Autumn",
    "colors": ["#8C5A3C", "#C08457", "#6B7F5B", "#B0463C", "#D9A05B"],
}


def _decode(dataurl: str, field: str):
    """Decode a photo field into a BGR (OpenCV-convention) image array.

    Accepts either a full `data:image/...;base64,XXX` dataURL or a bare
    base64 string, and tolerates surrounding/embedded whitespace (e.g. a
    line-wrapped base64 blob) -- the frontend contract only promises a
    dataURL, but a bare base64 string is easy to support and costs nothing.

    Raises HTTPException(422) -- never lets a bad payload reach cv2 as a
    `None` array or crash on invalid base64 -- for two distinct, recoverable
    problems: malformed base64 (`binascii.Error`), and base64 that decodes
    fine but isn't a readable image (`cv2.imdecode` returns `None`).
    """
    raw = dataurl.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    b64 = "".join(raw.split())  # strip embedded whitespace/newlines

    try:
        decoded = base64.b64decode(b64, validate=True)
    except binascii.Error:
        raise HTTPException(
            status_code=422,
            detail=f"{field} isn't valid image data. Please retake the photo.",
        )

    buf = np.frombuffer(decoded, np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(
            status_code=422,
            detail=f"{field} couldn't be read as an image. Please retake the photo.",
        )
    return img


@router.post("/analyze-body")
async def analyze_body(inp: AnalyzeIn):
    front = _decode(inp.frontPhoto, "frontPhoto")

    side = None
    if inp.sidePhoto:
        try:
            side = _decode(inp.sidePhoto, "sidePhoto")
        except HTTPException:
            # sidePhoto is optional -- an unusable one degrades to "not
            # provided" rather than failing the whole scan. See module
            # docstring for why.
            logger.warning(
                "sidePhoto was unusable (undecodable or malformed base64); "
                "ignoring it and proceeding with front-only analysis."
            )
            side = None

    try:
        m = measure_from_images(front, side, inp.heightCm, inp.weightKg)
    except ValueError as e:
        # Recoverable, shopper-facing problem (no person / cropped / bad
        # measurement) -- 422 with guidance, not a 500 stack trace.
        raise HTTPException(status_code=422, detail=str(e))

    profile = classify(m)

    if settings.use_mocks:
        palette = _PLACEHOLDER_PALETTE
    else:
        # `measure_from_images` above already ran PoseLandmarker on `front`
        # once (internally, via app.cv.measure -- not something we can
        # intercept without changing that module). Re-extracting landmarks
        # here and handing them to `analyze_color` at least spares *it*
        # from running PoseLandmarker a second time itself (it used to,
        # via analyze_color -> _crop_face -> extract_landmarks). Since
        # `measure_from_images` just succeeded on this same image, this
        # extraction is expected to succeed too; the try/except is a pure
        # safety net -- on the (unexpected) chance it doesn't, fall back to
        # landmarks=None so analyze_color extracts them itself, exactly as
        # it always has.
        try:
            front_landmarks = extract_landmarks(front)
        except ValueError:
            front_landmarks = None

        try:
            palette = await analyze_color(front, landmarks=front_landmarks)
        except Exception:
            # Belt-and-suspenders: analyze_color already catches its own
            # failure modes (see its docstring), but a colour-analysis bug
            # must still never break an otherwise-successful body scan.
            logger.warning("Unexpected error during colour analysis; using placeholder palette.", exc_info=True)
            palette = _PLACEHOLDER_PALETTE

    return {"profile": profile.model_dump(), "palette": palette}

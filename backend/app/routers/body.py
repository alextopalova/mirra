"""POST /analyze-body: photos + height/weight -> body profile + palette.

The palette is a PLACEHOLDER until the real YouCam Facial Color Tones
integration lands in Phase 4.

Error mapping (why 422, not 500): `measure_from_images` raises `ValueError`
for problems the *shopper* can fix by retaking a photo (no person detected,
body cropped out of frame, an anatomically implausible measurement). A bare
500 here would leave the kiosk showing a generic error with no guidance, so
those are caught and turned into a 422 with a shopper-facing `detail`
message. The same treatment applies to a photo payload that isn't decodable
at all (corrupt bytes, not an image, malformed base64) -- those are also
retake-able problems, not server bugs.
"""

import base64
import binascii
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cv.classify import classify
from app.cv.measure import measure_from_images

router = APIRouter()


class AnalyzeIn(BaseModel):
    frontPhoto: str
    sidePhoto: Optional[str] = None
    heightCm: float
    weightKg: float


# Placeholder palette until YouCam Facial Color Tones is wired (Phase 4).
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
def analyze_body(inp: AnalyzeIn):
    front = _decode(inp.frontPhoto, "frontPhoto")
    side = _decode(inp.sidePhoto, "sidePhoto") if inp.sidePhoto else None

    try:
        m = measure_from_images(front, side, inp.heightCm, inp.weightKg)
    except ValueError as e:
        # Recoverable, shopper-facing problem (no person / cropped / bad
        # measurement) -- 422 with guidance, not a 500 stack trace.
        raise HTTPException(status_code=422, detail=str(e))

    profile = classify(m)
    return {"profile": profile.model_dump(), "palette": _PLACEHOLDER_PALETTE}

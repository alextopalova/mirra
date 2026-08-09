"""POST /try-on: shopper photo + chosen garment -> a photorealistic try-on image.

This is the product's centerpiece -- the shopper sees themselves wearing
the garment on the mirror.

Mock mode (`settings.use_mocks`) and an unknown `garmentId` both return a
placeholder image without touching the network, keeping local development
off the YouCam credit budget (see app/youcam/CONTRACT.md's 1000-unit
note). Unknown `garmentId` is deliberately NOT a 404: a stale or mistyped
id degrading to a placeholder keeps the kiosk flow moving instead of
dumping a hard error on a shopper for what's ultimately a data problem,
not something they did wrong.

Error mapping: a YouCam task failure or timeout is a recoverable,
shopper-facing situation (try again / try a different item), not a
server bug -- both map to 503 with a plain-language `detail`, never a raw
500. The `detail` is always a fixed, hand-written string; the underlying
exception (which could reference request internals) is only logged
server-side, never echoed to the client, so nothing about the API key or
YouCam's raw error text can leak into the response. Malformed
`personPhoto` data maps to 422, matching the convention set by
app/routers/body.py's `_decode`.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.imaging import DataUrlError, decode_dataurl
from app.reco.catalog import load_catalog
from app.youcam.client import YouCamError, YouCamTaskError, YouCamTimeoutError
from app.youcam.vto import garment_category_for, try_on as run_try_on

logger = logging.getLogger(__name__)

router = APIRouter()

PLACEHOLDER_IMAGE = "https://picsum.photos/seed/tryon/600/840"


class TryOnIn(BaseModel):
    personPhoto: str
    garmentId: str


@router.post("/try-on")
async def try_on_route(inp: TryOnIn):
    garment = next((g for g in load_catalog() if g.id == inp.garmentId), None)

    if settings.use_mocks or garment is None:
        return {"image": PLACEHOLDER_IMAGE}

    try:
        person_bytes = decode_dataurl(inp.personPhoto)
    except DataUrlError:
        raise HTTPException(
            status_code=422,
            detail="personPhoto isn't valid image data. Please retake the photo.",
        )

    try:
        return await run_try_on(
            person_bytes, garment.image_url, garment_category_for(garment.category)
        )
    except (YouCamTaskError, YouCamTimeoutError):
        logger.exception("YouCam try-on task failed for garment %s", inp.garmentId)
        raise HTTPException(
            status_code=503,
            detail="The virtual try-on couldn't be generated — please try another item.",
        )
    except YouCamError:
        logger.exception("YouCam try-on failed unexpectedly for garment %s", inp.garmentId)
        raise HTTPException(
            status_code=503,
            detail="The virtual try-on is temporarily unavailable — please try again.",
        )

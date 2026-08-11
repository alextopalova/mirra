"""POST /recommend: shopper diagnosis -> ranked rack of store garments.

Takes the shopper's body profile, flattering palette, requested garment
category, and occasion, and returns the catalog's matches for that
category, best match first.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.reco.catalog import hex_to_lab, load_catalog
from app.reco.engine import rank
from app.schemas import BodyProfile

router = APIRouter()


class Palette(BaseModel):
    season: str
    colors: list[str]


class RecommendIn(BaseModel):
    profile: BodyProfile
    palette: Palette
    category: str
    occasion: str


@router.post("/recommend")
def recommend(inp: RecommendIn):
    palette_labs = [hex_to_lab(c) for c in inp.palette.colors]
    catalog = load_catalog()
    recs = rank(
        inp.profile, palette_labs, inp.category, inp.occasion, catalog,
        season=inp.palette.season,
    )
    return [
        {
            "garment": r["garment"].model_dump(),
            "score": r["score"],
            "reasons": r["reasons"],
            # False marks a garment shown to fill a thin rack: it's in the
            # right category but misses the season or occasion filter. The
            # kiosk labels these rather than passing them off as matches.
            "exact": r["exact"],
        }
        for r in recs
    ]

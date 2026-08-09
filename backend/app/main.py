from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.routers import body, recommend, youcam

app = FastAPI(title="Mirra API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(body.router)
app.include_router(recommend.router)
app.include_router(youcam.router)

# Garment images are committed to backend/data/garments/<id>.jpg and the
# catalog's `image_url` points at the relative path "/garments/<id>.jpg" --
# self-hosted instead of hot-linked. Mount that directory so the frontend
# can actually load them; the "/garments" prefix doesn't collide with any
# existing route above. mkdir(exist_ok=True) so app startup never fails
# just because no garment images have landed yet (StaticFiles requires the
# directory to exist at mount time).
_GARMENTS_DIR = Path(__file__).resolve().parents[1] / "data" / "garments"
_GARMENTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/garments", StaticFiles(directory=_GARMENTS_DIR), name="garments")

@app.get("/health")
def health():
    return {"status": "ok"}

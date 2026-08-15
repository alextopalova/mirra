#!/usr/bin/env python3
"""Rebuild backend/data/catalog.json and backend/data/garments/*.jpg.

Source
------
Product photography comes from the Hugging Face dataset
`yainage90/onthelook-fashion-anchor-positive-images` (MIT licence), a
retrieval-training set built from **OnTheLook** (온더룩), a Korean fashion
shopping/snap app. Each row pairs a street-snap crop (`anchor_image`) with
the matching retail product shot (`positive_image`) and carries a coarse
category label. We only ever use `positive_image` -- the clean, mostly
white-background product shot, which is what the try-on endpoint needs to
send YouCam as the garment reference. Provenance and licence are recorded
in `backend/data/garments/SOURCE.md`.

Why the rows are hard-coded
---------------------------
The 40 garments below were **hand-picked by eye** from contact sheets of
several hundred candidates, for three things a filter can't judge:

1. womenswear (the kiosk styles women; the dataset skews men's streetwear),
2. a usable photo -- one garment, shot flat or on a model, not a colourway
   collage, a rack of hangers, or a busy outdoor scene, and
3. a colour spread wide enough that all four personal-colour seasons and
   all three categories stay populated after tagging.

So this script does not re-run the selection; it re-downloads exactly the
rows that were chosen, by their absolute dataset row index (stable for a
given dataset revision), via the public datasets-server `/rows` endpoint.
Everything else in each entry -- name, silhouette, price, sizes, aisle --
is hand-authored here from looking at the photo, because the dataset ships
no product text at all.

`color_hex` is NOT hand-written: it is sampled from the downloaded pixels
(`dominant_color`, plus a per-item crop window where the default window
lands on background or on the model instead of the garment), and
`color_lab` is derived from it with the app's own `hex_to_lab` so the two
can never drift. `season_tags`/`occasion_tags` are placeholders here and
are re-derived by `scripts/retag_catalog.py`, which this script runs at the
end.

Run from `backend/` with the venv active:

    python scripts/build_catalog.py            # download + rebuild
    python scripts/build_catalog.py --no-fetch # re-derive metadata only

Network access required for the download; nothing here runs at test time.
"""

from __future__ import annotations

import argparse
import io
import json
import ssl
import subprocess
import sys
import time
from pathlib import Path

import certifi
import httpx
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.reco.catalog import hex_to_lab  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
GARMENTS_DIR = BACKEND_DIR / "data" / "garments"
CATALOG_PATH = BACKEND_DIR / "data" / "catalog.json"

DATASET = "yainage90/onthelook-fashion-anchor-positive-images"
ROWS_URL = "https://datasets-server.huggingface.co/rows"
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
TARGET_LONG_SIDE = 1024

# Default sampling window per category, as (x0, y0, x1, y1) fractions of the
# image: the part of a product shot that is reliably the garment itself.
DEFAULT_BOX = {
    "dress": (0.28, 0.25, 0.72, 0.75),
    "top": (0.20, 0.20, 0.80, 0.62),
    "pants": (0.25, 0.32, 0.75, 0.90),
}

# --------------------------------------------------------------------------
# The catalog. `row` is the absolute row index in the dataset's train split.
# `box` overrides DEFAULT_BOX where the default window misses the garment
# (garment shot on a diagonal, worn by a model, tiny against a wide frame).
# `crop` trims the stored image itself, for the one shot that carries a strip
# of other colourways below the garment.
# --------------------------------------------------------------------------

ITEMS: list[dict] = [
    # ---- dresses -------------------------------------------------------
    # d1/d2 lead the dress rack deliberately: tests/test_engine.py reads
    # `dresses[0]` as a garment that is Autumn-tagged *and* survives the
    # "date night" filter, and pins "d2" as a dress that is not Autumn.
    dict(id="d1", row=31700, category="dress", name="Ribbed Knit Mini Tank Dress",
         price=39, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=False, fabric="smooth", neckline="round", waist="regular")),
    dict(id="d2", row=39016, category="dress", name="Sleeveless Knit A-Line Midi Dress",
         price=59, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="d3", row=6088, category="dress", name="Bubble Hem Mini Dress",
         price=52, sizes=["XS", "S", "M"],
         silhouette=dict(structured=True, fabric="crisp", neckline="round", waist="defined")),
    dict(id="d4", row=10354, category="dress", name="Ditsy Print Collared Midi Dress",
         price=58, sizes=["S", "M", "L"],
         box=(0.38, 0.35, 0.62, 0.72),
         silhouette=dict(structured=False, fabric="light", neckline="collared", waist="defined")),
    dict(id="d5", row=10362, category="dress", name="Tie-Strap Ruched Mini Dress",
         price=54, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=False, fabric="light", neckline="round", waist="defined")),
    dict(id="d6", row=10374, category="dress", name="Balloon Hem Midi Dress",
         price=68, sizes=["S", "M", "L"],
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="d7", row=27070, category="dress", name="Tiered Shirt Dress",
         price=72, sizes=["XS", "S", "M", "L", "XL"],
         box=(0.30, 0.55, 0.70, 0.80), skin=False,
         silhouette=dict(structured=True, fabric="crisp", neckline="collared", waist="defined")),
    dict(id="d8", row=38984, category="dress", name="Satin Slip Midi Dress",
         price=64, sizes=["XS", "S", "M", "L"],
         box=(0.35, 0.30, 0.62, 0.70),
         silhouette=dict(structured=False, fabric="draping", neckline="v", waist="regular")),
    dict(id="d9", row=48337, category="dress", name="Poplin Shirt Dress",
         price=66, sizes=["S", "M", "L"],
         box=(0.36, 0.30, 0.64, 0.62),
         silhouette=dict(structured=True, fabric="crisp", neckline="collared", waist="regular")),
    dict(id="d10", row=66321, category="dress", name="Belted Wrap Coat Dress",
         price=79, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=True, fabric="structured", neckline="v", waist="defined")),
    dict(id="d11", row=91096, category="dress", name="Draped Neck Column Midi Dress",
         price=55, sizes=["S", "M", "L"],
         box=(0.35, 0.35, 0.65, 0.70), skin=False,
         silhouette=dict(structured=False, fabric="smooth", neckline="round", waist="defined")),
    dict(id="d12", row=91104, category="dress", name="Floral Satin Slip Midi Dress",
         price=61, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=False, fabric="draping", neckline="v", waist="defined")),
    dict(id="d13", row=91120, category="dress", name="Puff Sleeve Tiered Midi Dress",
         price=57, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="light", neckline="round", waist="regular")),
    dict(id="d14", row=31701, category="dress", name="Sleeveless A-Line Mini Dress",
         price=47, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=True, fabric="crisp", neckline="round", waist="regular")),
    dict(id="d15", row=38977, category="dress", name="Puff Sleeve Ruffle Mini Dress",
         price=63, sizes=["S", "M", "L"],
         box=(0.35, 0.45, 0.65, 0.75), skin=False,
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="d16", row=48336, category="dress", name="Pleated Midi Dress",
         price=74, sizes=["XS", "S", "M", "L", "XL"],
         silhouette=dict(structured=True, fabric="crisp", neckline="round", waist="defined")),
    dict(id="d17", row=48340, category="dress", name="Striped Belted Shirt Dress",
         price=69, sizes=["S", "M", "L"],
         silhouette=dict(structured=True, fabric="crisp", neckline="collared", waist="defined")),
    dict(id="d18", row=66320, category="dress", name="Striped Ruffle Hem Mini Dress",
         price=43, sizes=["XS", "S", "M"],
         silhouette=dict(structured=False, fabric="textured", neckline="round", waist="regular")),
    dict(id="d19", row=91075, category="dress", name="Houndstooth Cami Midi Dress",
         price=56, sizes=["S", "M", "L"],
         silhouette=dict(structured=False, fabric="smooth", neckline="v", waist="regular")),
    dict(id="d20", row=91107, category="dress", name="Floral Cami Midi Dress",
         price=49, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=False, fabric="light", neckline="v", waist="defined")),
    dict(id="d21", row=31673, category="dress", name="Rib Knit Cami Midi Dress",
         price=45, sizes=["S", "M", "L"],
         box=(0.38, 0.35, 0.62, 0.72),
         silhouette=dict(structured=False, fabric="smooth", neckline="round", waist="regular")),
    # The first pick here (row 38993) was a yellow floral mini shot against a
    # floral-wallpaper backdrop: unusable both for colour sampling and as a
    # garment reference to hand the VTO. Swapped for a clean studio shot.
    dict(id="d22", row=27069, category="dress", name="Puff Sleeve A-Line Dress",
         price=51, sizes=["XS", "S", "M", "L"], skin=False,
         silhouette=dict(structured=True, fabric="crisp", neckline="round", waist="regular")),
    dict(id="d23", row=6091, category="dress", name="Draped Slip Midi Dress",
         price=65, sizes=["S", "M", "L"],
         box=(0.38, 0.30, 0.62, 0.70), skin=False,
         silhouette=dict(structured=False, fabric="draping", neckline="round", waist="regular")),

    # ---- tops ----------------------------------------------------------
    dict(id="t1", row=13, category="top", name="Cropped Graphic Sweatshirt",
         price=32, sizes=["XS", "S", "M", "L"],
         box=(0.32, 0.30, 0.68, 0.60),
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="t2", row=44, category="top", name="Cable Knit Cricket Jumper",
         price=45, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="chunky", neckline="v", waist="regular")),
    dict(id="t3", row=54, category="top", name="Brushed Wool Crewneck Jumper",
         price=42, sizes=["XS", "S", "M", "L"],
         crop=0.72,
         silhouette=dict(structured=False, fabric="chunky", neckline="round", waist="regular")),
    dict(id="t4", row=67, category="top", name="Mohair Stripe Knit Jumper",
         price=47, sizes=["S", "M", "L"],
         box=(0.32, 0.35, 0.68, 0.62), hex_bin=1,
         silhouette=dict(structured=False, fabric="chunky", neckline="round", waist="regular")),
    dict(id="t5", row=70, category="top", name="Pigment Dyed Hoodie",
         price=38, sizes=["XS", "S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="t6", row=112, category="top", name="Boxy Logo T-Shirt",
         price=19, sizes=["S", "M", "L"],
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="t7", row=120, category="top", name="Fine Knit Button Cardigan",
         price=41, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=False, fabric="soft", neckline="v", waist="regular")),
    dict(id="t8", row=125, category="top", name="Washed Graphic Hoodie",
         price=36, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="t9", row=1155, category="top", name="Ribbed Short Sleeve Knit Top",
         price=27, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=False, fabric="textured", neckline="round", waist="regular")),
    dict(id="t10", row=1165, category="top", name="Pinstripe Oversized Shirt",
         price=34, sizes=["S", "M", "L"],
         silhouette=dict(structured=True, fabric="crisp", neckline="collared", waist="regular")),
    dict(id="t11", row=1169, category="top", name="Short Sleeve Camp Shirt",
         price=29, sizes=["XS", "S", "M", "L", "XL"],
         silhouette=dict(structured=True, fabric="crisp", neckline="collared", waist="regular")),
    dict(id="t12", row=1186, category="top", name="Gingham Short Sleeve Shirt",
         price=31, sizes=["S", "M", "L"],
         box=(0.35, 0.35, 0.65, 0.62), skin=False,
         silhouette=dict(structured=True, fabric="crisp", neckline="collared", waist="regular")),
    dict(id="t13", row=1188, category="top", name="Lace Trim Rib Camisole",
         price=22, sizes=["XS", "S", "M"],
         silhouette=dict(structured=False, fabric="smooth", neckline="v", waist="regular")),
    dict(id="t14", row=1189, category="top", name="Poplin Short Sleeve Shirt",
         price=28, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=True, fabric="crisp", neckline="collared", waist="regular")),
    dict(id="t15", row=1336, category="top", name="Ribbed Tank Top",
         price=18, sizes=["XS", "S", "M"],
         silhouette=dict(structured=False, fabric="textured", neckline="round", waist="regular")),
    dict(id="t16", row=1232, category="top", name="Wool Blend Knit Cardigan",
         price=52, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="chunky", neckline="v", waist="regular")),
    dict(id="t17", row=6012, category="top", name="Striped Mohair Jumper",
         price=44, sizes=["XS", "S", "M", "L"],
         box=(0.34, 0.22, 0.66, 0.45), skin=False,
         silhouette=dict(structured=False, fabric="chunky", neckline="round", waist="regular")),
    dict(id="t18", row=6068, category="top", name="Breton Stripe Long Sleeve Tee",
         price=26, sizes=["S", "M", "L"],
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="t19", row=6076, category="top", name="Knit Polo Top",
         price=39, sizes=["XS", "S", "M", "L"],
         skin=False,
         silhouette=dict(structured=False, fabric="textured", neckline="collared", waist="regular")),
    dict(id="t20", row=10305, category="top", name="Fine Knit Roll Neck",
         price=33, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="smooth", neckline="round", waist="regular")),
    dict(id="t21", row=10329, category="top", name="Ribbed High Neck Sleeveless Top",
         price=24, sizes=["XS", "S", "M"],
         silhouette=dict(structured=False, fabric="textured", neckline="round", waist="regular")),
    dict(id="t22", row=38965, category="top", name="Ribbon Tie Baby Tee",
         price=21, sizes=["XS", "S", "M", "L"],
         skin=False,
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="t23", row=128, category="top", name="Oversized Graphic Sweatshirt",
         price=37, sizes=["S", "M", "L", "XL"],
         skin=False,
         silhouette=dict(structured=False, fabric="soft", neckline="round", waist="regular")),
    dict(id="t24", row=1312, category="top", name="Short Sleeve Knit Polo",
         price=35, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=False, fabric="textured", neckline="collared", waist="regular")),

    # ---- pants ---------------------------------------------------------
    dict(id="p1", row=882, category="pants", name="Tailored Wide Leg Trousers",
         price=58, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=True, fabric="crisp", neckline="n-a", waist="high")),
    dict(id="p2", row=884, category="pants", name="Pleated Corduroy Trousers",
         price=49, sizes=["S", "M", "L"],
         box=(0.30, 0.35, 0.70, 0.70), skin=False,
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="high")),
    dict(id="p3", row=887, category="pants", name="Balloon Leg Jeans",
         price=62, sizes=["XS", "S", "M", "L", "XL"],
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="regular")),
    dict(id="p4", row=889, category="pants", name="Cotton Twill Straight Trousers",
         price=46, sizes=["S", "M", "L"],
         silhouette=dict(structured=True, fabric="natural", neckline="n-a", waist="regular")),
    dict(id="p5", row=894, category="pants", name="Pleated Wide Chinos",
         price=52, sizes=["XS", "S", "M", "L"],
         box=(0.35, 0.40, 0.65, 0.75), skin=False,
         silhouette=dict(structured=True, fabric="smooth", neckline="n-a", waist="high")),
    dict(id="p6", row=899, category="pants", name="Rigid Denim Straight Jeans",
         price=67, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="regular")),
    dict(id="p7", row=928, category="pants", name="Pleated Wide Leg Trousers",
         price=54, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=True, fabric="smooth", neckline="n-a", waist="high")),
    dict(id="p8", row=934, category="pants", name="Wide Leg Ecru Jeans",
         price=59, sizes=["S", "M", "L"],
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="regular")),
    dict(id="p9", row=936, category="pants", name="Washed Baggy Jeans",
         price=63, sizes=["XS", "S", "M", "L", "XL"],
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="regular")),
    dict(id="p10", row=958, category="pants", name="Tartan Check Trousers",
         price=48, sizes=["S", "M", "L"],
         silhouette=dict(structured=True, fabric="crisp", neckline="n-a", waist="regular")),
    dict(id="p11", row=973, category="pants", name="Stonewash Wide Jeans",
         price=57, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="regular")),
    dict(id="p12", row=976, category="pants", name="Parachute Cargo Trousers",
         price=44, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="light", neckline="n-a", waist="regular")),
    dict(id="p13", row=984, category="pants", name="Drawstring Wide Trousers",
         price=51, sizes=["XS", "S", "M", "L"],
         box=(0.40, 0.50, 0.60, 0.80), skin=False,
         silhouette=dict(structured=False, fabric="draping", neckline="n-a", waist="high")),
    dict(id="p14", row=1080, category="pants", name="Parachute Trousers",
         price=45, sizes=["S", "M", "L"],
         silhouette=dict(structured=False, fabric="light", neckline="n-a", waist="regular")),
    dict(id="p15", row=1011, category="pants", name="Straight Leg Wool Trousers",
         price=56, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=True, fabric="smooth", neckline="n-a", waist="regular")),
    dict(id="p16", row=966, category="pants", name="Balloon Leg Cargo Trousers",
         price=50, sizes=["S", "M", "L", "XL"],
         skin=False,
         silhouette=dict(structured=False, fabric="natural", neckline="n-a", waist="regular")),
    dict(id="p17", row=926, category="pants", name="Wide Leg Utility Trousers",
         price=53, sizes=["XS", "S", "M", "L"],
         skin=False,
         silhouette=dict(structured=True, fabric="natural", neckline="n-a", waist="high")),
    dict(id="p18", row=1056, category="pants", name="Wide Leg Twill Trousers",
         price=55, sizes=["S", "M", "L"],
         skin=False,
         silhouette=dict(structured=True, fabric="crisp", neckline="n-a", waist="high")),
    dict(id="p19", row=933, category="pants", name="Corduroy Straight Trousers",
         price=61, sizes=["XS", "S", "M", "L", "XL"],
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="regular")),
    dict(id="p20", row=1023, category="pants", name="Camo Print Cargo Trousers",
         price=47, sizes=["S", "M", "L"],
         skin=False,
         silhouette=dict(structured=True, fabric="natural", neckline="n-a", waist="regular")),
    dict(id="p21", row=1071, category="pants", name="Distressed Wide Jeans",
         price=64, sizes=["XS", "S", "M", "L"],
         silhouette=dict(structured=True, fabric="textured", neckline="n-a", waist="regular")),
    dict(id="p22", row=987, category="pants", name="Cotton Jogger Trousers",
         price=42, sizes=["S", "M", "L", "XL"],
         silhouette=dict(structured=False, fabric="soft", neckline="n-a", waist="relaxed")),
    dict(id="p23", row=911, category="pants", name="Pleated Camel Trousers",
         price=57, sizes=["XS", "S", "M", "L"],
         box=(0.35, 0.40, 0.65, 0.80), skin=False,
         silhouette=dict(structured=True, fabric="smooth", neckline="n-a", waist="high")),
]

LOCATION = {
    "dress": "Women's · Aisle 3 · Dresses",
    "top": "Women's · Aisle 2 · Tops",
    "pants": "Women's · Aisle 5 · Trousers",
}


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

def _get_with_retry(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """GET with backoff. The datasets-server rate-limits (429) well inside a
    70-request run, and answers 5xx while it warms a cold dataset."""
    delay = 2.0
    for attempt in range(8):
        resp = client.get(url, **kwargs)
        if resp.status_code < 400:
            return resp
        if resp.status_code not in (429, 500, 502, 503, 504):
            resp.raise_for_status()
        time.sleep(delay)
        delay = min(delay * 2, 60)
    resp.raise_for_status()
    return resp


def fetch_row_image(client: httpx.Client, row: int) -> Image.Image:
    """Fetch one row's `positive_image` (the retail product shot)."""
    resp = _get_with_retry(
        client,
        ROWS_URL,
        params={"dataset": DATASET, "config": "default", "split": "train",
                "offset": row, "length": 1},
    )
    payload = resp.json()["rows"][0]["row"]
    if payload["category"] not in (1, 2, 6):  # bottom / dress / top
        raise RuntimeError(f"row {row} is no longer a garment row: {payload['category']}")
    img_resp = _get_with_retry(client, payload["positive_image"]["src"])
    return Image.open(io.BytesIO(img_resp.content)).convert("RGB")


def save_image(img: Image.Image, dest: Path, crop: float | None) -> None:
    if crop is not None:
        w, h = img.size
        img = img.crop((0, 0, w, int(h * crop)))
    w, h = img.size
    if max(w, h) > TARGET_LONG_SIDE:
        scale = TARGET_LONG_SIDE / max(w, h)
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    img.save(dest, "JPEG", quality=88, optimize=True)


# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

_BINS = 16


def _bin_index(pixels: np.ndarray) -> np.ndarray:
    idx = np.clip((pixels / (256 / _BINS)).astype(np.int32), 0, _BINS - 1)
    return idx[:, 0] * _BINS * _BINS + idx[:, 1] * _BINS + idx[:, 2]


def dominant_color(path: Path, box: tuple[float, float, float, float], bin_rank: int = 0,
                   skin_filter: bool = True) -> str:
    """Modal colour of a window of the product shot.

    Three things this has to survive, all of them present in these photos:

    1. **Background.** The garment is shot on white or pale grey and often
       fills less than half the window (a pair of trousers is a narrow
       vertical band). A per-channel mean, or a plain histogram mode, comes
       back "white". So the colours that dominate a thin frame around the
       *whole* image are treated as background and dropped.
    2. **Skin.** Roughly a third of these are worn by a model. Skin is
       excluded on the standard YCbCr skin locus rather than an RGB
       "reddish" rule, which would also delete mustard and rust fabric.
    3. **Two-tone garments.** `bin_rank` selects a lower-ranked cluster, so
       a black-and-teal striped jumper can be tagged with the teal that
       identifies it instead of with the black half of the stripe.
    """
    arr = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    h, w, _ = arr.shape

    # Background = the modal colours of a 2% frame around the image edge.
    bw, bh = max(2, int(0.02 * w)), max(2, int(0.02 * h))
    border = np.concatenate([
        arr[:bh].reshape(-1, 3), arr[-bh:].reshape(-1, 3),
        arr[:, :bw].reshape(-1, 3), arr[:, -bw:].reshape(-1, 3),
    ])
    border_counts = np.bincount(_bin_index(border), minlength=_BINS ** 3)
    bg_bins = [int(b) for b in np.argsort(border_counts)[-3:]
               if border_counts[b] > 0.05 * len(border)]

    x0, y0, x1, y1 = box
    crop = arr[int(h * y0):int(h * y1), int(w * x0):int(w * x1)].reshape(-1, 3)
    r, g, b = crop[:, 0], crop[:, 1], crop[:, 2]
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    span = crop.max(axis=1) - crop.min(axis=1)
    if skin_filter:
        skin = ((cb >= 77) & (cb <= 127) & (cr >= 133) & (cr <= 173)
                & (crop.max(axis=1) > 60) & (span > 8))
    else:
        # Tan, khaki, camel and blush fabrics sit squarely inside the skin
        # locus, so the filter is switched off for the items whose sampling
        # window contains no skin anyway (flat shots, mannequins, and the
        # legs-only window on the one worn trouser shot).
        skin = np.zeros(len(crop), bool)

    flat = _bin_index(crop)
    keep = ~skin & ~np.isin(flat, bg_bins)
    if keep.sum() < 0.03 * len(flat):  # window is essentially all background
        keep = ~skin
    if keep.sum() == 0:
        keep = np.ones(len(flat), bool)

    pool, pool_bins = crop[keep], flat[keep]
    counts = np.bincount(pool_bins, minlength=_BINS ** 3)
    chosen = int(np.argsort(counts)[::-1][bin_rank])
    rep = pool[pool_bins == chosen].mean(axis=0)
    return "#%02X%02X%02X" % tuple(int(c) for c in rep)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-fetch", action="store_true",
                    help="reuse the images already in data/garments/")
    ap.add_argument("--resume", action="store_true",
                    help="skip ids whose image file is already on disk")
    args = ap.parse_args()

    GARMENTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.no_fetch:
        print(f"[1/3] downloading {len(ITEMS)} product shots from {DATASET} ...")
        with httpx.Client(verify=SSL_CTX, follow_redirects=True, timeout=120) as client:
            for item in ITEMS:
                dest = GARMENTS_DIR / f"{item['id']}.jpg"
                if args.resume and dest.exists():
                    continue
                save_image(fetch_row_image(client, item["row"]), dest, item.get("crop"))
                print(f"      {item['id']:>3}  row {item['row']:>6}  -> {dest.name}")
    else:
        print("[1/3] skipping download (--no-fetch)")

    print("[2/3] sampling colours + writing catalog ...")
    catalog = []
    for item in ITEMS:
        path = GARMENTS_DIR / f"{item['id']}.jpg"
        box = item.get("box") or DEFAULT_BOX[item["category"]]
        hex_color = dominant_color(path, box, item.get("hex_bin", 0), item.get("skin", True))
        catalog.append({
            "id": item["id"],
            "name": item["name"],
            "category": item["category"],
            "image_url": f"/garments/{item['id']}.jpg",
            "price": item["price"],
            "color_hex": hex_color,
            # Placeholders: retag_catalog.py (run below) derives both from
            # the colour and silhouette. Kept here only so the file is
            # schema-valid at the moment it is written.
            "season_tags": ["winter"],
            "silhouette": item["silhouette"],
            "occasion_tags": ["everyday"],
            "location": LOCATION[item["category"]],
            "sizes_in_stock": item["sizes"],
            "buy_url": "#",
            "color_lab": hex_to_lab(hex_color),
        })
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"      wrote {CATALOG_PATH} ({len(catalog)} items)")

    print("[3/3] re-deriving season/occasion tags ...")
    subprocess.run([sys.executable, str(Path(__file__).with_name("retag_catalog.py"))], check=True)


if __name__ == "__main__":
    main()

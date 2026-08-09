"""Store catalog schema + loader.

The catalog is the store's inventory: what the recommendation engine ranks
and what the shopper virtually tries on. `Garment` mirrors the frontend's
`Garment` interface (`frontend/src/api/types.ts`) verbatim for the shared
fields, plus the backend-only fields the scorers (Task 3.2) read.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

# Path to backend/data/catalog.json, resolved relative to this file so it
# works regardless of the process's current working directory (pytest,
# uvicorn, etc. may all be launched from different places).
_DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog.json"


class Garment(BaseModel):
    # Shared with frontend/src/api/types.ts — field names must match exactly.
    id: str
    name: str
    category: str
    image_url: str
    price: float
    location: str
    sizes_in_stock: list[str]
    buy_url: str

    # Backend-only: used by the recommendation scorers (Task 3.2/3.3).
    color_hex: str
    color_lab: list[float]
    season_tags: list[str]
    silhouette: dict
    occasion_tags: list[str]


def hex_to_lab(hex_str: str) -> list[float]:
    """Convert a hex color (e.g. "#8C5A3C" or "8c5a3c") to CIELab [L, a, b].

    sRGB -> linear RGB -> XYZ (D65) -> CIELab, per the standard formulas.
    Shared here so both the catalog seed data and Task 3.3's palette-match
    route (which converts the shopper's palette hexes to Lab) use the exact
    same conversion instead of two implementations drifting apart.
    """
    h = hex_str.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"invalid hex color: {hex_str!r}")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _linearize(c: float) -> float:
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

    r, g, b = _linearize(r), _linearize(g), _linearize(b)

    # sRGB -> XYZ (D65 reference white).
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.00000
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def _f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = _f(x), _f(y), _f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b_ = 200 * (fy - fz)
    return [round(L, 2), round(a, 2), round(b_, 2)]


def load_catalog(path: str | Path | None = None) -> list[Garment]:
    """Load and validate the store catalog.

    Raises FileNotFoundError if the catalog file doesn't exist, and
    ValueError (naming the offending item's id/index) if any entry fails
    schema validation — a kiosk booting in a store should fail loudly on
    bad data, not silently skip an item or surface an opaque traceback.
    """
    p = Path(path) if path is not None else _DEFAULT_CATALOG_PATH
    if not p.exists():
        raise FileNotFoundError(f"Catalog file not found: {p}")

    with p.open() as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise ValueError(f"Catalog file {p} must contain a JSON array of items")

    garments: list[Garment] = []
    for i, item in enumerate(raw):
        item_id = item.get("id", f"<no id, index {i}>") if isinstance(item, dict) else f"<index {i}>"
        try:
            garments.append(Garment(**item))
        except ValidationError as e:
            raise ValueError(
                f"Catalog entry at index {i} (id={item_id!r}) failed validation:\n{e}"
            ) from e

    return garments

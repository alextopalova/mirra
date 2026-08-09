import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.reco.catalog import Garment, hex_to_lab, load_catalog

_GARMENTS_DIR = Path(__file__).resolve().parents[1] / "data" / "garments"

_VALID_CATEGORIES = {"dress", "top", "pants"}
_VALID_SEASONS = {"autumn", "spring", "summer", "winter"}
_VALID_OCCASIONS = {"everyday", "work", "date night", "wedding guest"}
_VALID_FABRICS = {
    "crisp", "structured", "smooth", "soft", "draping", "light", "textured",
    "natural", "chunky",
}
_VALID_WAISTS = {"defined", "regular", "relaxed", "high"}


# --- brief's test (verbatim contract) ---------------------------------

def test_load_catalog_nonempty_and_typed():
    items = load_catalog()
    assert len(items) >= 12
    g = items[0]
    assert g.category in _VALID_CATEGORIES
    assert len(g.color_lab) == 3


# --- seed data quality -------------------------------------------------

def test_all_categories_represented_and_reasonably_balanced():
    items = load_catalog()
    counts = {c: 0 for c in _VALID_CATEGORIES}
    for g in items:
        counts[g.category] += 1
    assert all(n >= 3 for n in counts.values()), counts


def test_silhouette_and_tags_use_expected_vocabulary():
    items = load_catalog()
    for g in items:
        assert set(g.silhouette.keys()) >= {"structured", "fabric", "neckline", "waist"}
        assert isinstance(g.silhouette["structured"], bool)
        assert g.silhouette["fabric"] in _VALID_FABRICS, g.id
        assert g.silhouette["waist"] in _VALID_WAISTS, g.id
        assert set(g.season_tags) <= _VALID_SEASONS, g.id
        assert g.season_tags, g.id
        assert set(g.occasion_tags) <= _VALID_OCCASIONS, g.id
        assert g.occasion_tags, g.id
        assert g.sizes_in_stock, g.id


def test_color_hex_and_color_lab_never_drift():
    """The seed data's color_lab must be exactly what hex_to_lab(color_hex)
    produces — this is the whole point of storing both fields."""
    items = load_catalog()
    for g in items:
        assert g.color_lab == hex_to_lab(g.color_hex), g.id


# --- hex_to_lab correctness (known anchors) -----------------------------

def test_hex_to_lab_white_anchor():
    L, a, b = hex_to_lab("#FFFFFF")
    assert L == pytest.approx(100.0, abs=0.1)
    assert a == pytest.approx(0.0, abs=0.1)
    assert b == pytest.approx(0.0, abs=0.1)


def test_hex_to_lab_mid_grey_anchor():
    L, a, b = hex_to_lab("#808080")
    assert 50.0 < L < 56.0
    assert a == pytest.approx(0.0, abs=0.1)
    assert b == pytest.approx(0.0, abs=0.1)


def test_hex_to_lab_black_anchor():
    L, a, b = hex_to_lab("#000000")
    assert L == pytest.approx(0.0, abs=0.1)
    assert a == pytest.approx(0.0, abs=0.1)
    assert b == pytest.approx(0.0, abs=0.1)


def test_hex_to_lab_accepts_lowercase_and_no_hash():
    assert hex_to_lab("ffffff") == hex_to_lab("#FFFFFF")


# --- gap 1: CWD-independent loading --------------------------------------

def test_load_catalog_is_cwd_independent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    items = load_catalog()
    assert len(items) >= 12


def test_load_catalog_missing_file_raises_clear_error():
    with pytest.raises(FileNotFoundError, match="catalog"):
        load_catalog("/nonexistent/path/catalog.json")


# --- gap 2: loud validation on malformed entries --------------------------

# --- gap 3: catalog images must be real garment photos, not placeholders --

def test_no_catalog_image_url_points_at_a_placeholder_service():
    """The VTO endpoint sends `image_url` to YouCam as the garment reference
    (`ref_file_url`); a placeholder/stock-photo service (picsum.photos,
    placehold.co, via.placeholder.com, ...) returns an arbitrary image that
    has nothing to do with the garment, silently producing a nonsense
    try-on. Assert on the strings only -- no network calls here."""
    placeholder_markers = ("picsum.photos", "placehold", "via.placeholder")
    items = load_catalog()
    for g in items:
        lowered = g.image_url.lower()
        assert not any(marker in lowered for marker in placeholder_markers), (
            f"{g.id} image_url looks like a placeholder: {g.image_url}"
        )


def test_no_catalog_image_url_is_hot_linked_to_an_external_host():
    """Garment images are committed to the repo (backend/data/garments/) and
    served locally -- `image_url` must be a relative `/garments/<id>.jpg`
    path, never an `http(s)://` link to a third-party CDN. Hot-linking a
    third party at runtime is both a reliability risk (their host going
    down breaks try-on) and outside this project's licensing story for the
    images (see data/garments/SOURCE.md)."""
    items = load_catalog()
    for g in items:
        assert not g.image_url.lower().startswith(("http://", "https://")), (
            f"{g.id} image_url is hot-linked to an external host: {g.image_url}"
        )
        assert g.image_url.startswith("/garments/"), (
            f"{g.id} image_url should be a local /garments/<id>.jpg path: {g.image_url}"
        )


def test_all_catalog_images_exist_on_disk():
    """Every `image_url` must resolve to a real file under
    backend/data/garments/ -- a dangling reference would silently 404 at
    upload time (or, worse, get proxied to YouCam as a broken ref)."""
    items = load_catalog()
    for g in items:
        filename = g.image_url.removeprefix("/garments/")
        path = _GARMENTS_DIR / filename
        assert path.is_file(), f"{g.id} image_url points at a missing file: {path}"
        assert path.stat().st_size > 0, f"{g.id} image file is empty: {path}"


def test_load_catalog_malformed_entry_raises_clear_error(tmp_path):
    bad = [
        {
            "id": "ok1", "name": "Fine dress", "category": "dress",
            "image_url": "https://x/1.jpg", "price": 100,
            "color_hex": "#8C5A3C", "color_lab": [45.0, 12.0, 22.0],
            "season_tags": ["autumn"],
            "silhouette": {"waist": "defined", "fabric": "soft", "structured": False, "neckline": "v"},
            "occasion_tags": ["everyday"], "location": "Aisle 1",
            "sizes_in_stock": ["S", "M"], "buy_url": "#",
        },
        {
            "id": "bad-item", "name": "Broken top", "category": "top",
            # missing required fields (image_url, price, color_lab, etc.)
        },
    ]
    p = tmp_path / "bad_catalog.json"
    p.write_text(json.dumps(bad))

    with pytest.raises((ValueError, ValidationError)) as exc_info:
        load_catalog(str(p))

    msg = str(exc_info.value)
    assert "bad-item" in msg or "index 1" in msg

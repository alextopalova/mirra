"""Apparel Virtual Try-On via the YouCam `cloth` task.

Per app/youcam/CONTRACT.md (verified live against the real API):
- The task name is `cloth`, not `clothes-vto`.
- The person image goes in as `src_file_id` (we always upload, since the
  route only ever has photo bytes, never a public URL for the shopper).
- The garment goes in as either `ref_file_url` or `ref_file_id`:
    - Catalog entries now store `image_url` as a *relative* path
      ("/garments/<id>.jpg") served locally by app/main.py's static mount
      (see backend/data/garments/). Perfect Corp's servers can't reach
      `localhost`, so for those we read the file off disk and upload it
      the same way the person photo is uploaded, then pass `ref_file_id`.
    - A handful of catalog entries may still carry a fully-qualified
      http(s) URL (e.g. mid-migration, or a deliberately external image).
      Those are passed straight through as `ref_file_url` -- cheaper, one
      less round trip, and it's what CONTRACT.md verified live.
- `garment_category` is REQUIRED; see CATEGORY_MAP below.
- The poll payload's `results` was verified as an OBJECT with a `url` key
  for `cloth`, but older docs describe a list -- `_extract_result_url`
  below handles both shapes defensively.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app.youcam.client import YouCamClient, YouCamError, YouCamResponseError

# Maps this project's catalog `Garment.category` values to the YouCam
# `cloth` task's `garment_category` parameter. Kept in this one place per
# the task brief rather than scattered across callers.
#   - "top"   -> "upper_body" (verified working in CONTRACT.md)
#   - "pants" -> "lower_body" (presumed valid per CONTRACT.md; not yet
#                live-verified, but it's the obvious counterpart to
#                upper_body/full_body)
#   - "dress" -> "full_body"  (a dress covers the whole body, not just the
#                upper or lower half)
CATEGORY_MAP = {
    "top": "upper_body",
    "pants": "lower_body",
    "dress": "full_body",
}

# Any catalog category we haven't explicitly mapped (future catalog
# additions) defaults to the most inclusive option rather than raising,
# so an unmapped category degrades to "best effort" instead of crashing
# the shopper's try-on.
_DEFAULT_GARMENT_CATEGORY = "full_body"

# client.py's poll() defaults (60 tries x 2.5s ~= 150s) are shared across
# every YouCam task and are too loose for an unattended kiosk: CONTRACT.md
# says `cloth` generation takes "tens of seconds", so a shopper standing at
# the mirror shouldn't watch a spinner for 2.5 minutes before finding out
# it failed. Tighten just this call site to roughly a 60-75s ceiling --
# generous enough to absorb a slow generation, short enough that a genuine
# stall still fails fast for a kiosk. Do NOT change client.py's defaults;
# other callers (e.g. skin-tone-analysis) may need the looser budget.
_POLL_INTERVAL_SECONDS = 2.5
_POLL_MAX_TRIES = 28  # 2.5s * 28 = 70s ceiling

# Where self-hosted garment images actually live on disk. Resolved relative
# to this file (backend/app/youcam/vto.py -> parents[2] == backend/) so it
# works regardless of the process's cwd, matching app/reco/catalog.py's
# pattern for locating catalog.json.
_GARMENTS_DIR = (Path(__file__).resolve().parents[2] / "data" / "garments").resolve()


class GarmentImageError(YouCamError):
    """Raised when a garment's self-hosted image can't be resolved or read
    (missing file, or an `image_url` that tries to escape the garments
    directory). Subclasses YouCamError so it's caught by the router's
    existing shopper-facing 503 handling -- never a raw stack trace."""


def _is_absolute_url(image_url: str) -> bool:
    return image_url.startswith("http://") or image_url.startswith("https://")


def _resolve_garment_image_path(image_url: str) -> Path:
    """Resolve a relative catalog `image_url` (e.g. "/garments/d1.jpg") to
    the file on disk, guarding against path traversal.

    The catalog convention is "/garments/<id>.jpg"; the leading "/garments"
    segment (if present) is stripped before joining onto _GARMENTS_DIR so a
    bare "d1.jpg" also works. Whatever the input, the final resolved path
    is required to stay inside _GARMENTS_DIR -- a crafted `image_url` like
    "/garments/../../.env" or "/../../etc/passwd" is rejected rather than
    allowed to read an arbitrary file off the server.
    """
    relative = image_url.lstrip("/")
    if relative.startswith("garments/"):
        relative = relative[len("garments/") :]

    candidate = (_GARMENTS_DIR / relative).resolve()
    try:
        candidate.relative_to(_GARMENTS_DIR)
    except ValueError:
        raise GarmentImageError(
            f"garment image_url escapes the garments directory: {image_url!r}"
        ) from None
    return candidate


def garment_category_for(category: str) -> str:
    """Map a catalog garment category to the YouCam `garment_category` value."""
    return CATEGORY_MAP.get(category, _DEFAULT_GARMENT_CATEGORY)


def _extract_result_url(payload: dict) -> str:
    """Pull the result image URL out of a terminal poll payload.

    Handles both shapes seen across YouCam docs/versions:
      - {"results": {"url": "..."}}                       (verified live)
      - {"results": [{"url": "..."}]}
      - {"results": [{"data": [{"url": "..."}]}]}
    Raises YouCamResponseError with the offending payload if none match,
    rather than letting a KeyError/TypeError bubble up unexplained.
    """
    results = payload.get("results")

    if isinstance(results, dict):
        url = results.get("url")
        if isinstance(url, str) and url:
            return url

    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            url = first.get("url")
            if isinstance(url, str) and url:
                return url
            data = first.get("data")
            if isinstance(data, list) and data:
                inner = data[0]
                if isinstance(inner, dict):
                    inner_url = inner.get("url")
                    if isinstance(inner_url, str) and inner_url:
                        return inner_url

    raise YouCamResponseError(
        f"YouCam 'cloth' task result payload had no recognizable image URL: {payload!r}"
    )


async def try_on(person_bytes: bytes, garment_image_url: str, garment_category: str) -> dict:
    """Run the Apparel VTO (`cloth`) task end-to-end and return {"image": url}.

    `garment_image_url` is the catalog `Garment.image_url` value, which is
    either a fully-qualified http(s) URL (passed straight through as
    `ref_file_url`) or a relative "/garments/<id>.jpg" path served locally
    (read off disk and uploaded, then passed as `ref_file_id` -- YouCam
    can't reach localhost).

    Always closes the underlying HTTP client (via the async context
    manager), including when upload/run/poll raises.
    """
    async with YouCamClient() as client:
        person_file_id = await client.upload("cloth", person_bytes)

        ref_kwargs: dict[str, str]
        if _is_absolute_url(garment_image_url):
            ref_kwargs = {"ref_file_url": garment_image_url}
        else:
            garment_path = _resolve_garment_image_path(garment_image_url)
            if not garment_path.is_file():
                raise GarmentImageError(f"garment image file not found: {garment_path.name!r}")
            garment_bytes = garment_path.read_bytes()
            content_type = mimetypes.guess_type(garment_path.name)[0] or "image/jpeg"
            ref_file_id = await client.upload("cloth", garment_bytes, content_type=content_type)
            ref_kwargs = {"ref_file_id": ref_file_id}

        task_id = await client.run(
            "cloth",
            {
                "src_file_id": person_file_id,
                **ref_kwargs,
                "garment_category": garment_category,
            },
        )
        result = await client.poll(
            "cloth", task_id, interval=_POLL_INTERVAL_SECONDS, max_tries=_POLL_MAX_TRIES
        )

    return {"image": _extract_result_url(result)}

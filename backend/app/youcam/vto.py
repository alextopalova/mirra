"""Apparel Virtual Try-On via the YouCam `cloth` task.

Per app/youcam/CONTRACT.md (verified live against the real API):
- The task name is `cloth`, not `clothes-vto`.
- The person image goes in as `src_file_id` (we always upload, since the
  route only ever has photo bytes, never a public URL for the shopper).
- The garment goes in as `ref_file_url` (singular -- `ref_file_urls`
  plural is rejected by the API) pointing at the catalog's `image_url`.
- `garment_category` is REQUIRED; see CATEGORY_MAP below.
- The poll payload's `results` was verified as an OBJECT with a `url` key
  for `cloth`, but older docs describe a list -- `_extract_result_url`
  below handles both shapes defensively.
"""

from __future__ import annotations

from app.youcam.client import YouCamClient, YouCamResponseError

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

    Always closes the underlying HTTP client (via the async context
    manager), including when upload/run/poll raises.
    """
    async with YouCamClient() as client:
        person_file_id = await client.upload("cloth", person_bytes)
        task_id = await client.run(
            "cloth",
            {
                "src_file_id": person_file_id,
                "ref_file_url": garment_image_url,
                "garment_category": garment_category,
            },
        )
        result = await client.poll(
            "cloth", task_id, interval=_POLL_INTERVAL_SECONDS, max_tries=_POLL_MAX_TRIES
        )

    return {"image": _extract_result_url(result)}

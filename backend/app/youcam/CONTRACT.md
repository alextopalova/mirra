# YouCam / Perfect Corp S2S API — VERIFIED Integration Contract

**Status: verified live against the real API on 2026-08-09** with the project's own key.
Everything below was confirmed by actual HTTP calls, not inferred from docs.

## Base + Auth (VERIFIED)

- Base host: `https://yce-api-01.makeupar.com` (`https://yce-api-01.perfectcorp.com` also responds identically).
- **Auth: the `sk-…` API key works DIRECTLY as a bearer token.** No RSA `id_token` exchange, no client secret needed.
  ```
  Authorization: Bearer <YOUCAM_API_KEY>
  ```
- Credit balance: `GET /s2s/v1.0/client/credit` → `results[].amount`. Confirmed **1000 units** available (`ApiPaygToken`).
- Feature costs: `GET /s2s/v2.0/credit/feature-cost` → `result.skus[]`.
  **CAVEAT: this list is NOT exhaustive** — it returned 20 image/hair SKUs and did *not* include `cloth` or
  `skin-tone-analysis`, yet both endpoints exist and are authorized. Do not use it to decide what is callable.

## Endpoint availability (VERIFIED by direct probe)

| Endpoint | Status |
|---|---|
| `POST /s2s/v2.0/file/{task}` | ✅ exists |
| `POST /s2s/v2.0/task/cloth` (Apparel VTO) | ✅ exists + authorized |
| `POST /s2s/v2.0/task/skin-tone-analysis` | ✅ exists + authorized |
| `POST /s2s/v2.1/task/skin-analysis` | ✅ exists + authorized |
| `POST /s2s/v2.0/task/face-analyzer` | ❌ **404 — does not exist.** The Face Attributes add-on is unavailable at this path. |

## 1. Upload flow (VERIFIED end-to-end)

**Step 1 — create file entry:**
`POST /s2s/v2.0/file/{task}` (e.g. `/s2s/v2.0/file/cloth`), JSON:
```json
{ "files": [ { "content_type": "image/jpeg", "file_name": "p.jpg", "file_size": 111250 } ] }
```
Response (**note the nesting — it is NOT top-level**):
```json
{ "status": 200,
  "data": { "files": [ {
      "file_id": "<opaque id>",
      "requests": [ { "method": "PUT", "url": "<presigned S3 URL>", "headers": [...] } ]
  } ] } }
```
Read as: `resp["data"]["files"][0]["file_id"]` and `...["requests"][0]`.
`requests[0]["headers"]` may be a LIST of `{name, value}` objects — normalise to a dict before passing to httpx.

**Step 2 — upload bytes:** `PUT` the raw image bytes to `requests[0]["url"]` with those headers. Returns 200.

**Step 3 —** reference the image as `src_file_id` in the task call.

## 2. Apparel VTO — `POST /s2s/v2.0/task/cloth` (VERIFIED WORKING)

Accepted parameters (exact names, from the API's own 400 error):
`src_file_url`, `src_file_id`, `ref_file_url`, `ref_file_id`, `garment_category`, `template_id`.

- Person image: `src_file_id` (uploaded) **or** `src_file_url` (public URL).
- Garment: `ref_file_url` (**singular** — `ref_file_urls` plural is REJECTED) or `ref_file_id`.
- `garment_category`: **required**. `"upper_body"` verified working. (`full_body`, `lower_body` presumed valid.)

Verified working request:
```json
{ "src_file_id": "<file_id>",
  "ref_file_url": "https://.../garment.jpg",
  "garment_category": "upper_body" }
```
Response: `{ "status": 200, "data": { "task_id": "<id>" } }`

**Poll:** `GET /s2s/v2.0/task/cloth/{task_id}` →
```json
{ "data": { "status": "success", "error": null, "results": { "url": "<result image URL>" } } }
```
**`results` is an OBJECT with a `url` key** (not an array as older docs suggest). Handle both shapes defensively.
Result URLs are presigned and expire in ~2 hours. Poll every ~2.5s; the generation takes tens of seconds.

## 3. Skin Tone Analysis — `POST /s2s/v2.0/task/skin-tone-analysis`

Exists and is authorized. Requires `src_file_url` or `src_file_id` (same upload flow).
Result field names NOT yet verified live — inspect the poll payload on first real call and adapt.
**Season label is NOT expected to be returned** — derive the season from the returned tone/undertone values
in `app/youcam/color.py`.

## 4. Budget

1000 units total. A `cloth` generation costs a small number of units per call (exact SKU not listed).
Cache per session; keep `USE_MOCKS=true` during development; only call live for real runs and the demo.

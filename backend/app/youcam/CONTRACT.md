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

> **⚠️ VERIFIED LIVE (2026-08-09) — the polling status field name DIFFERS PER ENDPOINT:**
> - `task/cloth` → the terminal-state field is `status` (`{"data": {"status": "success", ...}}`).
> - `task/skin-tone-analysis` → the terminal-state field is **`task_status`**, not `status`
>   (see the real error payload below). `data.status` is simply absent on this endpoint.
>
> **Clients must accept both field names** (prefer `task_status` if present, else `status`) or a
> skin-tone-analysis error/success will look like "missing status" and the poller will spin until
> it times out (~150s) instead of surfacing the result. `app/youcam/client.py::poll()` does this.

## 3. Skin Tone Analysis — `POST /s2s/v2.0/task/skin-tone-analysis`

Exists and is authorized. Requires `src_file_url` or `src_file_id` (same upload flow).
Result field names NOT yet verified live — inspect the poll payload on first real call and adapt.
**Season label is NOT expected to be returned** — derive the season from the returned tone/undertone values
in `app/youcam/color.py`.

**Poll uses `task_status`, not `status` (VERIFIED live error payload):**
```json
{ "error": "error_face_not_forward_facing", "results": null, "task_status": "error" }
```
- The terminal state is in `data.task_status` (`"error"` here), not `data.status`.
- **`error` sometimes comes back as the literal string `"None"` (not JSON `null`)** on other failures —
  treat `"None"`/`"none"`/empty string as "no detail available" and fall back to reporting the raw
  payload rather than surfacing the useless text `"None"` to the caller.
- **Input requirement, verified live:** the source image must show a single **forward-facing face of
  adequate size/resolution**. A downscaled full-body photo was rejected with
  `error_face_not_forward_facing` — crop/zoom to a clear frontal face shot before calling this endpoint.

## 4. Budget

1000 units total. A `cloth` generation costs a small number of units per call (exact SKU not listed).
Cache per session; keep `USE_MOCKS=true` during development; only call live for real runs and the demo.

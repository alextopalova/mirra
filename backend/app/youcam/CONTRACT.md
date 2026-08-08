# YouCam / Perfect Corp S2S API — Integration Contract

Source: extracted from `yce.perfectcorp.com/document`, `app-cdn-01.perfectcorp.com/.../ai-api`,
the ReadMe `docs.perfectcorp.com/reference/*` pages, and a working `cloth` reference build.
Some exact JSON field names are SPA-gated in the docs and marked **UNCONFIRMED** — verify in the
API playground during Phase 5 before shipping.

## Two API generations — we build against **Generation B**

| | Gen A (older S2S) | **Gen B (current YouCam API) ← USE THIS** |
|---|---|---|
| Base host | `https://yce-api-01.perfectcorp.com` | `https://yce-api-01.makeupar.com` |
| Path prefix | `/s2s/v1.0/...` | `/s2s/v2.0/...` (skin-analysis: `/s2s/v2.1/...`) |
| Auth | RSA `id_token` → `access_token` | Bearer token (likely still obtained via the same RSA exchange) |

## 1. Auth

Two possible modes — the client supports both; **default to Mode A, fall back to Mode B**:

- **Mode A (try first):** use the `sk-…` API key directly as `Authorization: Bearer <API_KEY>`.
  We only have a single `sk-` key, and the v2 docs phrase auth as "include your API key as Bearer token."
- **Mode B (fallback, needs a client secret):** RSA `id_token` exchange.
  - `POST https://yce-api-01.perfectcorp.com/s2s/v1.0/client/auth`
  - body: `{ "client_id": "<API_KEY>", "id_token": "<b64(RSA_encrypt('client_id=<id>&timestamp=<epoch_ms>', client_secret_pubkey))>" }`
  - `client_secret` **is an RSA X.509 public key (PEM/Base64)**; encrypt with PKCS#1 v1.5 (**padding UNCONFIRMED** — PerfectCorp samples use `RSA/ECB/PKCS1Padding`).
  - response: `access_token` (valid **2 hours**) → send as Bearer on all subsequent calls.

> **ACTION:** if Mode A returns 401, we need the **client secret / RSA public key** from the YouCam console
> (`env YOUCAM_API_SECRET`). Ask the user for it then.

- Credit balance: `GET /s2s/v1.0/client/credit`. Feature cost: `GET /s2s/v2.0/credit/feature-cost`.

## 2. Upload (3-step presigned) — CONFIRMED pattern

1. `POST /s2s/v2.0/file/{task}` body `{ "files": [ { "content_type": "image/jpeg", "file_name": "img.jpg", "file_size": <bytes> } ] }`
   → response has `file_id` and `requests[]` (each `{ url, headers, method }` — presigned S3).
2. `PUT requests[0].url` with the raw bytes and `requests[0].headers`.
3. Reference the image in tasks by `src_file_id = file_id` (or pass a **public** image URL instead).

Fashion/try-on tasks effectively **require public URLs or uploaded file_ids** (no inline base64). Images ≤ **10 MB**; many tasks want long side ≤ 1024px, near-frontal face.

## 3. AI Skin Tone / Facial Color Tones (personal color)

- Create: `POST /s2s/v2.0/task/skin-tone-analysis` body `{ "src_file_id": "<id>" }` (or image URL). Extra params UNCONFIRMED.
- Poll: `GET /s2s/v2.0/task/skin-tone-analysis/{task_id}` → `task_status` ∈ `running|success|error`.
- Result outputs (confirmed *kinds*): skin tone, undertone (warm/cool/neutral), Fitzpatrick, eye/eyebrow/lip/hair colors. **Exact field names UNCONFIRMED.**
- **Season label: NOT returned by the API (best evidence).** Derive season ourselves from undertone + depth. Mapping lives in `color.py`.

## 4. AI Clothes / Apparel VTO — `cloth` (the try-on)

- Create: `POST /s2s/v2.0/task/cloth` (CONFIRMED path) body (confirmed field *names*, some values UNCONFIRMED):
  - person: `src_file_id` **or** `src_file_url` (public)
  - garment: `ref_file_id` **or** `ref_file_urls` (array of public URLs)
  - `garment_category` (**required**; enum e.g. upper/lower/full-body/`auto` — exact values UNCONFIRMED)
  - `change_shoes` (bool, optional)
- Garment image: JPG/PNG ≤10MB; flat-lay **or** on-model both supported. Person: full/half-body or selfie.
- Poll: `GET /s2s/v2.0/task/cloth/{task_id}` → `task_status`. Reference build polls every 2s up to 120×.
- Result image URL: in the success payload results array — pattern `results[].data[].url` (+ `dst_id`). **Exact path UNCONFIRMED.**

## 5. AI Face Attributes & Ratio (optional add-on)

- Create: `POST /s2s/v2.0/task/face-analyzer` body `{ "src_file_id": "<id>" }`. Poll `GET /s2s/v2.0/task/face-analyzer/{task_id}`.
- Outputs: 11 facial ratios + face/eye/lip/brow shape from 80+ landmarks. **Exact field names UNCONFIRMED.**

## 6. Async pattern, limits, quirks

- Pattern: create (`POST .../task/{type}` → `task_id`) → poll (`GET .../task/{type}/{task_id}`) until `task_status` `success`/`error` → read result URL(s).
- Rate limit (Gen B): **250 req / 300s, 5 QPS**. Exceed → 429.
- **Poll promptly** — a task can be dropped if not polled within ~10s of readiness.
- Uploads deleted ~24h; result URLs valid ~2h.
- Cost per call: query `/s2s/v2.0/credit/feature-cost` at runtime (don't hardcode). Free budget = 1,000 units — cache per session, use `USE_MOCKS=true` in dev.

## 7. Reference client implementation (Gen B)

Use this in `app/youcam/client.py` (reconcile the UNCONFIRMED bits against the playground in Phase 5).
Note the signatures: `upload(task, bytes)`, `run(task, payload)`, `poll(task, task_id)` — update
`tests/test_youcam_client.py` to match.

```python
import asyncio, base64, time
import httpx
from app.config import settings

BASE = "https://yce-api-01.makeupar.com"
AUTH_BASE = "https://yce-api-01.perfectcorp.com"

class YouCamClient:
    def __init__(self, transport=None):
        self._client = httpx.AsyncClient(base_url=BASE, transport=transport, timeout=60)
        self._token: str | None = None

    async def _bearer(self) -> str:
        # Mode A: sk- key used directly as bearer.
        if not settings.youcam_api_secret:
            return settings.youcam_api_key
        # Mode B: RSA id_token -> access_token (needs client_secret = RSA public key PEM).
        if self._token:
            return self._token
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        pub = load_pem_public_key(settings.youcam_api_secret.encode())
        plain = f"client_id={settings.youcam_api_key}&timestamp={int(time.time()*1000)}".encode()
        id_token = base64.b64encode(pub.encrypt(plain, padding.PKCS1v15())).decode()
        async with httpx.AsyncClient(base_url=AUTH_BASE, timeout=30) as ac:
            r = await ac.post("/s2s/v1.0/client/auth",
                              json={"client_id": settings.youcam_api_key, "id_token": id_token})
            r.raise_for_status()
            self._token = r.json()["access_token"]
        return self._token

    async def _headers(self) -> dict:
        return {"Authorization": f"Bearer {await self._bearer()}"}

    async def upload(self, task: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        h = await self._headers()
        r = await self._client.post(f"/s2s/v2.0/file/{task}", headers=h, json={
            "files": [{"content_type": content_type, "file_name": "img.jpg", "file_size": len(image_bytes)}]
        })
        r.raise_for_status()
        d = r.json()
        file_id = d.get("file_id") or d["result"][0]["file_id"]          # verify shape in playground
        req = (d.get("requests") or d.get("result"))[0]
        async with httpx.AsyncClient(timeout=60) as put:
            pr = await put.request(req.get("method", "PUT"), req["url"],
                                   content=image_bytes, headers=req.get("headers", {}))
            pr.raise_for_status()
        return file_id

    async def run(self, task: str, payload: dict) -> str:
        h = await self._headers()
        r = await self._client.post(f"/s2s/v2.0/task/{task}", headers=h, json=payload)
        r.raise_for_status()
        return r.json()["task_id"]

    async def poll(self, task: str, task_id: str, interval: float = 2.0, max_tries: int = 120) -> dict:
        h = await self._headers()
        for _ in range(max_tries):
            r = await self._client.get(f"/s2s/v2.0/task/{task}/{task_id}", headers=h)
            r.raise_for_status()
            d = r.json()
            st = d.get("task_status") or d.get("status")
            if st in ("success", "completed", "done"):
                return d
            if st in ("error", "failed"):
                raise RuntimeError(f"YouCam task failed: {d}")
            await asyncio.sleep(interval)
        raise TimeoutError("YouCam task timed out")
```

## 8. To verify live in the playground (Phase 5)
- Whether the `sk-` key works as a direct bearer (Mode A) or Mode B is required (→ get client secret).
- Exact result field names for `skin-tone-analysis` and `cloth`; the result-image URL path.
- `garment_category` enum values.
- Upload response shape (`file_id`/`requests` vs `result`).

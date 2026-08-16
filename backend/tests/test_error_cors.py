"""An unhandled 500 must still carry CORS headers.

Why this file exists
---------------------
Twice now a backend outage has reached the kiosk disguised as a CORS
problem, costing a debugging session each time. The mechanism:

    ServerErrorMiddleware   <- turns an unhandled exception into a 500
      CORSMiddleware        <- adds Access-Control-Allow-Origin
        ExceptionMiddleware
          router

Starlette builds the stack with ServerErrorMiddleware OUTERMOST, so a 500
it generates is returned *after* CORSMiddleware has already been passed by
-- the response carries no Access-Control-Allow-Origin. The browser sees a
header-less error and reports "Origin ... is not allowed by
Access-Control-Allow-Origin", which sends you off debugging CORS while the
real cause (an ImportError for a missing native library, both times) sits
in the server log.

Note that registering `@app.exception_handler(Exception)` does NOT fix
this: Starlette routes the `Exception` key to ServerErrorMiddleware, which
is exactly the layer that's outside CORS. The fix has to be a middleware
installed *inside* CORSMiddleware, which is what app/main.py does.
"""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

# raise_server_exceptions=False makes TestClient return the 500 the way a
# browser would receive it, instead of re-raising the exception in-process.
client = TestClient(app, raise_server_exceptions=False)

_BOOM = "/__test_unhandled_error__"


@app.get(_BOOM)
def _boom():
    raise RuntimeError("simulated unhandled failure")


def test_unhandled_error_returns_500_with_cors_header():
    r = client.get(_BOOM, headers={"Origin": settings.allowed_origin})
    assert r.status_code == 500
    # The whole point: without this header the browser reports a CORS
    # failure and hides the 500.
    assert r.headers.get("access-control-allow-origin") == settings.allowed_origin


def test_unhandled_error_body_is_json_and_leaks_no_traceback():
    r = client.get(_BOOM, headers={"Origin": settings.allowed_origin})
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert set(body) == {"detail"}
    # Never hand the shopper (or a passer-by at the kiosk) a stack trace.
    assert "RuntimeError" not in body["detail"]
    assert "Traceback" not in body["detail"]


def test_unhandled_error_from_disallowed_origin_gets_no_cors_header():
    # The error path must not become a way to bypass the origin allowlist.
    r = client.get(_BOOM, headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 500
    assert "access-control-allow-origin" not in r.headers


def test_normal_error_responses_still_carry_cors_header():
    # Regression guard: the handled paths (422s from a retake-able photo
    # problem, 404s) already worked -- the fix must not break them.
    r = client.post(
        "/analyze-body",
        json={"frontPhoto": "not-a-data-url", "heightCm": 170, "weightKg": 65},
        headers={"Origin": settings.allowed_origin},
    )
    assert r.status_code == 422
    assert r.headers.get("access-control-allow-origin") == settings.allowed_origin


def test_success_responses_still_carry_cors_header():
    r = client.get("/health", headers={"Origin": settings.allowed_origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == settings.allowed_origin

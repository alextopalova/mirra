import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings
from app.routers import body, recommend, youcam

logger = logging.getLogger(__name__)

app = FastAPI(title="Mirra API")


class ServerErrorAsJsonMiddleware(BaseHTTPMiddleware):
    """Turn an unhandled exception into a JSON 500 *inside* the CORS layer.

    Starlette's own ServerErrorMiddleware is the OUTERMOST layer of the
    stack, so a 500 it produces has already bypassed CORSMiddleware and
    carries no Access-Control-Allow-Origin. The browser then reports
    "Origin ... is not allowed by Access-Control-Allow-Origin" and hides
    the actual error -- which cost two debugging sessions, once for a
    missing libGL.so.1 and once for a missing libGLESv2.so.2, neither of
    which had anything to do with CORS.

    Catching here instead means the 500 travels back out through
    CORSMiddleware like any ordinary response and gets its headers, so the
    kiosk console shows a real status code and the network tab shows a
    readable body.

    Registering `@app.exception_handler(Exception)` would NOT work: FastAPI
    hands the `Exception` key to ServerErrorMiddleware, i.e. the very layer
    that sits outside CORS.

    Because this swallows the exception before Starlette sees it, it takes
    over the traceback logging Starlette would otherwise have done --
    hence logger.exception, which keeps the full stack in the Render logs.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled error serving %s %s", request.method, request.url.path
            )
            # Deliberately generic: this reaches an in-store kiosk screen,
            # and an exception message can carry internals. The detail for
            # a developer goes to the log above, not to the response.
            return JSONResponse(
                status_code=500,
                content={"detail": "Something went wrong. Please try again."},
            )


# ORDER MATTERS, and it reads backwards: add_middleware inserts at position
# 0, so the LAST one registered ends up OUTERMOST. CORSMiddleware must be
# registered after ServerErrorAsJsonMiddleware for the error responses the
# latter produces to pass back out through it and pick up their headers.
# Swapping these two lines silently reintroduces the header-less 500.
app.add_middleware(ServerErrorAsJsonMiddleware)
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

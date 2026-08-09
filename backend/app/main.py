from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import body

app = FastAPI(title="Mirra API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(body.router)

@app.get("/health")
def health():
    return {"status": "ok"}

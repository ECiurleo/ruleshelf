"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, campaigns, documents, games, meta, providers, search, users
from app.auth import COOKIE_NAME, public_user, user_from_token
from app.config import APP_NAME, APP_VERSION, DATA_DIR
from app.db import db, init_db
from app.extractors import ExtractionError
from app.providers.base import ProviderError
from app.services.config_store import CONFIG_PATH, apply_config_file, snapshot_config
from app.services.ingest import shutdown

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("ruleshelf")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    applied = apply_config_file()
    if not applied and not CONFIG_PATH.exists():
        # First run (or a fresh data folder): write the initial snapshot.
        snapshot_config()
    log.info("%s %s ready — data in %s", APP_NAME, APP_VERSION, DATA_DIR)
    yield
    shutdown()


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Search and ask questions across your tabletop rulebooks.",
    lifespan=lifespan,
)

# Local development: the Vite dev server runs on :5173.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


PUBLIC_API = {
    "/api",
    "/api/health",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if (
        request.method == "OPTIONS"
        or not path.startswith("/api/")
        or path in PUBLIC_API
    ):
        return await call_next(request)
    with db() as conn:
        row = user_from_token(conn, request.cookies.get(COOKIE_NAME))
        if not row:
            return JSONResponse(status_code=401, content={"detail": "Sign in to continue."})
        request.state.user = public_user(row)
    return await call_next(request)


@app.exception_handler(ProviderError)
async def provider_error_handler(_request, exc: ProviderError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(ExtractionError)
async def extraction_error_handler(_request, exc: ExtractionError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


for router in (
    auth.router,
    users.router,
    games.router,
    campaigns.router,
    documents.router,
    search.router,
    providers.router,
    meta.router,
):
    app.include_router(router)


@app.get("/api", include_in_schema=False)
def api_root():
    return {"name": APP_NAME, "version": APP_VERSION, "docs": "/docs"}


if STATIC_DIR.exists():
    if (STATIC_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        resolved = (STATIC_DIR / full_path).resolve()
        root = STATIC_DIR.resolve()
        if full_path and resolved.is_file() and root in resolved.parents:
            return FileResponse(resolved)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404, "Frontend build not found.")

else:

    @app.get("/", include_in_schema=False)
    def dev_root():
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "message": "API is running. Start the frontend with `npm run dev` in ./frontend.",
            "docs": "/docs",
        }


def main() -> None:
    import uvicorn

    from app.config import HOST, PORT

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()

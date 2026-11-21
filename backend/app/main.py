"""FastAPI application factory."""
from __future__ import annotations

import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.db import init_db

logging.basicConfig(level=get_settings().LOG_LEVEL.upper(),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sap_impact")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        logger.info("startup complete (environment=%s)", settings.ENVIRONMENT)
        yield

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="SAP-LIKE simulation platform: change impact analysis and "
                    "regression risk for S/4HANA-like estates. No real SAP system.",
        docs_url="/docs",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _safe_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # never leak internals to clients; log server-side only (no secrets)
        logger.error("unhandled error on %s: %s", request.url.path, type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    from backend.app.api.routes_analyses import router as analyses_router
    from backend.app.api.routes_approvals import router as approvals_router
    from backend.app.api.routes_alm import router as alm_router
    from backend.app.api.routes_evaluation import router as eval_router
    from backend.app.api.routes_executions import router as executions_router
    from backend.app.api.routes_meta import router as meta_router
    from backend.app.api.routes_transports import router as transports_router

    app.include_router(meta_router)
    app.include_router(transports_router)
    app.include_router(analyses_router)
    app.include_router(approvals_router)
    app.include_router(executions_router)
    app.include_router(alm_router)
    app.include_router(eval_router)

    # static SPA mounted LAST so API routes win
    frontend_dir = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()

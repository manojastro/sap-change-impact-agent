"""Health, readiness and meta endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.models import (
    Analysis, ConfigItem, CustomCode, InterfaceDef, Process, SapTable,
    TestCase, Transport,
)
from backend.app.schemas import MetaOut

router = APIRouter()


def _counts(db: Session) -> dict:
    return {
        "processes": db.query(Process).count(),
        "custom_code": db.query(CustomCode).count(),
        "config_items": db.query(ConfigItem).count(),
        "tables": db.query(SapTable).count(),
        "interfaces": db.query(InterfaceDef).count(),
        "test_cases": db.query(TestCase).count(),
        "transports": db.query(Transport).count(),
        "analyses": db.query(Analysis).count(),
    }


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/readiness")
def readiness(db: Session = Depends(get_db)) -> dict:
    seeded = db.query(Process).count() > 0
    return {"status": "ready" if seeded else "not_seeded", "database": "ok", "seeded": seeded}


@router.get("/metrics")
def prometheus_metrics():
    from fastapi import Response

    from backend.app.metrics import render_metrics

    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@router.get("/api/v1/meta", response_model=MetaOut)
def meta(db: Session = Depends(get_db)) -> MetaOut:
    settings = get_settings()
    return MetaOut(
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        mock_mode=True,
        llm_mode="mock" if settings.is_mock_llm else settings.LLM_MODE,
        simulator="SAP-LIKE SIMULATION (synthetic data, no real SAP system or license)",
        counts=_counts(db),
    )

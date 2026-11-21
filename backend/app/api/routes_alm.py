"""SAP Cloud ALM mock endpoints (local tables; clearly labeled MOCK)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import (
    AlmDefect, AlmExecution, AlmFeature, AlmReleasePlan, AlmTask, AlmTestLink,
)
from backend.app.schemas import AlmFeatureIn, AlmFeatureOut, ReleasePlanOut
from backend.app.services.alm_service import get_alm_adapter

router = APIRouter(prefix="/api/v1/alm", tags=["alm-mock"])


@router.get("/info")
def alm_info() -> dict:
    return {
        "adapter": "LocalCloudAlmAdapter",
        "mock": True,
        "note": "LOCAL MOCK of SAP Cloud ALM backed by cloud_alm_* tables. "
                "Real integration left as documented interface (see ARCHITECTURE.md).",
    }


@router.post("/features", response_model=AlmFeatureOut, status_code=201)
def upsert_feature(payload: AlmFeatureIn, db: Session = Depends(get_db)) -> dict:
    adapter = get_alm_adapter(db)
    result = adapter.upsert_feature(payload.external_id, payload.name, payload.description)
    row = db.query(AlmFeature).filter_by(external_id=payload.external_id).first()
    return row


@router.get("/features", response_model=list[AlmFeatureOut])
def features(db: Session = Depends(get_db)) -> list[AlmFeature]:
    return db.query(AlmFeature).order_by(AlmFeature.id).all()


@router.get("/requirements")
def requirements(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AlmTask).order_by(AlmTask.id.desc()).limit(100).all()
    return [
        {"external_id": r.external_id, "title": r.title, "task_type": r.task_type,
         "transport_id": r.transport_id, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.get("/test-links")
def test_links(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AlmTestLink).limit(200).all()
    return [{"requirement": r.task_external_id, "test_code": r.test_code} for r in rows]


@router.get("/executions")
def executions(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AlmExecution).order_by(AlmExecution.id.desc()).limit(100).all()
    return [
        {"test_code": r.test_code, "status": r.status,
         "executed_at": r.executed_at.isoformat(), "details": r.details}
        for r in rows
    ]


@router.get("/defects")
def defects(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AlmDefect).order_by(AlmDefect.id.desc()).limit(100).all()
    return [
        {"external_id": r.external_id, "title": r.title, "severity": r.severity,
         "transport_id": r.transport_id, "test_code": r.test_code, "status": r.status}
        for r in rows
    ]


@router.post("/release-plan", response_model=ReleasePlanOut, status_code=201)
def export_release_plan(payload: ReleasePlanOut, db: Session = Depends(get_db)) -> dict:
    adapter = get_alm_adapter(db)
    adapter.export_release_plan(payload.release, payload.transport_ids)
    row = db.query(AlmReleasePlan).order_by(AlmReleasePlan.id.desc()).first()
    return row


@router.get("/release-plans", response_model=list[ReleasePlanOut])
def release_plans(db: Session = Depends(get_db)) -> list[AlmReleasePlan]:
    return db.query(AlmReleasePlan).order_by(AlmReleasePlan.id.desc()).limit(20).all()

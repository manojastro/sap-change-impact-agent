"""Release validation execution, results, defects and confidence trend."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Defect, TestExecutionRow, Transport, ValidationRun
from backend.app.schemas import (
    DefectOut, ExecuteValidationIn, TestExecutionOut, ValidationOut,
)
from backend.app.services.validation_service import run_validation_for_transport

router = APIRouter(prefix="/api/v1", tags=["validation"])


@router.post("/test-executions/run", response_model=ValidationOut, status_code=201)
def execute(payload: ExecuteValidationIn, db: Session = Depends(get_db)) -> dict:
    try:
        val = run_validation_for_transport(db, payload.transport_pk)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    execs = (
        db.query(TestExecutionRow).filter_by(validation_fk=val.id)
        .order_by(TestExecutionRow.id).all()
    )
    d = _val_dict(val)
    d["executions"] = [
        {"code": r.code, "criticality": r.criticality, "status": r.status,
         "duration_ms": r.duration_ms, "failure_reason": r.failure_reason}
        for r in execs
    ]
    return d


def _val_dict(val: ValidationRun) -> dict:
    return {
        "id": val.id, "transport_fk": val.transport_fk, "analysis_fk": val.analysis_fk,
        "status": val.status, "total": val.total, "passed": val.passed,
        "failed": val.failed, "pass_rate": val.pass_rate,
        "release_confidence": val.release_confidence,
    }


@router.get("/validations", response_model=list[ValidationOut])
def list_validations(transport_id: int | None = None,
                     db: Session = Depends(get_db)) -> list[dict]:
    q = db.query(ValidationRun).order_by(ValidationRun.id.desc())
    if transport_id is not None:
        q = q.filter_by(transport_fk=transport_id)
    result = []
    for v in q.limit(50).all():
        execs = db.query(TestExecutionRow).filter_by(validation_fk=v.id).all()
        d = _val_dict(v)
        d["executions"] = [
            {"code": r.code, "criticality": r.criticality, "status": r.status,
             "duration_ms": r.duration_ms, "failure_reason": r.failure_reason}
            for r in execs
        ]
        result.append(d)
    return result


@router.get("/test-executions", response_model=list[TestExecutionOut])
def test_executions(validation_id: int | None = None,
                    db: Session = Depends(get_db)) -> list[TestExecutionRow]:
    q = db.query(TestExecutionRow).order_by(TestExecutionRow.id.desc())
    if validation_id is not None:
        q = q.filter_by(validation_fk=validation_id)
    return q.limit(200).all()


@router.get("/defects", response_model=list[DefectOut])
def defects(db: Session = Depends(get_db)) -> list[Defect]:
    return db.query(Defect).order_by(Defect.id.desc()).limit(100).all()


@router.get("/release-confidence")
def release_confidence_trend(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(ValidationRun)
        .filter_by(status="COMPLETED")
        .order_by(ValidationRun.id)
        .limit(50)
        .all()
    )
    points = []
    for v in rows:
        tr = db.get(Transport, v.transport_fk)
        points.append({
            "validation_id": v.id,
            "transport_id": tr.transport_id if tr else str(v.transport_fk),
            "release_confidence": v.release_confidence,
            "pass_rate": v.pass_rate,
            "failed": v.failed,
            "finished_at": v.finished_at.isoformat() if v.finished_at else None,
        })
    latest = points[-1]["release_confidence"] if points else None
    return {"trend": points, "latest": latest}

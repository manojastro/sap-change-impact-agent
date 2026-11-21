"""Evaluation + simulator + business metrics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import EvaluationRunRow, MetricSnapshot
from backend.app.schemas import EvaluationRunOut, SeedOut
from backend.app.services.evaluation_service import latest_evaluation, run_evaluation

router = APIRouter(prefix="/api/v1", tags=["evaluation"])


@router.post("/simulator/seed", response_model=SeedOut)
def simulator_seed(db: Session = Depends(get_db)) -> dict:
    from simulator.generate_landscape import SIMULATION_LABEL, seed_landscape

    counts = seed_landscape(db)
    return {"seeded": True, "counts": counts, "mode": SIMULATION_LABEL}


@router.post("/evaluation/run", response_model=EvaluationRunOut, status_code=201)
def evaluation_run(db: Session = Depends(get_db)) -> EvaluationRunRow:
    return run_evaluation(db)


@router.get("/evaluation/runs", response_model=list[EvaluationRunOut])
def evaluation_runs(db: Session = Depends(get_db)) -> list[EvaluationRunRow]:
    return db.query(EvaluationRunRow).order_by(EvaluationRunRow.id.desc()).limit(20).all()


@router.get("/evaluation/latest", response_model=EvaluationRunOut | None)
def evaluation_latest(db: Session = Depends(get_db)) -> EvaluationRunRow | None:
    return latest_evaluation(db)


@router.get("/business-metrics")
def business_metrics(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(MetricSnapshot)
        .order_by(MetricSnapshot.id.desc())
        .limit(200)
        .all()
    )
    latest: dict[str, dict] = {}
    for r in rows:
        if r.name not in latest:
            latest[r.name] = {
                "value": r.value,
                "captured_at": r.captured_at.isoformat() if r.captured_at else None,
            }
    history = {
        "release_confidence_trend": [
            {"name": r.name, "value": r.value} for r in rows if r.name == "defect_catch_count"
        ][:20],
    }
    return {"latest": latest, "history": history}

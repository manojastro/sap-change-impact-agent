"""Analyses: start, status, stages, impact results, selections, risk, graph."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.background import BackgroundTasks
from sqlalchemy.orm import Session

from backend.app.db import get_db, get_session_factory
from backend.app.graph.dependency_graph import DependencyGraph
from backend.app.models import (
    Analysis, ImpactResult, RiskAssessment, StageRun, TestSelection, Transport,
)
from backend.app.schemas import (
    AnalysisCreate, AnalysisOut, ImpactResultOut, RiskAssessmentOut,
    StageRunOut, TestSelectionOut,
)
from backend.app.workflow.engine import run_analysis, start_analysis

router = APIRouter(prefix="/api/v1", tags=["analyses"])


def _run_in_background(analysis_pk: int) -> None:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        run_analysis(db, analysis_pk)
    finally:
        db.close()


@router.post("/analyses", response_model=AnalysisOut, status_code=202)
def start(payload: AnalysisCreate, background: BackgroundTasks,
          db: Session = Depends(get_db)) -> Analysis:
    try:
        analysis = start_analysis(db, payload.transport_id_ref)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if payload.wait:
        run_analysis(db, analysis.id)  # synchronous for tests/scripts
        db.refresh(analysis)
    else:
        background.add_task(_run_in_background, analysis.id)
    return analysis


@router.get("/analyses", response_model=list[AnalysisOut])
def list_analyses(db: Session = Depends(get_db)) -> list[Analysis]:
    return db.query(Analysis).order_by(Analysis.id.desc()).limit(50).all()


@router.get("/analyses/{analysis_pk}", response_model=AnalysisOut)
def get_analysis(analysis_pk: int, db: Session = Depends(get_db)) -> Analysis:
    a = db.get(Analysis, analysis_pk)
    if a is None:
        raise HTTPException(404, "analysis not found")
    return a


@router.get("/analyses/{analysis_pk}/stages", response_model=list[StageRunOut])
def analysis_stages(analysis_pk: int, db: Session = Depends(get_db)) -> list[StageRun]:
    a = db.get(Analysis, analysis_pk)
    if a is None:
        raise HTTPException(404, "analysis not found")
    return db.query(StageRun).filter_by(analysis_fk=analysis_pk).order_by(StageRun.sequence).all()


@router.get("/impact-results", response_model=list[ImpactResultOut])
def impact_results(
    analysis_id: int | None = None,
    node_type: str | None = None,
    db: Session = Depends(get_db),
) -> list[ImpactResult]:
    q = db.query(ImpactResult)
    if analysis_id is None:
        latest = db.query(Analysis).order_by(Analysis.id.desc()).first()
        if latest is None:
            return []
        analysis_id = latest.id
    q = q.filter_by(analysis_fk=analysis_id)
    if node_type:
        q = q.filter_by(node_type=node_type)
    return q.order_by(ImpactResult.distance).all()


@router.get("/test-selections", response_model=list[TestSelectionOut])
def test_selections(
    analysis_id: int | None = None,
    included_only: bool = True,
    db: Session = Depends(get_db),
) -> list[TestSelection]:
    q = db.query(TestSelection)
    if analysis_id is None:
        latest = db.query(Analysis).order_by(Analysis.id.desc()).first()
        if latest is None:
            return []
        analysis_id = latest.id
    q = q.filter_by(analysis_fk=analysis_id)
    if included_only:
        q = q.filter_by(included=True)
    return q.order_by(TestSelection.rank).all()


@router.get("/risk-assessments", response_model=list[RiskAssessmentOut])
def risk_assessments(
    analysis_id: int | None = None,
    transport_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[RiskAssessment]:
    q = db.query(RiskAssessment)
    if analysis_id is not None:
        q = q.filter_by(analysis_fk=analysis_id)
    elif transport_id is not None:
        q = q.filter_by(transport_fk=transport_id)
    return q.order_by(RiskAssessment.id.desc()).limit(50).all()


@router.get("/graph")
def dependency_graph_endpoint(
    analysis_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Subgraph around the impacted nodes (or the whole estate when no analysis)."""
    if analysis_id is None:
        latest = db.query(Analysis).order_by(Analysis.id.desc()).first()
        analysis_id = latest.id if latest else None

    graph = DependencyGraph.from_session(db)
    if analysis_id is None:
        keys = sorted(graph.g.nodes)
    else:
        rows = db.query(ImpactResult).filter_by(analysis_fk=analysis_id).all()
        impacted = {r.node_key for r in rows}
        # include direct neighbourhood for context
        keys = set()
        for k in impacted:
            if graph.g.has_node(k):
                keys.add(k)
                keys.update(graph.g.predecessors(k))
                keys.update(graph.g.successors(k))
        keys = sorted(keys) or sorted(graph.g.nodes)
    view = graph.subgraph_view(keys)
    impacted_map = {}
    if analysis_id is not None:
        for r in db.query(ImpactResult).filter_by(analysis_fk=analysis_id).all():
            impacted_map[r.node_key] = {
                "distance": r.distance, "confidence": r.confidence,
                "discovered_by": r.discovered_by,
            }
    view["impacted"] = impacted_map
    view["analysis_id"] = analysis_id
    return view


@router.get("/transports-by-key/{transport_key}")
def transport_lookup(transport_key: str, db: Session = Depends(get_db)) -> dict:
    tr = db.query(Transport).filter_by(transport_id=transport_key).first()
    if tr is None:
        raise HTTPException(404, "transport not found")
    latest = (
        db.query(Analysis).filter_by(transport_fk=tr.id)
        .order_by(Analysis.id.desc()).first()
    )
    return {"id": tr.id, "transport_id": tr.transport_id, "status": tr.status,
            "latest_analysis_id": latest.id if latest else None}

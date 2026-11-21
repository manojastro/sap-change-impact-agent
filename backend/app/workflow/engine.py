"""Persisted workflow engine - the agentic analysis pipeline.

LangGraph mapping (documented; the production port would use langgraph):
    AnalysisState   = TypedDict(transport, seeds, closure, per-stage outputs)
    node(stage)     = each agent below is a stateless node fn(ctx)->StageOutput
    edges           = linear chain transport_analysis -> ... -> validation_readiness
    conditional edge= after `risk`, route to an approval-gate node when
                      decision.requires_approval else straight to readiness.
The local engine keeps every stage transition in the DB (stage_runs), which is
what the UI polls and what makes runs replayable/auditable.

LLM boundary: agents call tools for facts and use the LLM provider ONLY to
phrase rationales from those facts (mock = deterministic).
"""
from __future__ import annotations

import datetime as dt
import time
import traceback

from sqlalchemy.orm import Session

from backend.app import metrics
from backend.app.agents.base import AgentContext
from backend.app.agents.business_process import BusinessProcessAgent
from backend.app.agents.configuration import ConfigurationAgent
from backend.app.agents.custom_code import CustomCodeAgent
from backend.app.agents.interface_impact import InterfaceImpactAgent
from backend.app.agents.regression_scope import RegressionScopeAgent
from backend.app.agents.risk import RiskAgent
from backend.app.agents.transport_analysis import TransportAnalysisAgent
from backend.app.agents.validation import ValidationAgent
from backend.app.config import get_settings
from backend.app.graph.dependency_graph import DependencyGraph
from backend.app.llm.provider import get_llm_provider
from backend.app.models import (
    ActionRow, Analysis, EventRow, EvidenceRow, HypothesisRow, StageRun,
)
from backend.app.tools.sap_tools import build_registry, resolve_transport_object

STAGES: list[tuple[str, type]] = [
    ("transport_analysis", TransportAnalysisAgent),
    ("custom_code", CustomCodeAgent),
    ("configuration", ConfigurationAgent),
    ("business_process", BusinessProcessAgent),
    ("interface_impact", InterfaceImpactAgent),
    ("regression_scope", RegressionScopeAgent),
    ("risk", RiskAgent),
    ("validation_readiness", ValidationAgent),
]


def start_analysis(db: Session, transport_pk: int) -> Analysis:
    from backend.app.models import Transport

    tr = db.get(Transport, int(transport_pk))
    if tr is None:
        raise LookupError(f"transport {transport_pk} not found")
    if tr.status == "BLOCKED":
        raise ValueError("transport is BLOCKED; new analysis not allowed until unblocked")
    analysis = Analysis(transport_fk=tr.id, status="QUEUED",
                        started_at=dt.datetime.now(dt.timezone.utc), params={})
    db.add(analysis)
    db.add(EventRow(kind="ANALYSIS_QUEUED", ref_type="TRANSPORT", ref_id=tr.id,
                    message=f"Analysis queued for {tr.transport_id}"))
    db.commit()
    return analysis


def run_analysis(db: Session, analysis_id: int) -> None:
    """Execute all stages synchronously on the given session."""
    analysis = db.get(Analysis, int(analysis_id))
    if analysis is None:
        raise LookupError(f"analysis {analysis_id} not found")
    transport = analysis.transport
    t_start = time.perf_counter()
    analysis.status = "RUNNING"
    db.commit()

    graph = DependencyGraph.from_session(db)
    seeds: list[tuple[str, bool]] = []
    for obj in transport.objects:
        seeds.extend(resolve_transport_object(db, obj))
    # dedupe keeping order
    seen = set()
    seeds = [s for s in seeds if not (s[0] in seen or seen.add(s[0]))]
    closure = graph.impacted_closure(seeds)

    ctx = AgentContext(
        db=db,
        llm=get_llm_provider(get_settings()),
        tools=build_registry(db, graph=graph, analysis_id=analysis.id),
        graph=graph,
        analysis_id=analysis.id,
        transport=transport,
        seeds=seeds,
        closure=closure,
        settings=get_settings(),
    )

    try:
        for seq, (stage_name, agent_cls) in enumerate(STAGES, start=1):
            agent = agent_cls()
            stage_run = StageRun(analysis_fk=analysis.id, stage=stage_name,
                                 sequence=seq, status="RUNNING",
                                 started_at=dt.datetime.now(dt.timezone.utc))
            db.add(stage_run)
            analysis.current_stage = stage_name
            db.commit()

            t0 = time.perf_counter()
            out = agent.run(ctx)
            duration_ms = (time.perf_counter() - t0) * 1000.0

            evidence_ids: list[int] = []
            for ev in out.evidence:
                row = EvidenceRow(
                    analysis_fk=analysis.id, stage=stage_name,
                    source=ev["source"], timestamp=dt.datetime.now(dt.timezone.utc),
                    fact=ev["fact"], reliability=ev.get("reliability", 0.9),
                    raw_reference=ev.get("raw_reference", ""),
                )
                db.add(row)
                db.flush()
                evidence_ids.append(row.id)
            for hyp in out.hypotheses:
                db.add(HypothesisRow(
                    analysis_fk=analysis.id, stage=stage_name,
                    statement=hyp.get("statement", ""),
                    status=hyp.get("status", "CONFIRMED"),
                    confidence=hyp.get("confidence", 0.8),
                ))
            for act in out.actions:
                db.add(ActionRow(
                    analysis_fk=analysis.id, stage=stage_name,
                    action=act.get("action", ""), input_json=act.get("input_json", {}),
                    result_summary=act.get("result_summary", ""),
                ))

            decision = dict(out.decision)
            decision["evidence_ids"] = evidence_ids
            stage_run.status = "DONE"
            stage_run.finished_at = dt.datetime.now(dt.timezone.utc)
            stage_run.duration_ms = duration_ms
            stage_run.output = {"decision": decision, "output": out.output}
            metrics.observe_stage(stage_name, duration_ms / 1000.0)
            db.commit()

        analysis.status = "COMPLETED"
        analysis.current_stage = "done"
        transport.status = "ANALYZED" if transport.status in ("IMPORTED",) else transport.status
        db.commit()
        _snapshot_analysis_metrics(db, duration_ms=(time.perf_counter() - t_start) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        analysis.status = "FAILED"
        analysis.error = f"{type(exc).__name__}: {exc}"
        analysis.current_stage = "failed"
        failing = (
            db.query(StageRun)
            .filter_by(analysis_fk=analysis.id, status="RUNNING").first()
        )
        if failing is not None:
            failing.status = "FAILED"
            failing.finished_at = dt.datetime.now(dt.timezone.utc)
            failing.output = {"error": traceback.format_exc()[-2000:]}
        db.commit()
        raise
    finally:
        analysis.duration_ms = (time.perf_counter() - t_start) * 1000.0
        finished = dt.datetime.now(dt.timezone.utc)
        analysis.finished_at = finished
        db.commit()


def _snapshot_analysis_metrics(db: Session, duration_ms: float) -> None:
    from backend.app.models import RiskAssessment, TestCase, TestSelection

    metrics.ANALYSES_TOTAL.labels(status="COMPLETED").inc()
    total_tests = db.query(TestCase).count()
    selected_rows = db.query(TestSelection).filter_by(included=True).all()
    if total_tests and selected_rows:
        # scope reduction: selected/total averaged over analyses that have selections
        per_analysis: dict[int, int] = {}
        for r in selected_rows:
            per_analysis[r.analysis_fk] = per_analysis.get(r.analysis_fk, 0) + 1
        ratios = [n / total_tests for n in per_analysis.values()] or [0.0]
        metrics.persist_snapshot(db, "scope_reduction_ratio", round(sum(ratios) / len(ratios), 4))
    durations = list(db.query(Analysis.duration_ms).filter_by(status="COMPLETED").all())
    if durations:
        avg = sum((x[0] or 0) for x in durations) / len(durations)
        metrics.persist_snapshot(db, "avg_analysis_duration_ms", round(avg, 1))
    high = db.query(RiskAssessment).filter(RiskAssessment.band.in_(["HIGH", "CRITICAL"])).count()
    tot = db.query(RiskAssessment).count()
    if tot:
        metrics.persist_snapshot(db, "risk_high_critical_ratio", round(high / tot, 4))

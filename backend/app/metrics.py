"""Prometheus metrics + persisted business metric snapshots."""
from __future__ import annotations

import datetime as dt

from prometheus_client import (
    CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest,
)
from sqlalchemy.orm import Session

from backend.app.models import MetricSnapshot

REGISTRY = CollectorRegistry(auto_describe=True)

STAGE_LATENCY = Histogram(
    "sap_impact_stage_latency_seconds", "Workflow stage latency",
    labelnames=["stage"], registry=REGISTRY,
)
TOOL_LATENCY = Histogram(
    "sap_impact_tool_latency_seconds", "Tool execution latency",
    labelnames=["tool"], registry=REGISTRY,
)
LLM_LATENCY = Histogram(
    "sap_impact_llm_latency_seconds", "LLM (mock) call latency",
    labelnames=["provider"], registry=REGISTRY,
)
ANALYSES_TOTAL = Counter(
    "sap_impact_analyses_total", "Completed analyses by status",
    labelnames=["status"], registry=REGISTRY,
)
DEFECTS_CAUGHT = Counter(
    "sap_impact_defects_caught_total", "Defects raised by pre-release validation",
    registry=REGISTRY,
)
APPROVALS_TOTAL = Counter(
    "sap_impact_approvals_total", "Approval decisions",
    labelnames=["decision"], registry=REGISTRY,
)

BUSINESS_GAUGES = {
    name: Gauge(f"sap_impact_{name}", desc, registry=REGISTRY)
    for name, desc in [
        ("eval_process_recall", "Latest eval: impacted-process recall"),
        ("eval_process_precision", "Latest eval: impacted-process precision"),
        ("eval_interface_recall", "Latest eval: impacted-interface recall"),
        ("eval_interface_precision", "Latest eval: impacted-interface precision"),
        ("eval_test_recall", "Latest eval: regression test selection recall"),
        ("eval_test_precision", "Latest eval: regression test selection precision"),
        ("scope_reduction_ratio", "Selected tests vs total tests (latest analyses)"),
        ("avg_analysis_duration_ms", "Average analysis duration ms"),
        ("approval_turnaround_minutes", "Average approval turnaround minutes"),
        ("defect_catch_count", "Cumulative defects caught pre-release"),
        ("risk_high_critical_ratio", "Share of assessments rated HIGH or CRITICAL"),
    ]
}


def observe_stage(stage: str, seconds: float) -> None:
    STAGE_LATENCY.labels(stage=stage).observe(seconds)


def observe_tool(tool: str, seconds: float) -> None:
    TOOL_LATENCY.labels(tool=tool).observe(seconds)


def observe_llm(provider: str, seconds: float) -> None:
    LLM_LATENCY.labels(provider=provider).observe(seconds)


def persist_snapshot(db: Session, name: str, value: float, meta: dict | None = None) -> None:
    db.add(MetricSnapshot(name=name, value=float(value), meta=meta or {}, captured_at=dt.datetime.now(dt.timezone.utc)))
    gauge = BUSINESS_GAUGES.get(name)
    if gauge is not None:
        gauge.set(float(value))


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST

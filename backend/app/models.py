"""Persistence model for the SAP-LIKE change impact platform.

All entities describe a *simulated* SAP S/4HANA-like estate. Naming is
SAP-flavored but clearly synthetic (no real SAP objects are used).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ------------------------------------------------------------------ landscape

class Process(Base):
    __tablename__ = "processes"
    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False)   # ORDER_TO_CASH ...
    name = Column(String(128), nullable=False)
    module = Column(String(16), nullable=False)              # SD/MM/FI/HR
    criticality = Column(String(16), nullable=False)         # CRITICAL/HIGH/MEDIUM/LOW
    description = Column(Text, default="")
    owner = Column(String(64), default="")


class ProcessStep(Base):
    __tablename__ = "process_steps"
    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False)
    process_id = Column(Integer, ForeignKey("processes.id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    process = relationship("Process")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)   # SO_CREATE ...
    name = Column(String(128), nullable=False)
    module = Column(String(16), default="")
    description = Column(Text, default="")


class FioriApp(Base):
    __tablename__ = "fiori_apps"
    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")


class CustomCode(Base):
    __tablename__ = "custom_code"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)   # Z_PRICING_DETERMINATION_EXIT
    code_type = Column(String(24), nullable=False)           # USER_EXIT/BADI/REPORT/WORKFLOW/PROGRAM
    package = Column(String(32), default="Z_IMPACT")
    description = Column(Text, default="")
    owner = Column(String(64), default="")


class ConfigItem(Base):
    __tablename__ = "config_items"
    id = Column(Integer, primary_key=True)
    key = Column(String(96), unique=True, nullable=False)    # PRICING_COND_TYPE_ZPR0
    category = Column(String(32), nullable=False)            # PRICING/OUTPUT/POSTING_KEY/...
    value = Column(String(256), default="")
    value_flow = Column(Boolean, default=False, nullable=False)  # does it drive monetary values?
    description = Column(Text, default="")


class SapTable(Base):
    __tablename__ = "tables"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)   # sales_orders ...
    module = Column(String(16), default="")
    value_flow = Column(Boolean, default=False, nullable=False)  # carries money/qty consumed downstream?
    description = Column(Text, default="")


class TableField(Base):
    __tablename__ = "table_fields"
    id = Column(Integer, primary_key=True)
    table_id = Column(Integer, ForeignKey("tables.id"), nullable=False)
    name = Column(String(64), nullable=False)
    description = Column(Text, default="")
    table = relationship("SapTable")
    __table_args__ = (UniqueConstraint("table_id", "name", name="uq_table_field"),)


class InterfaceDef(Base):
    __tablename__ = "interfaces"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)   # ORDERS_OUT / API_SALES_ORDER_SRV
    direction = Column(String(16), nullable=False)           # INBOUND/OUTBOUND
    kind = Column(String(16), nullable=False)                # IDOC_LIKE/ODATA_LIKE
    partner = Column(String(64), default="")
    description = Column(Text, default="")


class BatchJob(Base):
    __tablename__ = "batch_jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String(96), unique=True, nullable=False)
    schedule = Column(String(64), default="NIGHTLY")
    description = Column(Text, default="")


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(96), unique=True, nullable=False)
    profile = Column(String(96), default="")
    description = Column(Text, default="")


class TestCase(Base):
    __tablename__ = "test_cases"
    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False)   # BILLING_CREATE_TEST
    name = Column(String(128), nullable=False)
    process_id = Column(Integer, ForeignKey("processes.id"), nullable=True)
    criticality = Column(String(16), nullable=False)
    kind = Column(String(24), default="FUNCTIONAL")          # FUNCTIONAL/INTERFACE/RECONCILIATION/API
    historical_runs = Column(Integer, default=0, nullable=False)
    historical_failures = Column(Integer, default=0, nullable=False)
    last_status = Column(String(16), default="PASS")
    avg_duration_s = Column(Float, default=12.0)
    description = Column(Text, default="")
    process = relationship("Process")

    @property
    def defect_rate(self) -> float:
        if not self.historical_runs:
            return 0.0
        return self.historical_failures / float(self.historical_runs)


class DefectSeed(Base):
    """Seeded known defects: the deterministic outcome source for the validation
    simulation (scenario_tag + test_code -> failure)."""
    __tablename__ = "defect_seeds"
    id = Column(Integer, primary_key=True)
    scenario_tag = Column(String(64), nullable=False, index=True)
    test_code = Column(String(64), nullable=False)
    failure_reason = Column(Text, nullable=False)
    severity = Column(String(16), default="HIGH")


# ------------------------------------------------------------------ transports

TRANSPORT_STATUSES = [
    "IMPORTED", "ANALYZED", "AWAITING_APPROVAL", "APPROVED",
    "BLOCKED", "VALIDATION_PASSED", "VALIDATION_FAILED",
]
CHANGE_TYPES = [
    "ABAP_CHANGE", "CONFIG_CHANGE", "PRICING_CHANGE", "TABLE_FIELD_CHANGE",
    "ODATA_CHANGE", "ROLE_CHANGE", "WORKFLOW_CHANGE", "INTERFACE_CHANGE",
    "FIORI_APP_CHANGE",
]

class Transport(Base):
    __tablename__ = "transports"
    id = Column(Integer, primary_key=True)
    transport_id = Column(String(32), unique=True, nullable=False)  # SIMK900001
    title = Column(String(200), nullable=False)
    kind = Column(String(16), nullable=False, default="WORKBENCH")  # WORKBENCH/CUSTOMIZING
    change_type = Column(String(32), nullable=False)
    scenario_tag = Column(String(64), default="", index=True)       # links to defect seeds / ground truth
    status = Column(String(32), nullable=False, default="IMPORTED")
    source_system = Column(String(32), default="SIM-DEV-100")
    target_release = Column(String(32), default="REL-2026.09")
    blocked_reason = Column(Text, default="")
    size_bucket = Column(String(16), default="SMALL")               # SMALL/MEDIUM/LARGE
    objects_changed = Column(Integer, default=0)
    config_changes = Column(Integer, default=0)
    loc_delta = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    objects = relationship("TransportObject", cascade="all, delete-orphan")


class TransportObject(Base):
    __tablename__ = "transport_objects"
    id = Column(Integer, primary_key=True)
    transport_fk = Column(Integer, ForeignKey("transports.id"), nullable=False, index=True)
    object_type = Column(String(24), nullable=False)
    # TABLE | TABLE_FIELD | CUSTOM_CODE | CONFIG_ITEM | ROLE | ODATA_SPEC |
    # FIORI_APP | INTERFACE_DEF | WORKFLOW
    object_key = Column(String(96), nullable=False)
    field_name = Column(String(64), default="")
    change_action = Column(String(16), default="MODIFY")     # MODIFY/INSERT/DELETE
    value_affecting = Column(Boolean, default=True, nullable=False)
    details = Column(JSON, default=dict)
    transport = relationship("Transport", back_populates="objects")


# ------------------------------------------------------------------ graph

class GraphEdgeRow(Base):
    """Stored with natural orientation (SUBJECT_VERB_OBJECT). Impact direction
    is derived per edge type in app.graph.dependency_graph."""
    __tablename__ = "graph_edges"
    id = Column(Integer, primary_key=True)
    edge_type = Column(String(48), nullable=False, index=True)
    src_type = Column(String(24), nullable=False)
    src_id = Column(Integer, nullable=False)
    dst_type = Column(String(24), nullable=False)
    dst_id = Column(Integer, nullable=False)


# ------------------------------------------------------------------ events / audit

class EventRow(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), default=utcnow)
    kind = Column(String(48), nullable=False)
    ref_type = Column(String(32), default="")
    ref_id = Column(Integer, default=0)
    message = Column(Text, default="")


class ToolCallRow(Base):
    __tablename__ = "tool_calls"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), default=utcnow)
    tool = Column(String(64), nullable=False)
    input_json = Column(JSON, default=dict)
    output_json = Column(JSON, default=dict)
    ok = Column(Boolean, default=True)
    duration_ms = Column(Float, default=0.0)
    analysis_id = Column(Integer, default=0, index=True)


# ------------------------------------------------------------------ analyses (investigations)

class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True)
    transport_fk = Column(Integer, ForeignKey("transports.id"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="QUEUED")  # QUEUED/RUNNING/COMPLETED/FAILED
    current_stage = Column(String(48), default="")
    started_at = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, default=0.0)
    error = Column(Text, default="")
    params = Column(JSON, default=dict)
    transport = relationship("Transport")


class StageRun(Base):
    __tablename__ = "stage_runs"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    stage = Column(String(48), nullable=False)
    sequence = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="PENDING")  # PENDING/RUNNING/DONE/FAILED/SKIPPED
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, default=0.0)
    output = Column(JSON, default=dict)
    decision_id = Column(Integer, default=0)
    analysis = relationship("Analysis")


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, default=0, index=True)
    stage = Column(String(48), default="")
    source = Column(String(128), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utcnow)
    fact = Column(Text, nullable=False)
    reliability = Column(Float, default=0.9)
    raw_reference = Column(String(256), default="")


class HypothesisRow(Base):
    __tablename__ = "hypotheses"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, default=0, index=True)
    stage = Column(String(48), default="")
    statement = Column(Text, nullable=False)
    status = Column(String(16), default="CONFIRMED")  # CONFIRMED/REJECTED/OPEN
    confidence = Column(Float, default=0.8)


class ActionRow(Base):
    __tablename__ = "actions"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, default=0, index=True)
    stage = Column(String(48), default="")
    action = Column(String(96), nullable=False)
    input_json = Column(JSON, default=dict)
    result_summary = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ImpactResult(Base):
    __tablename__ = "impact_results"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, nullable=False, index=True)
    node_type = Column(String(24), nullable=False)
    node_id = Column(Integer, nullable=False)
    node_key = Column(String(64), nullable=False)     # e.g. TRANSACTION:12
    name = Column(String(128), nullable=False)
    distance = Column(Integer, default=0)
    discovered_by = Column(String(16), default="TRAVERSED")  # DIRECT/TRAVERSED
    confidence = Column(Float, default=1.0)
    path_json = Column(JSON, default=list)


class TestSelection(Base):
    __tablename__ = "test_selections"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, nullable=False, index=True)
    test_case_id = Column(Integer, nullable=False)
    code = Column(String(64), nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Float, default=0.0)
    reason = Column(Text, default="")
    included = Column(Boolean, default=True)
    excluded_reason = Column(Text, default="")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, nullable=False, index=True)
    transport_fk = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)             # 0..100
    band = Column(String(16), nullable=False)         # LOW/MEDIUM/HIGH/CRITICAL
    factor_breakdown = Column(JSON, default=dict)     # component -> {weight, raw, contribution}
    rationale = Column(Text, default="")
    requires_approval = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id = Column(Integer, primary_key=True)
    transport_fk = Column(Integer, nullable=False, index=True)
    risk_assessment_id = Column(Integer, default=0)
    status = Column(String(16), nullable=False, default="PENDING")  # PENDING/APPROVED/REJECTED
    approver = Column(String(64), default="")
    comment = Column(Text, default="")
    requested_at = Column(DateTime(timezone=True), default=utcnow)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    turnaround_minutes = Column(Float, default=0.0)


# ------------------------------------------------------------------ validation simulation

class ValidationRun(Base):
    __tablename__ = "validations"
    id = Column(Integer, primary_key=True)
    transport_fk = Column(Integer, nullable=False, index=True)
    analysis_fk = Column(Integer, default=0)
    status = Column(String(16), default="COMPLETED")
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    pass_rate = Column(Float, default=0.0)
    release_confidence = Column(Float, default=0.0)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class TestExecutionRow(Base):
    __tablename__ = "test_executions"
    id = Column(Integer, primary_key=True)
    validation_fk = Column(Integer, nullable=False, index=True)
    test_case_id = Column(Integer, nullable=False)
    code = Column(String(64), nullable=False)
    criticality = Column(String(16), default="MEDIUM")
    status = Column(String(16), nullable=False)      # PASSED/FAILED/SKIPPED
    duration_ms = Column(Float, default=0.0)
    failure_reason = Column(Text, default="")


class OutcomeRow(Base):
    """Prediction vs simulated reality for each selected test."""
    __tablename__ = "outcomes"
    id = Column(Integer, primary_key=True)
    analysis_fk = Column(Integer, default=0, index=True)
    validation_fk = Column(Integer, default=0)
    test_code = Column(String(64), default="")
    predicted_selected = Column(Boolean, default=True)
    actual_result = Column(String(16), default="PASS")
    matched_expectation = Column(Boolean, default=True)
    notes = Column(Text, default="")


class Defect(Base):
    __tablename__ = "defects"
    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)   # DEF-0001
    transport_fk = Column(Integer, default=0, index=True)
    validation_fk = Column(Integer, default=0)
    test_execution_id = Column(Integer, default=0)
    title = Column(Text, nullable=False)
    severity = Column(String(16), default="HIGH")
    status = Column(String(16), default="OPEN")
    raised_at = Column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------ SAP Cloud ALM mock store

class AlmFeature(Base):
    __tablename__ = "cloud_alm_features"
    id = Column(Integer, primary_key=True)
    external_id = Column(String(64), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AlmTask(Base):
    __tablename__ = "cloud_alm_tasks"
    id = Column(Integer, primary_key=True)
    feature_id = Column(Integer, default=0)
    external_id = Column(String(64), unique=True, nullable=False)
    title = Column(String(200), nullable=False)
    task_type = Column(String(24), default="REQUIREMENT")
    transport_id = Column(String(32), default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AlmTestLink(Base):
    __tablename__ = "cloud_alm_test_links"
    id = Column(Integer, primary_key=True)
    task_external_id = Column(String(64), default="")
    test_code = Column(String(64), default="")


class AlmExecution(Base):
    __tablename__ = "cloud_alm_executions"
    id = Column(Integer, primary_key=True)
    test_code = Column(String(64), default="")
    status = Column(String(16), default="PASS")
    executed_at = Column(DateTime(timezone=True), default=utcnow)
    details = Column(JSON, default=dict)


class AlmDefect(Base):
    __tablename__ = "cloud_alm_defects"
    id = Column(Integer, primary_key=True)
    external_id = Column(String(64), unique=True, nullable=False)
    title = Column(Text, default="")
    severity = Column(String(16), default="HIGH")
    transport_id = Column(String(32), default="")
    test_code = Column(String(64), default="")
    status = Column(String(16), default="OPEN")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AlmReleasePlan(Base):
    __tablename__ = "cloud_alm_release_plans"
    id = Column(Integer, primary_key=True)
    release = Column(String(32), nullable=False)
    transport_ids = Column(JSON, default=list)
    exported_at = Column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------ metrics & evaluation

class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    id = Column(Integer, primary_key=True)
    captured_at = Column(DateTime(timezone=True), default=utcnow)
    name = Column(String(64), nullable=False, index=True)
    value = Column(Float, nullable=False)
    meta = Column(JSON, default=dict)


class EvaluationRunRow(Base):
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    transport_count = Column(Integer, default=0)
    impact_process_recall = Column(Float, default=0.0)
    impact_process_precision = Column(Float, default=0.0)
    impact_interface_recall = Column(Float, default=0.0)
    impact_interface_precision = Column(Float, default=0.0)
    test_selection_recall = Column(Float, default=0.0)
    test_selection_precision = Column(Float, default=0.0)
    false_positive_tests = Column(Integer, default=0)
    risk_accuracy = Column(Float, default=0.0)
    missed_critical = Column(Integer, default=0)
    details = Column(JSON, default=dict)

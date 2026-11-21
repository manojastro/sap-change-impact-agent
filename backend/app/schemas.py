"""Pydantic v2 API schemas."""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- core agent contracts


class Evidence(BaseModel):
    """A verifiable fact an agent decision rests on."""
    source: str = Field(..., description="e.g. graph:CONFIG_USED_BY_TRANSACTION")
    timestamp: dt.datetime = Field(default_factory=dt.datetime.now)
    fact: str
    reliability: float = Field(0.9, ge=0.0, le=1.0)
    raw_reference: str = ""


class Decision(BaseModel):
    """Structured decision emitted by a workflow stage."""
    decision: str
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    evidence_ids: list[int] = []
    alternatives: list[str] = []
    risk_level: str = "NONE"           # NONE/LOW/MEDIUM/HIGH/CRITICAL
    requires_approval: bool = False


# ---------------------------------------------------------------- transports


class TransportObjectIn(BaseModel):
    object_type: Literal[
        "TABLE", "TABLE_FIELD", "CUSTOM_CODE", "CONFIG_ITEM", "ROLE",
        "ODATA_SPEC", "FIORI_APP", "INTERFACE_DEF", "WORKFLOW",
    ]
    object_key: str = Field(..., min_length=2, max_length=96)
    field_name: str = ""
    change_action: Literal["MODIFY", "INSERT", "DELETE"] = "MODIFY"
    value_affecting: bool = True
    details: dict = {}


class TransportIn(BaseModel):
    transport_id: str = Field(..., pattern=r"^[A-Z0-9K]{6,20}$|^[A-Za-z0-9_\-]{4,32}$", min_length=4, max_length=32,
                              description="Synthetic transport id, e.g. SIMK900001")
    title: str = Field(..., min_length=3, max_length=200)
    kind: Literal["WORKBENCH", "CUSTOMIZING"] = "WORKBENCH"
    change_type: str = Field("ABAP_CHANGE")
    scenario_tag: str = ""
    source_system: str = "SIM-DEV-100"
    target_release: str = "REL-2026.09"
    loc_delta: int = Field(0, ge=0, le=1_000_000)
    objects: list[TransportObjectIn] = Field(..., min_length=1)

    model_config = {"json_schema_extra": {
        "example": {
            "transport_id": "SIMK900123", "title": "Pricing condition update",
            "kind": "CUSTOMIZING", "change_type": "PRICING_CHANGE",
            "scenario_tag": "PRICING_CANONICAL",
            "objects": [
                {"object_type": "CONFIG_ITEM", "object_key": "PRICING_COND_TYPE_ZPR0"},
                {"object_type": "CUSTOM_CODE", "object_key": "Z_PRICING_DETERMINATION_EXIT"},
            ],
        }
    }}


class TransportOut(BaseModel):
    id: int
    transport_id: str
    title: str
    kind: str
    change_type: str
    scenario_tag: str
    status: str
    source_system: str
    target_release: str
    size_bucket: str
    objects_changed: int
    config_changes: int
    loc_delta: int
    blocked_reason: str
    created_at: dt.datetime | None = None

    model_config = {"from_attributes": True}


class TransportObjectOut(TransportObjectIn):
    id: int
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------- analyses


class AnalysisCreate(BaseModel):
    transport_id_ref: int = Field(..., description="Transport PK (transports.id)")
    wait: bool = False  # run synchronously when true (used by tests/scripts)


class AnalysisOut(BaseModel):
    id: int
    transport_fk: int
    status: str
    current_stage: str
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    duration_ms: float
    error: str
    model_config = {"from_attributes": True}


class StageRunOut(BaseModel):
    id: int
    stage: str
    sequence: int
    status: str
    duration_ms: float
    output: dict
    decision_id: int
    model_config = {"from_attributes": True}


class ImpactResultOut(BaseModel):
    node_type: str
    node_key: str
    name: str
    distance: int
    discovered_by: str
    confidence: float
    path_json: list
    model_config = {"from_attributes": True}


class TestSelectionOut(BaseModel):
    code: str
    rank: int
    score: float
    reason: str
    included: bool
    excluded_reason: str
    model_config = {"from_attributes": True}


class RiskAssessmentOut(BaseModel):
    id: int
    analysis_fk: int
    transport_fk: int
    score: float
    band: str
    factor_breakdown: dict
    rationale: str
    requires_approval: bool
    created_at: dt.datetime | None = None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------- approvals


class ApprovalDecisionIn(BaseModel):
    approver: str = Field(..., min_length=2, max_length=64)
    comment: str = ""


class ApprovalOut(BaseModel):
    id: int
    transport_fk: int
    risk_assessment_id: int
    status: str
    approver: str
    comment: str
    requested_at: dt.datetime | None = None
    decided_at: dt.datetime | None = None
    turnaround_minutes: float
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------- validation


class ExecuteValidationIn(BaseModel):
    transport_pk: int = Field(..., description="Transport PK")


class TestExecutionOut(BaseModel):
    code: str
    criticality: str
    status: str
    duration_ms: float
    failure_reason: str
    model_config = {"from_attributes": True}


class ValidationOut(BaseModel):
    id: int
    transport_fk: int
    analysis_fk: int
    status: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    release_confidence: float
    executions: list[TestExecutionOut] = []
    model_config = {"from_attributes": True}


class DefectOut(BaseModel):
    code: str
    title: str
    severity: str
    status: str
    transport_fk: int
    raised_at: dt.datetime | None = None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------- ALM mock


class AlmFeatureIn(BaseModel):
    external_id: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=128)
    description: str = ""


class AlmFeatureOut(AlmFeatureIn):
    id: int
    created_at: dt.datetime | None = None
    model_config = {"from_attributes": True}


class ReleasePlanOut(BaseModel):
    release: str
    transport_ids: list[str]
    exported_at: dt.datetime | None = None


# ---------------------------------------------------------------- misc


class SeedOut(BaseModel):
    seeded: bool
    counts: dict
    mode: str = "SAP-LIKE SIMULATION - no real SAP system"


class MetaOut(BaseModel):
    app_name: str
    version: str
    environment: str
    mock_mode: bool
    llm_mode: str
    simulator: str
    counts: dict


class EvaluationRunOut(BaseModel):
    id: int
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    transport_count: int
    impact_process_recall: float
    impact_process_precision: float
    impact_interface_recall: float
    impact_interface_precision: float
    test_selection_recall: float
    test_selection_precision: float
    false_positive_tests: int
    risk_accuracy: float
    missed_critical: int
    details: dict
    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    detail: str

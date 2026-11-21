"""Workflow tests: HIGH risk requires approval; reject blocks release;
LOW/MEDIUM auto-approved per policy."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tests.conftest import import_and_analyze, import_transport


def test_high_risk_transport_requires_human_approval(seeded):
    tr, analysis = import_and_analyze(seeded, "PRICING_CANONICAL")
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "AWAITING_APPROVAL"
    risks = seeded.get(f"/api/v1/risk-assessments?analysis_id={analysis['id']}").json()
    assert risks[0]["requires_approval"] is True
    aps = [a for a in seeded.get("/api/v1/approvals").json()
           if a["transport_fk"] == tr["id"]]
    assert aps and aps[0]["status"] == "PENDING"


def test_rejected_transport_is_blocked(seeded):
    tr, _ = import_and_analyze(seeded, "PO_RELEASE_CONFIG")
    ap = next(a for a in seeded.get("/api/v1/approvals?status=PENDING").json()
              if a["transport_fk"] == tr["id"])
    seeded.post(f"/api/v1/approvals/{ap['id']}/reject",
                json={"approver": "cab", "comment": "no"})
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "BLOCKED"


def test_approved_transport_enters_release_queue_state(seeded):
    tr, _ = import_and_analyze(seeded, "PO_RELEASE_CONFIG")
    ap = next(a for a in seeded.get("/api/v1/approvals?status=PENDING").json()
              if a["transport_fk"] == tr["id"])
    seeded.post(f"/api/v1/approvals/{ap['id']}/approve",
                json={"approver": "cab"})
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "APPROVED"


def test_low_risk_auto_approved_without_approval_row(seeded):
    tr, analysis = import_and_analyze(seeded, "MM_STOCK_CLEAN")
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "APPROVED"
    risks = seeded.get(f"/api/v1/risk-assessments?analysis_id={analysis['id']}").json()
    assert risks[0]["band"] == "LOW"
    assert risks[0]["requires_approval"] is False
    aps = [a for a in seeded.get("/api/v1/approvals").json()
           if a["transport_fk"] == tr["id"]]
    assert aps == []


def test_stage_outputs_are_persisted_and_auditable(seeded):
    tr, analysis = import_and_analyze(seeded, "FX_REVALUATION")
    stages = seeded.get(f"/api/v1/analyses/{analysis['id']}/stages").json()
    risk_stage = next(s for s in stages if s["stage"] == "risk")
    assert risk_stage["output"]["decision"]["evidence_ids"]
    assert risk_stage["duration_ms"] >= 0
    # every stage carries a structured decision with evidence ids
    for s in stages:
        d = s["output"]["decision"]
        assert d["confidence"] > 0.5
        assert isinstance(d["alternatives"], list)

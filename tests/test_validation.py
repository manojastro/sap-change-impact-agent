"""Validation tests: canonical transport breaks billing as designed;
clean transport passes fully; blocked transports refuse execution."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tests.conftest import import_and_analyze


def _approve(seeded, tr_id):
    ap = next(a for a in seeded.get("/api/v1/approvals?status=PENDING").json()
              if a["transport_fk"] == tr_id)
    resp = seeded.post(f"/api/v1/approvals/{ap['id']}/approve",
                       json={"approver": "cab-chair", "comment": "ok"})
    assert resp.status_code == 200
    return ap


def test_canonical_pricing_transport_breaks_billing_before_release(seeded):
    tr, analysis = import_and_analyze(seeded, "PRICING_CANONICAL")
    _approve(seeded, tr["id"])
    resp = seeded.post("/api/v1/test-executions/run", json={"transport_pk": tr["id"]})
    assert resp.status_code == 201, resp.text
    val = resp.json()
    by_code = {e["code"]: e for e in val["executions"]}
    # the seeded defect: billing amount calculation broken by pricing change
    assert by_code["BILLING_CREATE_TEST"]["status"] == "FAILED"
    assert "golden copy" in by_code["BILLING_CREATE_TEST"]["failure_reason"]
    # downstream interface payload check fails too
    assert by_code["INVOIC_PAYLOAD_TEST"]["status"] == "FAILED"
    # everything else passes
    for code in ("SO_CREATE_TEST", "FI_RECONCILIATION_TEST"):
        assert by_code[code]["status"] == "PASSED"
    assert val["failed"] == 2 and val["passed"] == 2
    # release confidence weighted by criticality: (1.0 + 1.0) / (1.0+0.85+1.0+1.0)
    expected_conf = round(2.0 / 3.85 * 100, 2)
    assert abs(val["release_confidence"] - expected_conf) < 0.01
    assert val["pass_rate"] == 50.0
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "VALIDATION_FAILED"
    # failures raised defects into platform + ALM mock
    defects = seeded.get("/api/v1/defects").json()
    assert len(defects) >= 2
    alm_defects = seeded.get("/api/v1/alm/defects").json()
    codes = {d["code"] for d in defects}
    assert {d["external_id"] for d in alm_defects} >= codes
    alm_execs = seeded.get("/api/v1/alm/executions").json()
    assert len(alm_execs) >= 4
    trend = seeded.get("/api/v1/release-confidence").json()
    assert trend["latest"] is not None and trend["trend"]


def test_clean_transport_passes_fully(seeded):
    tr, _ = import_and_analyze(seeded, "MM_STOCK_CLEAN")  # LOW risk -> auto-approved
    resp = seeded.post("/api/v1/test-executions/run", json={"transport_pk": tr["id"]})
    assert resp.status_code == 201
    val = resp.json()
    assert val["failed"] == 0
    assert val["release_confidence"] == 100.0
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "VALIDATION_PASSED"
    assert seeded.get("/api/v1/defects").json() == []


def test_validation_refused_without_approval(seeded):
    tr, _ = import_and_analyze(seeded, "ODATA_SO_API")  # MEDIUM/HIGH -> gate applies per band
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    if t["status"] in ("AWAITING_APPROVAL",):
        resp = seeded.post("/api/v1/test-executions/run", json={"transport_pk": tr["id"]})
        assert resp.status_code == 409


def test_validation_requires_analysis_first(seeded):
    from tests.conftest import import_transport

    # auto-approved path needs selections; craft approval-less edge case:
    tr = import_transport(seeded, "ROLE_PAYROLL_DISPLAY")
    # force status to APPROVED without analysis to hit 'no regression scope' guard
    import sqlite3
    db_path = str(pathlib.Path(__import__("tests.conftest", fromlist=["TEST_DB"]).TEST_DB))
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE transports SET status='APPROVED' WHERE id=?", (tr["id"],))
    conn.commit()
    conn.close()
    resp = seeded.post("/api/v1/test-executions/run", json={"transport_pk": tr["id"]})
    assert resp.status_code == 409

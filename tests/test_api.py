"""API tests: meta/seed/transport/analyze/approve-reject/execute/eval + 422s."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tests.conftest import gt_entry, import_and_analyze, import_transport


# ------------------------------------------------------------------ meta

def test_health_and_meta(seeded):
    assert seeded.get("/health").json()["status"] == "ok"
    readiness = seeded.get("/readiness").json()
    assert readiness["seeded"] is True
    meta = seeded.get("/api/v1/meta").json()
    assert meta["mock_mode"] is True
    assert "SAP-LIKE SIMULATION" in meta["simulator"]
    assert meta["llm_mode"] == "mock"
    assert meta["counts"]["processes"] >= 5


def test_metrics_endpoint_exposes_prometheus(seeded):
    body = seeded.get("/metrics").text
    assert "sap_impact_stage_latency_seconds" in body
    assert "sap_impact_analyses_total" in body


# ------------------------------------------------------------------ transports

def test_transport_create_idempotent_and_objects(seeded):
    tr = import_transport(seeded, "PRICING_CANONICAL")
    again = seeded.post("/api/v1/transports", json=gt_entry("PRICING_CANONICAL")["transport"])
    assert again.status_code == 201
    assert again.json()["id"] == tr["id"]
    objs = seeded.get(f"/api/v1/transports/{tr['id']}/objects").json()
    keys = {o["object_key"] for o in objs}
    assert keys == {"PRICING_COND_TYPE_ZPR0", "Z_PRICING_DETERMINATION_EXIT"}
    assert tr["size_bucket"] == "MEDIUM"


def test_transport_validation_errors(seeded):
    bad_missing_title = {"transport_id": "SIMK900777", "objects": [
        {"object_type": "ROLE", "object_key": "ROLE_X"}]}
    assert seeded.post("/api/v1/transports", json=bad_missing_title).status_code == 422
    bad_empty_objects = {"transport_id": "SIMK900778", "title": "no objects", "objects": []}
    assert seeded.post("/api/v1/transports", json=bad_empty_objects).status_code == 422
    bad_enum = {"transport_id": "SIMK900779", "title": "bad kind", "kind": "WHATEVER",
                "objects": [{"object_type": "ROLE", "object_key": "ROLE_X"}]}
    assert seeded.post("/api/v1/transports", json=bad_enum).status_code == 422


# ------------------------------------------------------------------ analyses

def test_analysis_full_pipeline_sync(seeded):
    tr, analysis = import_and_analyze(seeded, "PRICING_CANONICAL")
    stages = seeded.get(f"/api/v1/analyses/{analysis['id']}/stages").json()
    names = [s["stage"] for s in stages]
    assert len(names) == 8 and all(s["status"] == "DONE" for s in stages)
    expected_order = ["transport_analysis", "custom_code", "configuration",
                      "business_process", "interface_impact", "regression_scope",
                      "risk", "validation_readiness"]
    assert names == expected_order

    processes = seeded.get(
        f"/api/v1/impact-results?analysis_id={analysis['id']}&node_type=PROCESS").json()
    proc_names = {p["name"] for p in processes}
    assert {"ORDER_TO_CASH", "RECORD_TO_REPORT"} <= proc_names

    interfaces = seeded.get(
        f"/api/v1/impact-results?analysis_id={analysis['id']}&node_type=INTERFACE").json()
    assert [i["name"] for i in interfaces] == ["INVOIC_OUT"]

    selections = seeded.get(f"/api/v1/test-selections?analysis_id={analysis['id']}").json()
    codes = [s["code"] for s in selections]
    assert set(codes) == {"SO_CREATE_TEST", "BILLING_CREATE_TEST",
                          "FI_RECONCILIATION_TEST", "INVOIC_PAYLOAD_TEST"}
    assert all(s["reason"] for s in selections)
    scores = [s["score"] for s in selections]
    assert scores == sorted(scores, reverse=True)

    risks = seeded.get(f"/api/v1/risk-assessments?analysis_id={analysis['id']}").json()
    assert risks[0]["band"] == "HIGH"
    fb = risks[0]["factor_breakdown"]
    assert abs(sum(v["contribution"] for v in fb.values()) - risks[0]["score"]) < 0.05

    graph = seeded.get(f"/api/v1/graph?analysis_id={analysis['id']}").json()
    assert graph["nodes"] and graph["edges"]
    impacted_keys = set(graph["impacted"])
    assert any(k.startswith("PROCESS:") for k in impacted_keys)


def test_analysis_background_mode_polling(seeded):
    tr = import_transport(seeded, "MM_STOCK_CLEAN")
    resp = seeded.post("/api/v1/analyses", json={"transport_id_ref": tr["id"], "wait": False})
    assert resp.status_code == 202
    analysis_id = resp.json()["id"]
    deadline = __import__("time").time() + 30
    status = None
    while __import__("time").time() < deadline:
        a = seeded.get(f"/api/v1/analyses/{analysis_id}").json()
        status = a["status"]
        if status in ("COMPLETED", "FAILED"):
            break
        __import__("time").sleep(0.3)
    assert status == "COMPLETED"


def test_analysis_unknown_transport_404(seeded):
    resp = seeded.post("/api/v1/analyses", json={"transport_id_ref": 987654, "wait": True})
    assert resp.status_code == 404


def test_graph_endpoint_without_analysis_returns_estate(seeded):
    graph = seeded.get("/api/v1/graph").json()
    assert len(graph["nodes"]) > 20


# ------------------------------------------------------------------ approvals

def test_approval_approve_then_conflict_on_second_decision(seeded):
    from tests.conftest import import_and_analyze

    tr, analysis = import_and_analyze(seeded, "PRICING_CANONICAL")
    aps = seeded.get("/api/v1/approvals?status=PENDING").json()
    ap = next(a for a in aps if a["transport_fk"] == tr["id"])
    ok = seeded.post(f"/api/v1/approvals/{ap['id']}/approve",
                     json={"approver": "cab-chair", "comment": "approved for pilot"})
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    conflict = seeded.post(f"/api/v1/approvals/{ap['id']}/approve",
                           json={"approver": "cab-chair"})
    assert conflict.status_code == 409
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "APPROVED"
    missing_approver = seeded.post(f"/api/v1/approvals/{ap['id']}/reject", json={})
    assert missing_approver.status_code in (409, 422)


def test_reject_blocks_transport_with_reason(seeded):
    tr, analysis = import_and_analyze(seeded, "PO_RELEASE_CONFIG")
    ap = next(a for a in seeded.get("/api/v1/approvals?status=PENDING").json()
              if a["transport_fk"] == tr["id"])
    rej = seeded.post(f"/api/v1/approvals/{ap['id']}/reject",
                      json={"approver": "cab-chair", "comment": "threshold change needs sign-off first"})
    assert rej.status_code == 200
    t = seeded.get(f"/api/v1/transports/{tr['id']}").json()
    assert t["status"] == "BLOCKED"
    assert "sign-off" in t["blocked_reason"]
    # blocked transports refuse new analyses and validation
    r2 = seeded.post("/api/v1/analyses", json={"transport_id_ref": tr["id"], "wait": True})
    assert r2.status_code == 409
    r3 = seeded.post("/api/v1/test-executions/run", json={"transport_pk": tr["id"]})
    assert r3.status_code == 409


# ------------------------------------------------------------------ evaluation

def test_evaluation_run_end_to_end(seeded):
    resp = seeded.post("/api/v1/evaluation/run")
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["transport_count"] >= 5
    for key in ("impact_process_recall", "impact_process_precision",
                "impact_interface_recall", "impact_interface_precision",
                "test_selection_recall", "test_selection_precision"):
        assert run[key] == 1.0, (key, run["details"])
    assert run["missed_critical"] == 0
    assert run["false_positive_tests"] == 0
    runs = seeded.get("/api/v1/evaluation/runs").json()
    assert runs and runs[0]["id"] == run["id"]

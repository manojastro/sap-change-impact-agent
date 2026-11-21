"""Evaluation tests: honest thresholds on the authored ground truth.

The world is deterministic, so the platform must hit 100% recall/precision on
authored truths and 0 missed critical items. If these fail we fix the logic -
we never silently loosen the thresholds.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def test_ground_truth_file_is_well_formed():
    from tests.conftest import gt_entry

    data = gt_entry("PRICING_CANONICAL")
    assert data["expected"]["processes"] == ["ORDER_TO_CASH", "RECORD_TO_REPORT"]
    assert "INVOIC_OUT" in data["expected"]["interfaces"]
    assert any("BILLING" in t for t in data["expected"]["tests"])
    assert len(data["expected"]["tests"]) >= 3  # canonical minimum incl. billing


def test_evaluation_metrics_meet_honest_thresholds(seeded):
    resp = seeded.post("/api/v1/evaluation/run")
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["transport_count"] >= 5

    # impact discovery: perfect on the authored deterministic world
    assert run["impact_process_recall"] >= 1.0 - 1e-9
    assert run["impact_process_precision"] >= 1.0 - 1e-9
    assert run["impact_interface_recall"] >= 1.0 - 1e-9
    assert run["impact_interface_precision"] >= 1.0 - 1e-9

    # regression test selection: perfect + no false positives
    assert run["test_selection_recall"] >= 1.0 - 1e-9
    assert run["test_selection_precision"] >= 1.0 - 1e-9
    assert run["false_positive_tests"] == 0

    # canonical transport must miss nothing critical
    assert run["missed_critical"] == 0

    # release risk band accuracy: exact match for every transport
    assert run["risk_accuracy"] == 1.0, run["details"]

    # persisted with per-transport details
    details = run["details"]["per_transport"]
    keys = {d["key"] for d in details}
    assert {"PRICING_CANONICAL", "MM_STOCK_CLEAN", "PO_RELEASE_CONFIG",
            "FX_REVALUATION", "ROLE_PAYROLL_DISPLAY", "ODATA_SO_API"} <= keys
    canonical = next(d for d in details if d["key"] == "PRICING_CANONICAL")
    assert canonical["computed_risk_band"] == "HIGH"
    assert not canonical["missing_tests"]
    assert not canonical["false_positive_tests"]


def test_evaluation_is_repeatable(seeded):
    r1 = seeded.post("/api/v1/evaluation/run").json()
    r2 = seeded.post("/api/v1/evaluation/run").json()
    stable_keys = ("impact_process_recall", "test_selection_recall",
                   "risk_accuracy", "missed_critical", "false_positive_tests")
    for k in stable_keys:
        assert r1[k] == r2[k], (k, r1[k], r2[k])


def test_business_metrics_reflect_latest_eval(seeded):
    seeded.post("/api/v1/evaluation/run")
    metrics = seeded.get("/api/v1/business-metrics").json()["latest"]
    assert abs(metrics["eval_process_recall"]["value"] - 1.0) < 1e-9
    assert "scope_reduction_ratio" in metrics

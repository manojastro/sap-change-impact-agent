"""Evaluation runner - measures impact discovery, test selection and risk
accuracy against the labeled ground truth in evaluation/ground_truth.json."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from sqlalchemy.orm import Session

from backend.app import metrics
from backend.app.models import (
    Analysis, EvaluationRunRow, ImpactResult, RiskAssessment, TestSelection,
)
from backend.app.services.transport_service import import_transport
from backend.app.schemas import TransportIn
from backend.app.workflow.engine import run_analysis

ROOT = pathlib.Path(__file__).resolve().parents[3]
GROUND_TRUTH_PATH = ROOT / "evaluation" / "ground_truth.json"


def _load_ground_truth() -> dict:
    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _set_metrics(found: set[str], expected: set[str]) -> tuple[float, float]:
    if expected:
        recall = len(found & expected) / len(expected)
    else:
        recall = 1.0 if not found else 0.0
    if found or expected:
        precision = len(found & expected) / len(found) if found else 0.0
    else:
        precision = 1.0
    return recall, precision


def run_evaluation(db: Session) -> EvaluationRunRow:
    gt = _load_ground_truth()
    details = []
    agg = {
        "process_r": [], "process_p": [], "iface_r": [], "iface_p": [],
        "test_r": [], "test_p": [],
    }
    false_positives: list[str] = []
    missed_critical = 0
    risk_correct = 0
    risk_total = 0

    for entry in gt["transports"]:
        payload = TransportIn(**entry["transport"])
        transport = import_transport(db, payload)

        analysis = Analysis(transport_fk=transport.id, status="QUEUED",
                            started_at=dt.datetime.now(dt.timezone.utc), params={"evaluation": entry["key"]})
        db.add(analysis)
        db.commit()
        run_analysis(db, analysis.id)

        impacted = db.query(ImpactResult).filter_by(analysis_fk=analysis.id).all()
        found_processes = {r.name for r in impacted if r.node_type == "PROCESS"}
        found_interfaces = {r.name for r in impacted if r.node_type == "INTERFACE"}
        selections = db.query(TestSelection).filter_by(analysis_fk=analysis.id, included=True).all()
        found_tests = {s.code for s in selections}
        risk = (
            db.query(RiskAssessment)
            .filter_by(analysis_fk=analysis.id)
            .order_by(RiskAssessment.id.desc())
            .first()
        )
        band = risk.band if risk else "NONE"

        exp = entry["expected"]
        pr, pp = _set_metrics(found_processes, set(exp["processes"]))
        ir, ip = _set_metrics(found_interfaces, set(exp["interfaces"]))
        tr, tp = _set_metrics(found_tests, set(exp["tests"]))
        missing_tests = sorted(set(exp["tests"]) - found_tests)
        fp_tests = sorted(found_tests - set(exp["tests"]))
        false_positives.extend(fp_tests)
        missed_critical += len(missing_tests)
        if entry.get("critical_truth"):
            missed_critical += len(set(exp["processes"]) - found_processes)
        risk_total += 1
        if band == exp["risk_band"]:
            risk_correct += 1

        agg["process_r"].append(pr)
        agg["process_p"].append(pp)
        agg["iface_r"].append(ir)
        agg["iface_p"].append(ip)
        agg["test_r"].append(tr)
        agg["test_p"].append(tp)

        details.append({
            "key": entry["key"],
            "found_processes": sorted(found_processes),
            "expected_processes": exp["processes"],
            "found_interfaces": sorted(found_interfaces),
            "expected_interfaces": exp["interfaces"],
            "found_tests": sorted(found_tests),
            "expected_tests": exp["tests"],
            "missing_tests": missing_tests,
            "false_positive_tests": fp_tests,
            "computed_risk_band": band,
            "expected_risk_band": exp["risk_band"],
            "process_recall": round(pr, 4), "process_precision": round(pp, 4),
            "interface_recall": round(ir, 4), "interface_precision": round(ip, 4),
            "test_recall": round(tr, 4), "test_precision": round(tp, 4),
        })

    avg = lambda k: round(sum(agg[k]) / max(1, len(agg[k])), 4)  # noqa: E731
    row = EvaluationRunRow(
        finished_at=dt.datetime.now(dt.timezone.utc),
        transport_count=len(gt["transports"]),
        impact_process_recall=avg("process_r"),
        impact_process_precision=avg("process_p"),
        impact_interface_recall=avg("iface_r"),
        impact_interface_precision=avg("iface_p"),
        test_selection_recall=avg("test_r"),
        test_selection_precision=avg("test_p"),
        false_positive_tests=len(false_positives),
        risk_accuracy=round(risk_correct / max(1, risk_total), 4),
        missed_critical=missed_critical,
        details={"per_transport": details},
    )
    db.add(row)
    db.commit()

    for name, value in [
        ("eval_process_recall", row.impact_process_recall),
        ("eval_process_precision", row.impact_process_precision),
        ("eval_interface_recall", row.impact_interface_recall),
        ("eval_interface_precision", row.impact_interface_precision),
        ("eval_test_recall", row.test_selection_recall),
        ("eval_test_precision", row.test_selection_precision),
    ]:
        metrics.persist_snapshot(db, name, value)
    db.commit()
    return row


def latest_evaluation(db: Session) -> EvaluationRunRow | None:
    return db.query(EvaluationRunRow).order_by(EvaluationRunRow.id.desc()).first()

"""Release validation simulation.

Executing release validation runs the selected regression tests deterministically:
outcomes derive from seeded defects (defect_seeds). The canonical pricing
transport BREAKS billing amount calculation, so BILLING_CREATE_TEST and
INVOIC_PAYLOAD_TEST fail while everything else passes - demonstrating the
platform catching a bad change BEFORE release.

Failed tests raise defects into the platform + the ALM mock. Release
Confidence = pass rate weighted by test criticality.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from backend.app import metrics
from backend.app.models import (
    Analysis, Approval, Defect, DefectSeed, EventRow, OutcomeRow,
    TestExecutionRow, TestSelection, TestCase, Transport, ValidationRun,
)
from backend.app.services.alm_service import get_alm_adapter

CRIT_W = {"CRITICAL": 1.0, "HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}


def _latest_analysis(db: Session, transport_pk: int) -> int:
    row = (
        db.query(Analysis)
        .filter_by(transport_fk=transport_pk, status="COMPLETED")
        .order_by(Analysis.id.desc())
        .first()
    )
    return row.id if row else 0


def run_validation_for_transport(db: Session, transport_pk: int, analysis_id: int = 0) -> ValidationRun:
    transport = db.get(Transport, int(transport_pk))
    if transport is None:
        raise LookupError(f"transport {transport_pk} not found")
    if transport.status == "BLOCKED":
        raise ValueError("transport BLOCKED; release validation refused")
    if transport.status in ("AWAITING_APPROVAL", "IMPORTED", "ANALYZED"):
        raise ValueError(
            f"release validation requires approval first (status={transport.status})"
        )

    analysis_id = analysis_id or _latest_analysis(db, transport.id)
    selections = (
        db.query(TestSelection)
        .filter_by(analysis_fk=analysis_id, included=True)
        .order_by(TestSelection.rank)
        .all()
    )
    if not selections:
        raise ValueError("no regression scope found; run an analysis first")

    seeds = {
        s.test_code: s
        for s in db.query(DefectSeed).filter_by(scenario_tag=transport.scenario_tag or "").all()
    }

    val = ValidationRun(
        transport_fk=transport.id, analysis_fk=analysis_id, status="RUNNING",
        started_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(val)
    db.commit()

    adapter = get_alm_adapter(db)
    weight_total = weight_passed = 0.0
    passed = failed = 0

    for sel in selections:
        tc = db.get(TestCase, sel.test_case_id)
        seed = seeds.get(tc.code)
        w = CRIT_W.get(tc.criticality, 0.5)
        weight_total += w
        status = "FAILED" if seed is not None else "PASSED"
        reason = seed.failure_reason if seed is not None else ""
        if seed is not None:
            failed += 1
        else:
            passed += 1
            weight_passed += w

        exec_row = TestExecutionRow(
            validation_fk=val.id, test_case_id=tc.id, code=tc.code,
            criticality=tc.criticality, status=status,
            duration_ms=int(tc.avg_duration_s * 100), failure_reason=reason,
        )
        db.add(exec_row)
        db.flush()

        db.add(OutcomeRow(
            analysis_fk=analysis_id, validation_fk=val.id, test_code=tc.code,
            predicted_selected=True, actual_result=status,
            matched_expectation=True,
            notes=("seeded defect triggered" if seed is not None else "no seeded defect"),
        ))

        adapter.record_test_execution(
            test_code=tc.code, status="PASS" if status == "PASSED" else "FAIL",
            details={"validation_id": val.id},
        )
        if status == "FAILED":
            seq = db.query(Defect).count() + 1
            defect = Defect(
                code=f"DEF-{seq:04d}", transport_fk=transport.id,
                validation_fk=val.id, test_execution_id=exec_row.id,
                title=f"[{transport.transport_id}] {tc.code}: {reason[:160]}",
                severity=seed.severity if seed is not None else "HIGH",
            )
            db.add(defect)
            db.commit()
            metrics.DEFECTS_CAUGHT.inc()
            adapter.record_defect(external_id=defect.code, title=defect.title,
                                  severity=defect.severity,
                                  transport_id=transport.transport_id,
                                  test_code=tc.code)

    confidence = round(weight_passed / weight_total * 100.0, 2) if weight_total else 0.0
    val.status = "COMPLETED"
    val.total = passed + failed
    val.passed = passed
    val.failed = failed
    val.pass_rate = round(passed / max(1, passed + failed) * 100.0, 2)
    val.release_confidence = confidence
    val.finished_at = dt.datetime.now(dt.timezone.utc)

    transport.status = "VALIDATION_FAILED" if failed else "VALIDATION_PASSED"

    db.add(EventRow(kind="RELEASE_VALIDATION", ref_type="TRANSPORT", ref_id=transport.id,
                    message=f"Validation {val.id}: {failed} failing test(s), "
                            f"confidence {confidence}%"))

    metrics.persist_snapshot(db, "defect_catch_count",
                             float(metrics.DEFECTS_CAUGHT._value.get()))
    approved = db.query(Approval).filter_by(transport_fk=transport.id, status="APPROVED").all()
    turnarounds = [a.turnaround_minutes for a in approved if a.turnaround_minutes]
    if turnarounds:
        metrics.persist_snapshot(db, "approval_turnaround_minutes",
                                 round(sum(turnarounds) / len(turnarounds), 2))
    db.commit()
    return val

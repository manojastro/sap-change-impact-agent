"""Change demo: full release-management walkthrough on the simulated estate.

  seed -> import canonical pricing transport -> analysis -> impact ->
  regression scope -> risk -> approval -> simulated regression ->
  confidence + defects -> clean transport contrast -> evaluation run.

Usage:
    .venv\\Scripts\\python.exe scripts\\run_change_demo.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

from backend.app.db import dispose_db, get_session_factory, init_db  # noqa: E402


def main() -> int:
    init_db()
    session = get_session_factory()()

    from backend.app.models import (
        Approval, Defect, ImpactResult, RiskAssessment, StageRun, TestCase,
        TestExecutionRow, TestSelection, Transport,
    )
    from backend.app.schemas import TransportIn
    from backend.app.services.evaluation_service import _load_ground_truth, run_evaluation
    from backend.app.services.transport_service import import_transport
    from backend.app.services.validation_service import run_validation_for_transport
    from backend.app.workflow.engine import run_analysis, start_analysis

    print("=== 0. Seed SAP-LIKE landscape ===")
    from simulator.generate_landscape import SIMULATION_LABEL, seed_landscape

    counts = seed_landscape(session)
    print(SIMULATION_LABEL)
    print(json.dumps(counts, sort_keys=True))

    gt = _load_ground_truth()
    by_key = {e["key"]: e for e in gt["transports"]}

    def analyze(key: str):
        tr = import_transport(session, TransportIn(**by_key[key]["transport"]))
        a = start_analysis(session, tr.id)
        run_analysis(session, a.id)
        return tr, a

    for key in ("PRICING_CANONICAL", "MM_STOCK_CLEAN"):
        print(f"\n=== {key}: import + analysis ===")
        tr, a = analyze(key)
        stages = (session.query(StageRun).filter_by(analysis_fk=a.id)
                  .order_by(StageRun.sequence).all())
        for s in stages:
            d = (s.output or {}).get("decision", {})
            print(f"  [{s.sequence}] {s.stage:<22} {d.get('decision', '')[:88]}")

        procs = [r.name for r in session.query(ImpactResult)
                 .filter_by(analysis_fk=a.id, node_type="PROCESS").all()]
        ifaces = [r.name for r in session.query(ImpactResult)
                  .filter_by(analysis_fk=a.id, node_type="INTERFACE").all()]
        sels = (session.query(TestSelection).filter_by(analysis_fk=a.id, included=True)
                .order_by(TestSelection.rank).all())
        total_tests = session.query(TestCase).count()
        ra = (session.query(RiskAssessment).filter_by(analysis_fk=a.id).one_or_none())
        print(f"  impacted processes : {', '.join(procs) or '-'}")
        print(f"  impacted interfaces: {', '.join(ifaces) or '-'}")
        print(f"  selected tests     : {', '.join(s.code for s in sels)} "
              f"({len(sels)}/{total_tests}, excluded {total_tests - len(sels)})")
        print(f"  risk               : {ra.score}/100 => {ra.band}")

    print("\n=== Approvals ===")
    pending = session.query(Approval).filter_by(status="PENDING").all()
    from datetime import datetime, timezone
    for ap in pending:
        ap.status = "APPROVED"
        ap.approver = "release-manager-demo"
        ap.comment = "Demo approval (run_change_demo.py)"
        ap.decided_at = datetime.now(timezone.utc)
        requested = ap.requested_at
        if requested.tzinfo is None:  # SQLite may return naive UTC
            requested = requested.replace(tzinfo=timezone.utc)
        ap.turnaround_minutes = round((ap.decided_at - requested).total_seconds() / 60.0, 2)
        t = session.get(Transport, ap.transport_fk)
        if t is not None and t.status == "AWAITING_APPROVAL":
            t.status = "APPROVED"
    session.commit()
    print(f"approved {len(pending)} pending approval(s)")

    print("\n=== Simulated regression execution (canonical) ===")
    canonical = session.query(Transport).filter_by(transport_id="SIMK910001").one()
    val = run_validation_for_transport(session, canonical.id)
    execs = (session.query(TestExecutionRow).filter_by(validation_fk=val.id)
             .order_by(TestExecutionRow.id).all())
    for e in execs:
        marker = "PASS" if e.status == "PASSED" else "FAIL"
        print(f"  [{marker}] {e.code:<26} {e.failure_reason[:70]}")
    print(f"  release confidence: {val.release_confidence}%")
    defects = session.query(Defect).filter_by(transport_fk=canonical.id).all()
    print(f"  defects raised pre-release: {[d.code for d in defects]}")

    clean = session.query(Transport).filter_by(transport_id="SIMK910002").one()
    val2 = run_validation_for_transport(session, clean.id)
    print(f"\n=== Clean transport control: confidence {val2.release_confidence}%, "
          f"{val2.failed} failures ===")

    print("\n=== Evaluation vs authored ground truth ===")
    row = run_evaluation(session)
    print(f"  transports evaluated      : {row.transport_count}")
    print(f"  impact process recall     : {row.impact_process_recall}")
    print(f"  impact process precision  : {row.impact_process_precision}")
    print(f"  impact interface recall   : {row.impact_interface_recall}")
    print(f"  impact interface precision: {row.impact_interface_precision}")
    print(f"  test selection recall     : {row.test_selection_recall}")
    print(f"  test selection precision  : {row.test_selection_precision}")
    print(f"  false positive tests      : {row.false_positive_tests}")
    print(f"  risk band accuracy        : {row.risk_accuracy}")
    print(f"  missed critical items     : {row.missed_critical}")

    session.close()
    dispose_db()
    print("\nDemo complete. Start the UI with:")
    print('  .venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --port 8013')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

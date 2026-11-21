"""Canonical pricing scenario, end-to-end (SAP-LIKE simulation).

Creates the high-risk PRICING_CANONICAL transport (pricing condition config +
Z_PRICING_DETERMINATION_EXIT), runs the full agentic analysis, walks through
approval, executes the simulated regression suite and prints every result.

Usage:
    .venv\\Scripts\\python.exe scripts\\create_high_risk_transport.py [--fresh]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

from backend.app.db import dispose_db, get_session_factory, init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true",
                        help="reseed the landscape first")
    args = parser.parse_args()

    init_db()
    session = get_session_factory()()

    from backend.app.models import Approval, Transport
    from backend.app.services.evaluation_service import _load_ground_truth
    from backend.app.services.transport_service import import_transport
    from backend.app.schemas import TransportIn
    from backend.app.workflow.engine import run_analysis, start_analysis
    from backend.app.services.validation_service import run_validation_for_transport

    if args.fresh:
        from simulator.generate_landscape import SIMULATION_LABEL, seed_landscape

        counts = seed_landscape(session)
        print(SIMULATION_LABEL)
        print("Seeded estate:", json.dumps(counts, sort_keys=True))

    entry = next(e for e in _load_ground_truth()["transports"]
                 if e["key"] == "PRICING_CANONICAL")

    print("\n=== 1. Import canonical pricing transport ===")
    payload = TransportIn(**entry["transport"])
    tr = import_transport(session, payload)
    session.flush()  # make changed objects visible to same-session queries
    print(f"transport {tr.transport_id} imported: status={tr.status} "
          f"size={tr.size_bucket} objects={tr.objects_changed}")

    print("\n=== 2. Agentic analysis (8 stages) ===")
    analysis = start_analysis(session, tr.id)
    run_analysis(session, analysis.id)
    from backend.app.models import StageRun

    for stage in (session.query(StageRun).filter_by(analysis_fk=analysis.id)
                  .order_by(StageRun.sequence).all()):
        decision = (stage.output or {}).get("decision", {})
        print(f"  [{stage.sequence}] {stage.stage:<22} {stage.status:<5} "
              f"{stage.duration_ms:7.1f}ms  {decision.get('decision', '')[:90]}")

    print("\n=== 3. Impact discovery ===")
    from backend.app.models import ImpactResult
    rows = (session.query(ImpactResult).filter_by(analysis_fk=analysis.id)
            .order_by(ImpactResult.distance).all())
    for node_type in ("PROCESS", "INTERFACE"):
        subset = [r for r in rows if r.node_type == node_type]
        print(f"  {node_type}: {', '.join(r.name for r in subset) or '-'}")

    print("\n=== 4. Regression scope (minimal, reason-coded) ===")
    from backend.app.models import TestSelection
    sels = (session.query(TestSelection)
            .filter_by(analysis_fk=analysis.id, included=True)
            .order_by(TestSelection.rank).all())
    from backend.app.models import TestCase as TCModel
    total_tests = session.query(TCModel).count()
    for s in sels:
        print(f"  #{s.rank} {s.code:<24} score={s.score:<7} {s.reason[:80]}")
    print(f"  -> {len(sels)} selected of {total_tests} total "
          f"(scope reduction to {round(len(sels)/total_tests*100, 1)}%); "
          f"NOT rerun-everything")

    print("\n=== 5. Risk & approval gate ===")
    from backend.app.models import RiskAssessment
    ra = (session.query(RiskAssessment).filter_by(analysis_fk=analysis.id)
          .one_or_none())
    print(f"  risk score {ra.score}/100 => {ra.band}; "
          f"requires_approval={ra.requires_approval}")
    top = sorted(ra.factor_breakdown.items(), key=lambda kv: -kv[1]["contribution"])[:3]
    for name, f in top:
        print(f"    {name}: raw={f['raw']} weight={f['weight']} "
              f"contribution={f['contribution']}")
    ap = (session.query(Approval).filter_by(transport_fk=tr.id, status="PENDING")
          .one_or_none())
    print(f"  transport status: {session.get(Transport, tr.id).status}")
    if ap is not None:
        ap.status = "APPROVED"
        ap.approver = "release-manager-demo"
        ap.comment = "Demo approval via create_high_risk_transport.py"
        from datetime import datetime, timezone
        ap.decided_at = datetime.now(timezone.utc)
        ap.turnaround_minutes = 0.0
        tr_model = session.get(Transport, tr.id)
        tr_model.status = "APPROVED"
        session.commit()
        print(f"  approval #{ap.id} APPROVED by release-manager-demo")

    print("\n=== 6. Simulated release validation ===")
    val = run_validation_for_transport(session, tr.id)
    from backend.app.models import TestExecutionRow
    execs = (session.query(TestExecutionRow).filter_by(validation_fk=val.id)
             .order_by(TestExecutionRow.id).all())
    for e in execs:
        marker = "PASS" if e.status == "PASSED" else "FAIL"
        print(f"  [{marker}] {e.code:<26} ({e.criticality}) {e.failure_reason[:60]}")
    print(f"  release confidence: {val.release_confidence}% "
          f"(criticality-weighted pass rate)")
    print(f"  transport status: {session.get(Transport, tr.id).status}")

    print("\n=== 7. Defects caught BEFORE release ===")
    from backend.app.models import Defect
    for d in session.query(Defect).filter_by(transport_fk=tr.id).all():
        print(f"  {d.code} [{d.severity}] {d.title[:100]}")

    session.close()
    dispose_db()
    print("\nCanonical pricing scenario complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

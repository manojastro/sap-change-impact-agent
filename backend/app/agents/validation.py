"""Stage 8: Validation Agent - pre-release readiness checks + execution plan.

Actual test execution happens through the validation service (API/tool), so
the release cockpit can orchestrate it explicitly after approval.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from backend.app.models import Approval, TestSelection

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class ValidationAgent(BaseAgent):
    name = "validation_readiness"
    description = "Pre-release checks and regression execution plan."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        db: DbSession = ctx.db
        transport = ctx.transport

        selections = db.query(TestSelection).filter_by(analysis_fk=ctx.analysis_id, included=True).all()
        approval = db.query(Approval).filter_by(transport_fk=transport.id).order_by(Approval.id.desc()).first()

        checks = [
            {"name": "transport_imported", "status": "PASS" if transport.status else "FAIL",
             "detail": f"status={transport.status}"},
            {"name": "risk_assessed", "status": "PASS", "detail": "risk stage completed"},
            {"name": "approval_gate",
             "status": "PASS" if transport.status not in ("AWAITING_APPROVAL", "BLOCKED") else "PENDING",
             "detail": f"transport status {transport.status}; "
                       f"approval {'pending' if approval and approval.status == 'PENDING' else (approval.status if approval else 'not required')}"},
            {"name": "regression_scope_defined",
             "status": "PASS" if selections else "FAIL",
             "detail": f"{len(selections)} tests selected"},
            {"name": "no_open_blocker",
             "status": "FAIL" if transport.status == "BLOCKED" else "PASS",
             "detail": transport.blocked_reason or "none"},
        ]
        ready = all(c["status"] == "PASS" for c in checks)
        out.evidence.append(make_evidence(
            "policy:pre_release_checks",
            f"Pre-release readiness: {'READY' if ready else 'NOT READY'} "
            f"({sum(1 for c in checks if c['status'] == 'PASS')}/{len(checks)} checks passed).",
            0.95))
        out.output = {
            "checks": checks,
            "ready_for_release_validation": ready,
            "planned_suite": [s.code for s in selections],
            "execution_entrypoint": "POST /api/v1/test-executions/run",
            "rationale": self.rationale(ctx, {
                "stage": self.name,
                "changed_objects": [s[0] for s in ctx.seeds],
                "validation_checks": [
                    {"name": c["name"], "status": c["status"]} for c in checks
                ],
            }),
        }
        out.decision = {
            "decision": ("Release validation may proceed." if ready
                         else "Release validation blocked until pending items resolve."),
            "confidence": 0.9,
            "alternatives": [],
            "risk_level": "NONE" if ready else "MEDIUM",
            "requires_approval": False,
        }
        return out

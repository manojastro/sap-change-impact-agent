"""Stage 7: Risk Agent - deterministic release-risk score + approval gating."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session as DbSession

from backend.app.graph.dependency_graph import CUSTOM_CODE, INTERFACE, PROCESS
from backend.app.models import Approval, RiskAssessment, StageRun, Transport
from backend.app.tools.sap_tools import compute_risk

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class RiskAgent(BaseAgent):
    name = "risk"
    description = "Computes the weighted release-risk score and opens approvals when needed."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        db: DbSession = ctx.db
        transport: Transport = ctx.transport

        processes = [
            (ctx.graph.label(k), ctx.graph.g.nodes[k].get("criticality", "MEDIUM"))
            for k in ctx.closure if ctx.graph.node_type(k) == PROCESS
        ]
        custom_code_count = sum(1 for k in ctx.closure if ctx.graph.node_type(k) == CUSTOM_CODE)
        interface_count = sum(1 for k in ctx.closure if ctx.graph.node_type(k) == INTERFACE)

        # inputs produced by the regression scope stage
        scope_stage = (
            db.query(StageRun)
            .filter_by(analysis_fk=ctx.analysis_id, stage="regression_scope").first()
        )
        selected_defect_rates: list[float] = []
        coverage_gap = 0.0
        if scope_stage is not None:
            selected_defect_rates = scope_stage.output.get("selected_defect_rates", [])
            coverage_gap = float(scope_stage.output.get("coverage_gap_ratio", 0.0))

        result = compute_risk(
            impacted_processes=processes,
            custom_code_count=custom_code_count,
            interface_count=interface_count,
            selected_defect_rates=selected_defect_rates,
            coverage_gap_ratio=coverage_gap,
            size_bucket=transport.size_bucket,
        )
        band = result["band"]
        requires_approval = band in ("HIGH", "CRITICAL")

        db.query(RiskAssessment).filter_by(analysis_fk=ctx.analysis_id).delete()
        ra = RiskAssessment(
            analysis_fk=ctx.analysis_id,
            transport_fk=transport.id,
            score=result["score"],
            band=band,
            factor_breakdown=result["factor_breakdown"],
            rationale="",
            requires_approval=requires_approval,
            created_at=dt.datetime.now(dt.timezone.utc),
        )
        db.add(ra)
        db.commit()

        # approval gating
        approval_id = 0
        if requires_approval and transport.status not in ("BLOCKED",):
            existing = db.query(Approval).filter_by(transport_fk=transport.id, status="PENDING").first()
            if existing is None:
                ap = Approval(transport_fk=transport.id, risk_assessment_id=ra.id, status="PENDING")
                db.add(ap)
                db.commit()
                approval_id = ap.id
            else:
                approval_id = existing.id
            transport.status = "AWAITING_APPROVAL"
        elif band in ("LOW", "MEDIUM"):
            # policy: LOW/MEDIUM auto-approved by change-advisory policy
            if transport.status in ("IMPORTED", "ANALYZED"):
                transport.status = "APPROVED"
        db.commit()

        top_factors = sorted(
            result["factor_breakdown"].items(), key=lambda kv: -kv[1]["contribution"]
        )[:3]
        factor_txt = "; ".join(f"{k} {v['raw']}x{v['weight']}" for k, v in top_factors)
        out.evidence.append(make_evidence(
            "tool:compute_risk_score",
            f"Risk score {result['score']}/100 => band {band}. Factors: "
            f"processes={[p for p, _ in processes]}, custom_code={custom_code_count}, "
            f"interfaces={interface_count}, size={transport.size_bucket}.",
            0.97))
        out.evidence.append(make_evidence(
            "policy:approval_gate",
            f"Band {band} -> human approval {'required' if requires_approval else 'not required'} "
            f"(auto-approved by CAB policy otherwise).",
            0.99))
        out.output = {
            "risk": result,
            "processes": [{"code": p, "criticality": c} for p, c in processes],
            "custom_code_count": custom_code_count,
            "interface_count": interface_count,
            "requires_approval": requires_approval,
            "approval_id": approval_id,
            "rationale": self.rationale(ctx, {
                "stage": self.name,
                "changed_objects": [s[0] for s in ctx.seeds],
                "impacted_processes": [p for p, _ in processes],
                "risk_score": result["score"],
                "risk_band": band,
                "top_risk_factors": [k for k, _ in top_factors],
                "findings": [],
            }),
        }
        out.hypotheses.append({
            "statement": f"Release risk is {band} ({result['score']}/100).",
            "status": "CONFIRMED", "confidence": 0.9,
        })
        out.decision = {
            "decision": f"Release risk {result['score']}/100 = {band}; "
                        f"{'human approval required' if requires_approval else 'auto-approved per policy'}.",
            "confidence": 0.93,
            "alternatives": ["hold release until next window (fallback)"],
            "risk_level": band,
            "requires_approval": requires_approval,
        }
        return out

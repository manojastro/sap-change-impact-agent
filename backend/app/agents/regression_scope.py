"""Stage 6: Regression Scope Agent - minimal high-value regression scope.

Explicitly NOT rerun-everything: tests are selected by coverage of impacted
objects, business criticality, historical defect rate and interface
involvement; every selection carries a reason; exclusions are counted.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session as DbSession

from backend.app.graph.dependency_graph import TESTABLE_NODE_TYPES
from backend.app.models import TestSelection, TestCase
from backend.app.tools.sap_tools import select_regression_tests

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class RegressionScopeAgent(BaseAgent):
    name = "regression_scope"
    description = "Selects the minimal high-value regression test set with reasons."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        db: DbSession = ctx.db
        seed_keys = {k for k, _ in ctx.seeds}
        result = select_regression_tests(ctx.graph, db, ctx.closure, seed_keys)

        # coverage gap over testable impacted objects (excludes direct seeds)
        testable_impacted = {
            k for k in ctx.closure
            if ctx.graph.node_type(k) in TESTABLE_NODE_TYPES and k not in seed_keys
        }
        covered_testable = set()
        for sel in result["selected"]:
            tc_row = db.get(TestCase, sel["test_case_id"])
            validated = set(ctx.graph.g.predecessors(f"TEST_CASE:{tc_row.id}"))
            covered_testable |= (validated & testable_impacted)
        coverage_gap = (
            len(testable_impacted - covered_testable) / len(testable_impacted)
            if testable_impacted else 0.0
        )

        # persist selections
        db.query(TestSelection).filter_by(analysis_fk=ctx.analysis_id).delete()
        for item in result["selected"] + result["excluded"]:
            db.add(TestSelection(
                analysis_fk=ctx.analysis_id,
                test_case_id=item["test_case_id"],
                code=item["code"],
                rank=item["rank"],
                score=item["score"],
                reason=item["reason"],
                included=item["included"],
                excluded_reason=item["excluded_reason"],
            ))
        db.commit()

        total = result["total_test_cases"]
        selected = result["selected"]
        names = [s["code"] for s in selected]
        out.evidence.append(make_evidence(
            "tool:select_regression_tests",
            f"Selected {len(selected)} of {total} regression tests "
            f"(scope reduction to {round(len(selected) / max(1, total) * 100, 1)}%); "
            f"{result['excluded_count']} excluded as unaffected or below threshold.",
            0.95))
        for s in selected[:8]:
            out.evidence.append(make_evidence(
                "tool:select_regression_tests",
                f"Test {s['code']} ranked #{s['rank']} (score {s['score']}): {s['reason']}",
                0.9, f"test_case:{s['test_case_id']}"))
        out.output = {
            "selected_tests": [
                {"code": s["code"], "rank": s["rank"], "score": s["score"], "reason": s["reason"]}
                for s in selected
            ],
            "excluded_tests": [s["code"] for s in result["excluded"]],
            "excluded_count": result["excluded_count"],
            "total_test_cases": total,
            "scope_reduction_ratio": round(len(selected) / max(1, total), 4),
            "coverage_gap_ratio": round(coverage_gap, 4),
            "selected_defect_rates": [
                db.get(TestCase, s["test_case_id"]).defect_rate for s in selected
            ],
            "rationale": self.rationale(ctx, {
                "stage": self.name,
                "changed_objects": [s[0] for s in ctx.seeds],
                "selected_tests": names,
                "excluded_tests": result["excluded_count"],
                "total_tests": total,
                "findings": ["Selection is minimal and reason-coded, not rerun-everything."],
            }),
        }
        out.actions.append({
            "action": "persist_test_selection",
            "input_json": {"analysis_id": ctx.analysis_id},
            "result_summary": f"{len(selected)} selected / {result['excluded_count']} excluded",
        })
        out.decision = {
            "decision": f"Regression scope fixed at {len(selected)} tests ({names}).",
            "confidence": 0.9,
            "alternatives": ["full regression rerun (rejected: cost without signal)",
                             "no regression (rejected: unbounded risk)"],
            "risk_level": "NONE",
            "requires_approval": False,
        }
        return out

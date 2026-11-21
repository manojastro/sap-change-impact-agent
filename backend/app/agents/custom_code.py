"""Stage 2: Custom Code Agent - where-used analysis for custom ABAP objects."""
from __future__ import annotations

from backend.app.graph.dependency_graph import CUSTOM_CODE, TABLE_FIELD

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class CustomCodeAgent(BaseAgent):
    name = "custom_code"
    description = "Where-used analysis of custom code and table-field consumers via the graph."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        impacted_code = []
        evidence_items = []
        for key in sorted(ctx.closure.keys()):
            if ctx.graph.node_type(key) == CUSTOM_CODE:
                label = ctx.graph.label(key)
                callers = [ctx.graph.label(s) for s in ctx.graph.g.successors(key)]
                impacted_code.append({"node_key": key, "name": label, "called_by": callers})
                evidence_items.append(make_evidence(
                    "graph:CUSTOM_CODE_CALLED_BY_TRANSACTION",
                    f"Custom code {label} is called by {', '.join(callers) or 'batch jobs only'}.",
                    0.95, key))
        field_consumers = []
        for key, meta in ctx.closure.items():
            if ctx.graph.node_type(key) == TABLE_FIELD:
                field_consumers.append({"field": ctx.graph.label(key),
                                        "distance": meta["distance"]})
        if not impacted_code and not field_consumers:
            evidence_items.append(make_evidence(
                "graph:closure", "No custom ABAP objects inside the impact radius.", 0.95))
        facts = {
            "stage": self.name,
            "changed_objects": [s[0] for s in ctx.seeds],
            "findings": [
                f"{len(impacted_code)} custom code object(s) within impact radius.",
                f"{len(field_consumers)} table field seed(s) under review.",
            ],
        }
        out.output = {"impacted_custom_code": impacted_code,
                      "table_field_seeds": field_consumers,
                      "rationale": self.rationale(ctx, facts)}
        out.evidence.extend(evidence_items)
        out.decision = {
            "decision": f"Where-used complete: {len(impacted_code)} custom code objects impacted.",
            "confidence": 0.93,
            "alternatives": ["manual where-used list from SE80-like index (not simulated)"],
            "risk_level": "NONE" if not impacted_code else "LOW",
            "requires_approval": False,
        }
        return out

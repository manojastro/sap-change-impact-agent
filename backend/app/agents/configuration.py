"""Stage 3: Configuration Agent - consumers of changed configuration records."""
from __future__ import annotations

from backend.app.graph.dependency_graph import CONFIG_ITEM

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class ConfigurationAgent(BaseAgent):
    name = "configuration"
    description = "Maps changed customizing records to their consuming transactions/code."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        impacted_config = []
        evidence_items = []
        for key in sorted(ctx.closure.keys()):
            if ctx.graph.node_type(key) == CONFIG_ITEM:
                label = ctx.graph.label(key)
                consumers = [{"node_key": s, "label": ctx.graph.label(s)}
                             for s in ctx.graph.g.successors(key) if s in ctx.closure]
                impacted_config.append({"node_key": key, "name": label, "consumers": consumers})
                evidence_items.append(make_evidence(
                    "graph:CONFIG_USED_BY_TRANSACTION",
                    f"Configuration {label} is consumed by "
                    f"{', '.join(c['label'] for c in consumers) or 'no transaction inside radius'}.",
                    0.95, key))
        if not impacted_config:
            evidence_items.append(make_evidence(
                "graph:closure", "No configuration records inside the impact radius.", 0.95))
        out.output = {
            "impacted_config_items": impacted_config,
            "rationale": self.rationale(ctx, {
                "stage": self.name,
                "changed_objects": [s[0] for s in ctx.seeds],
                "findings": [f"{len(impacted_config)} configuration record(s) inside impact radius."],
            }),
        }
        out.evidence.extend(evidence_items)
        out.decision = {
            "decision": f"Configuration consumer mapping complete ({len(impacted_config)} records).",
            "confidence": 0.92,
            "alternatives": [],
            "risk_level": "NONE",
            "requires_approval": False,
        }
        return out

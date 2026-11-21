"""Stage 5: Interface Impact Agent - inbound/outbound interfaces and partners."""
from __future__ import annotations

from backend.app.graph.dependency_graph import INTERFACE

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class InterfaceImpactAgent(BaseAgent):
    name = "interface_impact"
    description = "Identifies impacted interfaces, directions and partner systems."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        interfaces = []
        for key in sorted(ctx.closure.keys()):
            if ctx.graph.node_type(key) != INTERFACE:
                continue
            attrs = ctx.graph.g.nodes[key]
            meta = ctx.closure[key]
            impl_by = [ctx.graph.label(p) for p in ctx.graph.g.predecessors(key)]
            entry = {
                "node_key": key,
                "name": ctx.graph.label(key),
                "direction": attrs.get("direction", ""),
                "kind": attrs.get("kind", ""),
                "partner": attrs.get("partner", ""),
                "distance": meta["distance"],
                "implemented_by": [x for x in impl_by],
            }
            interfaces.append(entry)
            out.evidence.append(make_evidence(
                "graph:INTERFACE_IMPL_BY_CUSTOM_CODE",
                f"Interface {entry['name']} ({entry['direction']}, partner {entry['partner']}) "
                f"impacted; implemented by {', '.join(entry['implemented_by']) or 'standard'}.",
                0.93, key))
        if not interfaces:
            out.evidence.append(make_evidence(
                "graph:closure", "No interface inside the impact radius.", 0.95))
        names = ", ".join(i["name"] for i in interfaces) or "none"
        out.output = {
            "impacted_interfaces": interfaces,
            "partner_notification_required": bool(interfaces),
            "rationale": self.rationale(ctx, {
                "stage": self.name,
                "changed_objects": [s[0] for s in ctx.seeds],
                "impacted_interfaces": [i["name"] for i in interfaces],
                "findings": [
                    f"Interfaces within radius: {names}.",
                    "Partner systems require notification before release." if interfaces else "",
                ],
            }),
        }
        out.decision = {
            "decision": f"{len(interfaces)} interface(s) impacted ({names}).",
            "confidence": 0.92,
            "alternatives": [],
            "risk_level": "MEDIUM" if interfaces else "NONE",
            "requires_approval": False,
        }
        return out

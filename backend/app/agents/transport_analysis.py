"""Stage 1: Transport Analysis Agent - parse and classify the imported transport."""
from __future__ import annotations

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class TransportAnalysisAgent(BaseAgent):
    name = "transport_analysis"
    description = "Parses the transport, classifies change types, computes size metrics."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        result = ctx.tools.execute("analyze_transport", {"transport_pk": ctx.transport.id},
                                   session=ctx.db, analysis_id=ctx.analysis_id)
        size = result.get("size", {})
        cats = result.get("change_type_counts", {})
        facts_txt = "; ".join(f"{k}={v}" for k, v in sorted(cats.items())) or "no classified changes"
        out.output = {
            "change_types": cats,
            "size": size,
            "declared_change_type": ctx.transport.change_type,
            "objects": result.get("objects", []),
            "rationale": self.rationale(ctx, {
                "stage": self.name,
                "changed_objects": [f'{o["type"]}:{o["key"]}' for o in result.get("objects", [])],
                "findings": [
                    f"Transport {ctx.transport.transport_id} ({ctx.transport.kind}) "
                    f"declared as {ctx.transport.change_type}.",
                    f"Classified change categories: {facts_txt}.",
                    f"Size bucket {size.get('size_bucket')} "
                    f"({size.get('objects_changed')} objects, {size.get('loc_delta')} LOC delta).",
                ],
            }),
        }
        out.evidence.append(make_evidence(
            "tool:analyze_transport",
            f"Transport {ctx.transport.transport_id} contains {size.get('objects_changed')} changed objects: {facts_txt}.",
            0.97, f"transport:{ctx.transport.id}"))
        out.evidence.append(make_evidence(
            "tool:analyze_transport",
            f"Size metrics: bucket={size.get('size_bucket')}, loc_delta={size.get('loc_delta')}, config={size.get('config_changes')}.",
            0.95, f"transport:{ctx.transport.id}"))
        out.hypotheses.append({
            "statement": "Transport is classifiable with the standard change taxonomy.",
            "status": "CONFIRMED", "confidence": 0.9,
        })
        out.decision = {
            "decision": f"Classified as {', '.join(sorted(cats)) or 'UNKNOWN'}; size {size.get('size_bucket')}.",
            "confidence": 0.95,
            "alternatives": ["reject import on taxonomy mismatch (not applicable)"],
            "risk_level": {"LARGE": "MEDIUM", "MEDIUM": "LOW", "SMALL": "NONE"}[size.get("size_bucket", "SMALL")],
            "requires_approval": False,
        }
        return out

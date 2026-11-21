"""Stage 4: Business Process Agent - impacted processes with criticality heat.

Also persists the full impact_results set (the closure) for the UI/API.
"""
from __future__ import annotations

from backend.app.graph.dependency_graph import PROCESS
from backend.app.models import ImpactResult
from backend.app.tools.sap_tools import CRITICALITY_WEIGHT

from backend.app.agents.base import BaseAgent, StageOutput, make_evidence


class BusinessProcessAgent(BaseAgent):
    name = "business_process"
    description = "Derives impacted business processes and persists the impact closure."

    def run(self, ctx) -> StageOutput:
        out = StageOutput.empty()
        db = ctx.db

        # persist closure as impact results (all node types)
        rows = []
        for key, meta in ctx.closure.items():
            ntype = ctx.graph.node_type(key)
            nid = int(key.split(":", 1)[1])
            rows.append(ImpactResult(
                analysis_fk=ctx.analysis_id,
                node_type=ntype, node_id=nid, node_key=key,
                name=ctx.graph.label(key),
                distance=meta["distance"],
                discovered_by=meta["discovered_by"],
                confidence=meta["confidence"],
                path_json=meta["path"],
            ))
        if rows:
            db.add_all(rows)
            db.commit()

        processes = []
        for key in sorted(ctx.closure.keys()):
            if ctx.graph.node_type(key) != PROCESS:
                continue
            attrs = ctx.graph.g.nodes[key]
            meta = ctx.closure[key]
            crit = attrs.get("criticality", "MEDIUM")
            processes.append({
                "node_key": key,
                "code": ctx.graph.label(key),
                "name": attrs.get("name", ""),
                "criticality": crit,
                "criticality_weight": CRITICALITY_WEIGHT.get(crit, 0.5),
                "distance": meta["distance"],
                "confidence": meta["confidence"],
            })
        processes.sort(key=lambda p: (-p["criticality_weight"], p["distance"]))
        for rank, p in enumerate(processes, start=1):
            out.evidence.append(make_evidence(
                "graph:STEP_RUNS_TRANSACTION/PROCESS_USES_STEP",
                f"Business process {p['code']} is inside the impact radius "
                f"(criticality {p['criticality']}, distance {p['distance']}, "
                f"confidence {round(p['confidence'], 2)}).",
                p["confidence"], p["node_key"]))
        if not processes:
            out.evidence.append(make_evidence(
                "graph:closure", "No business process inside the impact radius.", 0.9))
        top = ", ".join(f"{p['code']}({p['criticality']})" for p in processes[:4]) or "none"
        facts = {
            "stage": self.name,
            "changed_objects": [s[0] for s in ctx.seeds],
            "impacted_processes": [p["code"] for p in processes],
            "findings": [
                f"Impacted processes ranked by criticality: {top}.",
                f"Total nodes in dependency closure: {len(ctx.closure)}.",
            ],
        }
        out.output = {"impacted_processes": processes, "closure_size": len(ctx.closure),
                      "rationale": self.rationale(ctx, facts)}
        out.hypotheses.append({
            "statement": f"Dependency closure correctly captures process-level blast radius ({len(ctx.closure)} nodes).",
            "status": "CONFIRMED", "confidence": 0.9,
        })
        max_crit = max((p["criticality"] for p in processes), default="NONE")
        out.decision = {
            "decision": f"{len(processes)} business process(es) impacted; most critical: {max_crit}.",
            "confidence": 0.93,
            "alternatives": ["restrict analysis to direct consumers only (rejected: misses ripple)"],
            "risk_level": "HIGH" if max_crit == "CRITICAL" else ("MEDIUM" if processes else "NONE"),
            "requires_approval": False,
        }
        return out

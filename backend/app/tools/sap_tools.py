"""SAP impact tools - the deterministic decision core exposed to agents.

Every tool is pure computation over the simulated estate (DB + NetworkX
graph). Agents call them through the audited ToolRegistry. There are NO shell
or network tools.

Tools:
  analyze_transport       classify changed objects, size metrics
  query_where_used        direct consumers of an estate object
  traverse_impact         dependency-closure impact discovery
  select_regression_tests minimal high-value regression scope (NOT rerun-all)
  compute_risk_score      weighted release-risk with factor breakdown
  run_regression_suite    simulated deterministic regression execution
  record_defect           raise a defect into the platform + ALM mock
  export_release_plan     push release plan to SAP Cloud ALM mock
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from backend.app.graph.dependency_graph import (
    BATCH_JOB, CONFIG_ITEM, CUSTOM_CODE, INTERFACE, PROCESS, TABLE, TABLE_FIELD,
    TEST_CASE, TRANSACTION, DependencyGraph, node_key, split_key,
)
from backend.app.models import (
    ConfigItem, CustomCode, Defect, DefectSeed, FioriApp, ImpactResult,
    InterfaceDef, RiskAssessment, Role, SapTable, TableField, TestCase,
    Transport, TransportObject,
)
from backend.app.tools.base import ToolRegistry, ToolSpec

CRITICALITY_WEIGHT = {"CRITICAL": 1.0, "HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}

RISK_WEIGHTS = {
    "process_criticality": 0.30,
    "process_breadth": 0.10,
    "custom_code": 0.15,
    "interfaces": 0.15,
    "failure_history": 0.10,
    "coverage_gap": 0.10,
    "size": 0.10,
}

SELECTION_THRESHOLD = 0.35
DEFECT_RATE_NORM = 0.12  # historical failure rate that maps to full weight

TEST_SELECTION_WEIGHTS = {
    "coverage_focus": 0.45,   # how much of the blast radius this test watches
    "criticality": 0.25,      # business criticality of the test
    "failure_history": 0.15,  # historical defect rate
    "interface_involvement": 0.15,
}


# ------------------------------------------------------------------ helpers


def resolve_transport_object(session: Session, obj: TransportObject) -> list[tuple[str, bool]]:
    """Map a transport object onto graph seed nodes -> [(node_key, value_affecting)]."""
    va = bool(obj.value_affecting)
    t, k = obj.object_type, obj.object_key
    seeds: list[tuple[str, bool]] = []

    def find_by(model, attr, val):
        return session.query(model).filter(getattr(model, attr) == val).first()

    if t == "TABLE":
        row = find_by(SapTable, "name", k)
        if row:
            seeds.append((node_key(TABLE, row.id), True))
    elif t == "TABLE_FIELD":
        tname, _, fname = k.partition(".")
        tbl = find_by(SapTable, "name", tname)
        fname = fname or obj.field_name
        if tbl and fname:
            fld = session.query(TableField).filter_by(table_id=tbl.id, name=fname).first()
            if fld:
                seeds.append((node_key(TABLE_FIELD, fld.id), True))
                seeds.append((node_key(TABLE, tbl.id), True))
    elif t in ("CUSTOM_CODE", "WORKFLOW"):
        row = find_by(CustomCode, "name", k)
        if row:
            seeds.append((node_key(CUSTOM_CODE, row.id), va))
    elif t == "CONFIG_ITEM":
        row = find_by(ConfigItem, "key", k)
        if row:
            seeds.append((node_key(CONFIG_ITEM, row.id), va))
    elif t == "ROLE":
        row = find_by(Role, "name", k)
        if row:
            seeds.append((node_key("ROLE", row.id), False))
    elif t in ("INTERFACE_DEF", "ODATA_SPEC"):
        row = find_by(InterfaceDef, "name", k)
        if row:
            seeds.append((node_key(INTERFACE, row.id), False))
    elif t == "FIORI_APP":
        row = find_by(FioriApp, "code", k)
        if row:
            seeds.append((node_key("FIORI_APP", row.id), False))
    return seeds


def classify_change_types(objects: list[TransportObject]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in objects:
        cat = {
            "TABLE": "TABLE_FIELD_CHANGE", "TABLE_FIELD": "TABLE_FIELD_CHANGE",
            "CUSTOM_CODE": "ABAP_CHANGE", "WORKFLOW": "WORKFLOW_CHANGE",
            "CONFIG_ITEM": "CONFIG_CHANGE", "ROLE": "ROLE_CHANGE",
            "ODATA_SPEC": "ODATA_CHANGE", "FIORI_APP": "FIORI_APP_CHANGE",
            "INTERFACE_DEF": "INTERFACE_CHANGE",
        }.get(o.object_type, "ABAP_CHANGE")
        if o.object_type == "CONFIG_ITEM" and str(o.details.get("category", "")).upper() == "PRICING":
            cat = "PRICING_CHANGE"
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def size_metrics(transport: Transport, n_objects: int, config_changes: int) -> dict:
    loc = max(int(transport.loc_delta or 0), 0)
    if n_objects >= 6 or loc >= 500:
        bucket = "LARGE"
    elif n_objects >= 3 or loc >= 150 or config_changes >= 2:
        bucket = "MEDIUM"
    else:
        bucket = "SMALL"
    return {
        "objects_changed": n_objects,
        "config_changes": config_changes,
        "loc_delta": loc,
        "size_bucket": bucket,
    }


# ------------------------------------------------------------------ test selection


def _test_candidates(graph: DependencyGraph, closure: dict[str, dict]) -> list[str]:
    """Tests validating at least one impacted object."""
    out = []
    for key in closure:
        for succ in graph.g.successors(key):
            if graph.node_type(succ) == TEST_CASE and succ not in out:
                out.append(succ)
    return out


def score_test_candidate(
    *,
    covered_impacted: int,
    total_validated: int,
    criticality: str,
    defect_rate: float,
    covers_interface: bool,
) -> tuple[float, dict]:
    w = TEST_SELECTION_WEIGHTS
    focus = covered_impacted / max(1, total_validated)
    crit_w = CRITICALITY_WEIGHT.get(criticality, 0.5)
    hist = min(1.0, defect_rate / DEFECT_RATE_NORM)
    iface = 1.0 if covers_interface else 0.0
    parts = {
        "coverage_focus": round(w["coverage_focus"] * focus, 4),
        "criticality": round(w["criticality"] * crit_w, 4),
        "failure_history": round(w["failure_history"] * hist, 4),
        "interface_involvement": round(w["interface_involvement"] * iface, 4),
    }
    return round(sum(parts.values()), 4), parts


def select_regression_tests(
    graph: DependencyGraph,
    session: Session,
    closure: dict[str, dict],
    seed_keys: set[str],
) -> dict:
    """Deterministic minimal-regression-scope selection with reasons."""
    impacted = set(closure.keys())
    candidates = _test_candidates(graph, closure)
    selected: list[dict] = []
    excluded: list[dict] = []
    total_tests = session.query(TestCase).count()

    for cand in candidates:
        tc_row = session.get(TestCase, int(split_key(cand)[1]))
        validated = sorted(graph.g.predecessors(cand))
        covered = [v for v in validated if v in impacted]
        if not covered:
            continue
        covers_iface = any(graph.node_type(v) == INTERFACE for v in covered)
        score, parts = score_test_candidate(
            covered_impacted=len(covered),
            total_validated=len(validated),
            criticality=graph.g.nodes[cand].get("criticality", "MEDIUM"),
            defect_rate=tc_row.defect_rate,
            covers_interface=covers_iface,
        )
        cov_txt = ", ".join(graph.label(v) for v in covered)
        reason = (
            f"validates impacted {cov_txt} "
            f"(coverage focus {len(covered)}/{len(validated)}); "
            f"criticality {tc_row.criticality}; historical defect rate "
            f"{tc_row.historical_failures}/{tc_row.historical_runs}"
            + ("; guards external interface" if covers_iface else "")
            + "."
        )
        item = {
            "test_case_id": tc_row.id, "code": tc_row.code, "rank": 0,
            "score": score, "reason": reason, "included": True,
            "excluded_reason": "", "parts": parts,
        }
        if score >= SELECTION_THRESHOLD or covers_iface:
            selected.append(item)
        else:
            item["included"] = False
            item["excluded_reason"] = f"score {score} below threshold {SELECTION_THRESHOLD} and no interface coverage"
            excluded.append(item)

    selected.sort(key=lambda x: (-x["score"], x["code"]))
    for i, s in enumerate(selected, start=1):
        s["rank"] = i
    excluded.sort(key=lambda x: (-x["score"], x["code"]))
    return {
        "selected": selected,
        "excluded": excluded,
        "total_test_cases": total_tests,
        "selected_count": len(selected),
        "excluded_count": len(excluded) + (total_tests - len(candidates)),
    }


# ------------------------------------------------------------------ risk scoring


def compute_risk(
    *,
    impacted_processes: list[tuple[str, str]],   # (code, criticality)
    custom_code_count: int,
    interface_count: int,
    selected_defect_rates: list[float],
    coverage_gap_ratio: float,
    size_bucket: str,
) -> dict:
    """Deterministic weighted release-risk score (0..100) + factor breakdown."""
    crit_vals = [CRITICALITY_WEIGHT.get(c, 0.5) for _, c in impacted_processes]
    if crit_vals:
        max_c, avg_c = max(crit_vals), sum(crit_vals) / len(crit_vals)
        proc_raw = 0.7 * max_c + 0.3 * avg_c
    else:
        proc_raw = 0.0
    breadth_raw = min(1.0, len(crit_vals) / 3.0)
    size_map = {"SMALL": 0.25, "MEDIUM": 0.5, "LARGE": 1.0}
    size_raw = size_map.get(size_bucket, 0.25)
    custom_raw = 0.0 if custom_code_count == 0 else min(1.0, size_raw + 0.3 * (custom_code_count - 1))
    iface_raw = min(1.0, interface_count / 2.0)
    hist_raw = min(1.0, max(selected_defect_rates, default=0.0) / DEFECT_RATE_NORM)
    gap_raw = min(1.0, max(0.0, coverage_gap_ratio))

    raws = {
        "process_criticality": proc_raw,
        "process_breadth": breadth_raw,
        "custom_code": custom_raw,
        "interfaces": iface_raw,
        "failure_history": hist_raw,
        "coverage_gap": gap_raw,
        "size": size_raw,
    }
    breakdown = {}
    total = 0.0
    for name, weight in RISK_WEIGHTS.items():
        contribution = round(weight * raws[name] * 100.0, 2)
        breakdown[name] = {"weight": weight, "raw": round(raws[name], 4), "contribution": contribution}
        total += contribution
    total = round(total, 2)
    band = band_for_score(total)
    return {"score": total, "band": band, "factor_breakdown": breakdown}


def band_for_score(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


# ------------------------------------------------------------------ tool registry


def build_registry(session: Session, graph: DependencyGraph | None = None,
                   analysis_id: int = 0, audit: bool = True) -> ToolRegistry:
    reg = ToolRegistry()
    graph = graph or DependencyGraph.from_session(session)

    def analyze_transport(payload: dict) -> dict:
        tr = session.get(Transport, int(payload["transport_pk"]))
        if tr is None:
            return {"error": "transport not found"}
        objs = tr.objects.all() if hasattr(tr.objects, "all") else list(tr.objects)
        cats = classify_change_types(list(objs))
        config_changes = sum(1 for o in objs if o.object_type == "CONFIG_ITEM")
        sm = size_metrics(tr, len(list(objs)), config_changes)
        return {"change_type_counts": cats, "size": sm,
                "objects": [{"type": o.object_type, "key": o.object_key,
                             "action": o.change_action, "value_affecting": o.value_affecting}
                            for o in objs]}

    def query_where_used(payload: dict) -> dict:
        key = payload["node_key"]
        if not graph.has_node(key):
            return {"error": f"unknown node {key}", "consumers": []}
        return {"node_key": key, "label": graph.label(key), "consumers": graph.where_used(key)}

    def traverse_impact(payload: dict) -> dict:
        seeds = payload.get("seeds") or []
        closure = graph.impacted_closure([(s["node_key"], bool(s.get("value_affecting", True))) for s in seeds])
        return {
            "seed_count": len(seeds),
            "impacted_count": len(closure),
            "impacted": [
                {"node_key": k, "type": graph.node_type(k), "label": graph.label(k),
                 "distance": v["distance"], "confidence": v["confidence"],
                 "discovered_by": v["discovered_by"], "path": v["path"]}
                for k, v in sorted(closure.items(), key=lambda kv: kv[1]["distance"])
            ],
        }

    def select_tests_tool(payload: dict) -> dict:
        seeds = payload.get("seeds") or []
        closure = graph.impacted_closure([(s["node_key"], bool(s.get("value_affecting", True))) for s in seeds])
        seed_keys = {s["node_key"] for s in seeds}
        result = select_regression_tests(graph, session, closure, seed_keys)
        result.pop("parts", None)
        return result

    def compute_risk_tool(payload: dict) -> dict:
        result = compute_risk(
            impacted_processes=[(p, c) for p, c in payload.get("impacted_processes", [])],
            custom_code_count=int(payload.get("custom_code_count", 0)),
            interface_count=int(payload.get("interface_count", 0)),
            selected_defect_rates=[float(x) for x in payload.get("selected_defect_rates", [])],
            coverage_gap_ratio=float(payload.get("coverage_gap_ratio", 0.0)),
            size_bucket=str(payload.get("size_bucket", "SMALL")),
        )
        return result

    def run_regression_suite(payload: dict) -> dict:
        # Heavy orchestration lives in services.validation_service; the tool
        # delegates so that agent-driven and API-driven runs share one path.
        from backend.app.services.validation_service import run_validation_for_transport

        val = run_validation_for_transport(session, int(payload["transport_pk"]), analysis_id=int(payload.get("analysis_pk", 0)))
        return {"validation_id": val.id, "status": val.status, "passed": val.passed,
                "failed": val.failed, "release_confidence": val.release_confidence}

    def record_defect(payload: dict) -> dict:
        from backend.app.services.alm_service import get_alm_adapter

        seq = session.query(Defect).count() + 1
        d = Defect(code=f"DEF-{seq:04d}",
                   transport_fk=int(payload.get("transport_fk", 0)),
                   validation_fk=int(payload.get("validation_fk", 0)),
                   title=payload["title"], severity=payload.get("severity", "HIGH"))
        session.add(d)
        session.commit()
        adapter = get_alm_adapter(session)
        adapter.record_defect(external_id=d.code, title=d.title, severity=d.severity,
                              transport_id="", test_code=payload.get("test_code", ""))
        return {"defect_code": d.code}

    def export_release_plan_tool(payload: dict) -> dict:
        from backend.app.services.alm_service import get_alm_adapter

        adapter = get_alm_adapter(session)
        plan = adapter.export_release_plan(release=payload.get("release", "REL-NEXT"),
                                           transport_ids=payload.get("transport_ids", []))
        return plan

    reg.register(ToolSpec(name="analyze_transport",
                          description="Classify transport changes and size metrics.",
                          input_schema={"required": ["transport_pk"], "type": "object"},
                          handler=analyze_transport))
    reg.register(ToolSpec(name="query_where_used",
                          description="Direct consumers of an estate object node.",
                          input_schema={"required": ["node_key"], "type": "object"},
                          handler=query_where_used))
    reg.register(ToolSpec(name="traverse_impact",
                          description="Dependency-closure impact discovery from seed nodes.",
                          input_schema={"required": ["seeds"], "type": "object"},
                          handler=traverse_impact))
    reg.register(ToolSpec(name="select_regression_tests",
                          description="Minimal high-value regression scope selection.",
                          input_schema={"required": ["seeds"], "type": "object"},
                          handler=select_tests_tool))
    reg.register(ToolSpec(name="compute_risk_score",
                          description="Weighted release-risk score with factor breakdown.",
                          input_schema={"required": [], "type": "object"},
                          handler=compute_risk_tool))
    reg.register(ToolSpec(name="run_regression_suite",
                          description="Execute the simulated regression suite for a transport.",
                          input_schema={"required": ["transport_pk"], "type": "object"},
                          handler=run_regression_suite))
    reg.register(ToolSpec(name="record_defect",
                          description="Raise a defect in the platform and the ALM mock.",
                          input_schema={"required": ["title"], "type": "object"},
                          handler=record_defect))
    reg.register(ToolSpec(name="export_release_plan",
                          description="Export the release plan to the ALM mock.",
                          input_schema={"required": [], "type": "object"},
                          handler=export_release_plan_tool))
    return reg

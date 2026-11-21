"""Tool tests: unknown tool rejected, audit rows persisted, registry contents."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from backend.app.graph.dependency_graph import DependencyGraph
from backend.app.models import ToolCallRow
from backend.app.db import get_session_factory
from backend.app.tools.base import ToolRegistry, UnknownToolError
from backend.app.tools.sap_tools import build_registry
from simulator.generate_landscape import seed_landscape

EXPECTED_TOOLS = {
    "analyze_transport", "query_where_used", "traverse_impact",
    "select_regression_tests", "compute_risk_score", "run_regression_suite",
    "record_defect", "export_release_plan",
}


@pytest.fixture()
def db():
    session = get_session_factory()()
    seed_landscape(session)
    yield session
    session.close()


def test_registry_has_exactly_the_sap_tools(db):
    reg = build_registry(db)
    names = {t["name"] for t in reg.list_tools()}
    assert names == EXPECTED_TOOLS


def test_unknown_tool_rejected(db):
    reg = build_registry(db)
    with pytest.raises(UnknownToolError):
        reg.execute("delete_everything", {}, session=db)


def test_execute_requires_declared_inputs(db):
    reg = build_registry(db, audit=False)
    from backend.app.tools.base import ToolError

    with pytest.raises(ToolError):
        reg.execute("analyze_transport", {}, session=db)  # transport_pk missing


def test_execute_audits_tool_calls(db):
    reg = build_registry(db)
    before = db.query(ToolCallRow).count()
    result = reg.execute("analyze_transport",
                         {"transport_pk": 999999}, session=db, audit=True)
    # unknown transport handled inside handler (no raise), audit still written
    after = db.query(ToolCallRow).count()
    assert after == before + 1
    row = db.query(ToolCallRow).order_by(ToolCallRow.id.desc()).first()
    assert row.tool == "analyze_transport"
    assert row.duration_ms >= 0


def test_traverse_impact_canonical_shape(db):
    from backend.app.models import ConfigItem, CustomCode
    from backend.app.tools.sap_tools import resolve_transport_object
    from backend.app.models import TransportObject

    reg = build_registry(db)
    cfg = db.query(ConfigItem).filter_by(key="PRICING_COND_TYPE_ZPR0").first()
    code = db.query(CustomCode).filter_by(name="Z_PRICING_DETERMINATION_EXIT").first()
    seeds = [
        {"node_key": f"CONFIG_ITEM:{cfg.id}", "value_affecting": True},
        {"node_key": f"CUSTOM_CODE:{code.id}", "value_affecting": True},
    ]
    result = reg.execute("traverse_impact", {"seeds": seeds}, session=db, audit=False)
    labels = {i["label"] for i in result["impacted"]}
    assert "ORDER_TO_CASH" in labels
    assert "RECORD_TO_REPORT" in labels
    assert "INVOIC_OUT" in labels
    assert "BILLING_CREATE" in labels


def test_select_tests_excludes_unaffected_processes(db):
    from backend.app.models import ConfigItem, CustomCode

    reg = build_registry(db)
    cfg = db.query(ConfigItem).filter_by(key="PRICING_COND_TYPE_ZPR0").first()
    code = db.query(CustomCode).filter_by(name="Z_PRICING_DETERMINATION_EXIT").first()
    result = reg.execute(
        "select_regression_tests",
        {"seeds": [
            {"node_key": f"CONFIG_ITEM:{cfg.id}", "value_affecting": True},
            {"node_key": f"CUSTOM_CODE:{code.id}", "value_affecting": True},
        ]},
        session=db, audit=False)
    selected = [t["code"] for t in result["selected"]]
    assert set(selected) == {"SO_CREATE_TEST", "BILLING_CREATE_TEST",
                             "FI_RECONCILIATION_TEST", "INVOIC_PAYLOAD_TEST"}
    assert result["selected_count"] < result["total_test_cases"]

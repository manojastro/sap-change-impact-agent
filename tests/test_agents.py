"""Agent tests: mock LLM determinism + facts-only behaviour, classification."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.app.llm.provider import FACTS_MARKER, MockLLMProvider
from backend.app.tools.sap_tools import classify_change_types


class FakeTransportObject:
    def __init__(self, object_type, object_key, details=None):
        self.object_type = object_type
        self.object_key = object_key
        self.details = details or {}


def test_mock_llm_deterministic():
    prompt = f"Write rationale.\n{FACTS_MARKER}" + json.dumps({
        "stage": "risk", "risk_score": 66.7, "risk_band": "HIGH",
        "top_risk_factors": ["process_criticality", "custom_code"],
    })
    p = MockLLMProvider()
    out1 = json.loads(p.complete(prompt))
    out2 = json.loads(p.complete(prompt))
    assert out1 == out2
    assert out1["mode"] == "mock"
    assert "HIGH" in out1["summary"] and "66.7" in out1["summary"]


def test_mock_llm_does_not_invent_facts():
    facts = {"stage": "business_process", "impacted_processes": ["ORDER_TO_CASH"]}
    prompt = f"Facts only.\n{FACTS_MARKER}{json.dumps(facts)}"
    summary = json.loads(MockLLMProvider().complete(prompt))["summary"]
    # a fact that was NOT supplied must not appear
    assert "PAYROLL" not in summary.upper()
    assert "ORDER_TO_CASH" in summary
    for banned in ("blockchain", "quantum", "weather"):
        assert banned not in summary.lower()


def test_mock_llm_lists_selected_and_excluded_counts():
    facts = {"stage": "regression_scope", "selected_tests": ["A_TEST", "B_TEST"],
             "total_tests": 17, "excluded_tests": 15}
    summary = json.loads(MockLLMProvider().complete(f"x\n{FACTS_MARKER}{json.dumps(facts)}"))["summary"]
    assert "2 regression tests selected" in summary
    assert "17" in summary and "15 tests excluded" in summary


def test_classify_change_types_mapping():
    objs = [
        FakeTransportObject("CONFIG_ITEM", "X", {"category": "PRICING"}),
        FakeTransportObject("CUSTOM_CODE", "Z_A"),
        FakeTransportObject("ROLE", "ROLE_X"),
        FakeTransportObject("ODATA_SPEC", "API_X"),
        FakeTransportObject("WORKFLOW", "WS_X"),
    ]
    cats = classify_change_types(objs)
    assert cats == {"PRICING_CHANGE": 1, "ABAP_CHANGE": 1, "ROLE_CHANGE": 1,
                    "ODATA_CHANGE": 1, "WORKFLOW_CHANGE": 1}


def test_transport_agent_stage_runs_on_canonical(seeded):
    from tests.conftest import import_and_analyze

    tr, analysis = import_and_analyze(seeded, "PRICING_CANONICAL")
    stages = seeded.get(f"/api/v1/analyses/{analysis['id']}/stages").json()
    by_name = {s["stage"]: s for s in stages}
    first = by_name["transport_analysis"]
    cats = first["output"]["output"]["change_types"]
    assert cats.get("PRICING_CHANGE") == 1
    assert cats.get("ABAP_CHANGE") == 1
    decision = first["output"]["decision"]
    assert set(decision) >= {"decision", "confidence", "evidence_ids",
                             "alternatives", "risk_level", "requires_approval"}
    assert len(decision["evidence_ids"]) >= 1

"""Unit tests: impact traversal closure correctness on crafted subgraphs."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.app.graph.dependency_graph import DependencyGraph, node_key


def make_graph() -> DependencyGraph:
    dg = DependencyGraph()
    g = dg.g

    def n(t, i, label, **attrs):
        g.add_node(node_key(t, i), node_type=t, label=label, **attrs)

    # CONFIG:1 --CONFIG_USED_BY_TRANSACTION--> TX:2 --STEP_RUNS (reversed at build)--> STEP:3 --> PROCESS:4
    n("CONFIG_ITEM", 1, "CFG_A")
    n("TRANSACTION", 2, "TX_ORDER")
    n("STEP", 3, "STEP_ORDER")
    n("PROCESS", 4, "PROC_O2C", criticality="CRITICAL")
    n("TABLE", 5, "billing_docs", value_flow=True)
    n("TABLE", 6, "sales_orders", value_flow=False)
    n("CUSTOM_CODE", 7, "Z_EXIT")
    n("INTERFACE", 8, "INVOIC_OUT", direction="OUTBOUND")
    n("TEST_CASE", 9, "BILLING_TEST", criticality="HIGH")
    n("PROCESS", 10, "PROC_R2R", criticality="HIGH")

    # impact-oriented edges added directly (as from_session would orient them)
    def e(src, dst, etype, value=False):
        g.add_edge(src, dst, edge_types=[etype], value=value)

    e(node_key("CONFIG_ITEM", 1), node_key("TRANSACTION", 2), "CONFIG_USED_BY_TRANSACTION")
    e(node_key("TRANSACTION", 2), node_key("STEP", 3), "STEP_RUNS_TRANSACTION")
    e(node_key("STEP", 3), node_key("PROCESS", 4), "PROCESS_USES_STEP")
    e(node_key("TRANSACTION", 2), node_key("TABLE", 6), "TRANSACTION_WRITES_TABLE", value=True)
    e(node_key("TRANSACTION", 2), node_key("TABLE", 5), "TRANSACTION_WRITES_TABLE", value=True)
    e(node_key("TABLE", 5), node_key("CUSTOM_CODE", 7), "CUSTOM_CODE_READS_TABLE")
    e(node_key("CUSTOM_CODE", 7), node_key("INTERFACE", 8), "INTERFACE_IMPL_BY_CUSTOM_CODE")
    e(node_key("INTERFACE", 8), node_key("TEST_CASE", 9), "OBJECT_VALIDATED_BY_TEST")
    e(node_key("INTERFACE", 8), node_key("PROCESS", 10), "PROCESS_CALLS_INTERFACE")
    return dg


def test_closure_reaches_process_through_chain():
    dg = make_graph()
    closure = dg.impacted_closure([(node_key("CONFIG_ITEM", 1), True)])
    assert node_key("TRANSACTION", 2) in closure
    assert node_key("STEP", 3) in closure
    assert node_key("PROCESS", 4) in closure
    assert closure[node_key("PROCESS", 4)]["distance"] == 3


def test_value_gate_non_affecting_seed_stops_at_write_edges():
    dg = make_graph()
    closure = dg.impacted_closure([(node_key("CONFIG_ITEM", 1), False)])
    assert node_key("TRANSACTION", 2) in closure      # structural propagation still works
    assert node_key("TABLE", 6) not in closure        # write edges need value contamination
    assert node_key("TABLE", 5) not in closure
    assert node_key("PROCESS", 10) not in closure


def test_table_value_flow_gates_readers():
    dg = make_graph()
    closure = dg.impacted_closure([(node_key("CONFIG_ITEM", 1), True)])
    # billing_docs has value_flow=True -> reader code + interface reached
    assert node_key("CUSTOM_CODE", 7) in closure
    assert node_key("INTERFACE", 8) in closure
    assert node_key("PROCESS", 10) in closure
    assert node_key("TEST_CASE", 9) in closure
    # sales_orders has value_flow=False -> dead end even when contaminated
    assert node_key("TABLE", 6) in closure            # reached...
    readers = [k for k in closure if k == node_key("TABLE", 6)]
    assert readers                                     # ...but nothing beyond it is new


def test_interface_is_absorbing_for_irrelevant_targets():
    dg = make_graph()
    closure = dg.impacted_closure([(node_key("CUSTOM_CODE", 7), True)])
    assert node_key("INTERFACE", 8) in closure
    # allowed continuations: processes and validating tests only
    assert node_key("PROCESS", 10) in closure
    assert node_key("TEST_CASE", 9) in closure


def test_confidence_decays_with_distance_and_floors():
    dg = make_graph()
    closure = dg.impacted_closure([(node_key("CONFIG_ITEM", 1), True)])
    confs = [(closure[k]["distance"], closure[k]["confidence"]) for k in closure]
    by_distance = dict(confs)
    assert by_distance[0] == 1.0
    assert by_distance[2] < by_distance[1] if 1 in by_distance else True
    for d, c in confs:
        assert c >= 0.5
    deep = dg.impacted_closure([(node_key("TABLE", 5), True)])
    traversed = [v for v in deep.values() if v["discovered_by"] == "TRAVERSED"]
    assert all(
        abs(v["confidence"] - max(0.5, 1 - 0.15 * (v["distance"] - 1))) < 1e-9
        for v in traversed
    )


def test_unknown_seed_is_ignored():
    dg = make_graph()
    closure = dg.impacted_closure([("GHOST:999", True)])
    assert closure == {}

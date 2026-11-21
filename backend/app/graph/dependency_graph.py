"""Dependency graph built with NetworkX from the DB estate.

Edges are stored in the graph_edges table with natural orientation
(SUBJECT_VERB_OBJECT). At build time every edge is re-oriented into IMPACT
direction (a change at the tail can affect the head), so impact discovery is a
plain forward BFS closure from changed objects.

Orientation rules (see ARCHITECTURE.md for rationale):

  edge type                          stored as            impact direction
  PROCESS_USES_STEP                  process -> step      step -> process
  STEP_RUNS_TRANSACTION              step -> transaction  transaction -> step
  TRANSACTION_READS_TABLE            tx -> table          table -> tx
  TRANSACTION_WRITES_TABLE           tx -> table [VALUE]  tx -> table (value flow)
  TABLE_FIELD_USED_BY_CUSTOM_CODE    field -> code        field -> code
  CUSTOM_CODE_CALLED_BY_TRANSACTION  code -> tx           code -> tx
  PROCESS_CALLS_INTERFACE            process -> iface     iface -> process
  INTERFACE_IMPL_BY_CUSTOM_CODE      iface -> code        code -> iface
  CONFIG_USED_BY_TRANSACTION         config -> tx         config -> tx
  CONFIG_USED_BY_CUSTOM_CODE         config -> code       config -> code
  OBJECT_VALIDATED_BY_TEST           object -> test       object -> test
  USER_ROLE_ASSIGNED_TO_PROCESS      role -> process      role -> process
  FIORI_APP_LAUNCHES_TRANSACTION     fiori -> tx          tx -> fiori
  BATCH_JOB_RUNS_CUSTOM_CODE         job -> code          code -> job
  BATCH_JOB_SUPPORTS_PROCESS         job -> process       job -> process
  TRANSACTION_CALLS_INTERFACE        tx -> iface          iface -> tx
  CUSTOM_CODE_READS_TABLE            code -> table        table -> code
  CUSTOM_CODE_WRITES_TABLE           code -> table [VALUE] code -> table

Value-flow gating: edges marked VALUE only carry "value contamination" when
the seed change is value-affecting (pricing/ABAP/table-field/workflow changes).
A table only forwards contamination to its readers if tables.value_flow is set.
Interface nodes are ABSORBING: expansion continues only to processes, to tests
that validate them and to transactions hosting them (prevents unbounded
ripples through integration hubs).
"""
from __future__ import annotations

from collections import deque

import networkx as nx
from sqlalchemy.orm import Session

from backend.app.models import (
    BatchJob, ConfigItem, CustomCode, FioriApp, GraphEdgeRow, InterfaceDef,
    Process, ProcessStep, Role, SapTable, TableField, TestCase, Transaction,
)

PROCESS = "PROCESS"
STEP = "STEP"
TRANSACTION = "TRANSACTION"
FIORI_APP = "FIORI_APP"
CUSTOM_CODE = "CUSTOM_CODE"
CONFIG_ITEM = "CONFIG_ITEM"
TABLE = "TABLE"
TABLE_FIELD = "TABLE_FIELD"
INTERFACE = "INTERFACE"
BATCH_JOB = "BATCH_JOB"
ROLE = "ROLE"
TEST_CASE = "TEST_CASE"

NODE_TYPES = [PROCESS, STEP, TRANSACTION, FIORI_APP, CUSTOM_CODE, CONFIG_ITEM,
              TABLE, TABLE_FIELD, INTERFACE, BATCH_JOB, ROLE, TEST_CASE]

# value-affecting transport object types propagate monetary/quantity damage
VALUE_AFFECTING_TYPES = {"CUSTOM_CODE", "TABLE", "TABLE_FIELD"}

TESTABLE_NODE_TYPES = {TRANSACTION, CUSTOM_CODE, INTERFACE, BATCH_JOB}

_MAX_DEPTH = 8


def node_key(node_type: str, node_id: int) -> str:
    return f"{node_type}:{node_id}"


def split_key(key: str) -> tuple[str, int]:
    t, i = key.split(":", 1)
    return t, int(i)


class DependencyGraph:
    """Impact-oriented digraph over the simulated estate."""

    def __init__(self) -> None:
        self.g = nx.DiGraph()
        self._labels: dict[str, str] = {}

    # ------------------------------------------------------------ build

    @classmethod
    def from_session(cls, session: Session) -> "DependencyGraph":
        dg = cls()

        def add(ntype: str, nid: int, label: str, **attrs):
            key = node_key(ntype, nid)
            dg.g.add_node(key, node_type=ntype, label=label, **attrs)
            dg._labels[key] = label

        for r in session.query(Process).all():
            add(PROCESS, r.id, r.code, criticality=r.criticality, name=r.name, module=r.module)
        for r in session.query(ProcessStep).all():
            add(STEP, r.id, r.code, name=r.name, sequence=r.sequence)
        for r in session.query(Transaction).all():
            add(TRANSACTION, r.id, r.code, name=r.name, module=r.module)
        for r in session.query(FioriApp).all():
            add(FIORI_APP, r.id, r.code, name=r.name)
        for r in session.query(CustomCode).all():
            add(CUSTOM_CODE, r.id, r.name, code_type=r.code_type)
        for r in session.query(ConfigItem).all():
            add(CONFIG_ITEM, r.id, r.key, category=r.category)
        for r in session.query(SapTable).all():
            add(TABLE, r.id, r.name, value_flow=bool(r.value_flow), module=r.module)
        for r in session.query(TableField).all():
            add(TABLE_FIELD, r.id, f"{r.table.name}.{r.name}" if r.table else r.name)
        for r in session.query(InterfaceDef).all():
            add(INTERFACE, r.id, r.name, direction=r.direction, kind=r.kind, partner=r.partner)
        for r in session.query(BatchJob).all():
            add(BATCH_JOB, r.id, r.name, schedule=r.schedule)
        for r in session.query(Role).all():
            add(ROLE, r.id, r.name, profile=r.profile)
        for r in session.query(TestCase).all():
            add(TEST_CASE, r.id, r.code, criticality=r.criticality)

        # (stored_src -> stored_dst, impact_reversed, value_edge)
        orientation = {
            "PROCESS_USES_STEP": True,               # step impacts process
            "STEP_RUNS_TRANSACTION": True,           # tx impacts step
            "TRANSACTION_READS_TABLE": True,         # table impacts reader tx
            "TRANSACTION_WRITES_TABLE": False,       # writer tx feeds table [value]
            "TABLE_FIELD_USED_BY_CUSTOM_CODE": False,# field impacts using code
            "CUSTOM_CODE_CALLED_BY_TRANSACTION": False,  # code impacts caller tx
            "PROCESS_CALLS_INTERFACE": True,         # interface impacts calling process
            "INTERFACE_IMPL_BY_CUSTOM_CODE": True,   # implementing code impacts interface
            "CONFIG_USED_BY_TRANSACTION": False,     # config impacts consuming tx
            "CONFIG_USED_BY_CUSTOM_CODE": False,     # config impacts consuming code
            "OBJECT_VALIDATED_BY_TEST": False,       # object risk impacts its test (forward)
            "USER_ROLE_ASSIGNED_TO_PROCESS": False,  # role change impacts process access
            "FIORI_APP_LAUNCHES_TRANSACTION": True,  # tx change impacts tile
            "BATCH_JOB_RUNS_CUSTOM_CODE": True,      # code change impacts job
            "BATCH_JOB_SUPPORTS_PROCESS": False,     # job failure impacts process
            "TRANSACTION_CALLS_INTERFACE": True,     # interface change impacts consuming tx
            "CUSTOM_CODE_READS_TABLE": True,         # table change impacts reading code
            "CUSTOM_CODE_WRITES_TABLE": False,       # code writes feed table [value]
        }

        rows = session.query(GraphEdgeRow).all()
        for row in rows:
            if row.edge_type not in orientation:
                continue
            reverse_impact = orientation[row.edge_type]
            src = node_key(row.src_type, row.src_id)
            dst = node_key(row.dst_type, row.dst_id)
            if reverse_impact:
                src, dst = dst, src
            value_edge = row.edge_type in ("TRANSACTION_WRITES_TABLE", "CUSTOM_CODE_WRITES_TABLE")
            etype = row.edge_type
            if not dg.g.has_node(src) or not dg.g.has_node(dst):
                continue
            if not dg.g.has_edge(src, dst):
                dg.g.add_edge(src, dst, edge_types=[etype], value=value_edge)
            else:
                data = dg.g.edges[src, dst]
                if etype not in data["edge_types"]:
                    data["edge_types"].append(etype)
                data["value"] = data.get("value", False) or value_edge
        return dg

    # ------------------------------------------------------------ queries

    def has_node(self, key: str) -> bool:
        return self.g.has_node(key)

    def label(self, key: str) -> str:
        return str(self.g.nodes[key].get("label", key))

    def node_type(self, key: str) -> str:
        return str(self.g.nodes[key].get("node_type", ""))

    def where_used(self, key: str, max_depth: int = 2) -> list[dict]:
        """Direct consumers of an object (nodes that can be impacted BY it,
        i.e. its predecessors in dependency terms / successors in impact
        direction are reachable via impacted_closure; here we list the direct
        impact successors)."""
        if key not in self.g:
            return []
        return [
            {"node": succ, "type": self.node_type(succ), "label": self.label(succ)}
            for succ in self.g.successors(key)
        ]

    def impacted_closure(self, seeds: list[tuple[str, bool]]) -> dict[str, dict]:
        """Multi-source BFS over impact-oriented edges.

        seeds: list of (node_key, value_affecting).
        Returns {node_key: {distance, path, confidence, discovered_by}}.
        """
        result: dict[str, dict] = {}
        queue: deque[tuple[str, bool, int, list]] = deque()
        for key, va in seeds:
            if not self.g.has_node(key):
                continue
            flag = bool(va) or self.node_type(key) in ("TABLE", "TABLE_FIELD")
            if key not in result or flag and not result[key]["_flag"]:
                result[key] = {
                    "distance": 0, "path": [key], "confidence": 1.0,
                    "discovered_by": "DIRECT", "_flag": flag,
                }
                queue.append((key, flag, 0, [key]))

        while queue:
            key, flag, dist, path = queue.popleft()
            if dist >= _MAX_DEPTH:
                continue
            ntype = self.node_type(key)
            for nxt in self.g.successors(key):
                edata = self.g.edges[key, nxt]
                is_value_edge = bool(edata.get("value"))
                nxt_type = self.node_type(nxt)
                # interface absorbing: expansion continues only to processes,
                # validating tests and transactions hosting the interface
                if ntype == INTERFACE and nxt_type not in (PROCESS, TEST_CASE, TRANSACTION):
                    continue
                # leaving a table requires the table to carry consumable values
                if ntype == TABLE and not self.g.nodes[key].get("value_flow", False):
                    continue
                # value edges only traverse when contamination is active
                if is_value_edge and not flag:
                    continue
                new_flag = flag
                if nxt_type == TABLE:
                    new_flag = flag  # contamination flows into the table
                nd = dist + 1
                known = result.get(nxt)
                if known is not None and known["distance"] <= nd and not (new_flag and not known["_flag"]):
                    continue
                entry = {
                    "distance": nd,
                    "path": path + [nxt],
                    "confidence": max(0.5, 1.0 - 0.15 * (nd - 1)),
                    "discovered_by": "TRAVERSED",
                    "_flag": new_flag or (known or {}).get("_flag", False),
                }
                result[nxt] = entry
                queue.append((nxt, entry["_flag"], nd, entry["path"]))
        for v in result.values():
            v.pop("_flag", None)
        return result

    def subgraph_view(self, keys: list[str]) -> dict:
        nodes = []
        for k in keys:
            if not self.g.has_node(k):
                continue
            attrs = self.g.nodes[k]
            nodes.append({
                "key": k, "id": k, "type": self.node_type(k),
                "label": self.label(k), "criticality": attrs.get("criticality", ""),
            })
        edges = []
        keyset = set(keys)
        for u, v, data in self.g.edges(data=True):
            if u in keyset and v in keyset:
                edges.append({"source": u, "target": v, "edge_types": data.get("edge_types", [])})
        return {"nodes": nodes, "edges": edges}

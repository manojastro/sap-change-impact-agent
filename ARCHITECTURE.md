# Architecture

## System shape

```
Browser SPA (vanilla ES modules, zero CDN)
        |
FastAPI  (backend/app/main.py - app factory, CORS from env, safe errors,
        |  StaticFiles mounted LAST so / serves the cockpit)
        |
API routers (api/routes_*.py)
        |
Workflow engine (workflow/engine.py)  -- persisted 8-stage state machine
        |
Agents (agents/*.py) -- one per stage; call tools, never raw guesses
        |
Tool registry (tools/base.py + sap_tools.py) -- audited, deterministic
        |                                   (NO shell/network tools)
Graph core (graph/dependency_graph.py) -- NetworkX DiGraph over graph_edges
        |
SQLAlchemy 2 models (models.py) on SQLite/Postgres (db.py)
        |
LLM provider layer (llm/provider.py) -- Protocol + Mock + OpenAI-compatible
```

## The agentic workflow

`POST /api/v1/analyses` starts a persisted `AnalysisRow`. `run_analysis` executes
eight stages in order, each a class in `backend/app/agents/`:

| # | Stage (agent) | Reads/writes | Decision it owns |
| --- | --- | --- | --- |
| 1 | transport_analysis | analyze_transport tool | change classification, size bucket |
| 2 | custom_code | query_where_used | which custom objects are in the blast radius and who calls them |
| 3 | configuration | config consumers | config items -> transactions/code that read them |
| 4 | business_process | traverse_impact closure | impacted business processes ranked by criticality; persists ImpactResult rows for the whole closure |
| 5 | interface_impact | closure INTERFACE nodes | external interfaces/partners affected |
| 6 | regression_scope | select_regression_tests | minimal high-value test set with per-test reasons; persists TestSelection rows |
| 7 | risk | compute_risk_score | 0..100 weighted risk band; opens approval when policy demands |
| 8 | validation_readiness | gates checks | ready/blocked for release validation |

Every stage run is persisted (`stage_runs`) with status, duration_ms, output JSON,
evidence rows, hypotheses and recommended actions. Re-running an analysis produces a
fresh, fully auditable record chain.

### LLM boundary (facts-only rationale)

Agents assemble a facts dict and pass it to the LLM behind the `FACTS_JSON:` marker.
The Mock provider renders rationale strictly from those facts; the OpenAI-compatible
provider gets temperature 0 and the same contract. The LLM never decides anything:
decisions (impacted sets, selected tests, risk bands) come exclusively from tools.
A unit test asserts the mock cannot invent facts not present in the input.

### LangGraph mapping note

The engine is deliberately framework-free. The docstring of
`backend/app/workflow/engine.py` documents the equivalent LangGraph program: an
`AnalysisState` TypedDict threaded through eight nodes, with the approval gate as a
conditional edge (`risk.requires_approval ? AWAITING_APPROVAL : auto-approve`). The
persisted stage machine gives the same replayability without a runtime dependency.

## Graph semantics (the heart of precision)

`DependencyGraph.from_session` loads every entity as a node and every row of
`graph_edges` as an arc. Stored edges are natural subject-verb-object triples
(`PROCESS USES PROCESS_STEP`); an orientation map flips them into *impact direction*
(change flows downstream to consumers). Two mechanisms keep the closure precise:

1. **Value-flow gating.** Edges flagged as value edges (`*_WRITES_TABLE`,
   field-level links) only propagate if the seed is value-affecting, and expansion
   out of a TABLE node requires `sap_tables.value_flow = true`. This is why a pricing
   change reaches Billing but not delivery logistics, while co-writers of the same
   table are never connected through it.
2. **Interface absorption.** INTERFACE nodes propagate only to PROCESS, TEST_CASE and
   TRANSACTION nodes - hub interfaces cannot explode the closure.

Confidence decays by BFS distance: seeds 1.0, traversed nodes
`max(0.5, 1 - 0.15*(distance-1))`. Every ImpactResult row records distance,
confidence, discovery method and path.

## Test selection

Candidates are TEST_CASE nodes validating at least one impacted object. Score:

```
0.45*coverage_focus + 0.25*criticality + 0.15*min(1, defect_rate/0.12)
+ 0.15*interface_involvement        (threshold 0.35, or any interface coverage)
```

Each selection persists score, rank and a human-readable reason citing coverage
focus, criticality and historical failure counts.

## Risk model

`compute_risk_score = sum(weight * raw * 100)` over seven factors:
process_criticality 0.30 (0.7*max + 0.3*avg), custom_code 0.15, interfaces 0.15,
process_breadth 0.10, failure_history 0.10, coverage_gap 0.10, size 0.10.
Bands: LOW <30, MEDIUM <50, HIGH <80, CRITICAL >=80. HIGH/CRITICAL set
`requires_approval`, flip the transport to AWAITING_APPROVAL and open a PENDING
approval row; rejection BLOCKS the transport (subsequent analyses/validation return
409).

## Validation simulation

`services/validation_service.py` runs each selected test deterministically: outcomes
come from `defect_seeds` keyed by `(scenario_tag, test_code)`. Failures raise platform
defects (DEF-%04d), mirror them into the ALM mock, and Release Confidence is the
criticality-weighted pass rate (CRITICAL 1.0, HIGH 0.85, MEDIUM 0.55, LOW 0.25).
Canonical expectation: 2 failures / 2 passes -> 51.95% confidence ->
transport VALIDATION_FAILED before release.

## Data model (selected tables)

transports, transport_objects, processes, process_steps, transactions, fiori_apps,
custom_code, config_items, sap_tables (+value_flow), table_fields, interfaces,
batch_jobs, roles, test_cases, defect_seeds, graph_edges, events, tool_calls,
analyses, stage_runs, evidence, hypotheses, actions, impact_results, test_selections,
risk_assessments, approvals, outcomes, validations, test_executions, defects,
cloud_alm_features/tasks/test_links/executions/defects/release_plans,
metric_snapshots, evaluation_runs.

## Metrics

Prometheus histograms for stage/tool/LLM latency and counters for analyses,
approvals and caught defects live on a private registry exposed at `/metrics`.
Business metrics (evaluation recalls/precisions, scope reduction ratio, average
analysis duration, approval turnaround, defect catch count, high+critical risk ratio)
are persisted to `metric_snapshots` on each analysis/evaluation/validation and served
via `/api/v1/business-metrics`.

## Frontend

Static SPA at `/` (vanilla ES modules, no build step, no CDN). Panels: Transport
Import, Analyses pipeline (8 stages with live polling), Impact graph (layered SVG),
Regression Scope (reason-coded table), Risk & Approval (approve/reject actions),
Validation & Confidence, ALM Sync, Evaluation. Amber MOCK MODE badge everywhere.

## Adapters

`adapters/cloud_alm.py` defines the protocol; `LocalCloudAlmAdapter` (mock=true)
persists into cloud_alm_* tables, `RealSapCloudAlmClient` raises NotImplementedError
with integration notes. All ALM traffic flows through `services/alm_service.py` so a
real client swaps in at exactly one place.

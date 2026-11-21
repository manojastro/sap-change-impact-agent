# Interview guide

## 30-second pitch

"I built a release-management cockpit for SAP S/4HANA transports. You import a
transport request, eight workflow agents analyze it against a dependency graph of the
SAP-like estate - processes, custom code, config, interfaces, tests - and it answers:
what is impacted, what is the minimal regression suite, how risky is this release,
and should a human approve it. In the canonical demo a pricing change breaks billing
amount calculation and the platform catches it BEFORE release: two seeded tests fail,
defects are raised into an ALM mock, and release confidence drops to 52 percent.
An evaluation harness scores impact discovery and test selection against authored
ground truth."

## 2-minute deep dive

- Problem: SAP teams rerun huge regression suites or ship blind; impact analysis is
  tribal knowledge.
- Approach: model the landscape as a directed graph (processes, steps, transactions,
  Fiori apps, custom code, config items, tables with value-flow flags, interfaces,
  batch jobs, roles, test cases). A transport maps to seed nodes; multi-source BFS
  computes the impact closure.
- Precision tricks: value-affecting gating on write edges, table-level value_flow
  flags, interface-absorbing propagation, confidence decay by distance.
- Regression scope: score candidate tests by coverage focus, criticality, historical
  defect rate, interface involvement; select at threshold - 4 of 17 for the canonical
  transport instead of everything.
- Risk: seven weighted factors produce a 0..100 band; HIGH/CRITICAL force a human
  approval gate enforced server-side (409s otherwise); rejection blocks the transport.
- Validation simulation: deterministic outcomes from seeded defects prove the pipeline
  catches a broken change pre-release; failures raise defects in-platform and mirror
  them to a SAP Cloud ALM mock through an adapter protocol.
- Evaluation: six ground-truth transports; measured recall/precision 1.0 across
  processes/interfaces/tests, risk-band accuracy 1.0, zero false-positive tests,
  zero missed critical items.

## Why agents + deterministic tools?

The "agentic" part is orchestration: one agent per stage, each calling audited tools
and writing rationale. All decisions are deterministic graph algorithms so results
are reproducible and testable; the LLM (mock or OpenAI-compatible) only phrases what
the tools proved, from a facts JSON - it cannot invent facts (unit-tested).

## Architecture questions you may get

- **Why not LangGraph?** The engine is a persisted stage machine; its docstring maps
  1:1 to a LangGraph StateGraph with a conditional approval edge. No runtime dep for
  a POC, trivial migration later.
- **How do you keep precision high?** Orientation map flips natural edges into impact
  direction; VALUE edges need a value-affecting seed; leaving a TABLE requires
  tables.value_flow; interfaces only propagate to processes/tests/transactions;
  co-writers never connect through shared tables.
- **How is risk computed?** Weighted sum of seven normalized factors (criticality of
  impacted processes dominates at 0.30); bands LOW<30, MEDIUM<50, HIGH<80,
  CRITICAL>=80; factor breakdown persisted per assessment.
- **Approval flow?** Risk stage opens PENDING approval + AWAITING_APPROVAL status;
  approve -> APPROVED; reject -> BLOCKED with reason; BLOCKED refuses new analyses and
  validation (409). Turnaround time recorded for metrics.
- **What happens on failure mid-pipeline?** Stage marked FAILED with error, analysis
  FAILED; prior stage outputs remain persisted and inspectable.
- **Metrics?** Prometheus histograms for stage/tool/LLM latency, counters for
  analyses/approvals/caught defects; business metrics snapshotted per run and exposed
  via /api/v1/business-metrics.

## Validation & evaluation talking points

- Outcomes derive from seeded defects keyed by scenario_tag+test_code -
  deterministic demos, no flaky CI.
- Release Confidence = pass rate weighted by test criticality (canonical: 2/3.85 =
  51.95%, not a misleading 50%).
- Tests assert honest thresholds (all eval metrics == 1.0 within 1e-9; missed
  critical must be 0). When logic regressed during development, we fixed logic -
  never loosened thresholds.

## Trade-offs to own up front

- Self-authored world + ground truth (perfect scores = spec compliance).
- Simulated test execution; adapter-only ALM integration (mock persists locally).
- SQLite + create_all instead of Alembic; in-process background tasks.
- Static vanilla-JS cockpit instead of a framework SPA.

## Rapid factual Q&A

- 8 stages? Transport Analysis, Custom Code, Configuration, Business Process,
  Interface Impact, Regression Scope, Risk, Validation Readiness.
- Exactly 8 tools, all deterministic; no shell/network tools in the registry.
- Canonical result: ORDER_TO_CASH + RECORD_TO_REPORT, INVOIC_OUT, 4/17 tests (23.5%),
  risk 63.5 HIGH, approval required, 2 failed tests, confidence 51.95%,
  defects DEF-0001/DEF-0002, transport VALIDATION_FAILED.
- Clean control: MM_STOCK_CLEAN - LOW 26.08, auto-approved, STOCK_SYNC_TEST only,
  validation 100%.
- Suite: 50 pytest tests green.

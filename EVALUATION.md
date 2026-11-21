# Evaluation

The evaluation harness is the honesty mechanism of this project: it scores the
engine against **authored ground truth** - transports whose true impacted processes,
interfaces, regression tests and risk bands were fixed in advance in
`evaluation/ground_truth.json`, before running the pipeline.

## Ground truth

Six transports of known truth (all synthetic, SAP-LIKE simulation):

| Key | Transport | Designed truth | Band |
| --- | --- | --- | --- |
| PRICING_CANONICAL | SIMK910001 | processes ORDER_TO_CASH + RECORD_TO_REPORT; interface INVOIC_OUT; tests BILLING_CREATE_TEST, INVOIC_PAYLOAD_TEST, FI_RECONCILIATION_TEST, SO_CREATE_TEST; critical item (billing test) | HIGH |
| MM_STOCK_CLEAN | SIMK910002 | INVENTORY_MANAGEMENT; no interface; STOCK_SYNC_TEST only | LOW |
| PO_RELEASE_CONFIG | SIMK910003 | PROCURE_TO_PAY; config change (non value-affecting) + workflow code | HIGH |
| FX_REVALUATION | SIMK910004 | RECORD_TO_REPORT; FI_RECONCILIATION_TEST among others | MEDIUM |
| ROLE_PAYROLL_DISPLAY | SIMK910005 | display-only role change; HIRE_TO_RETIRE radius only | LOW |
| ODATA_SO_API | SIMK910006 | ORDER_TO_CASH via OData spec incl. SO_CREATE_TEST | MEDIUM |

## Metrics computed per run (`POST /api/v1/evaluation/run`)

- impact discovery recall / precision for PROCESS nodes
- impact discovery recall / precision for INTERFACE nodes
- regression selection recall / precision
- false positive tests (selected but not warranted)
- missed critical items (missing critical tests/processes; must be 0)
- release-risk band accuracy

## Measured results (this build)

```
transports evaluated       : 6
impact process recall      : 1.0
impact process precision   : 1.0
impact interface recall    : 1.0
impact interface precision : 1.0
test selection recall      : 1.0
test selection precision   : 1.0
false positive tests       : 0
risk band accuracy         : 1.0
missed critical items      : 0
```

Measured risk scores vs designed bands:

| Transport | Score | Band (computed = designed) |
| --- | --- | --- |
| SIMK910001 | 63.5 | HIGH |
| SIMK910002 | 26.08 | LOW |
| SIMK910003 | 53.33 | HIGH |
| SIMK910004 | 45.83 | MEDIUM |
| SIMK910005 | 22.33 | LOW |
| SIMK910006 | 43.33 | MEDIUM |

Scope reduction on the canonical scenario: **4 of 17 test cases selected (23.5%)**
with reason-coded rationale per test; the clean control selects 1 of 17 (5.9%).
Measured analysis latency is dominated by graph construction and stage bookkeeping:
the full 8-stage canonical analysis completes end to end in well under one second
per stage timings are persisted in `stage_runs.duration_ms` and histogrammed.

Tests enforce these numbers as hard thresholds (`tests/test_evaluation.py`): if the
logic degrades, the suite fails - thresholds were never loosened to make it pass.

## Honesty notes

- The world model and ground truth were authored by the same project. Perfect scores
  therefore demonstrate that the implementation matches its own specification; they do
  NOT prove accuracy against a real SAP estate. The structural mechanisms (value-flow
  gating, interface absorption, distance confidence) are general, but recall/precision
  on real customer landscapes would be the meaningful benchmark.
- The evaluation runner uses the exact same production path as the API
  (import -> start_analysis -> run_analysis), so nothing is scored on a shortcut.
- Per-transport details (expected vs found sets) persist in `evaluation_runs.details`
  for inspection.

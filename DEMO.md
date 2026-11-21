# Demo script (5 minutes)

SAP-LIKE SIMULATION - synthetic estate, no real SAP system.

## Setup (once)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Option A: scripted walkthrough

```powershell
.\.venv\Scripts\python.exe scripts\create_high_risk_transport.py --fresh
```

Prints the whole story with ASCII output: seeding, import, 8 stage decisions,
impact, regression scope, risk factors, demo approval, validation results,
defects caught before release.

## Option B: full contrast + evaluation

```powershell
.\.venv\Scripts\python.exe scripts\run_change_demo.py
```

Adds the clean control transport and an evaluation run (all metrics 1.0).

## Option C: live UI cockpit

```powershell
.\.venv\Scripts\python.exe -m simulator.seed
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8013
# open http://127.0.0.1:8013/
```

Narrative in the browser:

1. **Transport Import** - paste/import SIMK910001 (pricing condition config +
   Z_PRICING_DETERMINATION_EXIT). Amber MOCK MODE badge is always visible.
2. **Run analysis** - the pipeline panel polls through the eight stages
   (Transport Analysis -> ... -> Validation Readiness), each with duration and
   decision.
3. **Impact graph** - ORDER_TO_CASH and RECORD_TO_REPORT highlighted; INVOIC_OUT
   marked as impacted interface; confidence decays with graph distance.
4. **Regression Scope** - 4 of 17 tests selected (23.5%), each row showing score and
   reason ("validates impacted BILLING_CREATE; coverage focus 1/1; criticality
   CRITICAL...").
5. **Risk & Approval** - 63.5/100 HIGH with factor contributions; transport parked at
   AWAITING_APPROVAL. Approve as `release-manager-demo` to proceed.
6. **Validation** - run release validation from the panel: BILLING_CREATE_TEST and
   INVOIC_PAYLOAD_TEST FAIL, Release Confidence 51.95%, defects DEF-0001/DEF-0002
   raised into the platform AND the ALM mock. Transport ends VALIDATION_FAILED -
   the bad pricing change was caught BEFORE release.
7. **Contrast** - import/analyze/approve-free MM_STOCK_CLEAN (LOW 26.08): 1 of 17
   tests, validation 100%, zero defects.
8. **Evaluation** - POST /api/v1/evaluation/run (or the Evaluation panel) shows all
   recall/precision metrics at 1.0 against authored ground truth.

## Key talking points while demoing

- Decisions are deterministic graph algorithms; the LLM only writes rationale from
  supplied facts (mock provider is provably facts-only).
- Value-flow gating keeps precision: pricing reaches Billing, not delivery logistics;
  co-writers never connect through shared tables.
- Approval gate is enforced server-side: AWAITING_APPROVAL refuses validation (409);
  rejection BLOCKS the transport permanently until re-import policy says otherwise.
- Failures raise defects pre-release into platform + ALM mock; confidence is
  criticality-weighted, not a raw pass rate.

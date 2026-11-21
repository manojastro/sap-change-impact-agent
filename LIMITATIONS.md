# Limitations

Honest constraints of this build. Nothing here is hidden from the demo narrative.

## Simulation scope

- **SAP-LIKE, not SAP.** No RFC/BAPI/OData calls to a real system; the estate is a
  synthetic graph seeded by `simulator/generate_landscape.py`. Entity shapes mimic
  SAP concepts (transport requests, condition records, custom code objects, iDoc and
  OData interfaces) but data is invented.
- **Validation is simulated deterministically.** Test outcomes come from
  `defect_seeds` keyed by scenario tag + test code. There is no real test execution;
  the simulation demonstrates orchestration (defect raising, confidence scoring,
  ALM sync), not actual QA.
- **Ground truth is self-authored.** Perfect evaluation scores prove the engine
  matches its own specification, not real-world accuracy. A meaningful external
  benchmark needs a customer's transport history with known incident outcomes.
- **Static relationship model.** `graph_edges` are seeded at landscape generation.
  Real usage would derive edges from where-used indexes (SAP ATC/Code Inspector),
  table technical names, transaction-to-tcode usage logs and interface mappings -
  the loader accepts any edge list, but none of those extractors exist here.

## Engineering trims

- **SQLite default, `create_all` schema.** No Alembic migrations; schema changes
  mean recreating the dev DB. Postgres works via `DATABASE_URL` but was exercised
  only lightly (driver included).
- **Background analyses run in-process** via FastAPI BackgroundTasks - fine for a
  single-worker POC; production would use a task queue for durability/retries.
- **No auth.** See SECURITY.md; approval identity is an unverified string in POC mode.
- **Frontend is a static SPA without a framework/build pipeline** - deliberate trade
  (zero CDN, easy audit) at the cost of componentization and tests on the UI layer.
- **Confidence decay (0.15/distance) and risk weights are calibrated heuristics**
  chosen so designed scenarios land in correct bands; they are not fitted to data.
- **Writer-side table-schema impact modeling is simplified:** changes to table fields
  propagate only through field-level links and value-flow flags; physical schema
  drift analysis (e.g., SE11 structure vs code) is out of scope.
- **DUNNING batch-job scenery** exists in the estate as context nodes but has no
  dedicated scenario transport.

## Operational notes

- Console scripts print ASCII only (cp1252-safe); no unicode arrows or emoji anywhere.
- Docker image runs uvicorn as root inside the container (fine locally; harden for prod).
- The evaluation runner reuses the live database: repeated runs accumulate analyses
  by design (idempotent imports keep results stable).

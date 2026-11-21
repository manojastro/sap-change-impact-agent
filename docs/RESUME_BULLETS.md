# Resume bullets

Implemented-only, POC-labeled (SAP-LIKE simulation; synthetic data; no real SAP
system or license).

- Built a working SAP S/4HANA change-impact POC: FastAPI + SQLAlchemy 2 backend with
  an 8-stage persisted agent workflow that maps transport changes onto a NetworkX
  dependency graph of the simulated estate and computes value-flow-gated impact
  closures with distance-based confidence.

- Implemented deterministic minimal-regression-scope selection (coverage focus,
  criticality, historical defect rate, interface involvement) reducing the canonical
  scenario to 4 of 17 test cases with reason-coded rationale, replacing
  rerun-everything regression strategy in the simulation.

- Designed a weighted release-risk model (7 factors, 0..100 bands) with a
  server-enforced human approval gate for HIGH/CRITICAL transports, including
  rejection blocking, 409 guards on downstream actions, and full audit trails
  (stage runs, evidence, tool calls, events).

- Simulated release validation end to end: seeded-defect execution caught a broken
  pricing change before release (2 failing tests), raised defects into the platform
  and a SAP Cloud ALM mock adapter, and reported criticality-weighted release
  confidence (51.95%).

- Authored an evaluation harness over 6 ground-truth transports measuring impact
  discovery recall/precision, regression selection recall/precision, false positives,
  missed critical items and risk-band accuracy; measured 1.0 across all metrics in the
  shipped build with thresholds enforced by the pytest suite (50 tests green).

- Shipped a zero-dependency dark-theme cockpit SPA (vanilla ES modules, layered SVG
  impact graph, live polling) plus Prometheus latency histograms, persisted business
  metrics, Dockerfile/docker-compose deployment, and demo scripts.

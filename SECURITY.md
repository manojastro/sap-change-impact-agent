# Security

This is a local POC running an SAP-LIKE simulation. The notes below describe the
security posture that exists in the code today and what a production deployment
would need to add.

## Implemented in this codebase

- **Safe errors.** A global exception handler logs only the exception type name and
  returns a generic JSON error (`{"error": "internal server error", ...}`) - stack
  traces, SQL fragments and internal paths never reach clients.
- **CORS from environment.** `CORSMiddleware` allowlist comes from `CORS_ORIGINS`
  (default `http://localhost:8013,http://127.0.0.1:8013`); nothing is wildcarded.
- **No shell/network tools.** The agent tool registry contains exactly eight
  deterministic analysis tools (analyze_transport, query_where_used,
  traverse_impact, select_regression_tests, compute_risk_score, run_regression_suite,
  record_defect, export_release_plan). There are no shell, file-system or arbitrary
  HTTP tools for a prompt to abuse.
- **Facts-only LLM.** The LLM provider renders rationale strictly from a facts dict
  passed behind a marker; decisions are computed by deterministic code. Prompt output
  is stored as text, never executed or parsed into control flow.
- **Input validation.** Pydantic schemas with pattern/length/enum constraints on all
  write endpoints; SQLAlchemy bound parameters throughout (no string-built SQL);
  transport IDs pattern-validated.
- **Human gate on dangerous actions.** HIGH/CRITICAL transports cannot reach release
  validation without an explicit approval (server-side 409 enforcement); rejection
  hard-BLOCKs the transport. Approval identity (`approver`) and comment are recorded
  with turnaround time.
- **Audit trail.** Every tool invocation persists a `tool_calls` row (input payload,
  output summary, duration); every stage persists evidence rows; state changes append
  to `events`.
- **Secrets in env only.** `.env.example` documents placeholders; `.gitignore`
  excludes `.env` and `data/`. No secrets in code or fixtures.

## Not implemented (POC scope)

- **Authentication/authorization.** API endpoints are unauthenticated locally. The
  approval endpoint accepts any `approver` string. Production would integrate SSO
  (e.g., Azure AD / SAP IAS) and role checks (release manager vs auditor).
- **HTTPS/TLS** termination is assumed to be external.
- **Rate limiting / request quotas** are not present.
- **Multi-tenancy isolation** does not exist; the single database is shared.
- **Real SAP credentials handling** is intentionally absent (no real SAP integration;
  the ALM adapter mock stores no credentials).

## Production checklist

1. Reverse proxy with TLS + auth (OIDC), map roles to approve/reject rights.
2. Postgres with per-tenant schemas and backups; Alembic migrations.
3. Secrets manager for `LLM_API_KEY`; short-lived tokens for ALM/OData calls.
4. Structured audit export (the events/tool_calls/evidence tables are the base).
5. Rate limiting and request size caps at the gateway.

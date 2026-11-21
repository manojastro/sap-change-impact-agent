// Thin API client (vanilla, zero dependencies)
const base = "";

async function jfetch(path, options) {
  const resp = await fetch(base + path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (_) { /* noop */ }
    const err = new Error(detail);
    err.status = resp.status;
    throw err;
  }
  if (resp.status === 204) return null;
  return resp.json();
}

const post = (path, body) => jfetch(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

export const api = {
  meta: () => jfetch("/api/v1/meta"),
  seed: () => post("/api/v1/simulator/seed"),
  transports: () => jfetch("/api/v1/transports"),
  transport: (id) => jfetch(`/api/v1/transports/${id}`),
  transportObjects: (id) => jfetch(`/api/v1/transports/${id}/objects`),
  startAnalysis: (transportId, wait = false) =>
    post("/api/v1/analyses", { transport_id_ref: transportId, wait }),
  analysis: (id) => jfetch(`/api/v1/analyses/${id}`),
  stages: (id) => jfetch(`/api/v1/analyses/${id}/stages`),
  impactResults: (analysisId, nodeType) =>
    jfetch(`/api/v1/impact-results?analysis_id=${analysisId}${nodeType ? `&node_type=${nodeType}` : ""}`),
  selections: (analysisId) => jfetch(`/api/v1/test-selections?analysis_id=${analysisId}&included_only=false`),
  risks: (analysisId) => jfetch(`/api/v1/risk-assessments?analysis_id=${analysisId}`),
  graph: (analysisId) => jfetch(analysisId ? `/api/v1/graph?analysis_id=${analysisId}` : "/api/v1/graph"),
  approvals: () => jfetch("/api/v1/approvals"),
  approve: (id, approver, comment) => post(`/api/v1/approvals/${id}/approve`, { approver, comment }),
  reject: (id, approver, comment) => post(`/api/v1/approvals/${id}/reject`, { approver, comment }),
  runValidation: (transportPk) => post("/api/v1/test-executions/run", { transport_pk: transportPk }),
  validations: (transportId) => jfetch(
    transportId ? `/api/v1/validations?transport_id=${transportId}` : "/api/v1/validations"),
  confidenceTrend: () => jfetch("/api/v1/release-confidence"),
  defects: () => jfetch("/api/v1/defects"),
};

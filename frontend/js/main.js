// Cockpit controller: state, polling, panel rendering
import { api } from "./api.js";
import { renderGraph } from "./graph.js";

const $ = (id) => document.getElementById(id);
const state = {
  selectedTransport: null,   // transport PK
  analysisId: null,
  pollTimer: null,
  metaCounts: null,
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------------------------------------------------------- meta
async function loadMeta() {
  const meta = await api.meta();
  if (meta.mock_mode) $("mock-badge").classList.remove("hidden");
  $("meta-subtitle").textContent =
    `${meta.simulator} - LLM: ${meta.llm_mode}`;
}

// ---------------------------------------------------------------- landscape + transports
async function refreshBoard() {
  const [transports, processes] = await Promise.all([
    api.transports(),
    fetch("/api/v1/graph").then(r => r.json()),
  ]);

  // process cards (from estate graph nodes)
  const procNodes = processes.nodes.filter(n => n.type === "PROCESS");
  const impactedNow = new Map(Object.entries(processes.impacted || {}));
  $("landscape-cards").innerHTML = procNodes.map(p => {
    const imp = impactedNow.get(p.key);
    return `<div class="card ${imp ? "impacted" : ""}">
      <div class="name">${esc(p.label)}</div>
      <div class="meta">${esc(p.criticality || "")}${imp ? ` - impacted d${imp.distance}` : ""}</div>
    </div>`;
  }).join("") || '<div class="empty">Seed the estate first.</div>';

  const c = state.metaCounts || {};
  $("estate-stats").innerHTML = Object.entries(c)
    .filter(([k]) => ["processes", "custom_code", "config_items", "tables",
                      "interfaces", "test_cases", "transports", "analyses"].includes(k))
    .map(([k, v]) => `<div><b>${v}</b>${esc(k.replace(/_/g, " "))}</div>`).join("");

  // risk per transport from latest assessments endpoint is heavy; use status only
  $("transport-table tbody").innerHTML = transports.map(t => `
    <tr data-id="${t.id}" class="${t.id === state.selectedTransport ? "selected" : ""}">
      <td>${esc(t.transport_id)}</td>
      <td>${esc(t.title)}</td>
      <td>${esc(t.change_type)}</td>
      <td>${esc(t.size_bucket)}</td>
      <td><span class="status-pill st-${esc(t.status)}">${esc(t.status)}</span></td>
      <td></td>
    </tr>`).join("") || '<tr><td colspan="6" class="empty">Queue empty - import a transport.</td></tr>';

  for (const tr of $("transport-table tbody").querySelectorAll("tr[data-id]")) {
    tr.addEventListener("click", () => selectTransport(Number(tr.dataset.id)));
  }
}

function meta_counts() { return {}; }
void meta_counts;

// ---------------------------------------------------------------- selection flow
async function selectTransport(id) {
  state.selectedTransport = id;
  state.analysisId = null;
  await renderTransportDetail();
  await resetAnalysisPanels();
  await refreshApprovals();
  await refreshValidations();
}

async function renderTransportDetail() {
  const id = state.selectedTransport;
  if (!id) return;
  const t = await api.transport(id);
  const objs = await api.transportObjects(id);
  $("#objects-subtitle").textContent =
    `${t.transport_id} - ${t.change_type}, ${t.size_bucket}, status ${t.status}`;

  $("#changed-objects").innerHTML = objs.map(o => `
    <li><div>${esc(o.object_key)}${o.field_name ? "." + esc(o.field_name) : ""}</div>
    <span class="type">${esc(o.object_type)} / ${esc(o.change_action)}</span></li>`).join("");

  $("#btn-analyze").disabled = ["BLOCKED"].includes(t.status);
  const approvableStatus = !["IMPORTED", "AWAITING_APPROVAL", "ANALYZED"].includes(t.status)
    && t.status !== "BLOCKED";
  $("#btn-validate").disabled = !approvableStatus;

  // risk panel for this transport
  const risks = await fetch(`/api/v1/risk-assessments?transport_id=${id}`).then(r => r.json());
  if (risks.length) renderRisk(risks[0]); else resetRisk();
}

function resetAnalysisPanels() {
  $("#stage-list").innerHTML = '<li class="empty">Idle.</li>';
  $("#process-impact").innerHTML = '<li class="empty">Run an analysis.</li>';
  $("#interface-list").innerHTML = '<li class="empty">Run an analysis.</li>';
  $("#scope-table tbody").innerHTML = '<tr><td colspan="4" class="empty">Run an analysis.</td></tr>';
  $("#scope-ratio").textContent = "";
  $("#scope-excluded").textContent = "";
  resetRisk();
}

// ---------------------------------------------------------------- analysis run
async function startAnalysis() {
  if (!state.selectedTransport) return;
  const resp = await api.startAnalysis(state.selectedTransport, false);
  state.analysisId = resp.id;
  await pollAnalysis();
}

async function pollAnalysis() {
  if (!state.analysisId) return;
  const a = await api.analysis(state.analysisId);
  const stages = await api.stages(state.analysisId);
  $("#stage-list").innerHTML = stages.map(s => {
    const cls = s.status === "DONE" ? "done" : (s.status === "RUNNING" ? "running" : "");
    const decision = (s.output && s.output.decision && s.output.decision.decision) || "";
    return `<li class="${cls}"><span class="dur">${s.duration_ms.toFixed(0)} ms</span>
      <b>${esc(s.stage)}</b><br><span style="color:var(--muted)">${esc(decision).slice(0, 110)}</span></li>`;
  }).join("");
  $("#poll-state").textContent = ` - polling analysis ${a.status}`;

  if (a.status === "COMPLETED") {
    await renderImpact();
    await renderTransportDetail();
    await refreshBoard();
    $("#poll-state").textContent = "";
  } else if (a.status === "RUNNING" || a.status === "QUEUED") {
    setTimeout(pollAnalysis, 1200);
  }
}

async function renderImpact() {
  const id = state.analysisId;
  const procs = await api.impactResults(id, "PROCESS");
  const ifaces = await api.impactResults(id, "INTERFACE");

  const critW = { CRITICAL: 1.0, HIGH: 0.85, MEDIUM: 0.55, LOW: 0.25 };
  $("#process-impact").innerHTML = procs.map(p => {
    const heat = Math.round((critW[p.name] ? 1 : 0.7) * p.confidence * 100);
    const color = p.confidence > 0.9 ? "#e5534b" : "#e5b567";
    return `<li><b>${esc(p.name)}</b> <span class="pill">${esc(p.distance)} hops</span>
      <span style="color:var(--muted);font-size:12px"> confidence ${(p.confidence * 100).toFixed(0)}%</span>
      <div class="heat-bar"><i style="width:${heat}%;background:${color}"></i></div></li>`;
  }).join("") || '<li class="empty">No process inside the impact radius.</li>';

  $("#interface-list").innerHTML = ifaces.map(i => `
    <li><b>${esc(i.name)}</b><br>
    <span style="color:var(--muted);font-size:12px">distance ${i.distance}, confidence ${(i.confidence * 100).toFixed(0)}% -
    partner systems must be notified before release</span></li>`).join("")
    || '<li class="empty">No interfaces affected.</li>';

  const sels = await api.selections(id);
  renderScope(sels);
  renderGraphPanel();
}

async function renderGraphPanel() {
  const data = await api.graph(state.analysisId);
  renderGraph($("depgraph"), data);
}

function renderScope(selections) {
  const included = selections.filter(s => s.included);
  const excludedCount = selections.filter(s => !s.included).length;
  $("#scope-table tbody").innerHTML = included.map(s => `
    <tr><td>#${s.rank}</td><td><b>${esc(s.code)}</b></td>
    <td>${s.score.toFixed(3)}</td><td>${esc(s.reason)}</td></tr>`).join("")
    || '<tr><td colspan="4" class="empty">No tests selected.</td></tr>';
  $("#scope-ratio").textContent = `${included.length} selected`;
  $("#scope-excluded").textContent =
    `Excluded ${excludedCount} candidate test(s) below threshold or unaffected; scope intentionally minimal - NOT rerun-everything.`;
}

// ---------------------------------------------------------------- risk
function resetRisk() {
  $("#risk-gauge").innerHTML = '<div class="empty">No risk assessment yet.</div>';
  $("#risk-factors").innerHTML = "";
}

function renderRisk(ra) {
  const bandColor = { LOW: "var(--ok)", MEDIUM: "var(--warn)", HIGH: "var(--bad)", CRITICAL: "var(--crit)" }[ra.band];
  const angle = Math.min(1, ra.score / 100);
  const r = 52, c = Math.PI * r;   // half-circle arc length
  $("#risk-gauge").innerHTML = `
    <svg width="150" height="90" viewBox="0 0 150 90">
      <path d="M 23 82 A ${r} ${r} 0 0 1 127 82" fill="none" stroke="#24303e" stroke-width="12" stroke-linecap="round"/>
      <path d="M 23 82 A ${r} ${r} 0 0 1 127 82" fill="none" stroke="${bandColor}" stroke-width="12"
        stroke-linecap="round" stroke-dasharray="${(c * angle).toFixed(1)} ${c}"/>
      <text x="75" y="66" text-anchor="middle" font-size="26" font-weight="700" fill="${bandColor}">${ra.score.toFixed(1)}</text>
      <text x="75" y="84" text-anchor="middle" font-size="11" fill="#8b9bab">${ra.band}</text>
    </svg>
    <div style="font-size:12px;color:var(--muted)">
      ${ra.requires_approval ? "human approval REQUIRED before release queue" : "auto-approved by CAB policy"}</div>`;
  const factors = Object.entries(ra.factor_breakdown)
    .sort((a, b) => b[1].contribution - a[1].contribution);
  $("#risk-factors").innerHTML = factors.map(([name, f]) => `
    <div class="factor-row">
      <span>${esc(name.replace(/_/g, " "))}</span>
      <span class="factor-bar"><i style="width:${Math.round(f.contribution * 2)}%"></i></span>
      <span class="val">${f.contribution}</span>
    </div>`).join("");
}

// ---------------------------------------------------------------- approvals
async function refreshApprovals() {
  if (!state.selectedTransport) {
    $("#approval-box").innerHTML = '<div class="empty">Select a transport.</div>';
    return;
  }
  const aps = await fetch(`/api/v1/approvals/for-transport/${state.selectedTransport}`).then(r => r.json());
  if (!aps) { $("#approval-box").innerHTML = '<div class="empty">No approval required yet.</div>'; return; }
  const pending = aps.status === "PENDING";
  $("#approval-box").innerHTML = `
    <p>Status <span class="status-pill st-${esc(aps.status)}">${esc(aps.status)}</span></p>
    ${aps.approver ? `<p style="color:var(--muted);font-size:12px">by ${esc(aps.approver)}${aps.comment ? " - " + esc(aps.comment) : ""}</p>` : ""}
    ${pending ? `<div class="decision">
        <input id="approver-name" placeholder="your name" style="flex:1;background:#0d1117;border:1px solid #24303e;color:var(--text);border-radius:8px;padding:6px 10px">
        <button id="btn-approve" class="btn primary">Approve</button>
        <button id="btn-reject" class="btn danger">Reject</button>
      </div>` : ""}`;
  if (pending) {
    $("#btn-approve").addEventListener("click", () => decideApproval("approve"));
    $("#btn-reject").addEventListener("click", () => decideApproval("reject"));
  }
}

async function decideApproval(kind) {
  const aps = await fetch(`/api/v1/approvals/for-transport/${state.selectedTransport}`).then(r => r.json());
  const name = ($("#approver-name") || {}).value || "cockpit-user";
  const comment = kind === "reject" ? window.prompt("Rejection reason:") || "" : "";
  try {
    await (kind === "approve"
      ? api.approve(aps.id, name, comment) : api.reject(aps.id, name, comment));
  } catch (e) { window.alert(e.message); }
  await Promise.all([refreshApprovals(), renderTransportDetail(), refreshBoard()]);
}

// ---------------------------------------------------------------- validation
async function runValidation() {
  if (!state.selectedTransport) return;
  try {
    await api.runValidation(state.selectedTransport);
  } catch (e) { window.alert(e.message); }
  await refreshValidations();
  await renderTransportDetail();
  await refreshBoard();
}

async function refreshValidations() {
  if (!state.selectedTransport) return;
  const vals = await api.validations(state.selectedTransport);
  const latest = vals[0];
  if (latest) {
    $("#execution-table tbody").innerHTML = (latest.executions || []).map(e => `
      <tr><td>${esc(e.code)}</td><td>${esc(e.criticality)}</td>
      <td><span class="pill ${e.status === "PASSED" ? "s-LOW" : "s-HIGH"}">${esc(e.status)}</span></td>
      <td style="color:var(--muted)">${esc((e.failure_reason || "ok").slice(0, 90))}</td></tr>`).join("");
  }
  const trend = await api.confidenceTrend();
  if (trend.trend && trend.trend.length) {
    const pts = trend.trend.slice(-8);
    const w = 420, h = 70;
    const xs = i => 10 + i * ((w - 20) / Math.max(1, pts.length - 1));
    const ys = v => h - 8 - (v / 100) * (h - 16);
    const path = pts.map((p, i) =>
      `${i ? "L" : "M"} ${xs(i).toFixed(1)} ${ys(p.release_confidence).toFixed(1)}`).join(" ");
    $("#confidence-view").innerHTML = `
      ${pts.map(p => `<div class="confidence-point"><b>${p.release_confidence}%</b>
        <span>${esc(p.transport_id)}</span>
        <span style="color:${p.failed ? "var(--bad)" : "var(--ok)"}">${p.failed} failure(s)</span></div>`).join("")}
      <svg class="spark" width="${w}" height="${h}">
        <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>
        ${pts.map((p, i) => `<circle cx="${xs(i)}" cy="${ys(p.release_confidence)}" r="3" fill="var(--accent)"/>`).join("")}
      </svg>`;
  } else {
    $("#confidence-view").innerHTML = '<div class="empty">No validations yet.</div>';
  }
}

// ---------------------------------------------------------------- wiring
async function init() {
  await loadMeta()
    .then(m => { state.metaCounts = m.counts; })
    .catch(() => {});
  $("#btn-seed").addEventListener("click", async () => {
    await api.seed();
    await refreshBoard();
    state.selectedTransport = null;
    await resetAnalysisPanels();
  });
  $("#btn-refresh").addEventListener("click", async () => {
    const m = await api.meta().catch(() => null);
    if (m) state.metaCounts = m.counts;
    await Promise.all([refreshBoard(), refreshApprovals(), refreshValidations()]);
  });
  $("#btn-analyze").addEventListener("click", startAnalysis);
  $("#btn-validate").addEventListener("click", runValidation);
  await refreshBoard().catch(e => console.warn(e));
  setInterval(refreshBoard, 15000);
}

init();

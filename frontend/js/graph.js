// Layered dependency graph renderer (pure SVG, no libraries)
const LAYER = {
  PROCESS: 0, STEP: 1, TRANSACTION: 2,
  TABLE: 3, CUSTOM_CODE: 3, CONFIG_ITEM: 3, BATCH_JOB: 3, ROLE: 3, TABLE_FIELD: 3, FIORI_APP: 3,
  INTERFACE: 4, TEST_CASE: 5,
};
const FILL = {
  PROCESS: "#58a6ff", STEP: "#7c9ec9", TRANSACTION: "#4cc38a",
  TABLE: "#9d7cd8", CUSTOM_CODE: "#b07cd8", CONFIG_ITEM: "#8d84e0",
  BATCH_JOB: "#6f7cd8", ROLE: "#5a6a8c", FIORI_APP: "#5480a8", TABLE_FIELD: "#9d7cd8",
  INTERFACE: "#e5b567", TEST_CASE: "#446a8f",
};

export function renderGraph(svgEl, data) {
  svgEl.innerHTML = "";
  const nodes = (data.nodes || []).filter(n => n.type in LAYER);
  if (!nodes.length) return;
  const impacted = data.impacted || {};

  // group nodes per layer
  const layers = {};
  for (const n of nodes) (layers[LAYER[n.type]] ||= []).push(n);

  const colW = Math.max(150, svgEl.clientWidth / Object.keys(layers).length);
  const width = colW * Object.keys(layers).length + 40;
  const maxRows = Math.max(...Object.values(layers).map(a => a.length));
  const rowH = 52;
  const height = Math.min(360, Math.max(200, maxRows * rowH));

  const pos = {};
  for (const [layerStr, arr] of Object.entries(layers)) {
    const layer = Number(layerStr);
    const x = 20 + layer * colW + colW / 2 - 60;
    const step = height / (arr.length + 1);
    arr.forEach((n, i) => { pos[n.key] = { x, y: step * (i + 1) }; });
  }

  const NS = "http://www.w3.org/2000/svg";
  const mk = (tag) => document.createElementNS(NS, tag);

  for (const e of data.edges || []) {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) continue;
    const line = mk("line");
    line.setAttribute("x1", a.x + 120); line.setAttribute("y1", a.y + 10);
    line.setAttribute("x2", b.x);        line.setAttribute("y2", b.y + 10);
    line.setAttribute("stroke", "#33465c");
    line.setAttribute("stroke-width", "1");
    if (impacted[e.source] && impacted[e.target]) line.setAttribute("stroke", "rgba(240,166,60,.55)");
    svgEl.appendChild(line);
  }

  for (const n of nodes) {
    const p = pos[n.key];
    if (!p) continue;
    const isImpacted = n.key in impacted;
    const g = mk("g");

    const rect = mk("rect");
    rect.setAttribute("x", p.x); rect.setAttribute("y", p.y);
    rect.setAttribute("width", 120); rect.setAttribute("height", 20);
    rect.setAttribute("rx", 5);
    rect.setAttribute("fill", FILL[n.type] || "#666");
    rect.setAttribute("opacity", isImpacted ? "1" : "0.32");
    if (isImpacted) rect.setAttribute("stroke", "#f0a63c");
    g.appendChild(rect);

    const label = mk("text");
    label.setAttribute("x", p.x + 6); label.setAttribute("y", p.y + 14);
    label.setAttribute("font-size", "9.5");
    label.setAttribute("font-family", "Consolas, monospace");
    label.setAttribute("fill", isImpacted ? "#10151c" : "#dbe4ee");
    let text = n.label || n.id;
    if (text.length > 18) text = text.slice(0, 17) + "...";
    label.textContent = text;
    g.appendChild(label);

    if (isImpacted) {
      const dist = impacted[n.key].distance ?? "?";
      const badge = mk("text");
      badge.setAttribute("x", p.x + 124); badge.setAttribute("y", p.y + 14);
      badge.setAttribute("font-size", "9"); badge.setAttribute("fill", "#f0a63c");
      badge.textContent = `d${dist}`;
      g.appendChild(badge);
    }
    const title = mk("title");
    title.textContent = isImpacted
      ? `${n.label} - impacted at distance ${impacted[n.key].distance}`
      : `${n.label} (${n.type})`;
    g.appendChild(title);
    svgEl.appendChild(g);
  }

  svgEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
}

"use strict";
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}, text) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; return e; };
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const state = { mode: "explore", year: "2026", swipe: 0.5, selected: null, alerts: [], filters: { minArea: 1, river: false, reserve: false, sort: "priority" } };
let S, map, panes = {}, overlays = {}, vectors = {}, alertLayer, markerLayer;

/* ---------- tooltip ---------- */
const tip = $("tip");
function showTip(e, text) { tip.textContent = text; tip.hidden = false; tip.style.left = Math.min(e.clientX + 12, innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (e.clientY - 30) + "px"; }
const hideTip = () => { tip.hidden = true; };

/* ---------- boot ---------- */
async function boot() {
  S = await (await fetch("/api/summary")).json();
  renderKpis();
  renderCharts();
  initMap();
  initLayers();
  initControls();
  await loadAlerts();
  applyHash();
}

/* Deep links, comma-separated: #compare, #y2020, #grid, #new, #footprint, #site-3 */
function applyHash() {
  const tokens = location.hash.slice(1).split(",").filter(Boolean);
  for (const t of tokens) {
    if (t === "compare") setMode("compare");
    else if (t === "y2020" || t === "y2026") document.querySelector(`#yearSwitch [data-year="${t.slice(1)}"]`)?.click();
    else if (["grid", "new", "footprint"].includes(t)) { $(`ly-${t}`).checked = true; applyLayers(); }
    else if (t.startsWith("site-")) select(+t.slice(5));
  }
}

/* ---------- KPIs ---------- */
function renderKpis() {
  const c = S.change, o = c.olofsson || {};
  const growth = (c.mining_2026_ha / c.mining_2020_ha - 1) * 100;
  const k = [
    { v: fmt(c.mining_2020_ha), u: "ha", l: "Mining 2020" },
    { v: fmt(c.mining_2026_ha), u: "ha", l: "Mining 2026" },
    { v: "+" + fmt(growth) + "%", l: "Growth in six years", accent: true },
    { v: fmt(o.adjusted_new_ha ?? c.new_mining_ha), u: o.ci95_ha ? "±" + fmt(o.ci95_ha) : "ha", l: "Ha newly mined (error-adjusted)" },
    { v: fmt(100 * S.alerts.near_river / S.alerts.count) + "%", l: "New sites ≤ 500 m from a stream" },
    { v: fmt(S.alerts.protected), l: "New sites in forest reserves" },
  ];
  $("kpis").innerHTML = k.map(x => `<div class="kpi"><div class="v${x.accent ? " accent" : ""}">${x.v}${x.u ? ` <small>${x.u}</small>` : ""}</div><div class="l">${x.l}</div></div>`).join("");
}

/* ---------- charts: single series, one scale, hover tooltip ---------- */
function bars(svg, items, { W, H, max, digits = 0, unit = "", horizontal = false }) {
  const pad = { l: horizontal ? 96 : 40, r: 34, t: 18, b: 22 }, iw = W - pad.l - pad.r, ih = H - pad.t - pad.b, ticks = horizontal ? 4 : 3;
  for (let i = 0; i <= ticks; i++) {
    const v = max * i / ticks;
    if (horizontal) { const x = pad.l + iw * i / ticks; svg.append(svgEl("line", { x1: x, x2: x, y1: pad.t, y2: pad.t + ih, class: i ? "grid" : "base" }), svgEl("text", { x, y: H - 6, "text-anchor": "middle" }, fmt(v, digits))); }
    else { const y = pad.t + ih - ih * i / ticks; svg.append(svgEl("line", { x1: pad.l, x2: pad.l + iw, y1: y, y2: y, class: i ? "grid" : "base" }), svgEl("text", { x: pad.l - 6, y: y + 4, "text-anchor": "end" }, fmt(v, digits))); }
  }
  const band = (horizontal ? ih : iw) / items.length, th = Math.min(band * 0.55, horizontal ? 18 : 44);
  items.forEach((it, i) => {
    const len = (horizontal ? iw : ih) * it.v / max;
    let mark, hit, val;
    if (horizontal) {
      const y = pad.t + band * i + (band - th) / 2;
      mark = svgEl("rect", { x: pad.l, y, width: len, height: th, rx: 3, class: "mark" + (it.hi ? " hi" : "") });
      val = svgEl("text", { x: pad.l + len + 5, y: y + th / 2 + 4, class: "val" }, fmt(it.v, digits));
      svg.append(svgEl("text", { x: pad.l - 6, y: y + th / 2 + 4, "text-anchor": "end" }, it.k));
      hit = svgEl("rect", { x: pad.l, y: pad.t + band * i, width: iw, height: band, class: "hit" });
    } else {
      const x = pad.l + band * i + (band - th) / 2;
      mark = svgEl("rect", { x, y: pad.t + ih - len, width: th, height: len, rx: 3, class: "mark" + (it.hi ? " hi" : "") });
      val = svgEl("text", { x: x + th / 2, y: pad.t + ih - len - 5, "text-anchor": "middle", class: "val" }, fmt(it.v, digits));
      svg.append(svgEl("text", { x: x + th / 2, y: H - 6, "text-anchor": "middle" }, it.k));
      hit = svgEl("rect", { x: pad.l + band * i, y: pad.t, width: band, height: ih, class: "hit" });
    }
    hit.addEventListener("pointermove", e => showTip(e, `${it.k}: ${fmt(it.v, digits)}${unit}`));
    hit.addEventListener("pointerleave", hideTip);
    svg.append(mark, val, hit);
  });
}
function renderCharts() {
  const c = S.change, m = S.models;
  bars($("chartArea"), [{ k: "2020", v: c.mining_2020_ha }, { k: "2026", v: c.mining_2026_ha, hi: true }], { W: 300, H: 150, max: 6000, unit: " ha" });
  bars($("chartModel"), [
    { k: "NDVI baseline", v: m.baseline_ndvi.iou }, { k: "U-Net RGB", v: m.unet_rgb.iou }, { k: "U-Net 12-band", v: m.unet_all_bands.iou, hi: true },
  ], { W: 300, H: 120, max: 1, digits: 2, horizontal: true });
}

/* ---------- map ---------- */
function initMap() {
  map = L.map("map", { zoomControl: false, attributionControl: true, minZoom: 9, maxZoom: 18 });
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Basemap © Esri · Imagery: Copernicus Sentinel-2", maxZoom: 18,
  }).addTo(map);
  [["y2020", 410], ["y2026", 411], ["mask2020", 420], ["mask2026", 421], ["fx", 430], ["grid", 440], ["lines", 450], ["sites", 460]]
    .forEach(([n, z]) => { panes[n] = map.createPane(n); panes[n].style.zIndex = z; });
  const b = S.layers.imagery_2026.bounds;
  map.fitBounds(b, { padding: [10, 10] });
  map.setMaxBounds(L.latLngBounds(b).pad(1.5));
  map.on("move zoom resize", updateClip);
}

const LAYERS = [
  { id: "imagery", name: "Sentinel-2 imagery", sw: "linear-gradient(135deg,#3d5b45,#a89a7c)", on: true, meta: "year" },
  { id: "mining", name: "Detected mining", sw: "var(--mine)", on: true, meta: "year" },
  { id: "new", name: "New mining 2020 → 2026", sw: "var(--new)", on: false },
  { id: "grid", name: "New-mining density, 1 km", sw: "var(--accent)", on: false },
  { id: "footprint", name: "Industrial mine footprint", sw: "var(--cyan)", line: true, on: false },
  { id: "reserves", name: "Forest reserves", sw: "var(--forest)", line: true, on: true },
  { id: "sites", name: "Alert sites", sw: "var(--new)", line: true, on: true },
];

function initLayers() {
  const L_ = S.layers;
  overlays.img2020 = L.imageOverlay(L_.imagery_2020.url, L_.imagery_2020.bounds, { pane: "y2020" });
  overlays.img2026 = L.imageOverlay(L_.imagery_2026.url, L_.imagery_2026.bounds, { pane: "y2026" });
  overlays.mask2020 = L.imageOverlay(L_.mining_2020.url, L_.mining_2020.bounds, { pane: "mask2020" });
  overlays.mask2026 = L.imageOverlay(L_.mining_2026.url, L_.mining_2026.bounds, { pane: "mask2026" });
  overlays.new = L.imageOverlay(L_.new_mining.url, L_.new_mining.bounds, { pane: "fx" });

  Promise.all(["grid", "footprint", "reserves"].map(n => fetch(`data/${n}.geojson`).then(r => r.json()))).then(([grid, fp, res]) => {
    const gmax = Math.max(...grid.features.map(f => f.properties.ha));
    vectors.grid = L.geoJSON(grid, { pane: "grid", style: f => ({ stroke: false, fillColor: css("--accent"), fillOpacity: 0.06 + 0.8 * Math.sqrt(f.properties.ha / gmax) }),
      onEachFeature: (f, l) => l.bindTooltip(`${fmt(f.properties.ha, 1)} ha new mining in this 1 km² cell`, { className: "site", sticky: true }) });
    vectors.gridMax = gmax;
    vectors.footprint = L.geoJSON(fp, { pane: "lines", interactive: false, style: { color: css("--cyan"), weight: 1.5, dashArray: "4 4", fill: false } });
    vectors.reserves = L.geoJSON(res, { pane: "lines", style: { color: css("--forest"), weight: 2, fillColor: css("--forest"), fillOpacity: 0.06 },
      onEachFeature: (f, l) => l.bindTooltip(`${f.properties.NAME} (${f.properties.DESIG_ENG || "protected area"})`, { className: "site", sticky: true }) });
    applyLayers();
  });

  $("layers").innerHTML = LAYERS.map(l => `<label class="layer" for="ly-${l.id}">
    <input type="checkbox" id="ly-${l.id}" ${l.on ? "checked" : ""}>
    <span class="sw${l.line ? " line" : ""}" style="${l.line ? `border-color:${l.sw}` : `background:${l.sw}`}"></span>
    <span>${l.name}</span><span class="meta" data-meta="${l.meta || ""}"></span></label>`).join("");
  LAYERS.forEach(l => $(`ly-${l.id}`).addEventListener("change", applyLayers));
  $("imgOpacity").addEventListener("input", e => { overlays.img2020.setOpacity(e.target.value / 100); overlays.img2026.setOpacity(e.target.value / 100); });
  applyLayers();
}

const isOn = (id) => $(`ly-${id}`)?.checked;
function toggle(layer, on) { if (!layer) return; if (on && !map.hasLayer(layer)) layer.addTo(map); if (!on && map.hasLayer(layer)) layer.remove(); }

function applyLayers() {
  const cmp = state.mode === "compare";
  const show2020 = cmp || state.year === "2020", show2026 = cmp || state.year === "2026";
  toggle(overlays.img2020, isOn("imagery") && show2020);
  toggle(overlays.img2026, isOn("imagery") && show2026);
  toggle(overlays.mask2020, isOn("mining") && show2020);
  toggle(overlays.mask2026, isOn("mining") && show2026);
  toggle(overlays.new, isOn("new"));
  toggle(vectors.grid, isOn("grid"));
  toggle(vectors.footprint, isOn("footprint"));
  toggle(vectors.reserves, isOn("reserves"));
  toggle(alertLayer, isOn("sites"));
  toggle(markerLayer, isOn("sites"));
  document.querySelectorAll('[data-meta="year"]').forEach(m => { m.textContent = cmp ? "both" : state.year; });
  renderLegend();
  updateClip();
}

function renderLegend() {
  const rows = [];
  if (isOn("mining")) {
    if (state.mode === "compare" || state.year === "2020") rows.push(`<div class="item"><span class="sw" style="background:var(--old)"></span>Mining detected, 2020</div>`);
    if (state.mode === "compare" || state.year === "2026") rows.push(`<div class="item"><span class="sw" style="background:var(--mine)"></span>Mining detected, 2026</div>`);
  }
  if (isOn("new")) rows.push(`<div class="item"><span class="sw" style="background:var(--new)"></span>New since 2020</div>`);
  if (isOn("sites")) rows.push(`<div class="item"><span class="sw" style="border:2px solid var(--new)"></span>Alert site (size = area)</div>`);
  if (isOn("reserves")) rows.push(`<div class="item"><span class="sw" style="border:2px solid var(--forest)"></span>Forest reserve</div>`);
  if (isOn("footprint")) rows.push(`<div class="item"><span class="sw" style="border:2px dashed var(--cyan)"></span>Industrial mine footprint</div>`);
  if (isOn("grid") && vectors.gridMax) rows.push(`<div>New mining per km² (ha)</div><div class="ramp"></div><div class="ticks"><span>0</span><span>${fmt(vectors.gridMax / 2)}</span><span>${fmt(vectors.gridMax)}</span></div>`);
  $("legend").innerHTML = rows.join("");
  $("legend").hidden = rows.length === 0;
}

/* ---------- compare (swipe) ---------- */
function updateClip() {
  const left = [panes.y2020, panes.mask2020], right = [panes.y2026, panes.mask2026];
  if (!map) return;
  if (state.mode !== "compare") { [...left, ...right].forEach(p => { p.style.clip = ""; }); return; }
  const nw = map.containerPointToLayerPoint([0, 0]), se = map.containerPointToLayerPoint(map.getSize());
  const x = nw.x + map.getSize().x * state.swipe;
  left.forEach(p => { p.style.clip = `rect(${nw.y}px, ${x}px, ${se.y}px, ${nw.x}px)`; });
  right.forEach(p => { p.style.clip = `rect(${nw.y}px, ${se.x}px, ${se.y}px, ${x}px)`; });
  $("swipeHandle").style.left = (state.swipe * 100) + "%";
  $("swipeHandle").setAttribute("aria-valuenow", Math.round(state.swipe * 100));
}
function setMode(mode) {
  state.mode = mode;
  $("modeExplore").setAttribute("aria-selected", mode === "explore");
  $("modeCompare").setAttribute("aria-selected", mode === "compare");
  $("swipe").hidden = $("swipeTags").hidden = mode !== "compare";
  $("yearSwitch").classList.toggle("disabled", mode === "compare");
  applyLayers();
}

/* ---------- alerts ---------- */
function alertQuery(extra = {}) {
  const f = state.filters, q = new URLSearchParams({ min_area: f.minArea, sort: f.sort, ...extra });
  if (f.river) q.set("near_river", "true");
  if (f.reserve) q.set("protected", "true");
  return q.toString();
}
async function loadAlerts() {
  const data = await (await fetch(`/api/alerts?${alertQuery({ limit: 500 })}`)).json();
  state.alerts = data.features;
  $("alertCount").textContent = fmt(data.total_matching);
  $("alertCountLabel").textContent = data.total_matching === 1 ? "site" : "sites";
  $("exportCsv").href = `/api/alerts.csv?${alertQuery()}`;

  if (alertLayer) alertLayer.remove();
  if (markerLayer) markerLayer.remove();
  const maxP = Math.max(1, ...state.alerts.map(a => a.properties.priority));
  alertLayer = L.geoJSON(data, { pane: "sites", style: { color: css("--new"), weight: 1.5, fillOpacity: 0.08 },
    onEachFeature: (f, l) => l.on("click", () => select(f.properties.rank)) });
  markerLayer = L.layerGroup(state.alerts.map(a => {
    const p = a.properties;
    return L.circleMarker([p.lat, p.lon], { pane: "sites", radius: 3 + Math.sqrt(p.area_ha) * 1.2, color: "#fff", weight: 1, fillColor: css("--new"), fillOpacity: 0.85 })
      .bindTooltip(`#${p.rank} · ${fmt(p.area_ha, 1)} ha`, { className: "site", direction: "top" })
      .on("click", () => select(p.rank));
  }));
  applyLayers();

  const shown = state.alerts.slice(0, 150);
  $("alertList").innerHTML = shown.map(a => {
    const p = a.properties, w = Math.max(4, 100 * p.priority / maxP);
    return `<li class="item-row${state.selected === p.rank ? " active" : ""}" data-rank="${p.rank}" tabindex="0">
      <span class="rank">#${p.rank}</span>
      <div class="item-main"><span class="ha">${fmt(p.area_ha, 1)} ha</span>
        <div class="tags">${p.near_river ? '<span class="tag river">stream</span>' : ""}${p.in_protected_area ? '<span class="tag reserve">reserve</span>' : ""}${p.verdict ? '<span class="tag check">checked</span>' : ""}</div></div>
      <span class="prio">${fmt(p.priority, 0)}<span class="bar"><i style="width:${w}%"></i></span></span></li>`;
  }).join("") + (data.total_matching > shown.length ? `<li class="more">Showing the top ${shown.length} of ${fmt(data.total_matching)}. Export CSV for all.</li>` : "");
  document.querySelectorAll(".item-row").forEach(li => {
    li.addEventListener("click", () => select(+li.dataset.rank));
    li.addEventListener("keydown", e => { if (e.key === "Enter") select(+li.dataset.rank); });
  });
}

function select(rank) {
  const a = state.alerts.find(x => x.properties.rank === rank);
  if (!a) return;
  state.selected = rank;
  const p = a.properties;
  document.querySelectorAll(".item-row").forEach(li => li.classList.toggle("active", +li.dataset.rank === rank));
  document.querySelector(`.item-row[data-rank="${rank}"]`)?.scrollIntoView({ block: "nearest" });
  alertLayer.eachLayer(l => {
    const on = l.feature.properties.rank === rank;
    l.setStyle({ color: on ? "#ffffff" : css("--new"), weight: on ? 3 : 1.5, fillOpacity: on ? 0.2 : 0.08 });
    if (on) l.bringToFront();
  });
  map.flyToBounds(L.geoJSON(a).getBounds().pad(1.2), { maxZoom: 16, duration: 0.8 });
  const d = $("detail");
  d.hidden = false;
  d.innerHTML = `<div class="head"><h3>Site #${p.rank}</h3><button class="close" id="closeDetail" aria-label="Close site details">×</button></div>
    <div class="pair">
      <figure><img src="/api/alerts/${rank}/chip/2020" alt="Site ${rank} in 2020"><figcaption>2020</figcaption></figure>
      <figure><img src="/api/alerts/${rank}/chip/2026" alt="Site ${rank} in 2026, outlined"><figcaption>2026</figcaption></figure>
    </div>
    ${p.verdict ? `<div class="verdict">Checked by eye: ${p.verdict}</div>` : ""}
    <dl class="facts">
      <dt>New mining</dt><dd>${fmt(p.area_ha, 2)} ha</dd>
      <dt>Nearest stream</dt><dd>${fmt(p.dist_to_stream_m)} m</dd>
      <dt>Forest reserve</dt><dd>${p.in_protected_area ? "Inside" : "No"}</dd>
      <dt>Model confidence</dt><dd>${fmt(p.confidence * 100)}%</dd>
      <dt>Priority score</dt><dd>${fmt(p.priority, 1)}</dd>
      <dt>Location</dt><dd>${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}</dd>
    </dl>`;
  $("closeDetail").addEventListener("click", () => { d.hidden = true; state.selected = null; document.querySelectorAll(".item-row").forEach(li => li.classList.remove("active")); });
  if (innerWidth <= 1100) $("alerts").classList.add("open");
}

/* ---------- controls ---------- */
function initControls() {
  $("modeExplore").addEventListener("click", () => setMode("explore"));
  $("modeCompare").addEventListener("click", () => setMode("compare"));
  document.querySelectorAll("#yearSwitch button").forEach(b => b.addEventListener("click", () => {
    state.year = b.dataset.year;
    document.querySelectorAll("#yearSwitch button").forEach(x => x.setAttribute("aria-checked", x === b));
    applyLayers();
  }));

  const handle = $("swipeHandle"), wrap = document.querySelector(".mapwrap");
  const move = (e) => { const r = wrap.getBoundingClientRect(); state.swipe = Math.min(0.98, Math.max(0.02, (e.clientX - r.left) / r.width)); updateClip(); };
  handle.addEventListener("pointerdown", e => { handle.setPointerCapture(e.pointerId); map.dragging.disable(); });
  handle.addEventListener("pointermove", e => { if (e.buttons) move(e); });
  handle.addEventListener("pointerup", () => map.dragging.enable());
  handle.addEventListener("keydown", e => { if (e.key === "ArrowLeft") state.swipe = Math.max(0.02, state.swipe - 0.05); if (e.key === "ArrowRight") state.swipe = Math.min(0.98, state.swipe + 0.05); updateClip(); });

  let t;
  const reload = () => { clearTimeout(t); t = setTimeout(loadAlerts, 150); };
  $("minArea").addEventListener("input", e => { state.filters.minArea = +e.target.value; $("minAreaVal").textContent = `${e.target.value} ha`; reload(); });
  [["fRiver", "river"], ["fReserve", "reserve"]].forEach(([id, key]) => $(id).addEventListener("click", e => {
    state.filters[key] = !state.filters[key]; e.currentTarget.setAttribute("aria-pressed", state.filters[key]); reload();
  }));
  $("sortBy").addEventListener("change", e => { state.filters.sort = e.target.value; reload(); });

  $("toggleSide").addEventListener("click", () => { $("side").classList.toggle("open"); $("alerts").classList.remove("open"); });
  $("toggleAlerts").addEventListener("click", () => { $("alerts").classList.toggle("open"); $("side").classList.remove("open"); });
}

boot().catch(err => {
  document.querySelector(".mapwrap").insertAdjacentHTML("beforeend",
    `<div class="legend" style="left:50%;top:50%;bottom:auto;transform:translate(-50%,-50%)">Could not load data: ${err.message}. Run <code>python -m webapp.build_assets</code>, then restart the server.</div>`);
});

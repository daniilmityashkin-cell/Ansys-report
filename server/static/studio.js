// Студия геометрии: пошаговый ввод замеров → восстановленная стенка → конструкция → нагрузки → страница расчёта.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";

const root = document.getElementById("studio");
const $ = (id) => document.getElementById(id);
const csrf = root.dataset.csrf;
const STEPS = 7;
const S = { D: 34.2, H: 12, angles: [], heights: [], values: [], thick: [], defects: [], raw: null, nozzles: [], title: "РВС-10000" };
let step = 1;

function num(v, d) { const x = parseFloat(String(v).replace(",", ".").replace("−", "-").trim()); return isFinite(x) ? x : (d === undefined ? 0 : d); }
function showErr(m) { const e = $("st-err"); e.textContent = m || ""; e.hidden = !m; if (m) e.scrollIntoView({ block: "center" }); }
function jet(t) { t = Math.min(1, Math.max(0, t)); const c = (k) => Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - k))); return [c(3), c(2), c(1)]; }
function rgb(a) { return "rgb(" + a.map((x) => Math.round(x * 255)).join(",") + ")"; }

/* ---------- данные ---------- */
function makeGrid(ng, nz) {
  S.D = num($("p-D").value, 30); S.H = num($("p-H").value, 18);
  S.angles = Array.from({ length: ng }, (_, i) => +(360 * i / ng).toFixed(4));
  S.heights = Array.from({ length: nz + 1 }, (_, k) => +(S.H * k / nz).toFixed(4));
  S.values = Array.from({ length: nz + 1 }, () => Array(ng).fill(0));
  S.thick = Array(nz).fill(10);
}
function resizeTo(ng, nz) {                                   // меняем размер сетки, сохраняя совпадающие ячейки
  const old = S.values, ot = S.thick;
  makeGrid(ng, nz);
  old.forEach((row, j) => { if (j < S.values.length) row.forEach((v, i) => { if (i < ng) S.values[j][i] = v; }); });
  ot.forEach((t, j) => { if (j < nz) S.thick[j] = t; });
}
function readParams() {
  S.title = $("p-title").value; S.D = num($("p-D").value, S.D); S.H = num($("p-H").value, S.H);
  $("st-tank").textContent = S.title + " · " + S.D + " × " + S.H + " м";
}

/* ---------- шаг 1: таблица ---------- */
function drawGrid() {
  const ng = S.angles.length, nz = S.heights.length - 1;
  let mx = 1; S.values.forEach((r) => r.forEach((v) => { mx = Math.max(mx, Math.abs(v)); }));
  let h = "<tr><th>z, м</th>" + S.angles.map((a, i) => "<th>" + (i + 1) + "<br><input data-a=\"" + i + "\" value=\"" + a + "\"></th>").join("") + "<th>t, мм</th></tr>";
  for (let j = 0; j <= nz; j++) {
    h += "<tr><th><input data-z=\"" + j + "\" value=\"" + S.heights[j] + "\"></th>";
    for (let i = 0; i < ng; i++) {
      const v = S.values[j][i], k = v / mx;
      const bg = k > 0 ? "rgba(255,90,70," + Math.min(.75, k * .75) + ")" : k < 0 ? "rgba(70,130,255," + Math.min(.75, -k * .75) + ")" : "transparent";
      h += "<td style=\"background:" + bg + "\"><input data-j=\"" + j + "\" data-i=\"" + i + "\" value=\"" + v + "\"></td>";
    }
    h += j === 0 ? "<td class=\"muted\">—</td>" : "<td><input data-t=\"" + (j - 1) + "\" value=\"" + S.thick[j - 1] + "\"></td>";
    h += "</tr>";
  }
  $("grid").innerHTML = h;
  $("fill-count").textContent = "Заполнено: " + countFilled() + " из " + ng + " образующих";
}
function countFilled() { let c = 0; for (let i = 0; i < S.angles.length; i++) { let any = false; for (let j = 1; j < S.values.length; j++) if (S.values[j][i] !== 0) any = true; if (any) c++; } return c; }
$("grid").addEventListener("change", (e) => {
  const t = e.target, d = t.dataset;
  if (d.j !== undefined) S.values[+d.j][+d.i] = num(t.value);
  else if (d.a !== undefined) S.angles[+d.a] = num(t.value);
  else if (d.z !== undefined) S.heights[+d.z] = num(t.value);
  else if (d.t !== undefined) S.thick[+d.t] = num(t.value, 10);
  drawGrid();
});
$("b-grid").onclick = () => {
  const ng = Math.max(3, Math.min(120, Math.round(num($("p-ng").value, 18)))), nz = Math.max(1, Math.min(60, Math.round(num($("p-nz").value, 9))));
  readParams(); makeGrid(ng, nz); S.raw = null; S.defects = []; drawGrid();
};
function parseBlock(text) {
  return text.split(/\r?\n/).map((r) => r.trim()).filter((r) => r).map((r) => r.split(/[\t;]+|\s{2,}/).map((c) => num(c, NaN)));
}
function applyBlock(rows) {
  rows = rows.filter((r) => r.some((x) => isFinite(x)));
  if (!rows.length) throw new Error("В буфере нет чисел.");
  const w = Math.max(...rows.map((r) => r.length));
  if (rows.some((r) => r.length !== w)) throw new Error("Строки разной длины: скопируйте прямоугольный блок.");
  let ng = S.angles.length, nz = S.heights.length - 1;
  const hasZ = w === ng + 1;                                  // первый столбец — отметки по высоте
  const body = rows.map((r) => (hasZ ? r.slice(1) : r));
  const withZeroRow = body.length === nz + 1;
  if (!withZeroRow && body.length !== nz) { nz = body.length; }
  if (body[0].length !== ng) ng = body[0].length;
  if (ng !== S.angles.length || nz !== S.heights.length - 1) { readParams(); makeGrid(ng, nz); }
  const off = withZeroRow ? 0 : 1;
  body.forEach((r, j) => r.forEach((v, i) => { S.values[j + off][i] = isFinite(v) ? v : 0; }));
  if (hasZ && withZeroRow) rows.forEach((r, j) => { S.heights[j] = r[0]; });
  $("p-ng").value = ng; $("p-nz").value = nz;
}
$("b-paste").onclick = async () => {
  let txt = "";
  try { txt = await navigator.clipboard.readText(); } catch (e) { txt = window.prompt("Вставьте блок чисел из Excel (Ctrl+V):") || ""; }
  if (!txt.trim()) return;
  try { applyBlock(parseBlock(txt)); S.raw = null; drawGrid(); $("src-msg").textContent = "Таблица вставлена."; showErr(""); } catch (e) { showErr(e.message); }
};
document.addEventListener("paste", (e) => {                   // Ctrl+V в сетку
  if (step !== 1 || !e.target.closest || !e.target.closest("#grid")) return;
  const txt = (e.clipboardData || window.clipboardData).getData("text");
  if (!/[\t\n]/.test(txt)) return;
  e.preventDefault();
  try { applyBlock(parseBlock(txt)); S.raw = null; drawGrid(); showErr(""); } catch (er) { showErr(er.message); }
});

/* ---------- загрузка файлов ---------- */
function loadProject(p) {
  S.raw = p;
  S.D = num(p.diameter); S.H = num(p.height);
  S.angles = (p.angles || []).map(Number); S.heights = (p.heights || []).map(Number);
  S.values = (p.values || []).map((r) => r.map(Number));
  S.thick = (p.bands || []).map((b) => num(b[1], 10));
  S.defects = p.defects || [];
  $("p-D").value = S.D; $("p-H").value = S.H; $("p-ng").value = S.angles.length; $("p-nz").value = S.heights.length - 1;
  const ex = p.export_selection;                              // что входит в модель — видимость на шаге 5
  if (ex) { $("v-nozzles").checked = ex.nozzles !== false; }
  const b = p.bottom; if (b) {
    $("s_bot_on").checked = b.enabled !== false;
    [["s_bot_outside", "outside_mm"], ["s_bot_width", "annular_width_mm"], ["s_bot_overlap", "overlap_mm"], ["s_bot_slope", "slope_denominator"], ["s_bot_plate_t", "plate_thickness_mm"], ["s_bot_ann_t", "annular_thickness_mm"]].forEach(([id, k]) => { if (b[k] !== undefined) $(id).value = b[k]; });
  }
  const r = p.roof; if (r) {
    $("s_roof_on").checked = r.enabled !== false;
    $("s_roof_shape").value = r.shape || "Сферическая";
    [["s_roof_sphere_r", "sphere_radius_m"], ["s_roof_cone_rise", "cone_rise_m"], ["s_roof_central_r", "central_radius_m"], ["s_roof_radial", "radial_count"], ["s_roof_first", "first_angle_deg"],
     ["s_roof_rings", "ring_count"], ["s_roof_deck_t", "deck_thickness_mm"], ["s_roof_band_w", "plate_width_mm"], ["s_roof_band_t", "plate_thickness_mm"], ["s_roof_band_drop", "plate_drop_mm"],
     ["s_roof_beam_drop", "beam_drop_mm"], ["s_roof_deck_inset", "deck_inset_mm"]].forEach(([id, k]) => { if (r[k] !== undefined) $(id).value = r[k]; });
  }
  const n = p.roof_nodes; if (n) {
    $("s_node_on").checked = n.enabled !== false;
    [["s_node_ring_h", "ring_height_mm"], ["s_node_ring_t", "ring_thickness_mm"], ["s_node_up_l", "upper_length_mm"], ["s_node_up_h", "upper_height_mm"], ["s_node_up_t", "upper_thickness_mm"],
     ["s_node_lo_l", "lower_length_mm"], ["s_node_lo_h", "lower_height_mm"], ["s_node_lo_t", "lower_thickness_mm"]].forEach(([id, k]) => { if (n[k] !== undefined) $(id).value = n[k]; });
  }
  const bs = p.beam_sections; if (bs) {
    [["s_beam_radial", "radial"], ["s_beam_central", "central_ring"], ["s_beam_rings", "hoop_1"], ["s_beam_edge", "channel"]].forEach(([id, k]) => { if (bs[k] && bs[k].name) $(id).value = bs[k].name; });
  }
  $("nz-rows").innerHTML = "";
  (p.nozzles || []).forEach((z) => addNozzle({ name: z.name, shape: z.shape, width: z.width_mm, height: z.height_mm, z: z.height_m, angle: z.anchor, t: z.thickness_mm, in: z.inside_mm, out: z.outside_mm }));
  if (p.wind_rings) { $("r-h").value = p.wind_rings.map((x) => x.h).join(" "); }
}
$("f-json").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try { const p = JSON.parse((await f.text()).replace(/^﻿/, "")); if (!p.angles || !p.values) throw new Error("В файле нет замеров (angles/values)."); loadProject(p); drawGrid();
    $("src-msg").textContent = "Файл проекта: " + S.angles.length + " образующих, " + (S.heights.length - 1) + " поясов, вмятин: " + S.defects.length + "."; readParams(); showErr("");
  } catch (er) { showErr("Не удалось прочитать файл проекта: " + er.message); }
};
$("f-xlsx").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("xlsx", f); fd.append("csrf", csrf);
  $("src-msg").textContent = "Читаю файл…";
  try {
    const r = await fetch("/studio/xlsx", { method: "POST", body: fd, credentials: "same-origin" }); const d = await r.json();
    if (!r.ok) throw new Error(d.error || "ошибка");
    if (!d.project) throw new Error("В файле не найдена таблица замеров.");
    const keepD = d.need_dims ? $("p-D").value : d.diameter, keepH = d.need_dims ? $("p-H").value : d.height;
    loadProject(d.project); S.raw = null; S.D = num(keepD); S.H = num(keepH); $("p-D").value = keepD; $("p-H").value = keepH;
    S.heights = S.heights.map((_, k) => +(S.H * k / (S.heights.length - 1)).toFixed(4));
    drawGrid(); readParams();
    $("src-msg").textContent = d.need_dims ? "Таблица загружена. Проверьте диаметр, высоту и толщины поясов." : "Геодезия загружена: " + S.angles.length + " образующих, " + (S.heights.length - 1) + " поясов.";
    showErr("");
  } catch (er) { $("src-msg").textContent = ""; showErr(er.message); }
};

/* ---------- шаг 2: профили образующих ---------- */
function drawProfiles() {
  const box = $("profiles"); box.innerHTML = "";
  let mx = 1; S.values.forEach((r) => r.forEach((v) => { mx = Math.max(mx, Math.abs(v)); }));
  const nz = S.heights.length;
  S.angles.forEach((a, i) => {
    const wrap = document.createElement("div"); wrap.className = "prof";
    const c = document.createElement("canvas"); c.width = 150; c.height = 240; wrap.appendChild(c);
    const lab = document.createElement("div"); lab.textContent = "№" + (i + 1) + " · " + a + "°"; wrap.appendChild(lab); box.appendChild(wrap);
    const g = c.getContext("2d"), X = (v) => 75 + v / mx * 60, Y = (z) => 228 - z / S.H * 214;
    g.strokeStyle = "#2a2e35"; g.beginPath(); g.moveTo(75, 8); g.lineTo(75, 232); g.stroke();
    g.strokeStyle = "#ffb71b"; g.lineWidth = 1.6; g.beginPath();
    for (let j = 0; j < nz; j++) { const x = X(S.values[j][i]), y = Y(S.heights[j]); j ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke(); g.fillStyle = "#ff6b6b";
    for (let j = 0; j < nz; j++) { g.beginPath(); g.arc(X(S.values[j][i]), Y(S.heights[j]), 2.4, 0, 6.3); g.fill(); }
  });
}

/* ---------- шаг 3: вмятины ---------- */
function drawDents() {
  const box = $("dent-list"); box.innerHTML = "";
  if (!S.defects.length) { box.innerHTML = "<p class=\"muted\">Вмятин нет.</p>"; return; }
  S.defects.forEach((d, k) => {
    const row = document.createElement("div"); row.className = "dent";
    const c = document.createElement("canvas"); c.width = 110; c.height = 110; row.appendChild(c);
    let mn = 0; (d.values || []).forEach((r) => r.forEach((v) => { mn = Math.min(mn, v); }));
    let mxv = 1e-9; (d.values || []).forEach((r) => r.forEach((v) => { mxv = Math.max(mxv, Math.abs(v)); }));
    const g = c.getContext("2d"), ny = (d.values || []).length, nx = ny ? d.values[0].length : 0;
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) { g.fillStyle = rgb(jet(Math.abs(d.values[j][i]) / mxv)); g.fillRect(i * 110 / nx, 110 - (j + 1) * 110 / ny, 110 / nx + 1, 110 / ny + 1); }
    const t = document.createElement("div"); t.innerHTML = "<b>" + (d.name || "Вмятина " + (k + 1)) + "</b><br><span class=\"muted\">центр " + d.anchor + "°, z = " + d.height + " м; " + d.width + " × " + d.span_height + " м; макс. отклонение " + mn.toFixed(1) + " мм</span>";
    row.appendChild(t);
    const b = document.createElement("button"); b.type = "button"; b.className = "btn light"; b.textContent = "Удалить"; b.onclick = () => { S.defects.splice(k, 1); drawDents(); }; row.appendChild(b);
    box.appendChild(row);
  });
}
$("b-dent").onclick = () => {
  const ang = num($("d-ang").value), z = num($("d-z").value), w = num($("d-w").value, 1.8), h = num($("d-h").value, 2), depth = num($("d-depth").value, -30);
  const nx = 13, ny = 11, x = Array.from({ length: nx }, (_, i) => -w / 2 + w * i / (nx - 1)), y = Array.from({ length: ny }, (_, j) => -h / 2 + h * j / (ny - 1));
  const values = y.map((yy) => x.map((xx) => +(depth * Math.exp(-((xx / (w / 2.6)) ** 2 + (yy / (h / 2.6)) ** 2)) ).toFixed(2)));
  S.defects.push({ name: "Вмятина " + (S.defects.length + 1), mode: "Угол, град", anchor: ang, height: z, width: w, span_height: h, nx, ny, x, y, values });
  drawDents();
};

/* ---------- 3D ---------- */
const views = {};
function makeView(id, target, cam) {
  if (views[id]) return views[id];
  const canvas = $(id), renderer = new THREE.WebGLRenderer({ canvas, antialias: true }); renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0b0d10);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 2000); camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, canvas); controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.1)); const sun = new THREE.DirectionalLight(0xffffff, 1.0); sun.position.set(1, -1, 2); scene.add(sun);
  const v = { id, canvas, renderer, scene, camera, controls, group: new THREE.Group(), home: null };
  scene.add(v.group);
  v.setHome = (t, c) => { v.home = { t, c }; camera.position.set(...c); controls.target.set(...t); controls.update(); };
  v.setHome(target, cam);
  v.clear = () => { while (v.group.children.length) { const o = v.group.children.pop(); o.traverse && o.traverse((m) => { if (m.geometry) m.geometry.dispose(); if (m.material) m.material.dispose(); }); } };
  views[id] = v; return v;
}
function loop() {
  requestAnimationFrame(loop);
  for (const k in views) {
    const v = views[k]; if (!v.canvas.offsetParent) continue;
    const w = v.canvas.clientWidth, h = v.canvas.clientHeight;
    if (v.canvas.width !== Math.round(w * v.renderer.getPixelRatio()) || v.canvas.height !== Math.round(h * v.renderer.getPixelRatio())) { v.renderer.setSize(w, h, false); v.camera.aspect = w / h; v.camera.updateProjectionMatrix(); }
    v.controls.update(); v.renderer.render(v.scene, v.camera);
  }
}
loop();

function catmull(p0, p1, p2, p3, t) { return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t); }
function fieldFn() {                                          // δr(θ, z), мм: бикубическая интерполяция сетки + вмятины
  const ng = S.angles.length, nz = S.heights.length, vals = S.values, hs = S.heights, an = S.angles;
  const D = S.D;
  function atTheta(row, th) {                                  // периодически по углу
    let a = ((th % 360) + 360) % 360, i = 0;
    for (let k = 0; k < ng; k++) if (an[k] <= a) i = k;
    const a0 = an[i], a1 = i + 1 < ng ? an[i + 1] : an[0] + 360, t = a1 > a0 ? (a - a0) / (a1 - a0) : 0;
    const g = (k) => row[((k % ng) + ng) % ng];
    return catmull(g(i - 1), g(i), g(i + 1), g(i + 2), t);
  }
  return (th, z) => {
    let j = 0; for (let k = 0; k < nz; k++) if (hs[k] <= z) j = k; j = Math.min(j, nz - 2);
    const z0 = hs[j], z1 = hs[j + 1], t = z1 > z0 ? (z - z0) / (z1 - z0) : 0;
    const r = (k) => atTheta(vals[Math.max(0, Math.min(nz - 1, k))], th);
    let v = catmull(r(j - 1), r(j), r(j + 1), r(j + 2), Math.min(1, Math.max(0, t)));
    for (const d of S.defects) {                               // локальные вмятины поверх основных замеров
      let dth = ((th - d.anchor + 540) % 360) - 180, x = dth * Math.PI / 180 * D / 2, y = z - d.height;
      if (Math.abs(x) > d.width / 2 || Math.abs(y) > d.span_height / 2 || !d.values) continue;
      const nx = d.x.length, ny = d.y.length, fx = (x - d.x[0]) / (d.x[nx - 1] - d.x[0]) * (nx - 1), fy = (y - d.y[0]) / (d.y[ny - 1] - d.y[0]) * (ny - 1);
      const i0 = Math.max(0, Math.min(nx - 2, Math.floor(fx))), j0 = Math.max(0, Math.min(ny - 2, Math.floor(fy))), tx = fx - i0, ty = fy - j0;
      const dv = (d.values[j0][i0] * (1 - tx) + d.values[j0][i0 + 1] * tx) * (1 - ty) + (d.values[j0 + 1][i0] * (1 - tx) + d.values[j0 + 1][i0 + 1] * tx) * ty;
      v += dv;
    }
    return v;
  };
}
function buildWall(view, amp, rings) {
  view.clear();
  const R = S.D / 2, H = S.H, NT = 220, NZ = 110, f = fieldFn();
  const pos = [], col = [], idx = []; let mxAbs = 1e-9; const vals = [];
  for (let j = 0; j <= NZ; j++) for (let i = 0; i <= NT; i++) { const th = 360 * (i % NT) / NT, z = H * j / NZ, v = f(th, z); vals.push(v); mxAbs = Math.max(mxAbs, Math.abs(v)); }
  let q = 0;
  for (let j = 0; j <= NZ; j++) for (let i = 0; i <= NT; i++) {
    const th = 2 * Math.PI * (i % NT) / NT, v = vals[q++], r = R + amp * v / 1000, c = jet(Math.abs(v) / mxAbs);
    pos.push(r * Math.cos(th), r * Math.sin(th), H * j / NZ); col.push(c[0], c[1], c[2]);
  }
  for (let j = 0; j < NZ; j++) for (let i = 0; i < NT; i++) { const a = j * (NT + 1) + i, b = a + 1, c = a + NT + 1, d = c + 1; idx.push(a, b, c, b, d, c); }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3)); g.setIndex(idx); g.computeVertexNormals();
  view.group.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide, roughness: .7, metalness: .05 })));
  view.setHome([0, 0, H / 2], [R * 2.4, -R * 2.6, H * 0.95 + R * 0.7]);
  return mxAbs;
}
function showWall() {
  const v = makeView("cv-wall", [0, 0, S.H / 2], [S.D * 1.2, -S.D * 1.3, S.H + S.D * .35]), amp = num($("amp").value, 10);
  const mx = buildWall(v, amp); $("lg-max").textContent = mx.toFixed(0) + " мм"; $("amp-v").textContent = amp; $("amp-l").textContent = amp;
}
$("amp").oninput = showWall;
$("v-reset").onclick = () => { const v = views["cv-wall"]; if (v && v.home) { v.camera.position.set(...v.home.c); v.controls.target.set(...v.home.t); } };

/* ---------- шаг 5: конструкция ---------- */
function addNozzle(r) {
  r = r || { name: "", shape: "Круглый", width: 426, height: 426, z: 1.1, angle: 0, t: 11, in: 200, out: 500 };
  const d = document.createElement("div"); d.className = "nzrow";
  d.innerHTML = "<input data-k=\"name\" placeholder=\"Название\" value=\"" + (r.name || "") + "\"><select data-k=\"shape\"><option" + (r.shape === "Овальный" ? "" : " selected") + ">Круглый</option><option" + (r.shape === "Овальный" ? " selected" : "") + ">Овальный</option></select>" +
    "<input data-k=\"width\" placeholder=\"Ø/ширина, мм\" value=\"" + r.width + "\"><input data-k=\"height\" placeholder=\"Высота овала, мм\" value=\"" + r.height + "\"><input data-k=\"z\" placeholder=\"Высота центра, м\" value=\"" + r.z + "\">" +
    "<input data-k=\"angle\" placeholder=\"Угол, °\" value=\"" + r.angle + "\"><input data-k=\"t\" placeholder=\"Толщина, мм\" value=\"" + r.t + "\"><input data-k=\"in\" placeholder=\"Внутри, мм\" value=\"" + r.in + "\"><input data-k=\"out\" placeholder=\"Снаружи, мм\" value=\"" + r.out + "\"><button type=\"button\" class=\"x\">×</button>";
  $("nz-rows").appendChild(d);
}
$("nz-add").onclick = () => { addNozzle(); showStruct(); };
$("nz-rows").addEventListener("click", (e) => { if (e.target.classList.contains("x")) { e.target.parentNode.remove(); showStruct(); } });
function nozzles() { return [...$("nz-rows").children].map((d) => { const o = {}; d.querySelectorAll("[data-k]").forEach((i) => { o[i.dataset.k] = i.value; }); return o; }); }
function structFields() {
  const f = {};
  document.querySelectorAll(".st-step[data-step='5'] input[id^='s_'], .st-step[data-step='5'] select[id^='s_']").forEach((el) => {
    if (!el.id || !el.id.startsWith("s_")) return;
    if (el.type === "checkbox") { if (el.checked) f[el.id] = "1"; } else f[el.id] = el.value;
  });
  const nz = nozzles(), keys = { s_nz_name: "name", s_nz_shape: "shape", s_nz_width: "width", s_nz_height: "height", s_nz_z: "z", s_nz_angle: "angle", s_nz_t: "t", s_nz_in: "in", s_nz_out: "out" };
  for (const k in keys) f[k] = nz.map((n) => n[keys[k]]);
  return f;
}
function showStruct() {
  readParams();
  const R = S.D / 2, H = S.H, v = makeView("cv-struct", [0, 0, H / 2], [R * 2.6, -R * 2.8, H + R * 1.1]); v.clear();
  const f = structFields(), G = v.group;
  const wall = new THREE.Mesh(new THREE.CylinderGeometry(R, R, H, 96, 1, true).rotateX(Math.PI / 2).translate(0, 0, H / 2), new THREE.MeshStandardMaterial({ color: 0x4f86c6, side: THREE.DoubleSide, transparent: true, opacity: .72 })); wall.userData.k = "wall"; G.add(wall);
  const gb = new THREE.Group(); gb.userData.k = "bottom";
  if (f.s_bot_on) {
    const out = num(f.s_bot_outside, 200) / 1000, disc = new THREE.Mesh(new THREE.CircleGeometry(R - 0.1, 96), new THREE.MeshStandardMaterial({ color: 0x7c8a6a, side: THREE.DoubleSide })), ann = new THREE.Mesh(new THREE.RingGeometry(R - num(f.s_bot_width, 1500) / 1000 + out, R + out, 96), new THREE.MeshStandardMaterial({ color: 0x9aa0a6, side: THREE.DoubleSide }));
    ann.position.z = -0.01; gb.add(disc, ann);
  }
  G.add(gb);
  const gr = new THREE.Group(); gr.userData.k = "roof";
  if (f.s_roof_on) {
    const cone = f.s_roof_shape === "Коническая", SR = num(f.s_roof_sphere_r, 50), rise = cone ? num(f.s_roof_cone_rise, 2) : SR - Math.sqrt(Math.max(SR * SR - R * R, 0)), cr = num(f.s_roof_central_r, 1.3);
    const zr = (r) => H + (cone ? rise * (1 - r / R) : (Math.sqrt(Math.max(SR * SR - r * r, 0)) - Math.sqrt(Math.max(SR * SR - R * R, 0))));
    const pts = []; for (let k = 0; k <= 24; k++) { const r = R * k / 24; pts.push(new THREE.Vector2(r, zr(r))); }
    const lp = pts.map((p) => new THREE.Vector3(p.x, 0, p.y)); void lp;
    const geo = new THREE.LatheGeometry(pts, 96); geo.rotateX(Math.PI / 2);
    gr.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0xc9a14a, side: THREE.DoubleSide, transparent: true, opacity: .55 })));
    const nr = Math.round(num(f.s_roof_radial, 24)), a0 = num(f.s_roof_first, 0) * Math.PI / 180, lm = new THREE.LineBasicMaterial({ color: 0xffd36e });
    for (let k = 0; k < nr; k++) { const a = a0 + 2 * Math.PI * k / nr, p = []; for (let s = 0; s <= 16; s++) { const r = cr + (R - cr) * s / 16; p.push(new THREE.Vector3(r * Math.cos(a), r * Math.sin(a), zr(r) + .02)); } gr.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(p), lm)); }
    const nrg = Math.round(num(f.s_roof_rings, 10));
    for (let k = 0; k <= nrg + 1; k++) { const r = cr + (R - cr) * k / (nrg + 1), p = []; for (let s = 0; s <= 96; s++) { const a = 2 * Math.PI * s / 96; p.push(new THREE.Vector3(r * Math.cos(a), r * Math.sin(a), zr(r) + .02)); } gr.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(p), lm)); }
  }
  G.add(gr);
  const gn = new THREE.Group(); gn.userData.k = "nozzles";
  nozzles().forEach((n) => {
    const w = num(n.width, 400) / 1000, len = (num(n.in, 0) + num(n.out, 500)) / 1000 + .1, a = num(n.angle) * Math.PI / 180;
    const c = new THREE.Mesh(new THREE.CylinderGeometry(w / 2, w / 2, len, 24), new THREE.MeshStandardMaterial({ color: 0xffb71b }));
    c.rotation.set(0, 0, 0); c.rotateZ(a + Math.PI / 2); c.position.set((R + (num(n.out, 500) - num(n.in, 0)) / 2000) * Math.cos(a), (R + (num(n.out, 500) - num(n.in, 0)) / 2000) * Math.sin(a), num(n.z));
    gn.add(c);
  });
  G.add(gn); applyVis();
}
function applyVis() { const v = views["cv-struct"]; if (!v) return; const map = { wall: "v-wall", roof: "v-roof", bottom: "v-bottom", nozzles: "v-nozzles" }; v.group.children.forEach((o) => { if (o.userData.k) o.visible = $(map[o.userData.k]).checked; }); }
["v-wall", "v-roof", "v-bottom", "v-nozzles"].forEach((id) => { $(id).onchange = applyVis; });
document.querySelector(".st-step[data-step='5']").addEventListener("change", (e) => { if (e.target.id !== undefined && !e.target.id.startsWith("v-")) showStruct(); });

/* ---------- шаг 6: ветровые кольца ---------- */
function ringHeights() { return $("r-h").value.split(/[\s;,]+/).map((x) => num(x, NaN)).filter((x) => isFinite(x) && x > 0 && x < S.H); }
function showRings() {
  const v = makeView("cv-rings", [0, 0, S.H / 2], [S.D * 1.2, -S.D * 1.3, S.H + S.D * .35]); buildWall(v, 1);
  const R = S.D / 2, f = fieldFn();
  ringHeights().forEach((z) => {
    const p = []; for (let s = 0; s <= 160; s++) { const th = 360 * s / 160, r = R + f(th, z) / 1000 + 0.05, a = th * Math.PI / 180; p.push(new THREE.Vector3(r * Math.cos(a), r * Math.sin(a), z)); }
    v.group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(p), new THREE.LineBasicMaterial({ color: 0xffffff })));
  });
}
$("r-h").oninput = showRings;

/* ---------- шаг 7: нагрузки и сборка ---------- */
function loadFields() {
  const l = { l_on: "1" };
  document.querySelectorAll(".st-step[data-step='7'] [id^='l_']").forEach((e) => { l[e.id] = e.value; });
  return l;
}
function buildProject() {
  readParams();
  const nz = S.heights.length - 1;
  const p = Object.assign({}, S.raw || {}, {
    version: S.raw ? S.raw.version : "1.0", diameter: String(S.D), height: String(S.H), angles: S.angles, heights: S.heights,
    values: S.values.map((r) => r.map((v) => String(v))),
    bands: Array.from({ length: nz }, (_, k) => [String(+(S.heights[k + 1] - S.heights[k]).toFixed(6)), String(S.thick[k])]),
    defects: S.defects, contour_threshold: S.raw ? S.raw.contour_threshold : "0.1", wall_includes_defects: S.raw ? S.raw.wall_includes_defects : !S.defects.length
  });
  const rg = ringHeights(); if (rg.length) p.wind_rings = rg.map((h) => ({ h })); else delete p.wind_rings;
  if (p.roof) {                                                // правки на шаге 5 переносим в файл проекта (каркас)
    const f = structFields(); p.roof = Object.assign({}, p.roof, { radial_count: Math.round(num(f.s_roof_radial, p.roof.radial_count)), ring_count: Math.round(num(f.s_roof_rings, p.roof.ring_count)),
      central_radius_m: String(f.s_roof_central_r), first_angle_deg: num(f.s_roof_first), enabled: !!f.s_roof_on });
  }
  return p;
}
function showSummary() {
  const nz = S.heights.length - 1, f = structFields();
  let mx = 0; S.values.forEach((r) => r.forEach((v) => { mx = Math.max(mx, Math.abs(v)); }));
  $("summary").innerHTML = "<table><tr><td>Резервуар</td><td>" + S.title + ": Ø" + S.D + " × " + S.H + " м, " + nz + " поясов</td></tr><tr><td>Замеры</td><td>" + S.angles.length + " образующих, макс. отклонение " + mx.toFixed(1) + " мм, вмятин: " + S.defects.length + "</td></tr>" +
    "<tr><td>Конструкция</td><td>патрубков " + nozzles().length + "; днище " + (f.s_bot_on ? "да" : "нет") + "; крыша " + (f.s_roof_on ? "да" : "нет") + "; ветровых колец " + ringHeights().length + "</td></tr></table>";
}
$("b-create").onclick = async () => {
  const b = $("b-create"); b.disabled = true; $("create-msg").textContent = "Строю модель…"; showErr("");
  try {
    const r = await fetch("/studio/create", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csrf, title: S.title, project: buildProject(), structure: structFields(), loads: loadFields() }) });
    const d = await r.json(); if (!r.ok) throw new Error(d.error || "ошибка");
    location.href = d.url;
  } catch (e) { b.disabled = false; $("create-msg").textContent = ""; showErr(e.message); }
};

/* ---------- навигация ---------- */
function validate1() {
  readParams();
  if (S.angles.length < 3) throw new Error("Нужно минимум 3 образующие. Нажмите «Создать сетку» или загрузите данные.");
  if (!(S.D > 0 && S.H > 0)) throw new Error("Укажите диаметр и высоту.");
  if (countFilled() === 0 && !confirm("Все отклонения равны нулю (идеальный резервуар). Продолжить?")) throw new Error("Заполните таблицу отклонений.");
}
function go(n) {
  if (n > step && step === 1) { try { validate1(); } catch (e) { showErr(e.message); return; } }
  showErr(""); step = Math.max(1, Math.min(STEPS, n));
  document.querySelectorAll(".st-step").forEach((s) => { s.hidden = +s.dataset.step !== step; });
  $("b-prev").style.visibility = step === 1 ? "hidden" : "visible"; $("b-next").style.display = step === STEPS ? "none" : "";
  $("dots").innerHTML = Array.from({ length: STEPS }, (_, i) => "<i class=\"" + (i + 1 === step ? "on" : i + 1 < step ? "done" : "") + "\"></i>").join("");
  const stage = step === 1 ? 1 : step <= 4 ? 2 : step <= 6 ? 3 : 4;
  document.querySelectorAll(".st-stages span").forEach((s) => s.classList.toggle("on", +s.dataset.st === stage));
  if (step === 2) drawProfiles(); if (step === 3) drawDents(); if (step === 4) showWall(); if (step === 5) showStruct(); if (step === 6) showRings(); if (step === 7) showSummary();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$("b-next").onclick = () => go(step + 1); $("b-prev").onclick = () => go(step - 1);
$("p-title").onchange = readParams; $("p-D").onchange = readParams;
$("p-H").onchange = () => {                                    // меняем высоту: отметки пропорционально
  const old = S.H; readParams();
  if (old > 0 && S.H > 0 && S.H !== old) { S.heights = S.heights.map((z) => +(z * S.H / old).toFixed(4)); drawGrid(); }
};
makeGrid(18, 9); drawGrid(); readParams(); go(1);

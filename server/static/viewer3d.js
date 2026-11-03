// Интерактивный 3D-просмотр стенки резервуара: вращение мышью, колесо - масштаб, правая кнопка - сдвиг.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";
import { modelQuality } from "./model-runtime.js";
import { modelInspector } from "./model-inspector.js";
import { modelControls } from "./model-controls.js";

const root = document.getElementById("viewer");
if (root) start(root).catch(function (e) { var m = "3D-просмотр не запустился: " + e.message; root.querySelector("#v-info").textContent = m; var d = document.createElement("div"); d.className = "viewer-fail"; d.textContent = m + ". Обновите страницу (Ctrl+F5); если не помогло - включите аппаратное ускорение/WebGL в браузере."; root.insertBefore(d, root.firstChild); root.classList.add("failed"); });

function jet(t) {
  t = Math.min(1, Math.max(0, t));
  const c = function (k) { return Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - k))); };
  return [c(3), c(2), c(1)];
}

async function start(box) {
  const source = await loadJson(box.dataset.src);
  const compact = modelQuality().compact;
  const columns = Array.from({length: compact ? Math.ceil(source.nt / 2) : source.nt}, (_, i) => i);
  const xs = columns.map(i => Math.round(i / (columns.length - 1) * (source.nt - 1)));
  const rows = compact ? Math.ceil(source.nz / 2) : source.nz;
  const ys = Array.from({length: rows}, (_, j) => Math.round(j / (rows - 1) * (source.nz - 1)));
  const data = {...source, nt: xs.length, nz: ys.length, grid: ys.flatMap(j => xs.map(i => source.grid[j * source.nt + i]))};
  box.dataset.modelQuality = compact ? "compact" : "full";
  box.dataset.displayVertices = data.nt * data.nz;
  const canvas = box.querySelector("canvas");
  const info = box.querySelector("#v-info");
  const ampInput = box.querySelector("#v-amp"), ampLabel = box.querySelector("#v-amp-l");
  const R = data.R, H = data.H, nt = data.nt, nz = data.nz;
  const maxAbs = Math.max(Math.abs(data.min), Math.abs(data.max), 1e-9);
  box.querySelector("#v-max").textContent = maxAbs.toFixed(0) + " мм";
  box.querySelector("#v-min").textContent = "0";

  const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setPixelRatio(modelQuality().pixelRatio);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0d10);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 1000);
  camera.up.set(0, 0, 1);
  const home = new THREE.Vector3(R * 2.4, -R * 2.6, H * 0.95 + R * 0.7);
  camera.position.copy(home);
  const controls = new OrbitControls(camera, canvas);
  controls.target.set(0, 0, H / 2);
  controls.enableDamping = true;
  controls.enableZoom = true;                       // колесо и жест двумя пальцами меняют масштаб
  controls.update();
  const interaction = modelControls(controls, canvas, camera, { scope: box });
  scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1);
  sun.position.set(R * 2, -R, H * 2);
  scene.add(sun);

  // --- поверхность
  const pos = new Float32Array(nt * nz * 3), col = new Float32Array(nt * nz * 3);
  for (let j = 0; j < nz; j++) for (let i = 0; i < nt; i++) {
    const v = data.grid[j * nt + i], c = jet(Math.abs(v) / maxAbs), k = (j * nt + i) * 3;
    col[k] = c[0]; col[k + 1] = c[1]; col[k + 2] = c[2];
  }
  const idx = [];
  for (let j = 0; j < nz - 1; j++) for (let i = 0; i < nt - 1; i++) {
    const a = j * nt + i, b = a + 1, c = a + nt, d = c + 1;
    idx.push(a, b, d, a, d, c);
  }
  const sg = new THREE.BufferGeometry();
  sg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  sg.setAttribute("color", new THREE.BufferAttribute(col, 3));
  sg.setIndex(idx);
  const surface = new THREE.Mesh(sg, new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide, roughness: 0.85, metalness: 0 }));
  scene.add(surface);

  // --- сетка: каждая 6-я линия
  const wirePairs = [];
  for (let j = 0; j < nz; j += 6) for (let i = 0; i < nt - 1; i++) wirePairs.push(j * nt + i, j * nt + i + 1);
  for (let i = 0; i < nt - 1; i += 10) for (let j = 0; j < nz - 1; j++) wirePairs.push(j * nt + i, (j + 1) * nt + i);
  const wg = new THREE.BufferGeometry();
  wg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  wg.setIndex(wirePairs);
  const wire = new THREE.LineSegments(wg, new THREE.LineBasicMaterial({ color: 0x1b1f24, transparent: true, opacity: 0.45 }));
  wire.visible = false;
  scene.add(wire);

  // --- измеренные точки
  const na = data.angles.length, nh = data.heights.length;
  const ppos = new Float32Array(na * nh * 3), pcol = new Float32Array(na * nh * 3);
  for (let j = 0; j < nh; j++) for (let i = 0; i < na; i++) {
    const c = jet(Math.abs(data.points[j * na + i]) / maxAbs), k = (j * na + i) * 3;
    pcol[k] = c[0]; pcol[k + 1] = c[1]; pcol[k + 2] = c[2];
  }
  const pg = new THREE.BufferGeometry();
  pg.setAttribute("position", new THREE.BufferAttribute(ppos, 3));
  pg.setAttribute("color", new THREE.BufferAttribute(pcol, 3));
  const points = new THREE.Points(pg, new THREE.PointsMaterial({ size: 8, sizeAttenuation: false, vertexColors: true }));
  points.visible = false;
  scene.add(points);

  // --- кольца низа и верха
  const ring = function (z) {
    const p = []; for (let i = 0; i <= 120; i++) { const t = i / 120 * Math.PI * 2; p.push(new THREE.Vector3(R * Math.cos(t), R * Math.sin(t), z)); }
    return new THREE.Line(new THREE.BufferGeometry().setFromPoints(p), new THREE.LineBasicMaterial({ color: 0x8a8f98 }));
  };
  scene.add(ring(0), ring(H));

  function rebuild() {
    const amp = (typeof shownAmp === "undefined" ? Number(ampInput.value) : shownAmp) / 1000;
    ampLabel.textContent = ampInput.value + "×";
    info.textContent = "Цвет — |Δr|, мм. Отклонения усилены в " + ampInput.value + " раз только для наглядности.";
    for (let j = 0; j < nz; j++) for (let i = 0; i < nt; i++) {
      const t = i / (nt - 1) * Math.PI * 2, z = j / (nz - 1) * H, r = R + data.grid[j * nt + i] * amp, k = (j * nt + i) * 3;
      pos[k] = r * Math.cos(t); pos[k + 1] = r * Math.sin(t); pos[k + 2] = z;
    }
    for (let j = 0; j < nh; j++) for (let i = 0; i < na; i++) {
      const t = data.angles[i] * Math.PI / 180, r = R + data.points[j * na + i] * amp * 1.02, k = (j * na + i) * 3;
      ppos[k] = r * Math.cos(t); ppos[k + 1] = r * Math.sin(t); ppos[k + 2] = data.heights[j];
    }
    sg.attributes.position.needsUpdate = true; pg.attributes.position.needsUpdate = true;
    sg.computeVertexNormals(); sg.computeBoundingSphere(); pg.computeBoundingSphere();
  }
  rebuild();
  const nominal = new THREE.Mesh(new THREE.CylinderGeometry(R,R,H,modelQuality().radial,1,true).rotateX(Math.PI/2).translate(0,0,H/2), new THREE.MeshBasicMaterial({color:0xb9c5d8,wireframe:true,transparent:true,opacity:.18,side:THREE.DoubleSide}));
  nominal.visible=false;scene.add(nominal);
  const comparison=document.createElement('div');comparison.className='comparison-tools';
  comparison.innerHTML='<label>Сравнение <select data-compare><option value="surface">Восстановленная поверхность</option><option value="measurements">Исходные замеры</option><option value="overlay">Поверхность и замеры</option></select></label><label><input type="checkbox" data-nominal> Проектный цилиндр</label><p>Исходные замеры показаны точками. Поверхность — интерполяция этих замеров с учётом вмятин. Проектный цилиндр не содержит отклонений.</p>';
  box.append(comparison);
  comparison.querySelector('[data-nominal]').onchange=e=>{nominal.visible=e.target.checked;};
  comparison.querySelector('select').onchange=e=>{
    interaction.stop();surface.visible=e.target.value!=='measurements';points.visible=e.target.value!=='surface';
    box.querySelector('#v-surf').checked=surface.visible;box.querySelector('#v-pts').checked=points.visible;
  };
  const inspector=modelInspector({THREE,renderer,scene,camera,canvas,scope:box,R,H,objects:()=>[surface,points],describe:(hit,angle)=>{
    if(hit.object===points){const i=hit.index%na,j=Math.floor(hit.index/na);return `Замер: образующая ${i+1} · φ = ${data.angles[i].toFixed(1)}° · Z = ${data.heights[j].toFixed(3)} м · Δr = ${data.points[hit.index].toFixed(1)} мм`;}
    const i=Math.round(angle/360*(source.nt-1)),j=Math.max(0,Math.min(source.nz-1,Math.round(hit.point.z/H*(source.nz-1))));
    return `Интерполированная поверхность: φ = ${angle.toFixed(1)}° · Z = ${hit.point.z.toFixed(3)} м · Δr ≈ ${source.grid[j*source.nt+i].toFixed(1)} мм (ближайший узел сетки)`;
  }});
  var shownAmp=Number(ampInput.value), targetAmp=shownAmp;

  const bind = function (id, obj) { box.querySelector(id).addEventListener("change", function (e) { obj.visible = e.target.checked; }); };
  bind("#v-surf", surface); bind("#v-pts", points); bind("#v-wire", wire);
  ampInput.addEventListener("input", () => {interaction.stop();inspector.clear();targetAmp=Number(ampInput.value);if(matchMedia("(prefers-reduced-motion: reduce)").matches){shownAmp=targetAmp;rebuild();}});
  const zoomInput = box.querySelector("#v-zoom"), zoomLabel = box.querySelector("#v-zoom-l");
  const homeDist = home.distanceTo(controls.target);
  controls.minDistance = Math.max(R, H / 2) * 1.1; controls.maxDistance = homeDist * 5;
  controls.addEventListener('change', () => {
    const percent = Math.round(homeDist / camera.position.distanceTo(controls.target) * 100);
    zoomInput.value = percent; zoomLabel.textContent = percent + '%';
  });
  function setZoom() {                                // 100% = исходный вид; больше - ближе
    const k = Number(zoomInput.value) / 100, dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).addScaledVector(dir, homeDist / k);
    zoomLabel.textContent = zoomInput.value + "%";
    controls.update();
  }
  zoomInput.addEventListener("input", setZoom);
  box.querySelector("#v-reset").addEventListener("click", function () { camera.position.copy(home); controls.target.set(0, 0, H / 2); zoomInput.value = 100; zoomLabel.textContent = "100%"; controls.update(); });
  box.querySelector("#v-full").addEventListener("click", function () { if (document.fullscreenElement) document.exitFullscreen(); else box.requestFullscreen && box.requestFullscreen(); });

  const advanced=document.createElement('details');advanced.className='model-analysis';
  const summary=document.createElement('summary');summary.textContent='Разрез, сравнение и отображение';advanced.append(summary);
  const selection=inspector.tools.querySelector('output');box.append(selection);
  advanced.append(comparison,inspector.tools,box.querySelector('.vbar'));box.append(advanced);

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.floor(w * renderer.getPixelRatio()) || canvas.height !== Math.floor(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    }
  }
  new ResizeObserver(resize).observe(canvas);
  resize();
  renderer.setAnimationLoop(function () {
    if (Math.abs(shownAmp-targetAmp)>.01) {shownAmp+=(targetAmp-shownAmp)*.16;rebuild();}
    if (interaction.update()) renderer.render(scene, camera);
  });
  box.classList.add("ready");
}

async function loadJson(url) {                      // файл может появиться на пару секунд позже страницы - повторяем
  for (let i = 0; ; i++) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (r.ok) return r.json();
    if (i >= 8) throw new Error("данные не найдены (" + r.status + ")");
    await new Promise(function (ok) { setTimeout(ok, 1000); });
  }
}

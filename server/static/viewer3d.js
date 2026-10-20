// Интерактивный 3D-просмотр стенки резервуара: вращение мышью, колесо - масштаб, правая кнопка - сдвиг.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";

const root = document.getElementById("viewer");
if (root) start(root).catch(function (e) { var m = "3D-просмотр не запустился: " + e.message; root.querySelector("#v-info").textContent = m; var d = document.createElement("div"); d.className = "viewer-fail"; d.textContent = m + ". Обновите страницу (Ctrl+F5); если не помогло - включите аппаратное ускорение/WebGL в браузере."; root.insertBefore(d, root.firstChild); root.classList.add("failed"); });

function jet(t) {
  t = Math.min(1, Math.max(0, t));
  const c = function (k) { return Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - k))); };
  return [c(3), c(2), c(1)];
}

async function start(box) {
  const data = await loadJson(box.dataset.src);
  const canvas = box.querySelector("canvas");
  const info = box.querySelector("#v-info");
  const ampInput = box.querySelector("#v-amp"), ampLabel = box.querySelector("#v-amp-l");
  const R = data.R, H = data.H, nt = data.nt, nz = data.nz;
  const maxAbs = Math.max(Math.abs(data.min), Math.abs(data.max), 1e-9);
  box.querySelector("#v-max").textContent = maxAbs.toFixed(0) + " мм";
  box.querySelector("#v-min").textContent = "0";

  const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0d10);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 1000);
  camera.up.set(0, 0, 1);
  const home = new THREE.Vector3(R * 2.4, -R * 2.6, H * 0.95 + R * 0.7);
  camera.position.copy(home);
  const controls = new OrbitControls(camera, canvas);
  controls.target.set(0, 0, H / 2);
  controls.enableDamping = true;
  controls.enableZoom = false;                       // колесо прокручивает страницу; масштаб - ползунком
  controls.update();
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
    const amp = +ampInput.value / 1000;
    ampLabel.textContent = ampInput.value + "×";
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

  const bind = function (id, obj) { box.querySelector(id).addEventListener("change", function (e) { obj.visible = e.target.checked; }); };
  bind("#v-surf", surface); bind("#v-pts", points); bind("#v-wire", wire);
  ampInput.addEventListener("input", rebuild);
  const zoomInput = box.querySelector("#v-zoom"), zoomLabel = box.querySelector("#v-zoom-l");
  const homeDist = home.distanceTo(controls.target);
  function setZoom() {                                // 100% = исходный вид; больше - ближе
    const k = Number(zoomInput.value) / 100, dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).addScaledVector(dir, homeDist / k);
    zoomLabel.textContent = zoomInput.value + "%";
    controls.update();
  }
  zoomInput.addEventListener("input", setZoom);
  box.querySelector("#v-reset").addEventListener("click", function () { camera.position.copy(home); controls.target.set(0, 0, H / 2); zoomInput.value = 100; zoomLabel.textContent = "100%"; controls.update(); });
  box.querySelector("#v-full").addEventListener("click", function () { if (document.fullscreenElement) document.exitFullscreen(); else box.requestFullscreen && box.requestFullscreen(); });

  // --- подсказка при наведении
  const ray = new THREE.Raycaster(); ray.params.Points.threshold = 6;
  canvas.addEventListener("pointermove", function (ev) {
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2((ev.clientX - r.left) / r.width * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
    const targets = []; if (points.visible) targets.push(points); if (surface.visible) targets.push(surface);
    const hit = ray.intersectObjects(targets, false)[0];
    if (!hit) return;
    if (hit.object === points) {
      const g = hit.index % na, b = Math.floor(hit.index / na);
      info.textContent = "Точка: образующая " + (g + 1) + ", отметка " + data.heights[b].toFixed(2) + " м: Δr = " + data.points[hit.index].toFixed(1) + " мм";
    } else {
      const v = hit.face.a, i = v % nt, j = Math.floor(v / nt);
      info.textContent = "Поверхность: φ = " + (i / (nt - 1) * 360).toFixed(0) + "°, высота " + (j / (nz - 1) * H).toFixed(2) + " м: Δr = " + data.grid[v].toFixed(1) + " мм";
    }
  });

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.floor(w * renderer.getPixelRatio()) || canvas.height !== Math.floor(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    }
  }
  new ResizeObserver(resize).observe(canvas);
  resize();
  renderer.setAnimationLoop(function () { controls.update(); renderer.render(scene, camera); });
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

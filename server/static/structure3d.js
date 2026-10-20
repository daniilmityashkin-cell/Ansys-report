// 3D-схема конструкции: стенка, патрубки, днище с окрайкой, крыша (каркас, кольца, настил). Масштаб - ползунком, колесо прокручивает страницу.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";

const root = document.getElementById("struct3d");
if (root) start(root).catch(function (e) { root.querySelector(".vinfo").textContent = "3D-схема не запустилась: " + e.message; });

function mat(color, opacity, extra) {
  return new THREE.MeshStandardMaterial(Object.assign({ color: color, transparent: opacity < 1, opacity: opacity, side: THREE.DoubleSide, roughness: 0.8, metalness: 0.05 }, extra || {}));
}
function lines(points, color) {
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color: color }));
}

async function start(box) {
  const S = await (await fetch(box.dataset.src, { credentials: "same-origin" })).json();
  const R = S.D / 2, H = S.H, canvas = box.querySelector("canvas");
  const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0d10);
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 2000);
  camera.up.set(0, 0, 1);
  const target = new THREE.Vector3(0, 0, H / 2);
  const home = new THREE.Vector3(R * 2.6, -R * 3.0, H * 1.3 + R * 0.8);
  camera.position.copy(home);
  const controls = new OrbitControls(camera, canvas);
  controls.target.copy(target); controls.enableDamping = true; controls.enableZoom = false; controls.update();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.0); sun.position.set(R * 2, -R, H * 2); scene.add(sun);
  const g = { wall: new THREE.Group(), nozzles: new THREE.Group(), bottom: new THREE.Group(), roof: new THREE.Group() };
  Object.values(g).forEach(function (x) { scene.add(x); });

  // стенка (по образующей №1 - угол 0, ось X)
  const wall = new THREE.Mesh(new THREE.CylinderGeometry(R, R, H, 96, 1, true), mat(0x5b9bd5, 0.35));
  wall.rotation.x = Math.PI / 2; wall.position.z = H / 2;
  g.wall.add(wall);
  g.wall.add(lines(Array.from({ length: 2 }, function (_, i) { return new THREE.Vector3(R, 0, i * H); }), 0xffffff));

  // патрубки
  (S.nozzles || []).forEach(function (n) {
    const a = n.angle * Math.PI / 180, len = (n.inside_mm + n.outside_mm) / 1000, rin = n.inside_mm / 1000;
    const w = n.width_mm / 2000, h = n.height_mm / 2000, shape = new THREE.Shape();
    if (n.shape === "Круглый") shape.absellipse(0, 0, w, w, 0, Math.PI * 2);
    else { const r = Math.min(w, h), hw = Math.max(w - r, 0), hh = Math.max(h - r, 0);
      shape.absarc(hw, hh, r, 0, Math.PI / 2); shape.absarc(-hw, hh, r, Math.PI / 2, Math.PI); shape.absarc(-hw, -hh, r, Math.PI, 1.5 * Math.PI); shape.absarc(hw, -hh, r, 1.5 * Math.PI, 2 * Math.PI); }
    const geo = new THREE.ExtrudeGeometry(shape, { depth: len, bevelEnabled: false, curveSegments: 24 });
    const mesh = new THREE.Mesh(geo, mat(0xe3a63b, 0.95));
    // экструзия по +Z -> радиально наружу: локальный X -> касательная, Y -> вертикаль
    const radial = new THREE.Vector3(Math.cos(a), Math.sin(a), 0), tang = new THREE.Vector3(-Math.sin(a), Math.cos(a), 0), up = new THREE.Vector3(0, 0, 1);
    mesh.matrix.makeBasis(tang, up, radial).setPosition(radial.clone().multiplyScalar(R - rin).setZ(n.height_m));
    mesh.matrixAutoUpdate = false;
    g.nozzles.add(mesh);
  });

  // днище и окрайка
  if (S.bottom) {
    const b = S.bottom, out = b.outside_mm / 1000, ann = b.annular_width_mm / 1000, rise = R / b.slope_denominator;
    const cone = new THREE.Mesh(new THREE.CylinderGeometry(0.001, R - (ann - out) + b.overlap_mm / 1000, rise, 96, 1, true), mat(0x7fb98a, 0.8));
    cone.rotation.x = Math.PI / 2; cone.position.z = rise / 2;
    g.bottom.add(cone);
    const ring = new THREE.Mesh(new THREE.RingGeometry(R - (ann - out), R + out, 128), mat(0xa8adb5, 0.95));
    g.bottom.add(ring);
  }

  // крыша: каркас, кольца, настил
  if (S.roof) {
    const r = S.roof, top = H, rc = r.central_radius_m, rise = r.rise_m;
    const zAt = function (x) {
      if (r.shape === "Сферическая") return top - r.beam_drop_mm / 1000 + (Math.sqrt(r.sphere_radius_m ** 2 - x * x) - Math.sqrt(r.sphere_radius_m ** 2 - R * R));
      return top - r.beam_drop_mm / 1000 + rise * (R - x) / (R - rc);
    };
    const N = r.radial_count, ringsR = [rc];
    for (let i = 1; i <= r.ring_count; i++) ringsR.push(rc + (R - rc) * i / (r.ring_count + 1));
    ringsR.push(R);
    // настил
    const seg = 160, pos = [], idx = [];
    const rd = R - r.deck_inset_mm / 1000;
    const rad = []; for (let i = 0; i <= 24; i++) rad.push(rc + (rd - rc) * i / 24);
    rad.forEach(function (x) { for (let k = 0; k <= seg; k++) { const t = k / seg * Math.PI * 2; pos.push(x * Math.cos(t), x * Math.sin(t), zAt(x)); } });
    for (let i = 0; i < rad.length - 1; i++) for (let k = 0; k < seg; k++) { const a = i * (seg + 1) + k, b = a + 1, c = a + seg + 1, d = c + 1; idx.push(a, b, d, a, d, c); }
    const dg = new THREE.BufferGeometry(); dg.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); dg.setIndex(idx); dg.computeVertexNormals();
    const deck = new THREE.Mesh(dg, mat(0xdfe8f2, 0.35)); deck.name = "deck"; g.roof.add(deck);
    // радиальные балки
    for (let k = 0; k < N; k++) {
      const t = (r.first_angle_deg + 360 / N * k) * Math.PI / 180, pts = [];
      for (let i = 0; i <= 30; i++) { const x = rc + (R - rc) * i / 30; pts.push(new THREE.Vector3(x * Math.cos(t), x * Math.sin(t), zAt(x))); }
      g.roof.add(lines(pts, 0x4f86c6));
    }
    // кольцевые балки и центральное кольцо
    ringsR.forEach(function (x, i) {
      const pts = []; for (let k = 0; k <= 128; k++) { const t = k / 128 * Math.PI * 2; pts.push(new THREE.Vector3(x * Math.cos(t), x * Math.sin(t), zAt(x))); }
      g.roof.add(lines(pts, i === 0 ? 0xc0476d : (i === ringsR.length - 1 ? 0x2f9d79 : 0xe08f2f)));
    });
  }

  // управление
  const info = box.querySelector(".vinfo");
  Object.keys(g).forEach(function (k) {
    const c = box.querySelector("#st-" + k);
    if (!c) return;
    if (k !== "wall" && (k === "nozzles" ? !(S.nozzles || []).length : !S[k])) { c.disabled = true; c.checked = false; g[k].visible = false; c.parentNode.style.opacity = 0.4; }
    c.addEventListener("change", function () { g[k].visible = c.checked; });
  });
  const zoomInput = box.querySelector("#st-zoom"), zoomLabel = box.querySelector("#st-zoom-l"), homeDist = home.distanceTo(target);
  zoomInput.addEventListener("input", function () {
    const dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).addScaledVector(dir, homeDist / (Number(zoomInput.value) / 100));
    zoomLabel.textContent = zoomInput.value + "%"; controls.update();
  });
  box.querySelector("#st-reset").addEventListener("click", function () { camera.position.copy(home); controls.target.copy(target); zoomInput.value = 100; zoomLabel.textContent = "100%"; controls.update(); });
  box.querySelector("#st-top").addEventListener("click", function () { camera.position.set(0.001, -0.001, H + R * 3.2); controls.target.set(0, 0, H); controls.update(); });
  function fit() { const w = canvas.clientWidth, h = canvas.clientHeight; if (canvas.width !== w * renderer.getPixelRatio()) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); } }
  new ResizeObserver(fit).observe(canvas); fit();
  renderer.setAnimationLoop(function () { controls.update(); renderer.render(scene, camera); });
}

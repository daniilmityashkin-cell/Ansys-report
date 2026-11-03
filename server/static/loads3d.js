// Нагрузки на модели: давление на стенку, крышу и днище для каждого расчётного случая отчёта.
// Показ обновляется по мере ввода в форму нагрузок (данные считает сервер той же формулой, что и скрипт наложения в Ansys).
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";
import { modelQuality } from "./model-runtime.js";
import { modelInspector } from "./model-inspector.js";
import { modelControls } from "./model-controls.js";

const root = document.getElementById("loads3d");
if (root) start(root).catch(function (e) { fail(root, "Показ нагрузок не запустился: " + e.message); });

function fail(box, msg) { const i = box.querySelector("#l3-info"); if (i) { i.textContent = msg; i.classList.add("bad"); } }

// диверging-шкала: синий (снаружи внутрь, «−») - серый (0) - красный (изнутри наружу, «+»)
function color(p, m) {
  const t = Math.max(-1, Math.min(1, p / m)), a = Math.abs(t);
  const base = [0.38, 0.40, 0.45], tgt = t >= 0 ? [1.0, 0.30, 0.20] : [0.20, 0.50, 1.0];
  return new THREE.Color(base[0] + (tgt[0] - base[0]) * a, base[1] + (tgt[1] - base[1]) * a, base[2] + (tgt[2] - base[2]) * a);
}
// цвет стрелки: направление должно читаться даже у малых нагрузок (снег рядом с гидростатикой), поэтому насыщенность не ниже 0.55
function acolor(p, m) { const t = Math.max(-1, Math.min(1, p / m)), a = Math.max(Math.abs(t), 0.55); return color(t >= 0 ? a * m : -a * m, m); }
const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)).replace(".", ",");

async function load(box) {
  const form = document.getElementById(box.dataset.form || "");
  let r;
  if (form) {
    const fd = new FormData(form); fd.delete("csrf"); fd.append("csrf", form.querySelector("[name=csrf]").value);
    r = await fetch(box.dataset.src, { method: "POST", body: fd, credentials: "same-origin" });
  } else r = await fetch(box.dataset.src, { credentials: "same-origin" });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || "ошибка");
  return d;
}

async function start(box) {
  const canvas = box.querySelector("canvas"), tabs = box.querySelector("#l3-tabs"), info = box.querySelector("#l3-info"), table = box.querySelector("#l3-table");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(modelQuality().pixelRatio);
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0b0d10);
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 3000); camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, canvas); controls.enableDamping = true; controls.enableZoom = true;
  const interaction = modelControls(controls, canvas, camera, { scope: box });
  scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.15));
  const sun = new THREE.DirectionalLight(0xffffff, 0.9); scene.add(sun);
  let data = await load(box), cur = 0, group = null, framed = false, inspector = null;
  const visibility = {wall:true, roof:true, bottom:true, liquid:true};
  const arrowsGroup = new THREE.Group();
  function frameModel() {
    if (!group) return;
    const bounds = new THREE.Box3().setFromObject(group), sphere = bounds.getBoundingSphere(new THREE.Sphere());
    const halfFov = Math.min(THREE.MathUtils.degToRad(camera.fov / 2), Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect));
    const distance = sphere.radius / Math.sin(halfFov) * .9;
    controls.target.copy(sphere.center);
    camera.position.copy(sphere.center).add(new THREE.Vector3(1.4, -1.8, 1).normalize().multiplyScalar(distance));
    controls.minDistance = sphere.radius * 1.15; controls.maxDistance = distance * 5;
    camera.far = Math.max(3000, distance * 10); camera.updateProjectionMatrix(); controls.update(0);
  }

  function resize() {
    const w = canvas.clientWidth || 600, h = canvas.clientHeight || 520;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    if (framed && !interaction.touched) frameModel();
  }
  new ResizeObserver(resize).observe(canvas); resize();

  function arrows(parent, list, scale, cMat) {
    // list: [{pos: Vector3, dir: Vector3 (куда направлено давление), p}]
    if (!list.length) return;
    const cone = new THREE.InstancedMesh(new THREE.ConeGeometry(scale * 0.16, scale * 0.42, 10), new THREE.MeshBasicMaterial({ color: 0xffffff }), list.length);
    const pts = [], m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
    list.forEach((a, i) => {
      const len = a.len, head = a.pos.clone(), tail = head.clone().addScaledVector(a.dir, -len);
      q.setFromUnitVectors(up, a.dir);
      m.compose(head.clone().addScaledVector(a.dir, -scale * 0.21), q, new THREE.Vector3(1, 1, 1));
      cone.setMatrixAt(i, m); cone.setColorAt(i, a.col);
      pts.push(tail, head.clone().addScaledVector(a.dir, -scale * 0.3));
    });
    cone.instanceColor.needsUpdate = true; cone.userData.surface=cMat;
    const lg = new THREE.BufferGeometry().setFromPoints(pts), lcol = [];
    list.forEach((a) => { lcol.push(a.col.r, a.col.g, a.col.b, a.col.r, a.col.g, a.col.b); });
    lg.setAttribute("color", new THREE.Float32BufferAttribute(lcol, 3));
    const shafts=new THREE.LineSegments(lg,new THREE.LineBasicMaterial({vertexColors:true}));shafts.userData.surface=cMat;parent.add(cone,shafts);
  }

  function build() {
    if (group) { scene.remove(group); group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) { const mats = Array.isArray(o.material) ? o.material : [o.material]; mats.forEach(m => m.dispose()); } }); }
    group = new THREE.Group(); arrowsGroup.clear(); group.add(arrowsGroup); scene.add(group);
    const c = data.cases[cur], R = data.D / 2, H = data.H, rise = data.rise_m || 1;
    const all = c.wall.p_kpa.concat([c.roof_kpa], c.bottom_kpa === null ? [] : [c.bottom_kpa]);
    const M = Math.max(1e-6, ...all.map(Math.abs)), L = Math.max(R * 0.16, 1.2);
    const Mw = Math.max(1e-6, ...c.wall.p_kpa.map(Math.abs)), Mr = Math.max(1e-6, Math.abs(c.roof_kpa)), Mb = Math.max(1e-6, Math.abs(c.bottom_kpa || 0));       // длина стрелок - по своей поверхности, цвет заливки - по общей шкале
    // стенка: цвет по высоте
    const nz = c.wall.z_m.length, nt = modelQuality().radial, pos = [], col = [], idx = [];
    for (let j = 0; j <= nz; j++) {
      const z = j === 0 ? 0 : j === nz ? H : (c.wall.z_m[j - 1] + c.wall.z_m[j]) / 2, p = c.wall.p_kpa[Math.min(Math.max(j === nz ? nz - 1 : j, 0), nz - 1)], cl = color(p, M);
      for (let i = 0; i <= nt; i++) { const a = 2 * Math.PI * i / nt; pos.push(R * Math.cos(a), R * Math.sin(a), z); col.push(cl.r, cl.g, cl.b); }
    }
    for (let j = 0; j < nz; j++) for (let i = 0; i < nt; i++) { const a = j * (nt + 1) + i, b = a + 1, d = a + nt + 1, e = d + 1; idx.push(a, b, e, a, e, d); }
    const wg = new THREE.BufferGeometry(); wg.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); wg.setAttribute("color", new THREE.Float32BufferAttribute(col, 3)); wg.setIndex(idx);
    wg.computeVertexNormals();
    const wallMesh=new THREE.Mesh(wg, new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide, roughness: .62, metalness: .12 }));wallMesh.userData.surface="wall";group.add(wallMesh);
    // линии поясов
    (data.belts_m || []).forEach((z) => {
      const pts = []; for (let i = 0; i <= 96; i++) { const a = 2 * Math.PI * i / 96; pts.push(new THREE.Vector3(R * Math.cos(a), R * Math.sin(a), z)); }
      const seam=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:0x3b4048}));seam.userData.surface="wall";group.add(seam);
    });
    // крыша: сферический купол с подъёмом rise
    const Rs = (R * R + rise * rise) / (2 * rise), prof = [];
    for (let k = 0; k <= 24; k++) { const r = R * k / 24; prof.push(new THREE.Vector2(r, H + Math.sqrt(Math.max(Rs * Rs - r * r, 0)) - (Rs - rise))); }
    const rg = new THREE.LatheGeometry(prof.reverse(), modelQuality().radial); rg.rotateX(Math.PI / 2);
    const roofMesh=new THREE.Mesh(rg,new THREE.MeshStandardMaterial({color:color(c.roof_kpa,M),side:THREE.DoubleSide,roughness:.6,metalness:.15}));roofMesh.userData.surface="roof";group.add(roofMesh);
    // днище
    const bt = c.bottom_kpa === null ? 0 : c.bottom_kpa;
    const bottomMesh=new THREE.Mesh(new THREE.CircleGeometry(R,modelQuality().radial),new THREE.MeshBasicMaterial({color:c.bottom_kpa===null?0x30343a:color(bt,M),side:THREE.DoubleSide}));bottomMesh.userData.surface="bottom";group.add(bottomMesh);
    // уровень налива
    if (c.free_surface_m) {
      const f = new THREE.Mesh(new THREE.CircleGeometry(R * 0.995, 72), new THREE.MeshBasicMaterial({ color: 0x3aa0ff, transparent: true, opacity: 0.14, side: THREE.DoubleSide })); f.position.z = c.free_surface_m; f.userData.surface="liquid";group.add(f);
      const levelPoints = Array.from({length: 97}, (_, i) => new THREE.Vector3(R * 1.015 * Math.cos(i * Math.PI / 48), R * 1.015 * Math.sin(i * Math.PI / 48), c.free_surface_m));
      const level = new THREE.Line(new THREE.BufferGeometry().setFromPoints(levelPoints), new THREE.LineDashedMaterial({color: 0x61c4ff, dashSize: R * .06, gapSize: R * .03}));
      level.computeLineDistances();level.userData.surface="liquid"; group.add(level);
    }
    // стрелки давления
    const wa = [];
    const nh = modelQuality().compact ? 3 : 5, na = modelQuality().compact ? 8 : 12;
    for (let j = 0; j < nh; j++) {
      const z = H * (j + 0.5) / nh, k = Math.min(nz - 1, Math.floor(z / H * nz)), p = c.wall.p_kpa[k];
      if (Math.abs(p) < Mw * 0.02) continue;
      for (let i = 0; i < na; i++) {
        const a = 2 * Math.PI * (i + (j % 2) * 0.5) / na, n = new THREE.Vector3(Math.cos(a), Math.sin(a), 0), len = L * (0.3 + 0.7 * Math.abs(p) / Mw);
        wa.push({ pos: new THREE.Vector3((R + (p > 0 ? len : 0)) * n.x, (R + (p > 0 ? len : 0)) * n.y, z), dir: n.clone().multiplyScalar(p > 0 ? 1 : -1), len, col: acolor(p, Mw) });
      }
    }
    arrows(arrowsGroup, wa, L * 0.9, "wall");
    const ra = [], rp = c.roof_kpa;
    if (Math.abs(rp) >= 1e-6) for (let rr = 1; rr <= 2; rr++) {
      const r = R * rr / 2.6, zr = H + Math.sqrt(Math.max(Rs * Rs - r * r, 0)) - (Rs - rise), n = Math.round(4 + 4 * rr);
      for (let i = 0; i < n; i++) { const a = 2 * Math.PI * i / n; ra.push({ pos: new THREE.Vector3(r * Math.cos(a), r * Math.sin(a), zr), dir: new THREE.Vector3(0, 0, rp > 0 ? 1 : -1), len: L * (0.3 + 0.7 * Math.abs(rp) / Mr), col: acolor(rp, Mr) }); }
    }
    arrows(arrowsGroup, ra, L * 0.9, "roof");
    const ba = [];
    if (bt && Math.abs(bt) >= 1e-6) for (let rr = 0; rr <= 2; rr++) {
      const r = R * rr / 2.6, n = rr === 0 ? 1 : 6 + 5 * rr;
      for (let i = 0; i < n; i++) { const a = 2 * Math.PI * i / n; ba.push({ pos: new THREE.Vector3(r * Math.cos(a), r * Math.sin(a), 0), dir: new THREE.Vector3(0, 0, bt > 0 ? -1 : 1), len: L * (0.3 + 0.7 * Math.abs(bt) / Mb), col: acolor(bt, Mb) }); }
    }
    arrows(arrowsGroup, ba, L * 0.9, "bottom");
    if (!framed) { frameModel(); framed = true; }
    sun.position.set(R * 2, -R, H * 2);
    group.traverse(o=>{if(o.userData.surface)o.visible=visibility[o.userData.surface];});
    inspector?.clear();
    // подписи
    box.querySelector("#l3-min").textContent = "−" + fmt(M) + " кПа";
    box.querySelector("#l3-max").textContent = "+" + fmt(M) + " кПа";
    info.classList.remove("bad");
    const rows = [["Давление на стенку", fmt(Math.min(...c.wall.p_kpa)) + " … " + fmt(Math.max(...c.wall.p_kpa)) + " кПа"],
      ["Давление на крышу", fmt(c.roof_kpa) + " кПа" + (c.snow_kpa ? " (снег " + fmt(c.snow_kpa) + ")" : "")],
      ["Давление на днище", c.bottom_kpa === null ? "нет (пустой резервуар)" : fmt(c.bottom_kpa) + " кПа"],
      ["Уровень продукта", c.free_surface_m ? c.free_surface_m + " м" : "пустой"],
      ["Избыточное давление / вакуум", fmt(c.uniform_kpa) + " кПа"],
      ["Ветер", c.wind ? "по поясам, до " + fmt(Math.max(...c.wind_kpa.map(Math.abs))) + " кПа" : "нет"],
      ["Собственный вес и оборудование", c.gravity ? "учтены" : "нет"]];
    table.innerHTML = rows.map((r) => "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>").join("");
    info.textContent = "Стрелки — направление давления. Красный: изнутри наружу («+»), синий: снаружи внутрь («−»). " + (data.notes || []).join(" ");
  }

  function tabsBuild() {
    tabs.innerHTML = "";
    data.cases.forEach((c, k) => {
      const b = document.createElement("button"); b.type = "button"; b.className = "dtab" + (k === cur ? " on" : ""); b.textContent = c.id.startsWith("fill_") ? "Уровень продукта " + fmt(c.free_surface_m) + " м" : c.name;
      b.onclick = () => { cur = k; tabsBuild(); build(); }; tabs.appendChild(b);
    });
  }
  tabsBuild(); build();
  inspector = modelInspector({THREE,renderer,scene,camera,canvas,scope:box,R:data.D/2,H:data.H,objects:()=>group.children.filter(o=>o!==arrowsGroup),describe:(hit,angle)=>{
    if(hit.object.userData.surface==="liquid")return `Уровень жидкости: Z = ${hit.point.z.toFixed(3)} м` ;
    const c=data.cases[cur],z=hit.point.z,k=Math.max(0,Math.min(c.wall.p_kpa.length-1,Math.floor(z/data.H*c.wall.p_kpa.length)));
    const roof=z>=data.H-.01,bottom=z<=.01,p=roof?c.roof_kpa:bottom?c.bottom_kpa:c.wall.p_kpa[k];
    return `φ = ${angle.toFixed(1)}° · Z = ${z.toFixed(3)} м · ${roof?'крыша':bottom?'днище':'стенка'}: ${p===null?'нет давления':fmt(p)+' кПа'}`;
  }});
  const options = document.createElement('div'); options.className = 'l3-options';
  const label = document.createElement('label'), check = document.createElement('input');
  check.type = 'checkbox'; check.checked = true;
  label.append(check, ' Показывать стрелки давления'); options.append(label);
  for(const [key,text] of Object.entries({wall:'Стенка',roof:'Крыша',bottom:'Днище',liquid:'Уровень жидкости'})){
    const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=true;
    input.onchange=()=>{visibility[key]=input.checked;group.traverse(o=>{if(o.userData.surface===key)o.visible=input.checked;});inspector.clear();};label.append(input,' '+text);options.append(label);
  }
  tabs.after(options);
  check.addEventListener('change', () => { arrowsGroup.visible = check.checked; });
  const explanation = document.createElement('div'); explanation.className = 'load-explainer';
  explanation.innerHTML = '<b>Что показывает модель</b><p>Цвет — приложенное давление, а не напряжения и не результат проверки прочности. Давление жидкости растёт с глубиной; стрелки показывают направление действия.</p><p>«Уровень продукта» — высота жидкости от днища. Дополнительные случаи автоматически берутся как 40%, 70% и 95% высоты стенки (кроме уровня, близкого к рабочему) для оценки допустимой высоты налива в отчёте.</p><p>Схема показывает распределение нагрузок на идеальной оболочке. Размер стрелок сравнивается отдельно для стенки, крыши и днища; цвета — по общей шкале.</p>';
  box.querySelector('#l3-info').before(explanation);
  box.querySelector("#l3-reset").onclick = () => { framed = false; build(); };
  (function loop() { requestAnimationFrame(loop); if (interaction.update()) renderer.render(scene, camera); })();

  // обновление по мере ввода в форму нагрузок
  const form = document.getElementById(box.dataset.form || "");
  if (form) {
    let t = null, seq = 0;
    const upd = () => { clearTimeout(t); t = setTimeout(async () => {
      const my = ++seq;
      try { const d = await load(box); if (my !== seq) return; data = d; cur = Math.min(cur, data.cases.length - 1); tabsBuild(); build(); }
      catch (e) { fail(box, "Нагрузки не обновлены: " + e.message); }
    }, 450); };
    form.addEventListener("input", upd); form.addEventListener("change", upd);
  }
}

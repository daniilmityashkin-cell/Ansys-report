export function modelInspector({THREE, renderer, scene, camera, canvas, scope, R, H, objects, describe}) {
  const tools = document.createElement('div'); tools.className = 'inspector-tools';
  tools.innerHTML = '<label><input type="checkbox" data-cut> Разрез</label><label>Положение сечения <input type="range" data-position min="-100" max="100" value="0" disabled></label><output class="point-result" aria-live="polite">Нажмите на модель, чтобы выбрать точку. Перетаскивание вращает вид.</output>';
  scope.append(tools);
  const plane = new THREE.Plane(new THREE.Vector3(1,0,0),0), cut = tools.querySelector('[data-cut]'), position = tools.querySelector('[data-position]'), output = tools.querySelector('output');
  function update() { plane.constant = Number(position.value) / 100 * R; position.disabled = !cut.checked; renderer.clippingPlanes = cut.checked ? [plane] : []; }
  cut.addEventListener('change',update); position.addEventListener('input',update);
  const marker = new THREE.Mesh(new THREE.SphereGeometry(Math.max(R,H)*.012,12,8), new THREE.MeshBasicMaterial({color:0xffffff,depthTest:false})); marker.visible=false; marker.renderOrder=10; scene.add(marker);
  const ray = new THREE.Raycaster(); ray.params.Points.threshold=Math.max(R,H)*.025;
  let down = null;
  canvas.addEventListener('pointerdown',e => { down={x:e.clientX,y:e.clientY}; });
  canvas.addEventListener('pointerup',e => {
    if (!down || Math.hypot(e.clientX-down.x,e.clientY-down.y)>6) {down=null;return;} down=null;
    const rect=canvas.getBoundingClientRect(); ray.setFromCamera(new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1),camera);
    const visible=[];
    for(const root of objects()) root.traverse(o=> { if(o.isMesh || o.isPoints) {let node=o;while(node&&node.visible)node=node.parent;if(!node)visible.push(o);} });
    const hit=ray.intersectObjects(visible,false).find(h=>!cut.checked || plane.distanceToPoint(h.point)>=0);
    if (!hit) {output.textContent='В этой точке нет видимой поверхности. Выберите другую точку.';marker.visible=false;return;}
    marker.position.copy(hit.point); marker.visible=true;
    const p=hit.point, angle=(THREE.MathUtils.radToDeg(Math.atan2(p.y,p.x))+360)%360;
    output.textContent=describe ? describe(hit,angle) : `φ = ${angle.toFixed(1)}° · Z = ${p.z.toFixed(3)} м · X = ${p.x.toFixed(3)} м · Y = ${p.y.toFixed(3)} м`;
  });
  return {
    clear(){marker.visible=false;output.textContent="Выберите точку на текущей модели.";},
    setBounds(radius,height){R=radius;H=height;ray.params.Points.threshold=Math.max(R,H)*.025;marker.visible=false;update();},
    tools
  };
}

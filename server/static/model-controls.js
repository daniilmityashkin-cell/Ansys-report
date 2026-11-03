// Shared model interaction: orbit around the vertical axis until the first gesture.
export function modelControls(controls, canvas, camera, options = {}) {
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let touched = false, last = 0;
  const scope = options.scope || canvas.parentElement;
  const toolbar = document.createElement('div');
  toolbar.className = 'model-tools';
  const rotate = document.createElement('button');
  const hint = document.createElement('span');
  hint.textContent = 'Перетаскивание — поворот · колесо / два пальца — масштаб';
  toolbar.append(hint);
  const button = (label, action) => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = label;
    b.addEventListener('click', action); toolbar.append(b); return b;
  };
  function sync() {
    controls.autoRotate = !touched && !motion.matches;
    rotate.disabled = motion.matches;
    rotate.title = motion.matches ? 'Анимация отключена системной настройкой уменьшения движения' : '';
    rotate.textContent = controls.autoRotate ? 'Пауза вращения' : 'Вращать';
    rotate.setAttribute('aria-pressed', String(controls.autoRotate));
  }
  function stop() { touched = true; sync(); }
  controls.enableZoom = true;
  controls.zoomSpeed = .75;
  controls.autoRotateSpeed = .3; // one revolution in about 200 seconds
  controls.enableDamping = true;
  function zoom(factor) {
    stop();
    const distance = camera.position.distanceTo(controls.target);
    const next = Math.max(controls.minDistance, Math.min(controls.maxDistance, distance * factor));
    camera.position.sub(controls.target).multiplyScalar(next / Math.max(distance, 1e-9)).add(controls.target);
    controls.update(0);
  }
  button('−', () => zoom(1.2)).setAttribute('aria-label', 'Отдалить модель');
  button('+', () => zoom(1 / 1.2)).setAttribute('aria-label', 'Приблизить модель');
  rotate.type = 'button'; rotate.addEventListener('click', () => { touched = !touched; sync(); }); toolbar.append(rotate);
  scope.append(toolbar);
  canvas.setAttribute('aria-label', 'Интерактивная 3D-модель. Поворот перетаскиванием, масштаб колесом или двумя пальцами.');
  canvas.addEventListener('pointerdown', stop, { passive: true });
  canvas.addEventListener('wheel', stop, { passive: true });
  controls.addEventListener('start', stop);
  motion.addEventListener('change', sync);
  sync();
  return {
    update(time = performance.now()) {
      const delta = last ? Math.min((time - last) / 1000, .05) : 0;
      last = time;
      if (document.hidden || !canvas.getClientRects().length) return false;
      const rect = canvas.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > innerHeight) return false;
      controls.update(delta);
      return true;
    },
    stop,
    get touched() { return touched; }
  };
}

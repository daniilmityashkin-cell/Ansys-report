// Detail affects presentation only; measured data and server calculations stay intact.
export function modelQuality() {
  const compact = matchMedia('(max-width: 700px)').matches || (navigator.deviceMemory && navigator.deviceMemory <= 4) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4);
  return {compact, radial: compact ? 48 : 96, wallTheta: compact ? 88 : 220, wallZ: compact ? 44 : 110, pixelRatio: Math.min(devicePixelRatio || 1, compact ? 1.25 : 2)};
}
export function whenVisible(root, start) {
  if (!root) return;
  let begun = false;
  const run = () => { if (begun) return; begun = true; start().catch(error => {
    const message = document.createElement('p'); message.className = 'err'; message.textContent = 'Не удалось открыть 3D: ' + error.message + '. Обновите страницу для повторной попытки.'; root.append(message);
  }); };
  if (!('IntersectionObserver' in window)) return run();
  const observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) {observer.disconnect(); run();} }, {rootMargin:'80px'});
  observer.observe(root);
}

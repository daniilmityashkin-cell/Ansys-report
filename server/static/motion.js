/* A subtle pointer light follows the hero; motion preferences remain live. */
(() => {
  const hero = document.querySelector('.solar-hero');
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  if (!hero) return;
  let frame = 0;
  hero.addEventListener('pointermove', event => {
    if (preference.matches || event.pointerType !== 'mouse') return;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const bounds = hero.getBoundingClientRect();
      const offset = (event.clientX - bounds.left - bounds.width / 2) / 35;
      hero.querySelector('.solar-halo').style.translate = `${offset}px 0`;
    });
  });
  const reset = () => {
    cancelAnimationFrame(frame);
    hero.querySelector('.solar-halo').style.translate = '0 0';
  };
  hero.addEventListener('pointerleave', reset);
  preference.addEventListener('change', reset);
})();

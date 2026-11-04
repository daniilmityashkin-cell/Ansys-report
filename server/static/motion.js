/* Landing motion: a rotating wireframe, orbit light and scroll depth. */
(() => {
  const menu = document.querySelector('.nav-sections');
  const toggle = document.querySelector('.nav-toggle');
  function closeMenu() {
    menu?.classList.remove('open');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-label', 'Открыть меню');
  }
  toggle?.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    menu.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
  });
  menu?.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeMenu(); toggle?.focus(); } });
  const hero = document.querySelector('.solar-hero');
  if (!hero) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const svg = hero.querySelector('.preview-model svg');
  const group = svg.querySelector('g');
  const panel = hero.querySelector('.workspace-preview');
  const stage = hero.querySelector('.solar-stage');
  const NS = 'http://www.w3.org/2000/svg';
  const wire = document.createElementNS(NS, 'path');
  wire.setAttribute('fill', 'url(#tank-fill)');
  group.replaceChildren(wire);
  let visible = true, frame = 0, angle = 0, last = 0;
  function draw(rotation) {
    const paths = [];
    function point(a, level) {
      return [200 + 110 * Math.cos(a), 60 + level * 112 + 34 * Math.sin(a)];
    }
    for (let level = 0; level <= 3; level++) {
      let ring = '';
      for (let i = 0; i <= 64; i++) {
        const [x, y] = point(i * Math.PI / 32, level / 3);
        ring += `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
      }
      paths.push(ring);
    }
    for (let i = 0; i < 18; i++) {
      const a = rotation + i * Math.PI / 9;
      const [x, y] = point(a, 0), [, bottom] = point(a, 1);
      paths.push(`M${x.toFixed(1)},${y.toFixed(1)}V${bottom.toFixed(1)}`);
    }
    wire.setAttribute('d', paths.join(' '));
  }
  function animate(time) {
    if (reduced.matches || document.hidden || !visible) return;
    const delta = last ? Math.min(time - last, 50) : 0;
    last = time;
    angle += delta * .00018;
    draw(angle);
    const rect = hero.getBoundingClientRect();
    const progress = Math.max(0, Math.min(1, -rect.top / rect.height));
    panel.style.setProperty('--panel-tilt', `${(1 - progress) * 3}deg`);
    stage.style.translate = stage.classList.contains("particles-ready") ? "0 0" : `0 ${progress * 35}px`;
    frame = requestAnimationFrame(animate);
  }
  function sync() {
    cancelAnimationFrame(frame);
    last = 0;
    if (!reduced.matches && visible && !document.hidden) frame = requestAnimationFrame(animate);
    else { panel.style.removeProperty('--panel-tilt'); stage.style.translate = '0 0'; }
  }
  draw(0);
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => { visible = entries[0].isIntersecting; sync(); }).observe(hero);
  }
  reduced.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
  sync();
})();

// Import the particle illustration only on desktop; touch/mobile keeps its current hero.
(() => {
  const stage=document.querySelector('.solar-stage');
  if(!stage)return;
  const desktop=matchMedia('(min-width: 1024px) and (hover: hover) and (pointer: fine)');
  let dispose=null,version=0;
  async function sync(){
    const current=++version;
    if(dispose){dispose();dispose=null;}
    if(!desktop.matches)return;
    try{
      const module=await import('./tank-particles.js');
      if(current===version&&desktop.matches)dispose=module.mountTankParticles(stage);
    }catch(error){ /* The existing solar illustration remains as the fallback. */ }
  }
  desktop.addEventListener('change',sync);sync();
})();

// Lower-page decoration is loaded only as the visitor reaches the content below the hero.
(() => {
  const hero=document.querySelector('.solar-hero'),entry=document.querySelector('.format-strip');
  if(!hero||!entry)return;
  const desktop=matchMedia('(min-width: 1024px) and (hover: hover) and (pointer: fine)');
  let dispose=null,observer=null,version=0;
  function sync(){
    const current=++version;observer?.disconnect();dispose?.();dispose=null;
    if(!desktop.matches)return;
    async function load(){
      observer?.disconnect();
      try{const module=await import('./industry-particles.js');if(current===version&&desktop.matches)dispose=module.mountIndustryParticles(hero);}catch(error){/* Decorative fallback: keep the existing page background. */}
    }
    if(!('IntersectionObserver' in window)){load();return;}
    observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting))load();},{rootMargin:'200px'});observer.observe(entry);
  }
  desktop.addEventListener('change',sync);sync();
})();

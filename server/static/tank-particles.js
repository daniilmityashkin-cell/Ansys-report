// Desktop landing illustration. The viewport layer never intercepts page controls.
export function mountTankParticles(stage) {
  const canvas=document.createElement('canvas');
  canvas.className='tank-particles';canvas.setAttribute('aria-hidden','true');
  const ctx=canvas.getContext('2d',{alpha:true});
  if(!ctx)return()=>{};
  const motion=matchMedia('(prefers-reduced-motion: reduce)');
  const hero=stage.closest('.solar-hero')||stage;
  const pointer={x:0,y:0,vx:0,vy:0,time:0,active:false};
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  let frame=0,elapsed=0,last=0,visible=false,width=0,height=0,disposed=false,zoom=1;
  let seed=1937;
  const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  const points=[];
  function addPoint(x,y,z,rim=false){
    points.push({x,y,z,sx:(random()-.5)*3.2,sy:(random()-.5)*2.1,sz:(random()-.5)*2.8,warm:random()<(rim ? .35 : .075),size:.7+random()*.55,delay:random()*.24,phase:random()*Math.PI*2,frequency:.6+random()*1.8,spread:20+Math.sqrt(random())*105,lag:.04+random()*.14,px:0,py:0,vx:0,vy:0,initialized:false});
  }
  // Shell, domed roof and highlighted seams are all made from individual points.
  for(let row=0;row<=49;row++)for(let col=0;col<100;col++){
    const angle=col/100*Math.PI*2;
    addPoint(Math.cos(angle),row/49*1.6-.8+(random()-.5)*.012,Math.sin(angle));
  }
  for(let i=0;i<800;i++){
    const radius=Math.sqrt(random()),a=random()*Math.PI*2;
    addPoint(radius*Math.cos(a),-.8-.22*(1-radius*radius),radius*Math.sin(a));
  }
  for(let i=0;i<400;i++){
    const a=i/200*Math.PI*2;addPoint(1.006*Math.cos(a),i<200?-.8:.8,1.006*Math.sin(a),true);
  }
  canvas.dataset.particleCount=points.length;
  function project(x,y,z,rotation,rect){
    const xx=x*Math.cos(rotation)+z*Math.sin(rotation),zz=z*Math.cos(rotation)-x*Math.sin(rotation);
    return {x:rect.left+rect.width/2+xx*rect.height*.66*zoom,y:rect.top+rect.height*.45+(y*rect.height*.37+zz*rect.height*.15)*zoom,depth:zz};
  }
  function draw(step=1){
    const rect=stage.getBoundingClientRect(),heroTop=hero.getBoundingClientRect().top+scrollY;
    const progress=clamp((scrollY-heroTop)/Math.max(400,stage.offsetTop+rect.height*.7),0,1);
    zoom+=((motion.matches?1:1-.58*(progress*progress*(3-2*progress)))-zoom)*(1-Math.pow(.86,step));
    const active=pointer.active&&!motion.matches;
    const assembling=motion.matches?1:Math.min(1,elapsed/2000);
    const rotation=motion.matches ? .3 : .3+Math.max(0,elapsed-2000)*.00009;
    ctx.clearRect(0,0,width,height);
    // No lines or meshes remain behind: every visible part belongs to the cloud.
    const dt=step/60,omega=16,decay=Math.exp(-omega*dt);
    pointer.vx*=Math.exp(-3*dt);pointer.vy*=Math.exp(-3*dt);
    // Batch particle circles by colour to keep the larger cloud inexpensive.
    const cool=new Path2D(),warm=new Path2D();
    for(const point of points){
      const t=clamp((assembling-point.delay)/(1-point.delay),0,1),ease=1-Math.pow(1-t,3);
      const home=project(point.sx+(point.x-point.sx)*ease,point.sy+(point.y-point.sy)*ease,point.sz+(point.z-point.sz)*ease,rotation,rect);
      if(!point.initialized){point.px=home.x;point.py=home.y;point.initialized=true;}
      const seconds=elapsed/1000,orbit=point.phase+seconds*.4;
      const noiseX=Math.sin(seconds*point.frequency+point.phase*2)*28;
      const noiseY=Math.cos(seconds*point.frequency*1.3+point.phase*3)*24;
      const dx=point.px-pointer.x,dy=point.py-pointer.y,distance=Math.hypot(dx,dy);
      const cut=active?Math.max(0,1-distance/110)*90:0;
      const nx=distance>1?dx/distance:Math.cos(point.phase),ny=distance>1?dy/distance:Math.sin(point.phase);
      const flow=Math.sin(seconds*1.8+point.phase)*18;
      const targetX=active?clamp(pointer.x+Math.cos(orbit)*point.spread+noiseX-pointer.vx*point.lag+nx*cut-ny*flow,2,width-2):home.x;
      const targetY=active?clamp(pointer.y+Math.sin(orbit)*point.spread*.75+noiseY-pointer.vy*point.lag+ny*cut+nx*flow,2,height-2):home.y;
      if(motion.matches){point.px=home.x;point.py=home.y;point.vx=point.vy=0;}
      else{
        // Exact critically damped spring: stable even on slower desktop GPUs.
        const ex=point.px-targetX,ey=point.py-targetY;
        const tx=(point.vx+omega*ex)*dt,ty=(point.vy+omega*ey)*dt;
        point.px=targetX+(ex+tx)*decay;point.py=targetY+(ey+ty)*decay;
        point.vx=(point.vx-omega*tx)*decay;point.vy=(point.vy-omega*ty)*decay;
      }
      if(point.px<-2||point.px>width+2||point.py<-2||point.py>height+2)continue;
      const radius=point.size*(active?1:Math.max(.65,zoom));
      const path=point.warm?warm:cool;path.moveTo(point.px+radius,point.py);path.arc(point.px,point.py,radius,0,Math.PI*2);
    }
    const fade=Math.min(1,assembling*5);
    ctx.fillStyle=`rgba(183,209,231,${fade*(active ? .32 : .6)})`;ctx.fill(cool);
    ctx.fillStyle=`rgba(255,151,87,${fade*(active ? .4 : .65)})`;ctx.fill(warm);
    stage.dataset.particlePhase=assembling<1?'assembling':'formed';
  }
  function resize(){
    width=innerWidth;height=innerHeight;const ratio=Math.min(devicePixelRatio||1,1.5);
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);draw();
  }
  function animate(time){
    frame=0;if(disposed||document.hidden||motion.matches||(!visible&&!pointer.active))return;
    // About 30 fps: enough for smooth pursuit, with less work on large displays.
    if(last&&time-last<30){frame=requestAnimationFrame(animate);return;}
    const delta=last?Math.min(time-last,100):16.67;elapsed+=delta;last=time;draw(delta/16.67);frame=requestAnimationFrame(animate);
  }
  function sync(){
    cancelAnimationFrame(frame);frame=0;last=0;if(disposed)return;
    if(motion.matches){draw();return;}
    if(!document.hidden&&(visible||pointer.active))frame=requestAnimationFrame(animate);
    else if(!document.hidden)ctx.clearRect(0,0,width,height);
  }
  function pointerMove(event){
    if(event.pointerType!=='mouse'||motion.matches)return;
    const wasActive=pointer.active;
    const seconds=Math.max(.008,(event.timeStamp-pointer.time)/1000);
    pointer.vx=wasActive?clamp((event.clientX-pointer.x)/seconds,-2500,2500):0;
    pointer.vy=wasActive?clamp((event.clientY-pointer.y)/seconds,-2500,2500):0;
    pointer.x=event.clientX;pointer.y=event.clientY;pointer.time=event.timeStamp;pointer.active=true;
    if(!wasActive)sync();
  }
  function pointerLeave(event){if(event?.type==='pointerout'&&event.relatedTarget)return;pointer.active=false;sync();}
  document.body.append(canvas);stage.classList.add('particles-ready');
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(stage);resize();
  let observer;
  if('IntersectionObserver' in window){observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;sync();});observer.observe(stage);}else{visible=true;sync();}
  window.addEventListener('pointermove',pointerMove,{passive:true});
  window.addEventListener('pointerout',pointerLeave,{passive:true});window.addEventListener('blur',pointerLeave);
  window.addEventListener('resize',resize,{passive:true});motion.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);
  return()=>{disposed=true;cancelAnimationFrame(frame);resizeObserver.disconnect();observer?.disconnect();window.removeEventListener('pointermove',pointerMove);window.removeEventListener('pointerout',pointerLeave);window.removeEventListener('blur',pointerLeave);window.removeEventListener('resize',resize);motion.removeEventListener('change',sync);document.removeEventListener('visibilitychange',sync);canvas.remove();stage.classList.remove('particles-ready');delete stage.dataset.particlePhase;};
}

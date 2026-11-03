// Desktop landing illustration. The viewport layer never intercepts page controls.
export function mountTankParticles(stage) {
  const canvas=document.createElement('canvas');
  canvas.className='tank-particles';canvas.setAttribute('aria-hidden','true');
  const ctx=canvas.getContext('2d',{alpha:true});
  if(!ctx)return()=>{};
  const motion=matchMedia('(prefers-reduced-motion: reduce)');
  const hero=stage.closest('.solar-hero')||stage;
  let previousPointer=null,pointer=null;
  const nextPanel=hero.querySelector(".workspace-preview")||hero.nextElementSibling;
  let targetZoom=1;
  const strokes=[];
  const cutRadius=46,cutLifetime=110;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  let frame=0,elapsed=0,last=0,visible=false,width=0,height=0,disposed=false,zoom=1;
  let seed=1937;
  const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  const points=[];
  function addPoint(x,y,z,rim=false,grid=false){
    points.push({x,y,z,grid,sx:(random()-.5)*3.2,sy:(random()-.5)*2.1,sz:(random()-.5)*2.8,warm:random()<(rim ? .35 : .075),size:.7+random()*.55,delay:random()*.24,phase:random()*Math.PI*2,frequency:.6+random()*1.8,spread:20+Math.sqrt(random())*105,lag:.04+random()*.14,dx:0,dy:0,vx:0,vy:0});
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
  // Meridians and belt rings are separate dots, subject to the same local forces.
  const shellCount=points.length;
  for(let ring=0;ring<=6;ring++)for(let i=0;i<180;i++){
    const a=i/180*Math.PI*2;addPoint(Math.cos(a)*1.008,ring/6*1.6-.8,Math.sin(a)*1.008,false,true);
  }
  for(let meridian=0;meridian<12;meridian++)for(let i=0;i<60;i++){
    const a=meridian/12*Math.PI*2;addPoint(Math.cos(a)*1.008,i/59*1.6-.8,Math.sin(a)*1.008,false,true);
  }
  canvas.dataset.gridParticleCount=points.length-shellCount;
  canvas.dataset.particleCount=points.length;
  function project(x,y,z,rotation,rect){
    const xx=x*Math.cos(rotation)+z*Math.sin(rotation),zz=z*Math.cos(rotation)-x*Math.sin(rotation);
    return {x:rect.left+rect.width/2+xx*rect.height*.66*zoom,y:rect.top+rect.height*.45+(y*rect.height*.37+zz*rect.height*.15)*zoom,depth:zz};
  }
  function updateZoom(){
    // Wait until the next panel reaches the main viewing area, then follow scroll.
    const heroTop=hero.getBoundingClientRect().top+scrollY;
    const panelTop=nextPanel?heroTop+nextPanel.offsetTop:heroTop+hero.offsetHeight;
    const start=Math.max(120,panelTop-innerHeight*.65);
    const progress=clamp((scrollY-start)/Math.max(300,stage.clientHeight*1.2),0,1);
    targetZoom=1-.58*progress*progress*(3-2*progress);
  }
  function draw(step=1){
    const rect=stage.getBoundingClientRect();
    zoom+=((motion.matches?1:targetZoom)-zoom)*(1-Math.pow(.86,step));
    const now=performance.now();
    while(strokes.length&&now-strokes[0].time>cutLifetime)strokes.shift();
    const assembling=motion.matches?1:Math.min(1,elapsed/2000);
    const rotation=motion.matches ? .3 : .3+Math.max(0,elapsed-2000)*.00009;
    ctx.clearRect(0,0,width,height);
    // No lines or meshes remain behind: every visible part belongs to the cloud.
    const dt=step/60,omega=60,decay=Math.exp(-omega*dt);
    // Batch particle circles by colour to keep the larger cloud inexpensive.
    const cool=new Path2D(),warm=new Path2D(),grid=new Path2D();
    const rx=rect.height*.66*zoom,ry=rect.height*.15*zoom,cx=rect.left+rect.width/2,cy=rect.top+rect.height*.45;
    const normalizedX=pointer?(pointer.x-cx)/rx:2;
    const cap=ry*Math.sqrt(Math.max(0,1-normalizedX*normalizedX));
    const hovered=pointer&&!motion.matches&&assembling>.85&&Math.abs(normalizedX)<=1&&pointer.y>=cy-.8*rect.height*.37*zoom-cap&&pointer.y<=cy+.8*rect.height*.37*zoom+cap;
    for(const point of points){
      const t=clamp((assembling-point.delay)/(1-point.delay),0,1),ease=1-Math.pow(1-t,3);
      const home=project(point.sx+(point.x-point.sx)*ease,point.sy+(point.y-point.sy)*ease,point.sz+(point.z-point.sz)*ease,rotation,rect);
      let targetX=0,targetY=0,strongest=0;
      if(!motion.matches){
        if(hovered){
          const dx=home.x-pointer.x,dy=home.y-pointer.y,d=Math.hypot(dx,dy);
          if(d<72){
            const influence=Math.pow(1-d/72,1.2),seconds=elapsed/1000;
            const nx=d>.1?dx/d:Math.cos(point.phase),ny=d>.1?dy/d:Math.sin(point.phase);
            const outward=(34+Math.sin(seconds*3.5+point.phase)*10)*influence;
            const swirl=Math.sin(seconds*point.frequency*2+point.phase)*24*influence;
            targetX=nx*outward-ny*swirl;targetY=ny*outward+nx*swirl;
            strongest=Math.hypot(targetX,targetY);
          }
        }
        for(const stroke of strokes){
          // Sweep the entire cursor segment, so a fast pass cannot skip particles.
          const sx=stroke.x1-stroke.x0,sy=stroke.y1-stroke.y0,length2=sx*sx+sy*sy;
          const along=length2?clamp(((home.x-stroke.x0)*sx+(home.y-stroke.y0)*sy)/length2,0,1):0;
          const nx=home.x-(stroke.x0+sx*along),ny=home.y-(stroke.y0+sy*along),distance=Math.hypot(nx,ny);
          if(distance>=cutRadius)continue;
          const age=now-stroke.time;
          const fade=age<20?1:Math.pow(Math.max(0,(cutLifetime-age)/(cutLifetime-20)),2);
          const strength=54*Math.pow(1-distance/cutRadius,1.3)*fade;
          if(strength<=strongest)continue;
          strongest=strength;
          const fallback=Math.sqrt(length2)||1;
          targetX=(distance>.1?nx/distance:-sy/fallback)*strength;
          targetY=(distance>.1?ny/distance:sx/fallback)*strength;
        }
      }
      if(motion.matches){point.dx=point.dy=point.vx=point.vy=0;}
      else{
        // Animate only local offsets: the reservoir never follows the mouse.
        // The fast return closes the local disturbance once the cursor leaves.
        const ex=point.dx-targetX,ey=point.dy-targetY;
        const tx=(point.vx+omega*ex)*dt,ty=(point.vy+omega*ey)*dt;
        point.dx=targetX+(ex+tx)*decay;point.dy=targetY+(ey+ty)*decay;
        point.vx=(point.vx-omega*tx)*decay;point.vy=(point.vy-omega*ty)*decay;
      }
      const px=home.x+point.dx,py=home.y+point.dy;
      if(px<-2||px>width+2||py<-2||py>height+2)continue;
      const radius=(point.grid?1:point.size)*Math.max(.65,zoom);
      const path=point.grid?grid:point.warm?warm:cool;path.moveTo(px+radius,py);path.arc(px,py,radius,0,Math.PI*2);
    }
    const fade=Math.min(1,assembling*5);
    ctx.fillStyle=`rgba(183,209,231,${fade*.6})`;ctx.fill(cool);
    ctx.fillStyle=`rgba(255,151,87,${fade*.65})`;ctx.fill(warm);
    ctx.fillStyle=`rgba(135,194,234,${fade*.72})`;ctx.fill(grid);
    stage.dataset.particlePhase=assembling<1?'assembling':'formed';
  }
  function resize(){
    width=innerWidth;height=innerHeight;const ratio=Math.min(devicePixelRatio||1,1.5);
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);updateZoom();draw();
  }
  function animate(time){
    frame=0;if(disposed||document.hidden||motion.matches||!visible)return;
    // About 30 fps: enough for smooth rotation and local cuts, with less work on large displays.
    if(last&&time-last<30){frame=requestAnimationFrame(animate);return;}
    const delta=last?Math.min(time-last,100):16.67;elapsed+=delta;last=time;draw(delta/16.67);frame=requestAnimationFrame(animate);
  }
  function sync(){
    cancelAnimationFrame(frame);frame=0;last=0;if(disposed)return;
    if(motion.matches){draw();return;}
    if(!document.hidden&&visible)frame=requestAnimationFrame(animate);
    else if(!document.hidden)ctx.clearRect(0,0,width,height);
  }
  function pointerMove(event){
    if(event.pointerType!=='mouse'||motion.matches)return;
    const now=performance.now(),x=event.clientX,y=event.clientY;
    pointer={x,y};
    if(previousPointer&&Math.hypot(x-previousPointer.x,y-previousPointer.y)<.5)return;
    const previous=previousPointer&&now-previousPointer.time<180?previousPointer:{x,y};
    // No attraction or remote forces: only particles near the cursor move.
    strokes.push({x0:previous.x,y0:previous.y,x1:x,y1:y,time:now});
    if(strokes.length>24)strokes.shift();
    previousPointer={x,y,time:now};
  }
  function pointerLeave(event){
    if(event?.type==='pointerout'&&event.relatedTarget)return;
    previousPointer=null;pointer=null;strokes.length=0;
  }
  document.body.append(canvas);stage.classList.add('particles-ready');
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(stage);resize();
  let observer;
  if('IntersectionObserver' in window){observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;sync();});observer.observe(stage);}else{visible=true;sync();}
  window.addEventListener('pointermove',pointerMove,{passive:true});
  window.addEventListener('pointerout',pointerLeave,{passive:true});window.addEventListener('blur',pointerLeave);
  window.addEventListener('scroll',updateZoom,{passive:true});
  window.addEventListener('resize',resize,{passive:true});motion.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);
  return()=>{disposed=true;cancelAnimationFrame(frame);resizeObserver.disconnect();observer?.disconnect();window.removeEventListener('pointermove',pointerMove);window.removeEventListener('pointerout',pointerLeave);window.removeEventListener('blur',pointerLeave);window.removeEventListener('scroll',updateZoom);window.removeEventListener('resize',resize);motion.removeEventListener('change',sync);document.removeEventListener('visibilitychange',sync);canvas.remove();stage.classList.remove('particles-ready');delete stage.dataset.particlePhase;};
}

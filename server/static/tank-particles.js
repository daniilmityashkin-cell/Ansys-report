// Desktop landing illustration only. No WebGL, input interception or model data.
export function mountTankParticles(stage) {
  const canvas = document.createElement('canvas');
  canvas.className = 'tank-particles'; canvas.setAttribute('aria-hidden', 'true');
  const ctx = canvas.getContext('2d', {alpha:true});
  if (!ctx) return () => {};
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let frame=0, elapsed=0, last=0, visible=false, width=0, height=0, disposed=false;
  const points=[];
  // A fixed seed keeps resizing and screenshots from generating a different cloud.
  let seed=1937;
  const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  for(let row=0;row<=24;row++)for(let col=0;col<60;col++){
    const angle=col/60*Math.PI*2;
    const x=Math.cos(angle),z=Math.sin(angle),y=row/24*1.6-.8;
    points.push({x,y,z,sx:(random()-.5)*3.2,sy:(random()-.5)*2.1,sz:(random()-.5)*2.8,warm:random()<.085,size:.65+random()*.55,delay:random()*.24});
  }
  function project(x,y,z,rotation){
    const xx=x*Math.cos(rotation)+z*Math.sin(rotation),zz=z*Math.cos(rotation)-x*Math.sin(rotation);
    return {x:width/2+xx*height*.53,y:height*.49+y*height*.37+zz*height*.15,depth:zz};
  }
  function draw(){
    ctx.clearRect(0,0,width,height);
    const assembling=motion.matches?1:Math.min(1,elapsed/2000);
    const rotation=motion.matches ? .3 : .3+Math.max(0,elapsed-2000)*.00009;
    // Grid appears as the measured points settle into the shell.
    const grid=Math.max(0,(assembling-.65)/.35);
    if(grid>0){
      ctx.lineWidth=.65;
      for(let row=0;row<=6;row++){
        ctx.beginPath();
        for(let i=0;i<=80;i++){const a=i/80*Math.PI*2,p=project(Math.cos(a),row/6*1.6-.8,Math.sin(a),rotation);i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);}
        ctx.strokeStyle=`rgba(145,183,215,${grid*((row===0||row===6) ? .32 : .13)})`;ctx.stroke();
      }
      for(let i=0;i<18;i++){
        const a=i/18*Math.PI*2,p=project(Math.cos(a),-.8,Math.sin(a),rotation),q=project(Math.cos(a),.8,Math.sin(a),rotation);
        ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.strokeStyle=`rgba(145,183,215,${grid*(.1+(p.depth+1)*.055)})`;ctx.stroke();
      }
    }
    for(const point of points){
      const t=Math.min(1,Math.max(0,(assembling-point.delay)/(1-point.delay))),ease=1-Math.pow(1-t,3);
      const p=project(point.sx+(point.x-point.sx)*ease,point.sy+(point.y-point.sy)*ease,point.sz+(point.z-point.sz)*ease,rotation);
      const alpha=(.18+(p.depth+1)*.22)*Math.min(1,assembling*5);
      ctx.fillStyle=point.warm?`rgba(255,151,87,${alpha*.9})`:`rgba(183,209,231,${alpha})`;
      ctx.beginPath();ctx.arc(p.x,p.y,point.size,0,Math.PI*2);ctx.fill();
    }
    stage.dataset.particlePhase=assembling<1?'assembling':'formed';
  }
  function resize(){
    width=stage.clientWidth;height=stage.clientHeight;
    const ratio=Math.min(devicePixelRatio||1,1.5);
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);draw();
  }
  function animate(time){
    frame=0;if(disposed||!visible||document.hidden||motion.matches)return;
    elapsed+=last?Math.min(time-last,50):0;last=time;draw();frame=requestAnimationFrame(animate);
  }
  function sync(){
    cancelAnimationFrame(frame);frame=0;last=0;
    if(disposed)return;
    if(motion.matches){draw();return;}
    if(visible&&!document.hidden)frame=requestAnimationFrame(animate);
  }
  stage.append(canvas);stage.classList.add('particles-ready');
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(stage);resize();
  let observer;
  if('IntersectionObserver' in window){observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;sync();});observer.observe(stage);}else{visible=true;sync();}
  motion.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);
  return ()=>{disposed=true;cancelAnimationFrame(frame);resizeObserver.disconnect();observer?.disconnect();motion.removeEventListener('change',sync);document.removeEventListener('visibilitychange',sync);canvas.remove();stage.classList.remove('particles-ready');delete stage.dataset.particlePhase;};
}

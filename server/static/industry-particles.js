// Sparse industrial motifs live behind the landing content, below its hero.
export function mountIndustryParticles(hero) {
  const canvas=document.createElement('canvas');canvas.className='industry-particles';canvas.setAttribute('aria-hidden','true');
  const ctx=canvas.getContext('2d',{alpha:true});if(!ctx)return()=>{};
  const motion=matchMedia('(prefers-reduced-motion: reduce)');
  let width=0,height=0,frame=0,last=0,elapsed=0,disposed=false,lowerVisible=false;
  function sample(draw){
    const bitmap=document.createElement('canvas');bitmap.width=240;bitmap.height=180;
    const ink=bitmap.getContext('2d',{willReadFrequently:true});ink.fillStyle='#fff';ink.strokeStyle='#fff';ink.lineWidth=2.5;draw(ink);
    const pixels=ink.getImageData(0,0,240,180).data,points=[];
    for(let y=0;y<180;y+=4)for(let x=0;x<240;x+=4)if(pixels[(y*240+x)*4+3]>100)points.push({x:x-120,y:y-90,phase:x*.17+y*.31});
    return points;
  }
  const motifs=[
    {x:.13,y:.24,scale:.85,phase:0,points:sample(ink=>{ink.font='700 58px Arial, sans-serif';ink.textAlign='center';ink.fillText('ANSYS',120,108);})},
    {x:.88,y:.56,scale:1.05,phase:2,points:sample(ink=>{
      // Abstract process diagram: vessel, pump, valve and directed connections.
      ink.strokeRect(20,55,42,65);ink.strokeRect(178,55,42,65);
      ink.beginPath();ink.moveTo(62,88);ink.lineTo(92,88);ink.moveTo(128,88);ink.lineTo(178,88);ink.moveTo(198,55);ink.lineTo(198,30);ink.lineTo(40,30);ink.lineTo(40,55);ink.stroke();
      ink.beginPath();ink.arc(110,88,18,0,Math.PI*2);ink.moveTo(102,78);ink.lineTo(120,88);ink.lineTo(102,98);ink.closePath();ink.stroke();
      ink.beginPath();ink.moveTo(144,78);ink.lineTo(164,98);ink.lineTo(164,78);ink.lineTo(144,98);ink.closePath();ink.stroke();
      ink.beginPath();ink.moveTo(76,82);ink.lineTo(84,88);ink.lineTo(76,94);ink.stroke();
    })},
    {x:.22,y:.86,scale:.85,phase:4,points:sample(ink=>{
      // An oil drop, outlined as a chain of particles.
      ink.beginPath();ink.moveTo(120,22);ink.bezierCurveTo(108,51,67,91,77,121);ink.bezierCurveTo(91,166,154,166,166,121);ink.bezierCurveTo(176,91,132,51,120,22);ink.stroke();
      ink.beginPath();ink.moveTo(95,113);ink.quadraticCurveTo(93,133,113,139);ink.stroke();
    })}
  ];
  for(const name of ['MITYASHKIN','STEPANOV'])motifs.push({points:sample(ink=>{ink.font='600 27px Arial, sans-serif';ink.textAlign='center';ink.fillText(name,120,100);})});
  // Fixed particle identities are reused for all five shapes, rather than crossfading images.
  const shapes=motifs.map(m=>Array.from({length:420},(_,i)=>m.points[Math.floor(i*m.points.length/420)]));
  const instances=motifs.slice(0,3);
  function draw(){
    ctx.clearRect(0,0,width,height);
    const start=Math.max(0,hero.getBoundingClientRect().bottom+32);if(start>=height)return;
    ctx.save();ctx.beginPath();ctx.rect(0,start,width,height-start);ctx.clip();
    const time=motion.matches?0:elapsed/1000;
    const cool=new Path2D(),warm=new Path2D();
    for(const [index,motif] of instances.entries()){
      const x=width*motif.x+Math.sin(time*.15+motif.phase)*16,y=height*motif.y+Math.cos(time*.12+motif.phase)*14;
      const rotation=Math.sin(time*.07+motif.phase)*.07,c=Math.cos(rotation),s=Math.sin(rotation);
      const cycle=time/10+index,step=Math.floor(cycle),phase=cycle-step;
      const from=shapes[step%shapes.length],to=shapes[(step+1)%shapes.length];
      const t=Math.max(0,(phase-.72)/.28),blend=t*t*(3-2*t);
      for(let i=0;i<420;i++){
        const a=from[i],b=to[i],arc=Math.sin(Math.PI*blend)*8;
        const p={x:a.x+(b.x-a.x)*blend+Math.sin(i*2.4)*arc,y:a.y+(b.y-a.y)*blend+Math.cos(i*1.7)*arc,phase:a.phase};
        const xx=(p.x*c-p.y*s)*motif.scale,yy=(p.x*s+p.y*c)*motif.scale;
        const px=x+xx+Math.sin(time*.6+p.phase)*.55,py=y+yy+Math.cos(time*.5+p.phase)*.55;
        const path=i%23===0?warm:cool;path.moveTo(px+.85,py);path.arc(px,py,.85,0,Math.PI*2);
      }
    }
    ctx.fillStyle='rgba(145,183,215,.4)';ctx.fill(cool);ctx.fillStyle='rgba(255,150,90,.38)';ctx.fill(warm);ctx.restore();
  }
  function animate(time){
    frame=0;if(disposed||document.hidden||motion.matches||!lowerVisible)return;
    if(last&&time-last<65){frame=requestAnimationFrame(animate);return;}
    elapsed+=last?Math.min(time-last,150):0;last=time;draw();frame=requestAnimationFrame(animate);
  }
  function sync(){cancelAnimationFrame(frame);frame=0;last=0;if(disposed)return;if(motion.matches){draw();return;}if(!document.hidden&&lowerVisible)frame=requestAnimationFrame(animate);}
  function resize(){width=innerWidth;height=innerHeight;const ratio=Math.min(devicePixelRatio||1,1.25);canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);lowerVisible=hero.getBoundingClientRect().bottom+32<height;draw();sync();}
  function scroll(){const next=hero.getBoundingClientRect().bottom+32<height;if(next!==lowerVisible){lowerVisible=next;draw();sync();}else if(motion.matches)draw();}
  document.body.append(canvas);resize();sync();
  window.addEventListener('resize',resize,{passive:true});window.addEventListener('scroll',scroll,{passive:true});document.addEventListener('visibilitychange',sync);motion.addEventListener('change',sync);
  return()=>{disposed=true;cancelAnimationFrame(frame);window.removeEventListener('resize',resize);window.removeEventListener('scroll',scroll);document.removeEventListener('visibilitychange',sync);motion.removeEventListener('change',sync);canvas.remove();};
}

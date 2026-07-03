/* Pundibari R.G.L High School — main.js v2 */

// Preloader
window.addEventListener('load',()=>setTimeout(()=>{
  const p=document.getElementById('preloader');
  if(p)p.classList.add('hidden');
},1600));

// Navbar scroll
const nb=document.getElementById('navbar');
window.addEventListener('scroll',()=>{
  nb?.classList.toggle('scrolled',window.scrollY>50);
  document.querySelector('.scroll-top')?.classList.toggle('visible',window.scrollY>300);
});

// Scroll to top
document.querySelector('.scroll-top')?.addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}));

// Hamburger
const ham=document.getElementById('hamburger'),nl=document.getElementById('navLinks');
ham?.addEventListener('click',()=>{ham.classList.toggle('open');nl?.classList.toggle('open')});
document.addEventListener('click',e=>{if(!ham?.contains(e.target)&&!nl?.contains(e.target)){ham?.classList.remove('open');nl?.classList.remove('open')}});

// Particles
(function(){
  const c=document.querySelector('.hero-particles');
  if(!c)return;
  for(let i=0;i<35;i++){
    const p=document.createElement('div');p.className='particle';
    p.style.cssText=`left:${Math.random()*100}%;--dur:${6+Math.random()*10}s;--delay:${Math.random()*8}s;width:${1+Math.random()*2}px;height:${1+Math.random()*2}px`;
    c.appendChild(p);
  }
})();

// Reveal on scroll
const ro=new IntersectionObserver(e=>e.forEach(x=>{if(x.isIntersecting){x.target.classList.add('visible');ro.unobserve(x.target)}}),{threshold:.1,rootMargin:'0px 0px -40px 0px'});
document.querySelectorAll('.reveal').forEach(el=>ro.observe(el));

// Counter animation
function animCount(el){
  const t=parseInt(el.dataset.target||el.textContent);
  const suf=el.dataset.suffix||'';
  let cur=0;const step=t/60;
  const tm=setInterval(()=>{cur=Math.min(cur+step,t);el.textContent=Math.round(cur)+suf;if(cur>=t)clearInterval(tm)},22);
}
const co=new IntersectionObserver(e=>e.forEach(x=>{if(x.isIntersecting){x.target.querySelectorAll('[data-target]').forEach(animCount);co.unobserve(x.target)}}),{threshold:.3});
document.querySelectorAll('.ach-grid,.stat-cards-row,.stats-row').forEach(el=>co.observe(el));

// Class page tabs
document.querySelectorAll('.ctab').forEach(tab=>{
  tab.addEventListener('click',()=>{
    document.querySelectorAll('.ctab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab)?.classList.add('active');
  });
});

// ══════════════════════════════════════════════════════
// Animated number counters (used on admin/dev/student stat cards)
// ══════════════════════════════════════════════════════
window.animateCounters = function(root){
  root = root || document;
  root.querySelectorAll('[data-count]').forEach(el=>{
    const target = parseFloat(el.dataset.count) || 0;
    const suffix = el.dataset.suffix || '';
    const isInt = Number.isInteger(target);
    let cur = 0;
    if(el._countTimer) clearInterval(el._countTimer);
    const step = Math.max(target/36, isInt ? 1 : 0.1);
    el._countTimer = setInterval(()=>{
      cur = Math.min(cur+step, target);
      el.textContent = (isInt ? Math.round(cur) : cur.toFixed(1)).toLocaleString ?
        (isInt ? Math.round(cur).toLocaleString('en-IN') : cur.toFixed(1)) + suffix :
        (isInt ? Math.round(cur) : cur.toFixed(1)) + suffix;
      if(cur >= target){
        clearInterval(el._countTimer);
        el.classList.add('count-pop');
        setTimeout(()=>el.classList.remove('count-pop'), 350);
      }
    }, 18);
  });
};
document.addEventListener('DOMContentLoaded', ()=>window.animateCounters());

// Dashboard sidebar panels — animated switch with stagger + counter replay
document.querySelectorAll('.sb-item[data-panel]').forEach(item=>{
  item.addEventListener('click',()=>{
    const targetId = item.dataset.panel;
    const targetPanel = document.getElementById(targetId);
    const current = document.querySelector('.dash-panel.active');
    if(current === targetPanel) return;

    document.querySelectorAll('.sb-item').forEach(i=>i.classList.remove('active'));
    item.classList.add('active');

    if(current){
      current.classList.add('panel-leaving');
      setTimeout(()=>{
        current.classList.remove('active','panel-leaving');
        targetPanel?.classList.add('active');
        staggerReveal(targetPanel);
        window.animateCounters(targetPanel);
        window.dispatchEvent(new Event('resize'));
      }, 140);
    } else {
      targetPanel?.classList.add('active');
      staggerReveal(targetPanel);
      window.animateCounters(targetPanel);
      window.dispatchEvent(new Event('resize'));
    }
  });
});

// Stagger-reveal list rows / cards inside a freshly-shown panel
function staggerReveal(panel){
  if(!panel) return;
  const items = panel.querySelectorAll('.hw-item, .notice-item, .event-item, .tt-today tbody tr, .result-table tbody tr, .student-att-row');
  items.forEach((el,i)=>{
    el.style.animation = 'none';
    void el.offsetWidth; // reflow to restart animation
    el.style.animation = `panelItemIn .38s cubic-bezier(.22,1,.36,1) both`;
    el.style.animationDelay = Math.min(i*35, 400) + 'ms';
  });
}
// Reveal the initially-active panel's items on first load too
document.addEventListener('DOMContentLoaded', ()=>{
  staggerReveal(document.querySelector('.dash-panel.active'));
});

// Mobile sidebar toggles
document.getElementById('dashToggle')?.addEventListener('click',()=>document.querySelector('.dash-sidebar')?.classList.toggle('open'));
document.getElementById('adminToggle')?.addEventListener('click',()=>document.querySelector('.admin-sidebar')?.classList.toggle('open'));

// Lightbox
function openLB(src){const lb=document.getElementById('lb'),img=document.getElementById('lbImg');if(lb&&img){img.src=src;lb.classList.add('open')}}
document.querySelectorAll('.masonry-item img,.gallery-item img,.facility-photo img').forEach(img=>img.addEventListener('click',()=>openLB(img.src)));
document.getElementById('lbClose')?.addEventListener('click',()=>document.getElementById('lb')?.classList.remove('open'));
document.getElementById('lb')?.addEventListener('click',e=>{if(e.target===e.currentTarget)e.currentTarget.classList.remove('open')});

// Gallery filter
document.querySelectorAll('.filter-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    const f=btn.dataset.filter;
    document.querySelectorAll('.masonry-item').forEach(item=>{
      item.style.display=(f==='all'||item.dataset.cat===f)?'block':'none';
    });
  });
});

// Notice filter
window.filterNotices=function(cat,btn){
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.notice-filterable').forEach(el=>{
    el.style.display=(cat==='all'||el.dataset.cat===cat)?'block':'none';
  });
};

// Flash auto-close
setTimeout(()=>document.querySelectorAll('.flash').forEach(f=>f.remove()),5000);

// Current date
const de=document.getElementById('currentDate');
if(de)de.textContent=new Date().toLocaleDateString('en-IN',{weekday:'long',year:'numeric',month:'long',day:'numeric'});

// Section dropdowns for forms
window.updateSections=function(srcId,tgtId,cls){
  const s=document.getElementById(tgtId);
  if(!s)return;
  s.innerHTML='<option value="">— Select Section —</option>';
  const opts=cls==='10'?['A','B','C']:(cls==='11'||cls==='12')?['Science','Arts']:['A','B','C','D'];
  opts.forEach(o=>{const el=document.createElement('option');el.value=o;el.textContent=o;s.appendChild(el)});
};

// Circular progress chart
function drawCircular(canvasId,pct,color='#10b981'){
  const canvas=document.getElementById(canvasId);
  if(!canvas)return;
  const ctx=canvas.getContext('2d');
  const W=canvas.width,H=canvas.height,cx=W/2,cy=H/2,r=W*0.38;
  ctx.clearRect(0,0,W,H);
  // BG ring
  ctx.beginPath();ctx.arc(cx,cy,r,0,2*Math.PI);
  ctx.strokeStyle='rgba(255,255,255,0.07)';ctx.lineWidth=12;ctx.stroke();
  // Fill
  const start=-Math.PI/2,end=start+(2*Math.PI*(pct/100));
  ctx.beginPath();ctx.arc(cx,cy,r,start,end);
  ctx.strokeStyle=color;ctx.lineWidth=12;ctx.lineCap='round';ctx.stroke();
}

// Init Charts (called when dashboard loads)
window.initDashCharts=function(attPct,attPresent,attTotal){
  // Circular attendance
  drawCircular('attCircle', attPct, '#10b981');

  // Attendance bar chart
  const bc=document.getElementById('attBarChart');
  if(bc&&window.Chart){
    if(bc._chart)bc._chart.destroy();
    bc._chart=new Chart(bc.getContext('2d'),{
      type:'bar',
      data:{
        labels:['01','05','10','15','20','25','30'],
        datasets:[{
          label:'Present',
          data:[22,20,24,18,23,21,22],
          backgroundColor:'rgba(16,185,129,0.7)',
          borderRadius:4,borderSkipped:false,
        }]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{legend:{display:false}},
        scales:{
          x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#7a9abf',font:{size:10}}},
          y:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#7a9abf',font:{size:10}},beginAtZero:true,max:30}
        }
      }
    });
  }
};

// Admin Charts
window.initAdminCharts=function(studentCount,noticeCount){
  // Line chart - Students Overview
  const lc=document.getElementById('studentLineChart');
  if(lc&&window.Chart){
    if(lc._chart)lc._chart.destroy();
    lc._chart=new Chart(lc.getContext('2d'),{
      type:'line',
      data:{
        labels:['Jan','Feb','Mar','Apr','May','Jun'],
        datasets:[{
          label:'Students',
          data:[980,1020,1080,1120,1160,studentCount],
          borderColor:'#f0b429',backgroundColor:'rgba(240,180,41,0.08)',
          borderWidth:2,pointBackgroundColor:'#f0b429',pointRadius:4,fill:true,tension:.4,
        }]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{legend:{display:false}},
        scales:{
          x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#7a9abf',font:{size:10}}},
          y:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#7a9abf',font:{size:10}},beginAtZero:false}
        }
      }
    });
  }
  // Donut chart - Notices
  const dc=document.getElementById('noticesDonut');
  if(dc&&window.Chart){
    if(dc._chart)dc._chart.destroy();
    dc._chart=new Chart(dc.getContext('2d'),{
      type:'doughnut',
      data:{
        labels:['Active','Expired','Draft'],
        datasets:[{
          data:[Math.round(noticeCount*0.72), Math.round(noticeCount*0.2), Math.round(noticeCount*0.08)],
          backgroundColor:['#10b981','#ef4444','#f0b429'],
          borderWidth:0,hoverOffset:4,
        }]
      },
      options:{
        responsive:true,maintainAspectRatio:false,cutout:'72%',
        plugins:{legend:{position:'right',labels:{color:'#7a9abf',font:{size:10},boxWidth:10}}}
      }
    });
  }
};

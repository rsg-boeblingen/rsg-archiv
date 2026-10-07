(function(){
  var d=document.getElementById('lb'); if(!d) return;
  var btns=[].slice.call(document.querySelectorAll('.galerie button')), i=0;
  var img=d.querySelector('img'), cap=d.querySelector('figcaption');
  function zeige(n){ i=(n+btns.length)%btns.length; var b=btns[i];
    img.src=b.dataset.gross; img.alt=b.querySelector('img').alt;
    cap.textContent=b.querySelector('img').alt+'  ('+(i+1)+' / '+btns.length+')'; }
  btns.forEach(function(b,n){ b.addEventListener('click',function(){ zeige(n); d.showModal(); }); });
  d.querySelector('.zu').onclick=function(){ d.close(); };
  d.querySelector('.vor').onclick=function(){ zeige(i+1); };
  d.querySelector('.zurueckb').onclick=function(){ zeige(i-1); };
  d.addEventListener('keydown',function(e){ if(e.key==='ArrowRight') zeige(i+1); if(e.key==='ArrowLeft') zeige(i-1); });
  var x0=null; d.addEventListener('touchstart',function(e){ x0=e.touches[0].clientX; },{passive:true});
  d.addEventListener('touchend',function(e){ if(x0===null) return; var dx=e.changedTouches[0].clientX-x0;
    if(Math.abs(dx)>50) zeige(i+(dx<0?1:-1)); x0=null; });
})();

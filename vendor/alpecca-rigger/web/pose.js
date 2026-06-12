/* ============================================================================
 * pose.js — Live2D Auto-Rigger : Pose & Expression preview
 * ----------------------------------------------------------------------------
 * An approximate 2D puppet that drives the classified PSD parts through their
 * pivots/bindings: head turn (X/Y/Z), eye blink + look, brows, mouth open/form,
 * body angle + breath, plus expression and pose presets, idle animation and
 * pose-PNG export. It is a preview to sanity-check the rig — not a Cubism
 * runtime — built only from translate/scale/rotate of each part.
 * Talks to index.html through window.__rig.
 * ==========================================================================*/
(function () {
  "use strict";

  var DEG = Math.PI / 180;
  var app = null, host = null, active = false, raf = 0, idle = false, t0 = 0;
  var handFront = { L:false, R:false };   // bring an arm in front of torso clothing
  var syncHandRef = null;

  var P = defaults();
  function defaults() {
    return {
      ParamAngleX:0, ParamAngleY:0, ParamAngleZ:0,
      ParamEyeLOpen:1, ParamEyeROpen:1, ParamEyeLSmile:0, ParamEyeRSmile:0,
      ParamEyeBallX:0, ParamEyeBallY:0,
      ParamBrowLY:0, ParamBrowRY:0, ParamBrowLForm:0, ParamBrowRForm:0,
      ParamMouthOpenY:0, ParamMouthForm:0,
      ParamBodyAngleX:0, ParamBodyAngleY:0, ParamBodyAngleZ:0, ParamBreath:0,
      ParamArmLA:0, ParamArmLB:0, ParamArmRA:0, ParamArmRB:0,
      ParamLegLA:0, ParamLegLB:0, ParamLegRA:0, ParamLegRB:0
    };
  }

  /* ---- geometry derived from classified parts ---------------------------- */
  function geom() {
    var r = app.result, W = app.canvasW, H = app.canvasH;
    var g = { headPivot:{x:W/2, y:H*0.55}, bodyPivot:{x:W/2, y:H*0.98},
              eye:{L:null, R:null} };
    var faceB=null, neckP=null;
    r.parts.forEach(function (p) {
      var k = p.cls.key, s = p.cls.side, b = p.bbox;
      if (k==='neck') neckP=p;
      if (k==='face') faceB=b;
      if ((k==='eyewhite'||k==='iris'||k==='eyelash') && s) {
        var c = g.eye[s];
        if (!c || k==='eyewhite') g.eye[s] = { x:(b.left+b.right)/2, y:(b.top+b.bottom)/2,
                                               w:Math.max(8,b.right-b.left), h:Math.max(6,b.bottom-b.top) };
      }
    });
    if (neckP) g.headPivot = { x:neckP.pivot.x, y:neckP.bbox.top };
    else if (faceB) g.headPivot = { x:(faceB.left+faceB.right)/2, y:faceB.bottom };
    return g;
  }

  var HEAD_FOLDERS = { 'Face':1,'Eyes':1,'Brows':1,'Mouth':1,'Hair Front':1,'Accessory':1,'Hair Back':1 };
  function isHead(p){ return p.cls.key!=='neck' && HEAD_FOLDERS[p.cls.folder]; }
  function isBody(p){ return p.cls.folder==='Body' || p.cls.key==='neck'; }
  function headDepth(k){
    var d={ face:0.05, ear:0, cheek:0.4, nose:0.7, eyebrow:0.5, eyelash:0.55,
            eyewhite:0.55, iris:0.85, eye_hl:0.9, mouth:0.6, hair_front:0.15,
            hair_side:0.1, headwear:0.25, accessory:0.2, hair_back:-0.35 };
    return (k in d) ? d[k] : 0.3;
  }

  /* ---- main draw: ctx is already scaled to display ----------------------- */
  function draw(ctx) {
    var r = app.result, layers = app.layers, g = geom();
    var bodyTx = P.ParamBodyAngleX*1.2, bodyTy = P.ParamBodyAngleY*1.0;
    function drawPart(p) {
      var l = layers[p.index]; if (!l || !l.cv) return;
      ctx.save();
      if (isBody(p)) applyBody(ctx, g);
      else if (isHead(p)) applyHead(ctx, p, g, bodyTx, bodyTy);
      applyLocal(ctx, p, g);
      // skinned limb warp (arms/legs) takes over rendering for its parts
      if (window.Skeleton && Skeleton.renderLimb(ctx, p.index, P)) { ctx.restore(); return; }
      ctx.drawImage(l.cv, l.left, l.top);
      ctx.restore();
    }
    // 'hand in front' arms are deferred and re-drawn just after the torso/clothing
    // region (order >= 44 = neck onward), so they sit over the jacket but under the head.
    var deferred = [], flushed = false;
    function flush(){ for (var i=0;i<deferred.length;i++) drawPart(deferred[i]); deferred=[]; flushed=true; }
    r.ordered.forEach(function (p) {
      if (!flushed && p.cls.order >= 44) flush();
      if (p.cls.key==='handwear' && p.cls.side && handFront[p.cls.side]) { deferred.push(p); return; }
      drawPart(p);
    });
    if (!flushed) flush();
    if (window.Skeleton) Skeleton.drawOverlay(ctx);
  }

  function applyHead(ctx, p, g, bodyTx, bodyTy) {
    ctx.translate(bodyTx*0.7, bodyTy*0.7);              // follow body
    ctx.translate(P.ParamAngleX*1.4, P.ParamAngleY*1.1); // head shift
    ctx.translate(g.headPivot.x, g.headPivot.y);
    ctx.rotate(P.ParamAngleZ*DEG);
    ctx.translate(-g.headPivot.x, -g.headPivot.y);
    var d = headDepth(p.cls.key);                       // parallax
    ctx.translate(P.ParamAngleX*d, P.ParamAngleY*d*0.8);
  }
  function applyBody(ctx, g) {
    ctx.translate(P.ParamBodyAngleX*1.2, P.ParamBodyAngleY*1.0);
    ctx.translate(g.bodyPivot.x, g.bodyPivot.y);
    ctx.rotate(P.ParamBodyAngleZ*DEG);
    ctx.scale(1, 1 + P.ParamBreath*0.02);
    ctx.translate(-g.bodyPivot.x, -g.bodyPivot.y);
  }

  function applyLocal(ctx, p, g) {
    var k = p.cls.key, s = p.cls.side, b = p.bbox;
    // --- eyes: blink + look ---
    if (k==='eyelash'||k==='eyewhite'||k==='iris'||k==='eye_hl') {
      var ec = (s && g.eye[s]) || { x:(b.left+b.right)/2, y:(b.top+b.bottom)/2,
                                    w:Math.max(8,b.right-b.left), h:Math.max(6,b.bottom-b.top) };
      var open = s==='R' ? P.ParamEyeROpen : P.ParamEyeLOpen;
      var smile = s==='R' ? P.ParamEyeRSmile : P.ParamEyeLSmile;
      var oeff = Math.max(0, open*(1 - 0.45*smile));
      ctx.translate(ec.x, ec.y);
      if (k==='iris'||k==='eye_hl')
        ctx.translate(P.ParamEyeBallX*ec.w*0.28, P.ParamEyeBallY*ec.h*0.28);
      ctx.scale(1, 0.06 + 0.94*oeff);
      ctx.translate(-ec.x, -ec.y);
      if (k==='eyelash') ctx.translate(0, (1-oeff)*ec.h*0.15);
      return;
    }
    // --- eyebrows: vertical move + form rotation ---
    if (k==='eyebrow') {
      var by = s==='R' ? P.ParamBrowRY : P.ParamBrowLY;
      var bf = s==='R' ? P.ParamBrowRForm : P.ParamBrowLForm;
      var range = Math.max(7, (b.bottom-b.top)*1.4);
      var cx = app.canvasW/2;
      var inner = (b.left+b.right)/2 < cx ? b.right : b.left; // end toward face center
      var pivY = (b.top+b.bottom)/2;
      ctx.translate(0, -by*range);
      ctx.translate(inner, pivY);
      var sign = (b.left+b.right)/2 < cx ? 1 : -1;            // mirror per side
      ctx.rotate(bf*10*DEG*sign);
      ctx.translate(-inner, -pivY);
      return;
    }
    // --- mouth: open (scale Y) + form (scale X) ---
    if (k==='mouth') {
      var cx2 = (b.left+b.right)/2, top = b.top;
      ctx.translate(cx2, top);
      ctx.scale(1 + P.ParamMouthForm*0.30, 1 + P.ParamMouthOpenY*1.8);
      ctx.translate(-cx2, -top);
      return;
    }
  }

  /* ---- presets ----------------------------------------------------------- */
  var EXPRESSIONS = {
    Neutral:   {},
    Happy:     { ParamMouthForm:0.85, ParamMouthOpenY:0.18, ParamBrowLY:0.2, ParamBrowRY:0.2,
                 ParamEyeLOpen:0.82, ParamEyeROpen:0.82, ParamEyeLSmile:0.6, ParamEyeRSmile:0.6 },
    Laugh:     { ParamMouthForm:0.6, ParamMouthOpenY:0.9, ParamEyeLOpen:0.4, ParamEyeROpen:0.4,
                 ParamEyeLSmile:0.9, ParamEyeRSmile:0.9, ParamBrowLY:0.35, ParamBrowRY:0.35 },
    Angry:     { ParamBrowLForm:-0.9, ParamBrowRForm:-0.9, ParamBrowLY:-0.5, ParamBrowRY:-0.5,
                 ParamMouthForm:-0.5, ParamMouthOpenY:0.12 },
    Sad:       { ParamBrowLForm:0.8, ParamBrowRForm:0.8, ParamBrowLY:0.35, ParamBrowRY:0.35,
                 ParamMouthForm:-0.6, ParamEyeLOpen:0.7, ParamEyeROpen:0.7 },
    Surprised: { ParamBrowLY:0.9, ParamBrowRY:0.9, ParamMouthOpenY:0.8,
                 ParamEyeLOpen:1, ParamEyeROpen:1 },
    Smug:      { ParamMouthForm:0.5, ParamBrowLForm:-0.25, ParamBrowRForm:-0.25,
                 ParamEyeLOpen:0.6, ParamEyeROpen:0.6, ParamEyeBallX:0.3 },
    Wink:      { ParamEyeLOpen:0, ParamEyeROpen:1, ParamEyeLSmile:1, ParamMouthForm:0.6, ParamMouthOpenY:0.15 },
    Sleepy:    { ParamEyeLOpen:0.25, ParamEyeROpen:0.25, ParamBrowLY:0.2, ParamBrowRY:0.2, ParamMouthOpenY:0.1 },
    Pout:      { ParamMouthForm:-0.7, ParamMouthOpenY:0.14, ParamBrowLY:-0.3, ParamBrowRY:-0.3 }
  };
  var POSES = {
    Front:   { ParamAngleX:0, ParamAngleY:0, ParamAngleZ:0, ParamEyeBallX:0, ParamEyeBallY:0, ParamBodyAngleX:0, ParamBodyAngleZ:0 },
    'Turn L':{ ParamAngleX:-25, ParamEyeBallX:-0.6, ParamBodyAngleX:-6 },
    'Turn R':{ ParamAngleX:25, ParamEyeBallX:0.6, ParamBodyAngleX:6 },
    'Look Up':{ ParamAngleY:18, ParamEyeBallY:0.7 },
    'Look Dn':{ ParamAngleY:-18, ParamEyeBallY:-0.7 },
    'Tilt L':{ ParamAngleZ:14, ParamBodyAngleZ:3 },
    'Tilt R':{ ParamAngleZ:-14, ParamBodyAngleZ:-3 }
  };

  function applyPreset(map, additive) {
    if (!additive) {
      // expressions reset only face params; poses reset only pose params
    }
    for (var k in map) P[k] = map[k];
    syncSliders(); render();
  }
  function setExpression(name) {
    // reset facial params first, then apply
    ['ParamEyeLOpen','ParamEyeROpen'].forEach(function(k){P[k]=1;});
    ['ParamEyeLSmile','ParamEyeRSmile','ParamBrowLY','ParamBrowRY','ParamBrowLForm',
     'ParamBrowRForm','ParamMouthOpenY','ParamMouthForm'].forEach(function(k){P[k]=0;});
    applyPreset(EXPRESSIONS[name] || {}, true);
  }
  function setPose(name) {
    ['ParamAngleX','ParamAngleY','ParamAngleZ','ParamEyeBallX','ParamEyeBallY',
     'ParamBodyAngleX','ParamBodyAngleY','ParamBodyAngleZ',
     'ParamArmLA','ParamArmLB','ParamArmRA','ParamArmRB',
     'ParamLegLA','ParamLegLB','ParamLegRA','ParamLegRB'].forEach(function(k){P[k]=0;});
    var map = POSES[name] || {};
    handFront.L = !!map.handFrontL; handFront.R = !!map.handFrontR;
    var clean = {}; for (var k in map) if (k.indexOf('Param') === 0) clean[k] = map[k];
    applyPreset(clean, true);
    if (syncHandRef) syncHandRef();
  }

  /* ---- UI ---------------------------------------------------------------- */
  var SLIDERS = [
    ['Head', [['ParamAngleX','Angle X',-30,30,1],['ParamAngleY','Angle Y',-30,30,1],['ParamAngleZ','Angle Z',-30,30,1]]],
    ['Eyes', [['ParamEyeLOpen','Open L',0,1,0.01],['ParamEyeROpen','Open R',0,1,0.01],
              ['ParamEyeBallX','Look X',-1,1,0.01],['ParamEyeBallY','Look Y',-1,1,0.01]]],
    ['Brows',[['ParamBrowLY','Y L',-1,1,0.01],['ParamBrowRY','Y R',-1,1,0.01],
              ['ParamBrowLForm','Form L',-1,1,0.01],['ParamBrowRForm','Form R',-1,1,0.01]]],
    ['Mouth',[['ParamMouthOpenY','Open',0,1,0.01],['ParamMouthForm','Form',-1,1,0.01]]],
    ['Arms', [['ParamArmLA','L Raise',-1,1,0.01],['ParamArmLB','L Bend',-1,1,0.01],
              ['ParamArmRA','R Raise',-1,1,0.01],['ParamArmRB','R Bend',-1,1,0.01]]],
    ['Legs', [['ParamLegLA','L Raise',-1,1,0.01],['ParamLegLB','L Bend',-1,1,0.01],
              ['ParamLegRA','R Raise',-1,1,0.01],['ParamLegRB','R Bend',-1,1,0.01]]],
    ['Body', [['ParamBodyAngleX','Angle X',-10,10,1],['ParamBodyAngleY','Angle Y',-10,10,1],
              ['ParamBodyAngleZ','Angle Z',-10,10,1],['ParamBreath','Breath',0,1,0.01]]]
  ];
  var sliderEls = {};

  var profileMerged = false;
  function mergeProfile() {
    if (profileMerged || !window.ALPECCA_PROFILE) return; profileMerged = true;
    var pf = window.ALPECCA_PROFILE;
    if (pf.expressions) for (var en in pf.expressions) EXPRESSIONS[en] = pf.expressions[en];
    if (pf.poses)       for (var pn in pf.poses)       POSES[pn]       = pf.poses[pn];
  }
  function build(hostEl) {
    mergeProfile();
    host = hostEl; host.innerHTML='';
    host.appendChild(section('Expressions', grid(Object.keys(EXPRESSIONS), setExpression)));
    host.appendChild(section('Poses', grid(Object.keys(POSES), setPose)));
    SLIDERS.forEach(function (grp) {
      var wrap = document.createElement('div'); wrap.className='pgrp';
      var h = document.createElement('div'); h.className='ph'; h.textContent=grp[0]; wrap.appendChild(h);
      grp[1].forEach(function (s) {
        var row = document.createElement('label'); row.className='prow';
        var nm = document.createElement('span'); nm.className='pl'; nm.textContent=s[1];
        var rng = document.createElement('input'); rng.type='range'; rng.min=s[2]; rng.max=s[3]; rng.step=s[4];
        rng.value=P[s[0]];
        var val = document.createElement('span'); val.className='pv'; val.textContent=(+P[s[0]]).toFixed(s[4]<1?2:0);
        rng.oninput=function(){ P[s[0]]=+rng.value; val.textContent=(+rng.value).toFixed(s[4]<1?2:0); render(); };
        sliderEls[s[0]]={rng:rng,val:val,step:s[4]};
        row.appendChild(nm); row.appendChild(rng); row.appendChild(val); wrap.appendChild(row);
      });
      host.appendChild(wrap);
    });
    var ctl = document.createElement('div'); ctl.className='pctl';
    var handBtns = {};
    function syncHand(){ ['L','R'].forEach(function(s){ var b=handBtns[s]; if(!b) return;
      b.textContent='Arm '+s+': '+(handFront[s]?'front':'behind'); b.classList.toggle('primary', handFront[s]); }); }
    syncHandRef = syncHand;
    ctl.appendChild(mkBtn('Reset', function(){ P=defaults(); handFront.L=handFront.R=false; syncSliders(); syncHand(); render(); }));
    ctl.appendChild(mkBtn('Mirror', function(){ mirrorPose(); syncHand(); }));
    ctl.appendChild(mkBtn('Save pose', savePose));
    ctl.appendChild(mkBtn('Load pose', loadPose));
    var idleBtn = mkBtn('Idle: off', function(){ toggleIdle(idleBtn); }); ctl.appendChild(idleBtn);
    ['L','R'].forEach(function(s){ var b=mkBtn('', function(){ handFront[s]=!handFront[s]; syncHand(); render(); });
      handBtns[s]=b; ctl.appendChild(b); }); syncHand();
    if (window.Skeleton) {
      var skBtn = mkBtn('Skeleton: off', function(){
        Skeleton.setEditing(!Skeleton.editing); skBtn.textContent='Skeleton: '+(Skeleton.editing?'on':'off');
        skBtn.classList.toggle('primary', Skeleton.editing);
      });
      ctl.appendChild(skBtn);
      var limBtn = mkBtn('Limits: '+(Skeleton.limitsEnabled?'on':'off'), function(){
        Skeleton.setLimits(!Skeleton.limitsEnabled);
        limBtn.textContent='Limits: '+(Skeleton.limitsEnabled?'on':'off');
        limBtn.classList.toggle('primary', Skeleton.limitsEnabled);
      });
      if (Skeleton.limitsEnabled) limBtn.classList.add('primary');
      ctl.appendChild(limBtn);
      ctl.appendChild(mkBtn('Reset skeleton', function(){ Skeleton.reset(); }));
    }
    ctl.appendChild(mkBtn('Export pose PNG', exportPNG, true));
    host.appendChild(ctl);
  }
  function section(title, body) {
    var w=document.createElement('div'); w.className='pgrp';
    var h=document.createElement('div'); h.className='ph'; h.textContent=title; w.appendChild(h); w.appendChild(body); return w;
  }
  function grid(names, fn) {
    var g=document.createElement('div'); g.className='pgrid';
    names.forEach(function(n){ var b=document.createElement('button'); b.className='chip'; b.textContent=n;
      b.onclick=function(){ fn(n); }; g.appendChild(b); });
    return g;
  }
  function mkBtn(label, fn, primary){ var b=document.createElement('button'); if(primary)b.className='primary';
    b.textContent=label; b.onclick=fn; return b; }

  function syncSliders(){ for (var k in sliderEls){ var e=sliderEls[k];
    e.rng.value=P[k]; e.val.textContent=(+P[k]).toFixed(e.step<1?2:0); } }

  /* ---- idle animation ---------------------------------------------------- */
  var nextBlink = 0;
  function toggleIdle(btn){ idle=!idle; btn.textContent='Idle: '+(idle?'on':'off');
    if(idle){ t0=performance.now(); nextBlink=t0+1500+Math.random()*2500; loop(); } else cancelAnimationFrame(raf); }
  function loop(){
    if(!idle||!active){ return; }
    var t=performance.now(), dt=(t-t0)/1000;
    P.ParamBreath = 0.5+0.5*Math.sin(dt*1.6);
    P.ParamBodyAngleY = 1.2*Math.sin(dt*1.6);
    P.ParamAngleX = 6*Math.sin(dt*0.5);
    P.ParamAngleZ = 2*Math.sin(dt*0.37);
    if(t>nextBlink){ var ph=(t-nextBlink)/120; if(ph<1){ var o=Math.abs(1-2*ph); P.ParamEyeLOpen=o; P.ParamEyeROpen=o; }
      else { P.ParamEyeLOpen=1; P.ParamEyeROpen=1; nextBlink=t+1500+Math.random()*2800; } }
    syncSliders(); render(); raf=requestAnimationFrame(loop);
  }

  /* ---- export ------------------------------------------------------------ */
  function exportPNG(){
    var c=document.createElement('canvas'); c.width=app.canvasW; c.height=app.canvasH;
    var ctx=c.getContext('2d'); draw(ctx);
    c.toBlob(function(b){ var a=document.createElement('a'); a.href=URL.createObjectURL(b);
      a.download=(app.fileName||'character')+'_pose.png'; document.body.appendChild(a); a.click();
      setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},1500); });
  }

  function dl(obj, name){ var b=new Blob([JSON.stringify(obj,null,2)],{type:'application/json'});
    var a=document.createElement('a'); a.href=URL.createObjectURL(b); a.download=name;
    document.body.appendChild(a); a.click(); setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},1500); }

  function savePose(){
    var pose = { tool:'live2d-autorigger', kind:'rigpose', version:1,
      params: JSON.parse(JSON.stringify(P)), handFront:{L:handFront.L,R:handFront.R},
      limits: window.Skeleton ? Skeleton.limitsEnabled : true,
      joints: window.Skeleton ? Skeleton.getJoints() : null };
    dl(pose, (app.fileName||'character')+'.rigpose.json');
  }
  function applyPose(pose){
    if (!pose || !pose.params) return;
    for (var k in pose.params) if (k in P) P[k]=pose.params[k];
    if (pose.handFront){ handFront.L=!!pose.handFront.L; handFront.R=!!pose.handFront.R; }
    if (window.Skeleton){
      if (pose.joints) Skeleton.setJoints(pose.joints);
      if (typeof pose.limits==='boolean') Skeleton.setLimits(pose.limits);
    }
    syncSliders(); if (syncHandRef) syncHandRef(); render();
  }
  function loadPose(){
    var inp=document.createElement('input'); inp.type='file'; inp.accept='.json,application/json';
    inp.onchange=function(e){ var f=e.target.files[0]; if(!f) return; var rd=new FileReader();
      rd.onload=function(){ try{ applyPose(JSON.parse(rd.result)); }catch(err){ console.error('bad rigpose',err); } };
      rd.readAsText(f); };
    inp.click();
  }
  var XSWAP=['ParamAngleX','ParamAngleZ','ParamEyeBallX','ParamBodyAngleX','ParamBodyAngleZ'];
  var PAIRS=[['ParamArmLA','ParamArmRA'],['ParamArmLB','ParamArmRB'],['ParamLegLA','ParamLegRA'],
    ['ParamLegLB','ParamLegRB'],['ParamEyeLOpen','ParamEyeROpen'],['ParamEyeLSmile','ParamEyeRSmile'],
    ['ParamBrowLY','ParamBrowRY'],['ParamBrowLForm','ParamBrowRForm']];
  function mirrorPose(){
    var m=JSON.parse(JSON.stringify(P));
    PAIRS.forEach(function(p){ var t=m[p[0]]; m[p[0]]=m[p[1]]; m[p[1]]=t; });
    XSWAP.forEach(function(k){ m[k]=-m[k]; });
    P=m; var t=handFront.L; handFront.L=handFront.R; handFront.R=t;
    syncSliders(); if (syncHandRef) syncHandRef(); render();
  }

  function render(){ app.requestRender(); }

  /* ---- public ------------------------------------------------------------ */
  window.PoseUI = {
    get active(){ return active; },
    init: function (a, hostEl) { app=a; if(window.Skeleton) Skeleton.build(a); build(hostEl); },
    setActive: function (b) { active=b; if(!b && idle){ idle=false; cancelAnimationFrame(raf); } },
    draw: draw,
    params: P
  };
})();

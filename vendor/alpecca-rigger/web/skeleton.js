/* ============================================================================
 * skeleton.js — Live2D Auto-Rigger : skeleton mapping + skinned limb warp
 * ----------------------------------------------------------------------------
 * Adds individual arm/leg posing to Pose mode. Each limb is a 2-bone chain
 * (root -> mid -> tip). Bending uses 2-bone linear-blend skinning over a
 * triangulated mesh: each mesh vertex is blended between the two bone
 * transforms by its position along the bone, and every triangle is texture-
 * warped (affine) to its deformed position. The art STRETCHES smoothly across
 * the joint instead of clipping / tearing, with no strip "fan" artifacts.
 *
 * Also draws an editable skeleton overlay (drag joints to map them onto the
 * art) and exports the bone hierarchy for the rig manifest.
 *
 * Arms (handwear-l/r) are separate layers and pose cleanly. The legs are one
 * merged "legwear" layer, so it is split down the centre into L/R halves so
 * each leg can be posed independently. Talks to the app through window.__rig.
 * ==========================================================================*/
(function () {
  "use strict";
  var DEG = Math.PI / 180;
  var app = null, limbs = [], joints = {}, bones = [], editing = false, drag = null, built = false;

  // tunables (max degrees per slider unit, and direction signs per limb)
  var ARM_UP = 80, ARM_BEND = 100, LEG_UP = 55, LEG_BEND = 85;

  // joint limiters: allowed rotation per segment, in natural slider-degrees
  // (sign is applied per side afterwards). a = root joint, b = mid joint.
  // elbows/knees fold mostly one way -> no hyperextension.
  var limitsOn = true;
  var ROOT_HOLD = 0.12;   // fraction of the limb near the root that stays glued to the body
  var LIMITS = { arm:{ a:[-100,100], b:[-5,135] }, leg:{ a:[-70,70], b:[-135,8] } };
  function clamp(v,lo,hi){ return v<lo?lo:(v>hi?hi:v); }

  /* ---------- helpers ---------- */
  function rot(v, a){ var c=Math.cos(a), s=Math.sin(a); return { x:v.x*c - v.y*s, y:v.x*s + v.y*c }; }
  function sub(a,b){ return { x:a.x-b.x, y:a.y-b.y }; }
  function add(a,b){ return { x:a.x+b.x, y:a.y+b.y }; }
  function mul(v,k){ return { x:v.x*k, y:v.y*k }; }
  function len(v){ return Math.hypot(v.x, v.y); }
  function unit(v){ var l=len(v)||1; return { x:v.x/l, y:v.y/l }; }
  function dot(a,b){ return a.x*b.x + a.y*b.y; }

  function maskHalf(part, keepRightOfCenter) {
    // returns a canvas same size as the part's source, with only one X half kept
    var l = app.layers[part.index], src = l.cv; if (!src) return null;
    var cx = app.canvasW / 2;
    var c = document.createElement('canvas'); c.width = src.width; c.height = src.height;
    var cx2 = c.getContext('2d'); cx2.drawImage(src, 0, 0);
    var im = cx2.getImageData(0, 0, c.width, c.height), d = im.data;
    var fw = 12;                                   // feather width across the split (px)
    for (var y = 0; y < c.height; y++) for (var x = 0; x < c.width; x++) {
      var canvasX = l.left + x;
      var wr = clamp((canvasX - (cx - fw)) / (2*fw), 0, 1);   // 0 = left .. 1 = right of centre
      var w = keepRightOfCenter ? wr : (1 - wr);             // halves overlap+blend in the band
      var ix = (y*c.width + x)*4 + 3; d[ix] = Math.round(d[ix]*w);
    }
    cx2.putImageData(im, 0, 0);
    return { cv:c, left:l.left, top:l.top, width:c.width, height:c.height };
  }

  /* ---------- build skeleton + limbs from classified parts ---------- */
  function getPart(key, side){
    var r = app.result; if (!r) return null;
    return r.parts.filter(function(p){ return p.cls.key===key && (side?p.cls.side===side:true); })[0] || null;
  }

  function build(a) {
    app = a; limbs = []; joints = {}; bones = []; built = true;
    var cx = app.canvasW/2;

    // ----- arms (separate layers) -----
    [['L', getPart('handwear','L')], ['R', getPart('handwear','R')]].forEach(function (e) {
      var side = e[0], part = e[1]; if (!part) return;
      var l = app.layers[part.index]; if (!l || !l.cv) return;
      var b = part.bbox, midY = (b.top+b.bottom)/2, center = (b.left+b.right)/2;
      var innerX = center > cx ? b.left : b.right;     // shoulder end (toward torso)
      var outerX = center > cx ? b.right : b.left;     // wrist end
      var sh = 'shoulder'+side, el = 'elbow'+side, wr = 'wrist'+side;
      joints[sh] = { x:innerX, y:midY };
      joints[wr] = { x:outerX, y:midY };
      joints[el] = { x:(innerX+outerX)/2, y:midY };
      var upSign = side==='R' ? 1 : -1;
      limbs.push({ kind:'arm', side:side, index:part.index,
        src:{ cv:l.cv, left:l.left, top:l.top, width:l.cv.width, height:l.cv.height },
        A:sh, B:el, C:wr, pA:'ParamArm'+side+'A', pB:'ParamArm'+side+'B',
        upSign:upSign, bendSign:upSign, lim:LIMITS.arm });
      bones.push({ id:'Arm_'+side+'_Upper', parent:'Body', from:sh, to:el, limitDeg:LIMITS.arm.a },
                 { id:'Arm_'+side+'_Fore',  parent:'Arm_'+side+'_Upper', from:el, to:wr, limitDeg:LIMITS.arm.b });
    });

    // ----- legs (split merged legwear into halves) -----
    var legPart = getPart('legwear');
    if (legPart) {
      var lb = legPart.bbox, lcx = (lb.left+lb.right)/2;
      [['L', true], ['R', false]].forEach(function (e) {
        var side = e[0], rightHalf = e[1];
        var src = maskHalf(legPart, rightHalf); if (!src) return;
        var hx = rightHalf ? (lcx+lb.right)/2 : (lb.left+lcx)/2;
        var hip='hip'+side, kn='knee'+side, an='ankle'+side;
        joints[hip] = { x:hx, y:lb.top };
        joints[an]  = { x:hx, y:lb.bottom };
        joints[kn]  = { x:hx, y:(lb.top+lb.bottom)/2 };
        var upSign = side==='L' ? 1 : -1;
        limbs.push({ kind:'leg', side:side, index:legPart.index, multi:true, src:src,
          A:hip, B:kn, C:an, pA:'ParamLeg'+side+'A', pB:'ParamLeg'+side+'B',
          upSign:upSign, bendSign:upSign, lim:LIMITS.leg });
        bones.push({ id:'Leg_'+side+'_Thigh', parent:'Body', from:hip, to:kn, limitDeg:LIMITS.leg.a },
                   { id:'Leg_'+side+'_Shin',  parent:'Leg_'+side+'_Thigh', from:kn, to:an, limitDeg:LIMITS.leg.b });
      });
      // feet follow the shin (split footwear too)
      var footPart = getPart('footwear');
      if (footPart) {
        var fb = footPart.bbox, fcx = (fb.left+fb.right)/2;
        [['L', true], ['R', false]].forEach(function (e) {
          var side=e[0], rightHalf=e[1]; var src = maskHalf(footPart, rightHalf); if(!src) return;
          limbs.push({ kind:'foot', side:side, index:footPart.index, multi:true, src:src,
            A:'ankle'+side, B:'ankle'+side, C:'ankle'+side,
            pA:'ParamLeg'+side+'A', pB:'ParamLeg'+side+'B', upSign:(side==='L'?1:-1), bendSign:(side==='L'?1:-1), foot:true });
        });
      }
    }
  }

  /* ---------- FK math for a limb ---------- */
  function fk(limb, P) {
    var A = joints[limb.A], B = joints[limb.B], C = joints[limb.C];
    var maxUp  = (limb.kind==='leg'||limb.kind==='foot') ? LEG_UP : ARM_UP;
    var maxBd  = (limb.kind==='leg'||limb.kind==='foot') ? LEG_BEND : ARM_BEND;
    var aDeg = (P[limb.pA]||0) * maxUp, bDeg = (P[limb.pB]||0) * maxBd;
    if (limitsOn && limb.lim) { aDeg = clamp(aDeg, limb.lim.a[0], limb.lim.a[1]);
                                bDeg = clamp(bDeg, limb.lim.b[0], limb.lim.b[1]); }
    var alpha = aDeg * DEG * limb.upSign;
    var beta  = bDeg * DEG * limb.bendSign;
    var e1 = unit(sub(C, A));
    var axisLen = len(sub(C, A)) || 1;
    var Se = dot(sub(B, A), e1); if (Se < 1) Se = axisLen*0.5;
    return { A:A, e1:e1, axisLen:axisLen, Se:Se, alpha:alpha, beta:beta };
  }
  function Qfk(f, s) {
    if (s <= f.Se) return add(f.A, rot(mul(f.e1, s), f.alpha));
    var Bp = add(f.A, rot(mul(f.e1, f.Se), f.alpha));
    return add(Bp, rot(mul(f.e1, s - f.Se), f.alpha + f.beta));
  }
  function Theta(f, s) {
    var d = Math.max(16, f.axisLen*0.28);
    if (s <= f.Se - d) return f.alpha;
    if (s >= f.Se + d) return f.alpha + f.beta;
    var t = (s - (f.Se - d)) / (2*d);                 // smooth blend across the joint
    return f.alpha + f.beta * (t*t*(3-2*t));
  }

  /* ---------- render one limb with skinned strip warp ----------
   * ctx already carries the display scale (and any body-group transform).      */
  function renderLimb(ctx, partIndex, P) {
    if (!built) return false;
    var mine = limbs.filter(function(L){ return L.index===partIndex; });
    if (!mine.length) return false;
    var base = ctx.getTransform();
    var B = { a:base.a, b:base.b, c:base.c, d:base.d, e:base.e, f:base.f };
    mine.forEach(function (limb) { drawLimb(ctx, limb, P, B); });
    ctx.setTransform(B.a, B.b, B.c, B.d, B.e, B.f);
    return true;
  }

  function drawFoot(ctx, limb, P, B) {
    // the foot rides the deformed end of its leg's shin (follows the ankle),
    // so the shoe stays attached when the leg is posed.
    var src = limb.src, ankleRest = joints[limb.A];
    var leg = limbs.filter(function(L){ return L.kind==='leg' && L.side===limb.side; })[0];
    var th = 0, Q = ankleRest;
    if (leg) { var f = fk(leg, P); th = Theta(f, f.axisLen); Q = Qfk(f, f.axisLen); }
    var cos = Math.cos(th), sin = Math.sin(th);
    var tx = Q.x - (cos*ankleRest.x - sin*ankleRest.y);
    var ty = Q.y - (sin*ankleRest.x + cos*ankleRest.y);
    var a = B.a*cos + B.c*sin, b = B.b*cos + B.d*sin;
    var c = B.a*(-sin) + B.c*cos, d = B.b*(-sin) + B.d*cos;
    var e = B.a*tx + B.c*ty + B.e, ff = B.b*tx + B.d*ty + B.f;
    ctx.setTransform(a, b, c, d, e, ff);
    ctx.drawImage(src.cv, src.left, src.top);
  }

  /* 2-bone linear-blend skin: a rest canvas point -> deformed canvas point.
   * bone1 = rotate whole limb about root A by alpha; bone2 = rotate forearm/
   * shin about the (deformed) elbow by alpha+beta. Blend by along-bone weight. */
  function skin(f, Brest, pt) {
    var r1 = add(f.A, rot(sub(pt, f.A), f.alpha));
    var Bp = add(f.A, rot(sub(Brest, f.A), f.alpha));
    var r2 = add(Bp, rot(sub(pt, Brest), f.alpha + f.beta));
    var w = boneWeight(f, dot(sub(pt, f.A), f.e1));
    var d = { x: r1.x*(1-w) + r2.x*w, y: r1.y*(1-w) + r2.y*w };
    // root anchor: ease deformation in near the attachment so the top stays glued
    var t = dot(sub(pt, f.A), f.e1) / f.axisLen, hold;
    if (t <= 0) hold = 0; else if (t >= ROOT_HOLD) hold = 1;
    else { var u = t/ROOT_HOLD; hold = u*u*(3-2*u); }
    return { x: pt.x*(1-hold) + d.x*hold, y: pt.y*(1-hold) + d.y*hold };
  }
  function boneWeight(f, t) {                 // along-bone distance -> bone2 weight
    var d = Math.max(10, f.axisLen*0.22);     // blend half-width across the joint
    if (t <= f.Se - d) return 0;
    if (t >= f.Se + d) return 1;
    var u = (t - (f.Se - d)) / (2*d);
    return u*u*(3 - 2*u);                      // smoothstep
  }
  // affine mapping source-pixel triangle -> dest-canvas triangle
  function solveAffine(s0,s1,s2,d0,d1,d2) {
    var x1=s1.x-s0.x, y1=s1.y-s0.y, x2=s2.x-s0.x, y2=s2.y-s0.y;
    var det = x1*y2 - y1*x2; if (Math.abs(det) < 1e-6) return null;
    var u1=d1.x-d0.x, u2=d2.x-d0.x, v1=d1.y-d0.y, v2=d2.y-d0.y;
    var a=(u1*y2 - y1*u2)/det, c=(x1*u2 - u1*x2)/det;
    var b=(v1*y2 - y1*v2)/det, d=(x1*v2 - v1*x2)/det;
    return { a:a, b:b, c:c, d:d, e:d0.x-(a*s0.x+c*s0.y), f:d0.y-(b*s0.x+d*s0.y) };
  }
  function tri(ctx, img, s0,s1,s2, d0,d1,d2, B) {
    var m = solveAffine(s0,s1,s2,d0,d1,d2); if (!m) return;
    var a=B.a*m.a+B.c*m.b, b=B.b*m.a+B.d*m.b, c=B.a*m.c+B.c*m.d, d=B.b*m.c+B.d*m.d;
    var e=B.a*m.e+B.c*m.f+B.e, ff=B.b*m.e+B.d*m.f+B.f;
    ctx.save();
    ctx.setTransform(B.a,B.b,B.c,B.d,B.e,B.f);  // clip in body space, using dest canvas coords
    ctx.beginPath(); ctx.moveTo(d0.x,d0.y); ctx.lineTo(d1.x,d1.y); ctx.lineTo(d2.x,d2.y); ctx.closePath(); ctx.clip();
    ctx.setTransform(a,b,c,d,e,ff);             // map source pixels onto the deformed triangle
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }
  function drawLimb(ctx, limb, P, B) {
    if (limb.foot) { drawFoot(ctx, limb, P, B); return; }
    var f = fk(limb, P), src = limb.src, e1 = f.e1;
    var Brest = add(f.A, mul(e1, f.Se));
    var horiz = Math.abs(e1.x) >= Math.abs(e1.y);
    var cols = horiz ? 12 : 3, rows = horiz ? 3 : 12;   // mesh grid: more divisions along the bone
    var gx = cols+1, gy = rows+1, W = src.width, H = src.height;
    var sv = new Array(gx*gy), dv = new Array(gx*gy);   // source-pixel verts + deformed canvas verts
    for (var j=0; j<gy; j++) for (var i=0; i<gx; i++) {
      var sx = i*W/cols, sy = j*H/rows, idx = j*gx+i;
      sv[idx] = { x:sx, y:sy };
      dv[idx] = skin(f, Brest, { x:src.left+sx, y:src.top+sy });
    }
    for (var jj=0; jj<rows; jj++) for (var ii=0; ii<cols; ii++) {
      var a=jj*gx+ii, b=a+1, cc=a+gx, d2=cc+1;
      tri(ctx, src.cv, sv[a],sv[b],sv[cc], dv[a],dv[b],dv[cc], B);
      tri(ctx, src.cv, sv[b],sv[d2],sv[cc], dv[b],dv[d2],dv[cc], B);
    }
  }

  /* ---------- editable overlay ---------- */
  function drawOverlay(ctx) {
    if (!editing || !built) return;
    var pairs = bones.map(function(bn){ return [bn.from, bn.to]; });
    // spine/neck/head reference line if available
    ctx.lineWidth = 2.2; ctx.strokeStyle = '#ffd166cc';
    pairs.forEach(function (pr) {
      var a = joints[pr[0]], b = joints[pr[1]]; if (!a||!b) return;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });
    for (var k in joints) {
      var j = joints[k];
      ctx.beginPath(); ctx.arc(j.x, j.y, 6, 0, 7); 
      ctx.fillStyle = (drag===k) ? '#fff' : '#ffd166'; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#7a5b00'; ctx.stroke();
    }
    if (limitsOn) limbs.forEach(function (L) {
      if (!L.lim) return;
      var A=joints[L.A], Bj=joints[L.B], C=joints[L.C];
      arc(ctx, A, Math.atan2(Bj.y-A.y, Bj.x-A.x), L.lim.a, L.upSign, len(sub(Bj,A))*0.42);
      arc(ctx, Bj, Math.atan2(C.y-Bj.y, C.x-Bj.x), L.lim.b, L.bendSign, len(sub(C,Bj))*0.42);
    });
  }
  function arc(ctx, c, baseAng, range, sign, r) {
    var lo = baseAng + range[0]*DEG*sign, hi = baseAng + range[1]*DEG*sign;
    if (lo>hi){ var t=lo; lo=hi; hi=t; }
    ctx.beginPath(); ctx.arc(c.x, c.y, r, lo, hi); ctx.strokeStyle='#4dd0ff88'; ctx.lineWidth=2; ctx.stroke();
    [lo,hi].forEach(function(ang){ ctx.beginPath(); ctx.moveTo(c.x,c.y);
      ctx.lineTo(c.x+Math.cos(ang)*r, c.y+Math.sin(ang)*r); ctx.strokeStyle='#4dd0ff66'; ctx.lineWidth=1.5; ctx.stroke(); });
  }

  function previewScale(){ var cv = document.getElementById('preview'); return cv ? cv.width/app.canvasW : 1; }
  function evtToCanvas(ev){ var cv=document.getElementById('preview'); var r=cv.getBoundingClientRect();
    var sx=cv.width/r.width, sy=cv.height/r.height, sc=previewScale();
    return { x:((ev.clientX-r.left)*sx)/sc, y:((ev.clientY-r.top)*sy)/sc }; }

  function attach() {
    var cv = document.getElementById('preview'); if (!cv || cv.__skel) return; cv.__skel = true;
    cv.addEventListener('pointerdown', function (ev) {
      if (!editing || !window.PoseUI || !PoseUI.active) return;
      var pt = evtToCanvas(ev), best=null, bd=18;
      for (var k in joints){ var d=Math.hypot(joints[k].x-pt.x, joints[k].y-pt.y); if(d<bd){bd=d;best=k;} }
      if (best){ drag=best; cv.setPointerCapture(ev.pointerId); app.requestRender(); }
    });
    cv.addEventListener('pointermove', function (ev) {
      if (!drag) return; var pt=evtToCanvas(ev); joints[drag].x=pt.x; joints[drag].y=pt.y; app.requestRender();
    });
    cv.addEventListener('pointerup', function (ev) { if(drag){ drag=null; app.requestRender(); } });
  }

  function exportBones() {
    var out = { limitsEnabled:limitsOn,
      joints:{}, bones:bones.map(function(b){ return {id:b.id, parent:b.parent, from:b.from, to:b.to, rotationLimitDeg:b.limitDeg||null}; }) };
    for (var k in joints) out.joints[k] = { x:Math.round(joints[k].x), y:Math.round(joints[k].y) };
    return out;
  }

  window.Skeleton = {
    build: function (a) { build(a); attach(); },
    renderLimb: renderLimb,
    drawOverlay: drawOverlay,
    isLimb: function (idx) { return built && limbs.some(function(L){return L.index===idx;}); },
    setEditing: function (b) { editing = !!b; if(app) app.requestRender(); },
    get editing(){ return editing; },
    setLimits: function (b) { limitsOn = !!b; if(app) app.requestRender(); },
    get limitsEnabled(){ return limitsOn; },
    reset: function () { if (app) { build(app); app.requestRender(); } },
    exportBones: exportBones,
    get bones(){ return bones; },
    getJoints: function(){ var o={}; for(var k in joints) o[k]={x:joints[k].x,y:joints[k].y}; return o; },
    setJoints: function(o){ if(!o) return; for(var k in o) if(joints[k]){ joints[k].x=o[k].x; joints[k].y=o[k].y; } if(app) app.requestRender(); },
    _debug: function(){ return { skin:skin, solveAffine:solveAffine, fk:fk, limbs:limbs, joints:joints }; }
  };
})();

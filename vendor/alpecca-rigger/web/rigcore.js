/* ============================================================================
 * rigcore.js  —  Live2D Auto-Rigger core engine
 * ----------------------------------------------------------------------------
 * Pure, dependency-free logic shared by the browser tool (index.html) and the
 * Node test harness. Takes a parsed PSD layer tree and produces:
 *   - a classification for every layer (canonical Live2D part)
 *   - a clean, re-ordered, foldered export tree (Cubism-ready)
 *   - a rig manifest (parameters, deformers, bindings, draw order, physics)
 *
 * Works in both browser (attached to window.RigCore) and Node (module.exports).
 * ==========================================================================*/
(function (root) {
  'use strict';

  /* ---- Canonical Live2D part schema -------------------------------------
   * Each entry describes one canonical part type. Matching is keyword-based,
   * longest-keyword-wins, after side tokens (-l / -r / left / right) are
   * detected. folder drives the Cubism "Parts" grouping; order is the
   * canonical back->front draw order; params/deformer use {S} = L/R.
   * --------------------------------------------------------------------- */
  var SCHEMA = {
    hair_back:   { label:'Back Hair',  folder:'Hair Back',  order:10,  side:false,
      params:['ParamAngleX','ParamAngleY','ParamAngleZ','ParamHairBack'],
      deformer:'Hair_Back', mesh:'high',
      kw:['back hair','backhair','back-hair','hair back','rear hair','ushirogami','後ろ髪','後髪','うしろ髪'] },
    hair_side:   { label:'Side Hair',  folder:'Hair Front', order:118, side:true,
      params:['ParamAngleX','ParamAngleY','ParamHairSide'],
      deformer:'Hair_Side', mesh:'high',
      kw:['side hair','sidehair','side-hair','hair side','yokogami','横髪','よこ髪'] },
    hair_front:  { label:'Front Hair', folder:'Hair Front', order:120, side:false,
      params:['ParamAngleX','ParamAngleY','ParamAngleZ','ParamHairFront'],
      deformer:'Hair_Front', mesh:'high',
      kw:['front hair','fronthair','front-hair','hair front','bangs','fringe','maegami','前髪','まえ髪'] },
    headwear:    { label:'Headwear',   folder:'Accessory',  order:130, side:false,
      params:['ParamAngleX','ParamAngleY','ParamAngleZ'],
      deformer:'Head_Accessory', mesh:'medium',
      kw:['headwear','head wear','hat','cap','hairclip','hair clip','hairpin','clip','ribbon','bow','crown','horn','halo','帽子','髪飾り','ヘッドアクセ'] },
    face:        { label:'Face',       folder:'Face',       order:50,  side:false,
      params:['ParamAngleX','ParamAngleY','ParamAngleZ'],
      deformer:'Face', mesh:'high',
      kw:['face base','base face','faceskin','face skin','face','head skin','顔','かお','フェイス'] },
    ear:         { label:'Ear',        folder:'Face',       order:48,  side:true,
      params:['ParamAngleX','ParamAngleY'],
      deformer:'Ear_{S}', mesh:'medium',
      kw:['ear','ears','耳','みみ'] },
    cheek:       { label:'Cheek',      folder:'Face',       order:60,  side:false,
      params:['ParamCheek','ParamAngleX','ParamAngleY'],
      deformer:'Face', mesh:'low',
      kw:['cheek','blush','頬','ほほ','チーク'] },
    nose:        { label:'Nose',       folder:'Face',       order:62,  side:false,
      params:['ParamAngleX','ParamAngleY'],
      deformer:'Face', mesh:'low',
      kw:['nose','鼻','はな'] },
    eyebrow:     { label:'Eyebrow',    folder:'Brows',      order:90,  side:true,
      params:['ParamBrow{S}Y','ParamBrow{S}Form','ParamBrow{S}Angle','ParamAngleX','ParamAngleY'],
      deformer:'Brow_{S}', mesh:'medium',
      kw:['eyebrow','eye brow','eyebrows','brow','mayuge','まゆげ','眉毛','眉','まゆ'] },
    eyelash:     { label:'Eyelash',    folder:'Eyes',       order:80,  side:true,
      params:['ParamEye{S}Open','ParamEye{S}Smile','ParamAngleX','ParamAngleY'],
      deformer:'Eye_{S}', mesh:'medium',
      kw:['eyelash','eye lash','eyelashes','lash','eyelid','eye lid','upper eyelid','upper lid','matsuge','まつげ','まつ毛','上まぶた','まぶた','瞼'] },
    eyewhite:    { label:'Eye White',  folder:'Eyes',       order:70,  side:true,
      params:['ParamEye{S}Open','ParamAngleX','ParamAngleY'],
      deformer:'Eye_{S}', mesh:'medium',
      kw:['eyewhite','eye white','eye-white','sclera','whiteeye','shirome','白目','しろめ'] },
    iris:        { label:'Iris',       folder:'Eyes',       order:74,  side:true,
      params:['ParamEyeBallX','ParamEyeBallY','ParamEye{S}Open'],
      deformer:'Eye_{S}_Ball', mesh:'medium',
      kw:['irides','iris','irid','pupil','eyeball','eye ball','kurome','黒目','瞳孔','瞳','ひとみ'] },
    eye_hl:      { label:'Eye Highlight', folder:'Eyes',    order:76,  side:true,
      params:['ParamEyeBallX','ParamEyeBallY','ParamEye{S}Open'],
      deformer:'Eye_{S}_Ball', mesh:'low',
      kw:['eye highlight','highlight','catchlight','catch light','eyeshine','ハイライト','瞳ハイライト','光'] },
    mouth:       { label:'Mouth',      folder:'Mouth',      order:64,  side:false,
      params:['ParamMouthOpenY','ParamMouthForm','ParamAngleX','ParamAngleY'],
      deformer:'Mouth', mesh:'medium',
      kw:['mouth','lips','lip','teeth','tongue','口','くち','唇'] },
    neck:        { label:'Neck',       folder:'Neck',       order:44,  side:false,
      params:['ParamAngleX','ParamAngleY','ParamAngleZ','ParamBodyAngleX'],
      deformer:'Neck', mesh:'medium',
      kw:['neck','首','くび'] },
    neckwear:    { label:'Neckwear',   folder:'Body',       order:42,  side:false,
      params:['ParamBodyAngleX','ParamBodyAngleY','ParamAngleZ','ParamBreath'],
      deformer:'Body', mesh:'medium',
      kw:['neckwear','neck wear','collar','scarf','necktie','tie','choker','necklace','muffler','襟','マフラー','首飾り'] },
    topwear:     { label:'Topwear',    folder:'Body',       order:34,  side:false,
      params:['ParamBodyAngleX','ParamBodyAngleY','ParamBodyAngleZ','ParamBreath'],
      deformer:'Body', mesh:'high',
      kw:['topwear','top wear','shirt','blouse','jacket','coat','hoodie','top','上着','トップス','服'] },
    handwear:    { label:'Arm / Handwear', folder:'Body',   order:33,  side:true,
      params:['ParamArm{S}A','ParamArm{S}B','ParamBodyAngleX'],
      deformer:'Arm_{S}', mesh:'high',
      kw:['handwear','hand wear','sleeve','glove','gauntlet','bracelet','arm','hand','腕','手','袖','手袋'] },
    bottomwear:  { label:'Bottomwear', folder:'Body',       order:30,  side:false,
      params:['ParamBodyAngleX','ParamBodyAngleZ','ParamBreath'],
      deformer:'Body', mesh:'high',
      kw:['bottomwear','bottom wear','skirt','pants','trousers','shorts','bottom','スカート','ズボン','下衣'] },
    legwear:     { label:'Legwear',    folder:'Body',       order:20,  side:false,
      params:['ParamBodyAngleX','ParamLegL','ParamLegR'],
      deformer:'Legs', mesh:'medium',
      kw:['legwear','leg wear','legs','leg','sock','socks','tights','stocking','thigh','脚','足','靴下','タイツ'] },
    footwear:    { label:'Footwear',   folder:'Body',       order:24,  side:false,
      params:['ParamBodyAngleX','ParamLegL','ParamLegR'],
      deformer:'Legs', mesh:'medium',
      kw:['footwear','foot wear','shoe','shoes','boot','boots','sneaker','foot','靴','くつ','シューズ','ブーツ'] },
    body:        { label:'Body',       folder:'Body',       order:32,  side:false,
      params:['ParamBodyAngleX','ParamBodyAngleY','ParamBodyAngleZ','ParamBreath'],
      deformer:'Body', mesh:'high',
      kw:['body','torso','chest','breast','belly','skin body','胴','体','からだ','胸'] },
    accessory:   { label:'Accessory',  folder:'Accessory',  order:128, side:false,
      params:['ParamAngleX','ParamAngleY'],
      deformer:'Accessory', mesh:'low',
      kw:['accessory','wing','wings','tail','prop','item','アクセ','装飾','翼','尻尾'] }
  };

  /* Full Live2D-standard parameter table. Only params referenced by classified
   * parts are emitted into the manifest, but this is the canonical source. */
  var PARAM_DEFS = {
    ParamAngleX:    { name:'Angle X',        group:'Head',  min:-30, max:30,  def:0 },
    ParamAngleY:    { name:'Angle Y',        group:'Head',  min:-30, max:30,  def:0 },
    ParamAngleZ:    { name:'Angle Z',        group:'Head',  min:-30, max:30,  def:0 },
    ParamEyeLOpen:  { name:'Eye Open (L)',   group:'Eyes',  min:0,   max:1,   def:1 },
    ParamEyeROpen:  { name:'Eye Open (R)',   group:'Eyes',  min:0,   max:1,   def:1 },
    ParamEyeLSmile: { name:'Eye Smile (L)',  group:'Eyes',  min:0,   max:1,   def:0 },
    ParamEyeRSmile: { name:'Eye Smile (R)',  group:'Eyes',  min:0,   max:1,   def:0 },
    ParamEyeBallX:  { name:'Eyeball X',      group:'Eyes',  min:-1,  max:1,   def:0 },
    ParamEyeBallY:  { name:'Eyeball Y',      group:'Eyes',  min:-1,  max:1,   def:0 },
    ParamBrowLY:    { name:'Brow Y (L)',     group:'Brows', min:-1,  max:1,   def:0 },
    ParamBrowRY:    { name:'Brow Y (R)',     group:'Brows', min:-1,  max:1,   def:0 },
    ParamBrowLForm: { name:'Brow Form (L)',  group:'Brows', min:-1,  max:1,   def:0 },
    ParamBrowRForm: { name:'Brow Form (R)',  group:'Brows', min:-1,  max:1,   def:0 },
    ParamBrowLAngle:{ name:'Brow Angle (L)', group:'Brows', min:-1,  max:1,   def:0 },
    ParamBrowRAngle:{ name:'Brow Angle (R)', group:'Brows', min:-1,  max:1,   def:0 },
    ParamMouthOpenY:{ name:'Mouth Open',     group:'Mouth', min:0,   max:1,   def:0 },
    ParamMouthForm: { name:'Mouth Form',     group:'Mouth', min:-1,  max:1,   def:0 },
    ParamCheek:     { name:'Cheek',          group:'Face',  min:0,   max:1,   def:0 },
    ParamHairFront: { name:'Hair Front Sway',group:'Hair',  min:-1,  max:1,   def:0 },
    ParamHairSide:  { name:'Hair Side Sway', group:'Hair',  min:-1,  max:1,   def:0 },
    ParamHairBack:  { name:'Hair Back Sway', group:'Hair',  min:-1,  max:1,   def:0 },
    ParamBodyAngleX:{ name:'Body Angle X',   group:'Body',  min:-10, max:10,  def:0 },
    ParamBodyAngleY:{ name:'Body Angle Y',   group:'Body',  min:-10, max:10,  def:0 },
    ParamBodyAngleZ:{ name:'Body Angle Z',   group:'Body',  min:-10, max:10,  def:0 },
    ParamBreath:    { name:'Breath',         group:'Body',  min:0,   max:1,   def:0 },
    ParamArmLA:     { name:'Arm L A',        group:'Body',  min:-1,  max:1,   def:0 },
    ParamArmLB:     { name:'Arm L B',        group:'Body',  min:-1,  max:1,   def:0 },
    ParamArmRA:     { name:'Arm R A',        group:'Body',  min:-1,  max:1,   def:0 },
    ParamArmRB:     { name:'Arm R B',        group:'Body',  min:-1,  max:1,   def:0 },
    ParamLegL:      { name:'Leg L',          group:'Body',  min:-1,  max:1,   def:0 },
    ParamLegR:      { name:'Leg R',          group:'Body',  min:-1,  max:1,   def:0 }
  };

  // Folder stacking order (back -> front). Folders are emitted in this order.
  var FOLDER_ORDER = ['Hair Back','Body','Neck','Face','Mouth','Eyes','Brows','Hair Front','Accessory'];

  /* ---- side detection ---------------------------------------------------- */
  function detectSide(rawName) {
    var n = ' ' + rawName.toLowerCase().replace(/[_\-]/g, ' ') + ' ';
    if (/(^|[ (\[])left([ )\]]|$)/.test(n) || /左/.test(rawName)) return 'L';
    if (/(^|[ (\[])right([ )\]]|$)/.test(n) || /右/.test(rawName)) return 'R';
    var m = rawName.toLowerCase().match(/[ _\-]([lr])(?:[ _\-.)]|$)/);
    if (m) return m[1].toUpperCase();
    return null;
  }

  /* ---- classify one layer ------------------------------------------------ */
  function classify(rawName) {
    var lower = (' ' + rawName.toLowerCase().replace(/[_\-]+/g, ' ') + ' ');
    var best = null, bestLen = 0;
    for (var key in SCHEMA) {
      var rule = SCHEMA[key];
      for (var i = 0; i < rule.kw.length; i++) {
        var kw = rule.kw[i];
        var isLatin = /[a-z0-9]/.test(kw);
        var found = isLatin
          ? (lower.indexOf(' ' + kw + ' ') >= 0 || lower.indexOf(kw) >= 0)
          : (rawName.indexOf(kw) >= 0);
        if (found && kw.length > bestLen) { best = key; bestLen = kw.length; }
      }
    }
    var side = detectSide(rawName);
    if (!best) {
      return { key:null, label:'Unclassified', folder:'Unsorted', order:200,
               side:side, params:[], deformer:null, mesh:'medium', confidence:0 };
    }
    var s = SCHEMA[best];
    var sub = function (arr) {
      if (!side) return arr.filter(function (p) { return p.indexOf('{S}') < 0; });
      return arr.map(function (p) { return p.replace(/\{S\}/g, side); });
    };
    return {
      key: best,
      label: s.label,
      folder: s.folder,
      order: s.order + (side === 'R' ? 0.2 : side === 'L' ? 0.1 : 0),
      side: s.side ? side : null,
      params: sub(s.params),
      deformer: s.deformer ? s.deformer.replace(/\{S\}/g, side || '').replace(/_$/, '') : null,
      mesh: s.mesh,
      confidence: Math.min(1, bestLen / 6)
    };
  }

  /* ---- classify with a forced category (used by manual UI overrides) ---- */
  function classifyAs(key, side) {
    if (!key || key === 'unsorted' || !SCHEMA[key]) {
      return { key:null, label:'Unclassified', folder:'Unsorted', order:200,
               side:side||null, params:[], deformer:null, mesh:'medium', confidence:0, manual:true };
    }
    var s = SCHEMA[key];
    side = s.side ? (side || 'L') : null;
    var sub = function (arr) {
      if (!side) return arr.filter(function (p) { return p.indexOf('{S}') < 0; });
      return arr.map(function (p) { return p.replace(/\{S\}/g, side); });
    };
    return {
      key: key, label: s.label, folder: s.folder,
      order: s.order + (side === 'R' ? 0.2 : side === 'L' ? 0.1 : 0),
      side: s.side ? side : null,
      params: sub(s.params),
      deformer: s.deformer ? s.deformer.replace(/\{S\}/g, side || '').replace(/_$/, '') : null,
      mesh: s.mesh, confidence: 1, manual: true
    };
  }

  /* ---- unique, human readable part name --------------------------------- */
  function partName(cls, taken) {
    var base = cls.label + (cls.side ? ' ' + cls.side : '');
    var name = base, i = 2;
    while (taken[name]) { name = base + ' ' + i; i++; }
    taken[name] = true;
    return name;
  }

  /* ---- build everything from a flat list of {name,bbox} ------------------
   * layers: [{ name, left, top, right, bottom }], in any order.
   * opts.reorder: reorder to canonical draw order (default true)
   * opts.overrides: { index: {key, side} } manual corrections
   * --------------------------------------------------------------------- */
  function analyze(layers, opts) {
    opts = opts || {};
    var reorder = opts.reorder !== false;
    var overrides = opts.overrides || {};
    var taken = {};

    var parts = layers.map(function (l, idx) {
      var ov = overrides[idx];
      var cls = ov ? classifyAs(ov.key, ov.side === undefined ? detectSide(l.name) : ov.side)
                   : classify(l.name);
      return {
        index: idx,
        original: l.name,
        bbox: { left:l.left, top:l.top, right:l.right, bottom:l.bottom },
        pivot: { x: Math.round((l.left + l.right) / 2), y: Math.round((l.top + l.bottom) / 2) },
        cls: cls,
        partName: partName(cls, taken),
        drawOrder: cls.order,
        origStack: idx
      };
    });

    var ordered = parts.slice().sort(function (a, b) {
      if (reorder) return a.drawOrder - b.drawOrder || a.origStack - b.origStack;
      return a.origStack - b.origStack;
    });
    ordered.forEach(function (p, i) { p.finalStack = i; });

    var byFolder = {};
    ordered.forEach(function (p) {
      var f = p.cls.folder;
      (byFolder[f] = byFolder[f] || []).push(p);
    });
    var folderNames = Object.keys(byFolder).sort(function (a, b) {
      var ia = FOLDER_ORDER.indexOf(a), ib = FOLDER_ORDER.indexOf(b);
      if (ia < 0) ia = 100; if (ib < 0) ib = 100;
      return ia - ib;
    });
    var folders = folderNames.map(function (f) { return { name: f, parts: byFolder[f] }; });

    var manifest = buildManifest(ordered, folders, opts);
    return { parts: parts, ordered: ordered, folders: folders, manifest: manifest };
  }

  /* ---- rig manifest ------------------------------------------------------ */
  function buildManifest(ordered, folders, opts) {
    var usedParams = {};
    ordered.forEach(function (p) {
      p.cls.params.forEach(function (pid) { usedParams[pid] = true; });
    });
    ['ParamAngleX','ParamAngleY','ParamAngleZ'].forEach(function (pid) {
      if (ordered.some(function (p) { return p.cls.folder === 'Face' || p.cls.key === 'mouth'; }))
        usedParams[pid] = true;
    });
    var parameters = Object.keys(usedParams).map(function (pid) {
      var d = PARAM_DEFS[pid] || { name: pid, group:'Misc', min:-1, max:1, def:0 };
      return { id: pid, name: d.name, group: d.group, min: d.min, max: d.max, default: d.def };
    });

    var defMap = {};
    ordered.forEach(function (p) {
      if (!p.cls.deformer) return;
      (defMap[p.cls.deformer] = defMap[p.cls.deformer] || []).push(p.partName);
    });
    var deformers = Object.keys(defMap).map(function (id) {
      return {
        id: id,
        type: /Ball|Eye_|Face|Body|Hair|Neck|Arm|Leg/.test(id) ? 'warp' : 'rotation',
        parent: parentDeformer(id),
        affects: defMap[id],
        parameters: deformerParams(id, parameters)
      };
    });

    var physics = [];
    if (ordered.some(function (p){return p.cls.key==='hair_front';}))
      physics.push({ group:'Hair Front', input:['ParamAngleX','ParamAngleZ'], output:['ParamHairFront'] });
    if (ordered.some(function (p){return p.cls.key==='hair_side';}))
      physics.push({ group:'Hair Side', input:['ParamAngleX','ParamAngleZ'], output:['ParamHairSide'] });
    if (ordered.some(function (p){return p.cls.key==='hair_back';}))
      physics.push({ group:'Hair Back', input:['ParamAngleX','ParamAngleY','ParamAngleZ'], output:['ParamHairBack'] });

    return {
      meta: {
        generator: 'Live2D Auto-Rigger',
        version: '1.0',
        generatedAt: new Date().toISOString(),
        canvas: opts.canvas || null,
        partCount: ordered.length,
        note: 'The .moc3 binary is proprietary to Live2D Cubism Editor and cannot be ' +
              'generated outside it. Import the cleaned PSD, then follow this manifest ' +
              '(parameters, deformers, bindings, draw order) to finish rigging.'
      },
      parameters: parameters,
      deformerTree: deformers,
      parts: ordered.map(function (p) {
        return {
          id: p.partName,
          folder: p.cls.folder,
          category: p.cls.key || 'unsorted',
          side: p.cls.side,
          original: p.original,
          drawOrder: p.finalStack,
          bbox: p.bbox,
          pivot: p.pivot,
          deformer: p.cls.deformer,
          bind: p.cls.params,
          meshDensity: p.cls.mesh,
          confidence: +p.cls.confidence.toFixed(2)
        };
      }),
      drawOrder: ordered.map(function (p) { return p.partName; }),
      physics: physics
    };
  }

  function parentDeformer(id) {
    if (/^Eye_[LR]_Ball$/.test(id)) return id.replace('_Ball', '');
    if (/^Eye_[LR]$/.test(id)) return 'Face';
    if (id === 'Brow_L' || id === 'Brow_R' || id === 'Mouth' || id === 'Ear_L' ||
        id === 'Ear_R' || id === 'Hair_Front' || id === 'Hair_Side' || id === 'Head_Accessory') return 'Face';
    if (id === 'Face' || id === 'Hair_Back') return 'Neck';
    if (id === 'Neck') return 'Body';
    if (/^Arm_[LR]$/.test(id) || id === 'Legs') return 'Body';
    return null;
  }
  function deformerParams(id, parameters) {
    var ids = parameters.map(function (p){return p.id;});
    var inSet = function(p){ return ids.indexOf(p)>=0; };
    if (/Eye_[LR]_Ball/.test(id)) return ['ParamEyeBallX','ParamEyeBallY'].filter(inSet);
    if (/Eye_[LR]/.test(id))      return [id.indexOf('L')>=0?'ParamEyeLOpen':'ParamEyeROpen'].filter(inSet);
    if (id==='Face')              return ['ParamAngleX','ParamAngleY','ParamAngleZ'].filter(inSet);
    if (id==='Neck'||id==='Body') return ['ParamBodyAngleX','ParamBodyAngleY','ParamBodyAngleZ'].filter(inSet);
    if (id==='Mouth')             return ['ParamMouthOpenY','ParamMouthForm'].filter(inSet);
    return [];
  }

  /* ---- markdown rig plan ------------------------------------------------- */
  function buildPlan(result, sourceName) {
    var m = result.manifest;
    var L = [];
    L.push('# Live2D Rig Plan — ' + (sourceName || 'character'));
    L.push('');
    L.push('_Generated by Live2D Auto-Rigger on ' + new Date().toISOString().slice(0,10) + '._');
    L.push('');
    L.push('Canvas: ' + (m.meta.canvas ? m.meta.canvas.width + ' x ' + m.meta.canvas.height : 'n/a') +
           ' - Parts detected: ' + m.meta.partCount);
    L.push('');
    L.push('> ' + m.meta.note);
    L.push('');
    L.push('## 1. Import the cleaned PSD');
    L.push('');
    L.push('Open Cubism Editor, then File > Import > Photoshop file (.psd), and select the ' +
           '`*_rigged.psd` produced by the tool. Layers are already grouped into Cubism ' +
           'Parts and stacked in the correct draw order below.');
    L.push('');
    L.push('## 2. Draw order (back to front)');
    L.push('');
    m.drawOrder.forEach(function (n, i) { L.push((i+1) + '. ' + n); });
    L.push('');
    L.push('## 3. Parameters to create');
    L.push('');
    L.push('| Parameter | ID | Range | Default | Group |');
    L.push('|---|---|---|---|---|');
    m.parameters.forEach(function (p) {
      L.push('| ' + p.name + ' | `' + p.id + '` | ' + p.min + ' ... ' + p.max + ' | ' + p.default + ' | ' + p.group + ' |');
    });
    L.push('');
    L.push('## 4. Deformer hierarchy');
    L.push('');
    m.deformerTree.forEach(function (d) {
      L.push('- **' + d.id + '** (' + d.type + ')' +
             (d.parent ? ' inside ' + d.parent : '') +
             (d.parameters.length ? ' - driven by ' + d.parameters.join(', ') : '') +
             '  \n  affects: ' + d.affects.join(', '));
    });
    L.push('');
    L.push('## 5. Part bindings & mesh');
    L.push('');
    L.push('| Part | Bind to parameters | Mesh | Pivot |');
    L.push('|---|---|---|---|');
    m.parts.forEach(function (p) {
      L.push('| ' + p.id + ' | ' + (p.bind.length ? p.bind.map(function(x){return '`'+x+'`';}).join(', ') : '-') +
             ' | ' + p.meshDensity + ' | ' + p.pivot.x + ',' + p.pivot.y + ' |');
    });
    L.push('');
    if (m.physics.length) {
      L.push('## 6. Physics groups (Modeling > Physics)');
      L.push('');
      m.physics.forEach(function (ph) {
        L.push('- **' + ph.group + '**: input ' + ph.input.join(', ') + ' -> output ' + ph.output.join(', '));
      });
      L.push('');
    }
    L.push('## 7. Suggested rigging order');
    L.push('');
    var steps = [
      'Set draw order and create all parameters listed above.',
      'Auto-mesh every ArtMesh (Modeling > Mesh > Auto). Use higher density on hair, face and clothing.',
      'Build the deformer hierarchy in section 4 (rotation deformer for Face/Neck/Body, warp deformers nested inside).',
      'Eye blink: bind eyelash / eye-white / iris to ParamEye_Open per side (closed at 0, open at 1).',
      'Eye look: bind iris and highlight to ParamEyeBallX/Y through the Eye_*_Ball warp.',
      'Mouth: bind to ParamMouthOpenY (open) and ParamMouthForm (smile/frown).',
      'Brows: bind to ParamBrow*Y and ParamBrow*Form.',
      'Head XYZ: rotate the Face deformer on ParamAngleX/Y/Z; add depth offset for a natural turn.',
      'Body: ParamBodyAngleX/Y/Z on the Body deformer; add ParamBreath as a slow idle.',
      'Add physics from section 6 for hair and accessory secondary motion.'
    ];
    steps.forEach(function (s, i) { L.push((i+1) + '. ' + s); });
    L.push('');
    return L.join('\n');
  }

  /* ---- apply a learned character profile (extends the classifier) -------- */
  function applyProfile(profile) {
    if (!profile) return;
    (profile.parts || []).forEach(function (p) {
      SCHEMA[p.key] = { label:p.label, folder:p.folder, order:p.order, side:!!p.side,
        params:p.params || [], deformer:p.deformer || null, mesh:p.mesh || 'medium', kw:p.kw || [] };
    });
    var syn = profile.synonyms || {};
    for (var k in syn) { if (SCHEMA[k]) SCHEMA[k].kw = SCHEMA[k].kw.concat(syn[k]); }
    if (profile.folderOrder && profile.folderOrder.length) {
      FOLDER_ORDER.length = 0;
      profile.folderOrder.forEach(function (f) { FOLDER_ORDER.push(f); });
    }
    API.profile = profile;
  }

  var API = { SCHEMA:SCHEMA, PARAM_DEFS:PARAM_DEFS, FOLDER_ORDER:FOLDER_ORDER, detectSide:detectSide,
              classify:classify, classifyAs:classifyAs, analyze:analyze, applyProfile:applyProfile,
              buildManifest:buildManifest, buildPlan:buildPlan, profile:null };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else root.RigCore = API;
})(typeof window !== 'undefined' ? window : this);

/* ============================================================================
 * alpecca.profile.js  —  Character profile "learned" from Alpecca's master art
 * ----------------------------------------------------------------------------
 * Distilled from the Alpecca master/Live2D reference sheets (layer & deformer
 * guide, hair/eye breakdowns, expression sheets, action & movement library).
 * The auto-rigger consumes this to (a) recognise Alpecca's specific layer
 * vocabulary, (b) stack parts in the documented draw order, and (c) load the
 * documented expression + action-pose libraries into Pose mode.
 *
 * Extensible / "recursive": add more reference sheets -> extend this profile
 * (more parts, synonyms, expressions, poses) and the rig improves with it.
 * ==========================================================================*/
window.ALPECCA_PROFILE = {
  meta: {
    name: 'Alpecca',
    role: 'Local Companion / desktop AI assistant',
    tagline: 'Your Local Companion. Always here with you.',
    source: 'Alpecca master art sheets (Live2D layer/deformer guide, hair & eye breakdowns, expression sheet, action & movement library)',
    palette: { primary:'#f4f6fb', accent:'#5b8cff', glowUV:'#9ad1ff', detail:'#2b2f3a' }
  },

  /* New canonical part types specific to Alpecca (merged into the classifier).
   * order = back->front draw order; folder must be one of the rig folders.    */
  parts: [
    { key:'ahoge',           label:'Ahoge',            folder:'Hair Front', order:122, side:false,
      params:['ParamHairFront','ParamAngleX','ParamAngleZ'], deformer:'Hair_Ahoge', mesh:'high',
      kw:['ahoge','antenna hair','cowlick','アホ毛'] },
    { key:'top_hair',        label:'Top Hair',         folder:'Hair Front', order:119, side:false,
      params:['ParamHairFront','ParamAngleX','ParamAngleY'], deformer:'Hair_Front', mesh:'high',
      kw:['top hair','tophair','crown hair'] },
    { key:'hair_clip',       label:'Hair Clip',        folder:'Accessory',  order:133, side:false,
      params:['ParamAngleX','ParamAngleY','ParamAngleZ'], deformer:'Head_Accessory', mesh:'low',
      kw:['hair clip','hairclip','hairpin','clip','barrette'] },
    { key:'back_hair_upper', label:'Back Hair Upper',  folder:'Hair Back',  order:11, side:false,
      params:['ParamHairBack','ParamAngleX','ParamAngleY','ParamAngleZ'], deformer:'Hair_Back', mesh:'high',
      kw:['back hair upper','upper back hair','back hair (upper)'] },
    { key:'back_hair_lower', label:'Back Hair Lower',  folder:'Hair Back',  order:9, side:false,
      params:['ParamHairBack','ParamAngleX','ParamAngleY'], deformer:'Hair_Back', mesh:'high',
      kw:['back hair lower','lower back hair','back hair (lower)'] },
    { key:'inner_hair',      label:'Inner Hair',       folder:'Hair Back',  order:8, side:false,
      params:['ParamHairBack','ParamAngleX'], deformer:'Hair_Back', mesh:'medium',
      kw:['inner hair','inner back hair','hair inner'] },
    { key:'hood',            label:'Hood',             folder:'Body',       order:36, side:false,
      params:['ParamBodyAngleX','ParamBodyAngleY','ParamBodyAngleZ','ParamBreath'], deformer:'Body', mesh:'high',
      kw:['hood','jacket hood'] },
    { key:'jacket_back',     label:'Jacket (Back)',    folder:'Body',       order:12, side:false,
      params:['ParamBodyAngleX','ParamBodyAngleZ','ParamBreath'], deformer:'Body', mesh:'high',
      kw:['jacket back','jacket (back)','back jacket','coat back'] },
    { key:'lanyard',         label:'Lanyard & Card',   folder:'Body',       order:41, side:false,
      params:['ParamBodyAngleX','ParamBodyAngleY','ParamBreath'], deformer:'Lanyard', mesh:'medium',
      kw:['lanyard','id card','id badge','card','badge','neck card','staff pass'] },
    { key:'thigh_strap',     label:'Thigh Strap',      folder:'Body',       order:26, side:true,
      params:['ParamLeg{S}','ParamBodyAngleX'], deformer:'Leg_{S}', mesh:'low',
      kw:['thigh strap','garter','leg strap','thigh band'] },
    { key:'stockings',       label:'Stockings',        folder:'Body',       order:22, side:false,
      params:['ParamBodyAngleX','ParamLegL','ParamLegR'], deformer:'Legs', mesh:'medium',
      kw:['stocking','stockings','thighhigh','thigh high','thigh-high','knee high'] },
    { key:'socks',           label:'Socks',            folder:'Body',       order:16, side:false,
      params:['ParamLegL','ParamLegR'], deformer:'Legs', mesh:'low',
      kw:['socks','sock','socks under','under socks'] }
  ],

  /* Extra keywords for existing part types (Alpecca's layer naming). */
  synonyms: {
    hair_front: ['front bangs','bangs','front fringe'],
    hair_side:  ['side hair l','side hair r','side hair'],
    iris:       ['iris top','iris base','iris'],
    eye_hl:     ['highlight 1','highlight 2','main highlight','secondary highlight','catch light','catchlight','eye shine'],
    eyelash:    ['upper lid','upper eyelid','lashes','bottom lid','lower lid','eyelid'],
    eyewhite:   ['eye white','sclera'],
    cheek:      ['blush shade','blush'],
    mouth:      ['lips','lip'],
    topwear:    ['jacket','jacket front','jacket (front)','coat','hoodie'],
    bottomwear: ['shorts','short pants'],
    footwear:   ['shoes','sneakers','boots'],
    neck:       ['neck'],
    pupil:      []
  },

  /* documented draw order folders, back -> front (matches sheet 09 layer order) */
  folderOrder: ['Hair Back','Body','Neck','Face','Mouth','Eyes','Brows','Hair Front','Accessory'],

  /* physics groups recommended on the sheets */
  physics: [
    { group:'Ahoge',        input:['ParamAngleX','ParamAngleZ'], output:['ParamHairFront'] },
    { group:'Hair Back',    input:['ParamAngleX','ParamAngleY','ParamAngleZ'], output:['ParamHairBack'] },
    { group:'Lanyard & Card', input:['ParamBodyAngleX','ParamBodyAngleZ'], output:['ParamBodyAngleX'] },
    { group:'Jacket',       input:['ParamBodyAngleX','ParamBodyAngleY'], output:['ParamBreath'] },
    { group:'Thigh Strap',  input:['ParamLegL','ParamLegR'], output:['ParamLegL'] }
  ],

  /* Expression library (face params), from the expression reference sheets. */
  expressions: {
    'Warm Smile':   { ParamMouthForm:0.7, ParamMouthOpenY:0.12, ParamEyeLSmile:0.45, ParamEyeRSmile:0.45,
                      ParamEyeLOpen:0.85, ParamEyeROpen:0.85, ParamBrowLY:0.12, ParamBrowRY:0.12 },
    'Happy':        { ParamMouthForm:0.85, ParamMouthOpenY:0.28, ParamEyeLSmile:0.65, ParamEyeRSmile:0.65,
                      ParamEyeLOpen:0.78, ParamEyeROpen:0.78, ParamBrowLY:0.2, ParamBrowRY:0.2 },
    'Curious':      { ParamBrowLY:0.45, ParamBrowRY:0.12, ParamAngleZ:6, ParamEyeBallX:0.25,
                      ParamMouthForm:0.2, ParamMouthOpenY:0.16, ParamEyeLOpen:1, ParamEyeROpen:1 },
    'Thinking':     { ParamEyeBallX:0.35, ParamEyeBallY:0.35, ParamBrowLForm:-0.25, ParamBrowLY:-0.1,
                      ParamMouthForm:-0.1, ParamEyeLOpen:0.8, ParamEyeROpen:0.8 },
    'Concerned':    { ParamBrowLForm:0.5, ParamBrowRForm:0.5, ParamBrowLY:0.28, ParamBrowRY:0.28,
                      ParamMouthForm:-0.3, ParamEyeLOpen:0.9, ParamEyeROpen:0.9 },
    'Compassionate':{ ParamBrowLForm:0.4, ParamBrowRForm:0.4, ParamBrowLY:0.2, ParamBrowRY:0.2,
                      ParamMouthForm:0.3, ParamEyeLSmile:0.3, ParamEyeRSmile:0.3, ParamEyeLOpen:0.8, ParamEyeROpen:0.8 },
    'Playful':      { ParamEyeLOpen:0, ParamEyeLSmile:1, ParamEyeROpen:1, ParamMouthForm:0.6, ParamMouthOpenY:0.2,
                      ParamBrowLY:0.1, ParamBrowRY:0.1 },
    'Gentle':       { ParamEyeLOpen:0.7, ParamEyeROpen:0.7, ParamEyeLSmile:0.3, ParamEyeRSmile:0.3,
                      ParamMouthForm:0.4, ParamBrowLY:0.1, ParamBrowRY:0.1 },
    'Soft Sadness': { ParamBrowLForm:0.7, ParamBrowRForm:0.7, ParamBrowLY:0.3, ParamBrowRY:0.3,
                      ParamMouthForm:-0.5, ParamEyeLOpen:0.65, ParamEyeROpen:0.65, ParamEyeBallY:-0.2 },
    'Focus':        { ParamBrowLForm:-0.3, ParamBrowRForm:-0.3, ParamBrowLY:-0.2, ParamBrowRY:-0.2,
                      ParamMouthForm:-0.1, ParamEyeLOpen:1, ParamEyeROpen:1 },
    'Serious':      { ParamBrowLForm:-0.5, ParamBrowRForm:-0.5, ParamBrowLY:-0.3, ParamBrowRY:-0.3,
                      ParamMouthForm:-0.2, ParamEyeLOpen:0.95, ParamEyeROpen:0.95 },
    'Surprised':    { ParamBrowLY:0.9, ParamBrowRY:0.9, ParamMouthOpenY:0.7, ParamEyeLOpen:1, ParamEyeROpen:1 }
  },

  /* Action / movement library (full-body params), from the action sheets.
   * Limb sign directions are best-effort and can be tuned with the sliders.   */
  poses: {
    /* arms rest DOWN from the T-pose source (negative Raise = down for both sides);
       gestures raise one arm and/or bring the hand in front of the jacket. */
    'Neutral Standing':   { ParamArmLA:-0.95, ParamArmRA:-0.95, ParamArmLB:0.12, ParamArmRB:0.12 },
    'Arms Down (rest)':   { ParamArmLA:-1, ParamArmRA:-1 },
    'Attentive Listening':{ ParamArmLA:-0.92, ParamArmRA:-0.92, ParamArmLB:0.15, ParamArmRB:0.15,
                            ParamAngleZ:6, ParamAngleX:4, ParamEyeBallX:0.2 },
    'Observing':          { ParamArmLA:-0.95, ParamArmRA:-0.9, ParamAngleX:10, ParamAngleY:3, ParamEyeBallX:0.4 },
    'Present Information': { ParamArmLA:-0.95, ParamArmRA:-0.55, ParamArmRB:0.5, handFrontR:true,
                            ParamAngleX:-5, ParamEyeBallX:-0.2 },
    'Explain / Teach':    { ParamArmLA:-0.9, ParamArmRA:-0.2, ParamArmRB:0.55, handFrontR:true, ParamAngleZ:-4 },
    'Thinking':           { ParamArmLA:-0.9, ParamArmRA:0.05, ParamArmRB:0.95, handFrontR:true,
                            ParamAngleZ:6, ParamEyeBallY:0.3, ParamEyeBallX:0.25, ParamBrowLForm:-0.2 },
    'Reading / Review':   { ParamArmLA:-0.6, ParamArmRA:-0.6, ParamArmLB:0.6, ParamArmRB:0.6,
                            handFrontL:true, handFrontR:true, ParamAngleY:-8, ParamEyeBallY:-0.4 },
    'Compassion':         { ParamArmLA:-0.85, ParamArmRA:-0.7, ParamArmRB:0.35, handFrontR:true,
                            ParamAngleZ:5, ParamAngleX:3 },
    'Celebrate Success':  { ParamArmLA:0.9, ParamArmRA:0.9, ParamArmLB:0.2, ParamArmRB:0.2,
                            ParamMouthOpenY:0.6, ParamMouthForm:0.6, ParamEyeLSmile:0.8, ParamEyeRSmile:0.8 },
    'Gentle Laugh':       { ParamArmLA:-0.9, ParamArmRA:-0.1, ParamArmRB:0.85, handFrontR:true,
                            ParamAngleY:4, ParamAngleZ:4, ParamMouthOpenY:0.5, ParamMouthForm:0.6,
                            ParamEyeLSmile:0.7, ParamEyeRSmile:0.7 },
    'Wave':               { ParamArmLA:-0.95, ParamArmRA:0.8, ParamArmRB:0.35,
                            ParamMouthForm:0.5, ParamEyeLSmile:0.4, ParamEyeRSmile:0.4 },
    'Warning':            { ParamArmLA:-0.9, ParamArmRA:0.75, ParamArmRB:0.1,
                            ParamBrowLForm:-0.4, ParamBrowRForm:-0.4 },
    'Guard / Protect':    { ParamArmLA:-0.25, ParamArmLB:0.95, ParamArmRA:-0.25, ParamArmRB:0.95,
                            handFrontL:true, handFrontR:true, ParamAngleX:-4 }
  }
};

// auto-apply to the classifier if it is already present
if (window.RigCore && window.RigCore.applyProfile) window.RigCore.applyProfile(window.ALPECCA_PROFILE);

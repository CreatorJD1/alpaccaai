/* Alpecca's VRM embodiment inside the House HQ scene.
 *
 * Ports the working /vrm page driver (web/vrm.html), her mood mapping
 * (alpecca/vrm.py), and the studio's animation library (apps/vcs
 * frontend/src/lib/vrmAnimations.js: walk/run/jump locomotion + the per-clip
 * expression profiles) into a self-contained module: the caller owns the
 * scene and the sprite state machine; this module only wears the body. Real
 * VRoid motion clips (.vrma) drive her when available -- the procedural clips
 * below are the always-there fallback, and locomotion is procedural-only
 * (no walking .vrma exists). The heavy deps (GLTFLoader, @pixiv/three-vrm,
 * three-vrm-animation) are dynamically imported inside activate() so Vite
 * code-splits them and the default bundle is unchanged.
 */
import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { VRMAnimation } from "@pixiv/three-vrm-animation";

export type EmbodimentStatus = "idle" | "loading" | "active" | "failed";

export interface VrmEmbodimentDeps {
  parent: THREE.Group;
  targetHeight: number;
  groundClearance: number;
  manifestUrl: () => string;
  modelUrl: (file: string) => string;
  animationUrl?: (fileName: string) => string;   // absent -> procedural clips only
  onStatus: (status: EmbodimentStatus, detail?: string, progress?: number) => void;
}

export interface VrmEmbodiment {
  readonly status: EmbodimentStatus;
  activate(): Promise<boolean>;
  deactivate(): void;
  dispose(): void;
  setMood(label: string, dims: { love?: number; compassion?: number; fear?: number; energy?: number }): void;
  setSpriteState(name: string, moving: boolean, talking: boolean): void;
  update(dt: number, camera: THREE.Camera, engaged: boolean, distanceToPlayer?: number): void;
  debug(): { groundBase: number; groundOffset: number; lowestSoleY: number | null };
}

type MoodDims = { love: number; compassion: number; fear: number; energy: number };

const c01 = (v: number): number => Math.max(0, Math.min(1, v));

// Ported verbatim from alpecca/vrm.py MOOD_CLIPS -- every mood label the mood
// model can produce gets a clip, so her whole emotional range is embodied.
const MOOD_CLIPS: Record<string, string> = {
  sleepy: "sleep",
  anxious: "cry",
  worried: "thinking",
  tender: "idle_soft",
  joyful: "cheer",
  affectionate: "wave",
  playful: "dance",
  content: "idle",
  withdrawn: "idle_soft",
  lonely: "sit",
};

// alpecca/vrm.py _TALK_EMOTIONS: her mood folded onto the talking clip's
// emotion-overlay vocabulary. Never "angry" -- she has no anger dimension.
const TALK_EMOTIONS: Record<string, string> = {
  joyful: "happy",
  affectionate: "happy",
  playful: "happy",
  lonely: "sad",
  withdrawn: "sad",
  anxious: "surprised",
  worried: "surprised",
  tender: "relaxed",
  content: "relaxed",
  sleepy: "relaxed",
};

// Internal clip id -> real VRoid motion clip served at /assets/vrma/. This is
// VCS's approved ALPECCA_MOOD_VRMA table (VRMViewer.jsx) with two changes:
// wave plays "Hello" here (a player greeting), not "Goodbye", and point plays
// the new "PeaceSign". Locomotion (walk/run/jump) is intentionally absent --
// no such .vrma exists, the procedural cycles carry it.
const CLIP_VRMA: Record<string, string> = {
  sleep: "Sleepy",
  cry: "Sad",
  thinking: "Thinking",
  idle_soft: "Relax",
  cheer: "Clapping",
  wave: "Hello",
  dance: "Jump",
  idle: "LookAround",
  sit: "Relax",
  talking: "LookAround",
  point: "PeaceSign",
};

// vrmAnimations.js CLIP_EXPRESSIONS: each clip's facial profile, layered
// atLeast (max) over the mood-lerped weights every frame. A "blink" entry
// means the clip HOLDS the eyes closed, which also suppresses auto-blink
// (clipHoldsEyesClosed). "point" borrows VCS's peace-sign profile.
const CLIP_EXPRESSIONS: Record<string, Record<string, number>> = {
  idle: { relaxed: 0.2 },
  idle_soft: { relaxed: 0.35 },
  wave: { happy: 0.7 },
  cheer: { happy: 1.0 },
  thinking: { relaxed: 0.15 },
  talking: {},
  cry: { sad: 1.0 },
  sleep: { relaxed: 0.7, blink: 1.0 },
  dance: { happy: 0.85 },
  walk: { relaxed: 0.2 },
  run: { surprised: 0.25 },
  jump: { happy: 0.6 },
  sit: { relaxed: 0.35 },
  point: { happy: 0.85 },
};

// vrmAnimations.js clipHoldsEyesClosed: whether the active clip holds blink.
function clipHoldsEyesClosed(clip: string): boolean {
  const e = CLIP_EXPRESSIONS[clip];
  return !!(e && "blink" in e);
}

// alpecca/vrm.py expressions_for_state: slow mood-driven preset weights.
// "angry" is hard-pinned 0.0 -- the face is a readout, not a costume.
function expressionsForState(d: MoodDims): Record<string, number> {
  const { love, compassion: care, fear, energy } = d;
  return {
    happy: c01(love * 1.2 - fear * 0.6),
    sad: c01((0.35 - love) * 2.2 + (0.25 - energy) * 0.8),
    surprised: c01((fear - 0.45) * 2.5),
    relaxed: c01(care * 0.5 + (0.6 - fear) * 0.4 + (0.4 - energy) * 0.3),
    angry: 0.0,
  };
}

const BONES: readonly VRMHumanBoneName[] = [
  "leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm",
  "leftHand", "rightHand", "chest", "upperChest", "head", "neck", "spine", "hips",
  "leftUpperLeg", "rightUpperLeg", "leftLowerLeg", "rightLowerLeg",
];

const MOUTH = ["aa", "ih", "ou", "ee", "oh"] as const;

const LOAD_WATCHDOG_MS = 45_000;
const MEASURE_SAMPLES = 1200;
const VRMA_FADE = 0.35;        // crossfade between mixer actions, like VCS
const NOTICE_DISTANCE = 4.5;   // she notices you approaching inside this range

// vrmIK.js: the bone origin isn't the sole -- ankles sit ~7 cm above it, toe
// bones ~2 cm. Model-space metres; scaled by the wrapper's world scale when
// measuring in world space.
const SOLE_OFFSET: Partial<Record<VRMHumanBoneName, number>> = {
  leftFoot: 0.07, rightFoot: 0.07, leftToes: 0.02, rightToes: 0.02,
};
const SOLE_BONES = Object.keys(SOLE_OFFSET) as VRMHumanBoneName[];

function withWatchdog<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(what)), ms);
    p.then(
      (v) => { clearTimeout(timer); resolve(v); },
      (e) => { clearTimeout(timer); reject(e); },
    );
  });
}

export function createVrmEmbodiment(deps: VrmEmbodimentDeps): VrmEmbodiment {
  let status: EmbodimentStatus = "idle";
  let vrm: VRM | null = null;
  let wrapper: THREE.Group | null = null;
  let axisFlip: 1 | -1 = 1;
  let deepDispose: ((obj: THREE.Object3D) => void) | null = null;
  let loadPromise: Promise<boolean> | null = null;

  // Lazy module handles captured at activate() so background .vrma fetches
  // don't re-import (and stay code-split with the model loader).
  let GLTFLoaderCtor: typeof import("three/examples/jsm/loaders/GLTFLoader.js").GLTFLoader | null = null;
  let vrmaLib: typeof import("@pixiv/three-vrm-animation") | null = null;

  let moodLabel = "content";
  const dims: MoodDims = { love: 0.5, compassion: 0.5, fear: 0.2, energy: 0.5 };
  let exprTarget: Record<string, number> = expressionsForState(dims);
  const exprNow: Record<string, number> = {};

  let spriteName = "";
  let spriteMoving = false;
  let spriteTalking = false;

  let clipName = "idle";
  let clipTime = 0;   // restarts when the resolved clip changes (fresh cycle)
  let elapsed = 0;    // monotonic while active; drives the blink cycle

  // .vrma playback: one persistent mixer, clips cached per motion name.
  let mixer: THREE.AnimationMixer | null = null;
  let currentAction: THREE.AnimationAction | null = null;
  let currentVrmaName: string | null = null;
  const vrmaClips = new Map<string, THREE.AnimationClip>();
  const vrmaLoading = new Set<string>();
  const vrmaFailed = new Set<string>();   // never refetched; procedural covers them
  const fading: THREE.AnimationAction[] = [];

  const bone = (n: VRMHumanBoneName): THREE.Object3D | null =>
    vrm ? vrm.humanoid.getNormalizedBoneNode(n) : null;

  function setExpr(name: string, v: number, atLeast = false): void {
    const em = vrm?.expressionManager;
    if (!em) return;
    const cur = em.getValue(name);
    if (cur == null) return;
    em.setValue(name, atLeast ? Math.max(cur, v) : v);
  }

  /* ---- the studio's clip engine (ported from web/vrm.html) ---- */

  function relaxArms(): void {
    // Signs are in the VRM 1.0 frame: +z RAISES her left arm, so resting
    // arms need the negatives. 0.x models get x/z negated after the clip.
    const l = bone("leftUpperArm"); if (l) l.rotation.z = -1.2;
    const r = bone("rightUpperArm"); if (r) r.rotation.z = 1.2;
  }
  function idle(t: number): void {
    const chest = bone("chest") ?? bone("upperChest");
    const head = bone("head");
    const spine = bone("spine");
    const breath = Math.sin(t * 1.4) * 0.03, sway = Math.sin(t * 0.6) * 0.03;
    if (chest) { chest.rotation.x += breath; chest.rotation.z += sway * 0.3; }
    if (spine) spine.rotation.z += sway * 0.15;
    if (head) { head.rotation.y += Math.sin(t * 0.5) * 0.08; head.rotation.x += Math.sin(t * 0.7) * 0.03; }
    const lh = bone("leftHand"), rh = bone("rightHand");
    if (lh) lh.rotation.z = Math.sin(t * 0.8) * 0.05;
    if (rh) rh.rotation.z = -Math.sin(t * 0.8) * 0.05;
  }
  function idleSoft(t: number): void {
    idle(t * 0.6);
    const hips = bone("hips"); if (hips) hips.rotation.y = Math.sin(t * 0.35) * 0.04;
  }
  function wave(t: number): void {
    idle(t * 0.7);
    const u = bone("rightUpperArm"), l = bone("rightLowerArm"), h = bone("rightHand");
    if (u) { u.rotation.z = -1.5; u.rotation.x = -0.6; }
    if (l) l.rotation.z = -0.4 + Math.sin(t * 6) * 0.4;
    if (h) h.rotation.z = Math.sin(t * 6) * 0.3;
  }
  function cheer(t: number): void {
    // +-2.2 puts both hands up-overhead (+-3.0 overshoots half a turn).
    const lu = bone("leftUpperArm"), ru = bone("rightUpperArm");
    const ll = bone("leftLowerArm"), rl = bone("rightLowerArm");
    const chest = bone("chest") ?? bone("upperChest"), head = bone("head");
    const beat = Math.sin(t * 5);
    if (lu) lu.rotation.z = 2.2 + Math.abs(beat) * 0.15;
    if (ru) ru.rotation.z = -2.2 - Math.abs(beat) * 0.15;
    if (ll) ll.rotation.z = 0.3 + beat * 0.15;
    if (rl) rl.rotation.z = -0.3 - beat * 0.15;
    if (chest) chest.rotation.x = beat * 0.05;
    if (head) head.rotation.x = -beat * 0.08;
  }
  function thinking(t: number): void {
    // Elbow folds live in the frontal plane -- folding around x on a sideways
    // arm is a twist, so the hand would never reach her chin.
    idle(t * 0.4);
    const ru = bone("rightUpperArm"), rl = bone("rightLowerArm"), rh = bone("rightHand");
    const head = bone("head"), chest = bone("chest") ?? bone("upperChest");
    if (ru) { ru.rotation.z = 0.9; ru.rotation.y = 0.25; }
    if (rl) { rl.rotation.z = -2.5; rl.rotation.y = 0.5; }
    if (rh) rh.rotation.z = -0.5;
    if (head) { head.rotation.z = -0.15; head.rotation.x = 0.08; head.rotation.y = Math.sin(t * 0.5) * 0.1; }
    if (chest) chest.rotation.z = 0.05;
  }
  function dance(t: number): void {
    const chest = bone("chest") ?? bone("upperChest"), spine = bone("spine");
    const hips = bone("hips"), head = bone("head");
    const lu = bone("leftUpperArm"), ru = bone("rightUpperArm");
    const ll = bone("leftLowerArm"), rl = bone("rightLowerArm");
    const beat = t * 3, sway = Math.sin(beat) * 0.35, bounce = Math.sin(beat * 2) * 0.15;
    if (hips) {
      hips.rotation.z = sway * 0.4; hips.rotation.y = Math.sin(beat * 0.5) * 0.2;
      hips.position.y = -Math.abs(Math.sin(beat)) * 0.06;
    }
    if (spine) spine.rotation.z = -sway * 0.3;
    if (chest) chest.rotation.z = -sway * 0.2;
    if (head) head.rotation.y = Math.sin(beat * 0.5) * 0.3;
    if (lu) lu.rotation.z = 1.0 + sway * 0.6;
    if (ru) ru.rotation.z = -1.0 - sway * 0.6;
    if (ll) ll.rotation.x = -1.0 - bounce;
    if (rl) rl.rotation.x = -1.0 + bounce;
  }
  function sit(t: number): void {
    const spine = bone("spine"), hips = bone("hips");
    for (const n of ["leftUpperLeg", "rightUpperLeg", "leftLowerLeg", "rightLowerLeg"] as const) {
      const b = bone(n); if (b) b.rotation.x = -1.5;
    }
    if (spine) spine.rotation.x = 0.05 + Math.sin(t * 1.2) * 0.02;
    if (hips) hips.position.y = -0.35;
  }
  function sleep(t: number): void {
    sit(t);
    const spine = bone("spine"), chest = bone("chest") ?? bone("upperChest"), head = bone("head");
    const lu = bone("leftUpperArm"), ru = bone("rightUpperArm");
    const breath = Math.sin(t * 1.0) * 0.04;
    if (spine) spine.rotation.x = 0.15;
    if (chest) chest.rotation.x = 0.1 + breath;
    if (head) { head.rotation.x = 0.2; head.rotation.z = 0.4; }
    if (lu) { lu.rotation.z = -1.4; lu.rotation.x = -0.15; }
    if (ru) { ru.rotation.z = 1.4; ru.rotation.x = -0.15; }
    // Closed eyes + relaxed face come from CLIP_EXPRESSIONS, not the clip.
  }
  function cry(t: number): void {
    const head = bone("head"), spine = bone("spine"), chest = bone("chest") ?? bone("upperChest");
    const lu = bone("leftUpperArm"), ru = bone("rightUpperArm");
    const ll = bone("leftLowerArm"), rl = bone("rightLowerArm");
    const shake = Math.sin(t * 8) * 0.03;
    if (spine) spine.rotation.x = 0.25;
    if (chest) chest.rotation.x = 0.2 + shake;
    if (head) { head.rotation.x = 0.4; head.rotation.z = shake * 3; }
    if (lu) { lu.rotation.z = -0.9; lu.rotation.y = -0.35; }
    if (ru) { ru.rotation.z = 0.9; ru.rotation.y = 0.35; }
    if (ll) { ll.rotation.z = 2.5; ll.rotation.y = -0.5; }
    if (rl) { rl.rotation.z = -2.5; rl.rotation.y = 0.5; }
  }
  // Locomotion cycles ported from vrmAnimations.js -- self-timed (sin(t*3) /
  // sin(t*6)), so they run off the clip clock like every other clip.
  function walk(t: number): void {
    const swing = Math.sin(t * 3);
    const lUp = bone("leftUpperLeg"), rUp = bone("rightUpperLeg");
    const lLo = bone("leftLowerLeg"), rLo = bone("rightLowerLeg");
    const luA = bone("leftUpperArm"), ruA = bone("rightUpperArm");
    const chest = bone("chest") ?? bone("upperChest");
    const hips = bone("hips");
    if (lUp) lUp.rotation.x = swing * 0.6;
    if (rUp) rUp.rotation.x = -swing * 0.6;
    if (lLo) lLo.rotation.x = -Math.max(0, -swing) * 0.9;   // knee bends only behind
    if (rLo) rLo.rotation.x = -Math.max(0, swing) * 0.9;
    if (luA) luA.rotation.x = -swing * 0.5;                 // opposite arm swing
    if (ruA) ruA.rotation.x = swing * 0.5;
    if (chest) chest.rotation.y = swing * 0.08;             // counter-rotation
    if (hips) hips.position.y = -Math.abs(swing) * 0.02;    // step bob
  }
  function run(t: number): void {
    const swing = Math.sin(t * 6);
    const lUp = bone("leftUpperLeg"), rUp = bone("rightUpperLeg");
    const lLo = bone("leftLowerLeg"), rLo = bone("rightLowerLeg");
    const luA = bone("leftUpperArm"), ruA = bone("rightUpperArm");
    const llA = bone("leftLowerArm"), rlA = bone("rightLowerArm");
    const spine = bone("spine");
    const chest = bone("chest") ?? bone("upperChest");
    const hips = bone("hips");
    if (lUp) lUp.rotation.x = swing * 1.05;
    if (rUp) rUp.rotation.x = -swing * 1.05;
    if (lLo) lLo.rotation.x = -Math.max(0, -swing) * 1.6;
    if (rLo) rLo.rotation.x = -Math.max(0, swing) * 1.6;
    // Arms stay down at the sides (relaxArms rest z), elbows bent ~90deg,
    // pumping forward/back opposite the legs.
    if (luA) luA.rotation.x = -0.2 + swing * 0.9;
    if (ruA) ruA.rotation.x = -0.2 - swing * 0.9;
    if (llA) llA.rotation.x = -1.6;
    if (rlA) rlA.rotation.x = -1.6;
    if (spine) spine.rotation.x = 0.18;   // forward lean
    if (chest) chest.rotation.y = swing * 0.15;
    if (hips) hips.position.y = -Math.abs(swing) * 0.04;
  }
  function jump(t: number): void {
    // Crouch -> launch -> land -> recover on a 1.4s cycle.
    const cycle = 1.4;
    const local = (t % cycle) / cycle;
    const hips = bone("hips"), spine = bone("spine");
    const luA = bone("leftUpperArm"), ruA = bone("rightUpperArm");
    const lUp = bone("leftUpperLeg"), rUp = bone("rightUpperLeg");
    const lLo = bone("leftLowerLeg"), rLo = bone("rightLowerLeg");
    let hipY = 0, crouch = 0;
    if (local < 0.2) { crouch = local / 0.2; hipY = -0.18 * crouch; }
    else if (local < 0.5) {
      const air = (local - 0.2) / 0.3;
      hipY = Math.max(0, -Math.pow(1 - air * 2, 2) * 0.4 + 0.4);
    } else if (local < 0.7) {
      const land = (local - 0.5) / 0.2;
      hipY = -0.2 * land;
      crouch = land;
    } else {
      const rec = (local - 0.7) / 0.3;
      hipY = -0.2 * (1 - rec);
      crouch = 1 - rec;
    }
    if (hips) hips.position.y = hipY;
    if (spine) spine.rotation.x = crouch * 0.25;
    const knee = -1.2 * crouch;
    if (lUp) lUp.rotation.x = -0.5 * crouch + (local > 0.2 && local < 0.5 ? 0.5 : 0);
    if (rUp) rUp.rotation.x = -0.5 * crouch + (local > 0.2 && local < 0.5 ? 0.5 : 0);
    if (lLo) lLo.rotation.x = knee;
    if (rLo) rLo.rotation.x = knee;
    const armX = local < 0.2 ? -local / 0.2 * 0.5 : local < 0.5 ? -1.5 : local < 0.7 ? -1.0 : -0.2;
    if (luA) { luA.rotation.z = 1.2; luA.rotation.x = armX; }
    if (ruA) { ruA.rotation.z = -1.2; ruA.rotation.x = armX; }
  }
  // Talking body: light idle sway + a head bob for emphasis. The mouth-shape
  // cycling and the emotion overlay are time-driven expressions, applied in
  // applyClipExpressions so they also layer over a mixer-driven body.
  function talking(t: number): void {
    idle(t * 0.5);
    const head = bone("head"); if (head) head.rotation.x += Math.sin(t * 4) * 0.02;
  }

  const CLIPS: Record<string, (t: number) => void> = {
    idle, idle_soft: idleSoft, wave, cheer, thinking, dance, sit, sleep, cry,
    talking, walk, run, jump,
    point: wave,   // procedural fallback while the PeaceSign .vrma is away
  };

  // vrmAnimations.js applyClipExpressions: the clip's facial profile merges
  // atLeast (max) ON TOP of the mood-lerped weights, every frame, whichever
  // engine drives the bones -- plus the time-driven talking mouth at ~0.28s
  // per shape with a sine envelope, and the mood's talk-emotion overlay.
  function applyClipExpressions(clip: string, t: number): void {
    const preset = CLIP_EXPRESSIONS[clip];
    if (preset) for (const name of Object.keys(preset)) setExpr(name, preset[name] ?? 0, true);
    if (clip === "talking") {
      const cyc = 0.28, idx = Math.floor(t / cyc), local = (t % cyc) / cyc;
      const env = Math.max(0, Math.sin(local * Math.PI) * (0.55 + 0.35 * Math.sin(t * 3.0)));
      setExpr(MOUTH[idx % MOUTH.length], env, true);
      setExpr(TALK_EMOTIONS[moodLabel] ?? "relaxed", 0.55, true);
    }
  }

  function applyExpressions(dt: number): void {
    for (const k of Object.keys(exprTarget)) {
      const cur = exprNow[k] ?? 0;
      const next = cur + ((exprTarget[k] ?? 0) - cur) * Math.min(1, dt * 3);
      exprNow[k] = next;
      setExpr(k, next);
    }
  }
  function autoBlink(t: number): void {
    const cyc = 4.5, local = t % cyc;
    let v = 0;
    if (local < 0.15) v = local / 0.15;
    else if (local < 0.3) v = 1 - (local - 0.15) / 0.15;
    if (v > 0) setExpr("blink", v, true);
  }

  // Which clip she performs right now: speech wins, then the airborne action,
  // then locomotion, then the named action states, then her mood. Prefix
  // matching on the lowercased name strips the directional suffixes the house
  // appends (walkDown, runNortheast, jumpUp, waveSide, ...).
  function resolveClip(): string {
    if (spriteTalking) return "talking";
    const n = spriteName.toLowerCase();
    if (n.startsWith("jump")) return "jump";
    if (spriteMoving) return n.startsWith("run") || n.startsWith("dash") ? "run" : "walk";
    if (n.startsWith("talk")) return "talking";
    if (n.startsWith("wave")) return "wave";
    if (n.startsWith("sit")) return "sit";
    if (n.startsWith("sleep")) return "sleep";
    if (n.startsWith("kneel") || n.startsWith("crouch") || n.startsWith("pickup")) return "thinking";
    if (n.startsWith("dance")) return "dance";
    if (n.startsWith("victory")) return "cheer";
    if (n.startsWith("point")) return "point";
    if (n.startsWith("climb")) return "idle";
    return MOOD_CLIPS[moodLabel] ?? "idle";   // idle* and unknowns read her mood
  }

  /* ---- .vrma playback (pattern from apps/vcs VRMViewer.jsx) ---- */

  function requestVrma(name: string): void {
    const urlOf = deps.animationUrl;
    const lib = vrmaLib;
    const forVrm = vrm;
    if (!urlOf || !GLTFLoaderCtor || !lib || !forVrm) return;
    if (vrmaClips.has(name) || vrmaFailed.has(name) || vrmaLoading.has(name)) return;
    vrmaLoading.add(name);
    const loader = new GLTFLoaderCtor();
    loader.register((parser) => new lib.VRMAnimationLoaderPlugin(parser));
    loader.loadAsync(urlOf(`${name}.vrma`))
      .then((gltf) => {
        vrmaLoading.delete(name);
        if (vrm !== forVrm) return;   // body swapped or disposed mid-fetch
        const anims = gltf.userData.vrmAnimations as VRMAnimation[] | undefined;
        const anim = anims?.[0];
        if (!anim) { vrmaFailed.add(name); return; }
        // createVRMAnimationClip retargets to THIS vrm instance (VRM 0.x too),
        // so mixer-driven frames need no manual axisFlip.
        vrmaClips.set(name, lib.createVRMAnimationClip(anim, forVrm));
      })
      .catch(() => {
        vrmaLoading.delete(name);
        vrmaFailed.add(name);   // procedural covers it permanently
      });
  }

  function playVrma(name: string, clip: THREE.AnimationClip): void {
    if (!vrm) return;
    if (!mixer) mixer = new THREE.AnimationMixer(vrm.scene);
    const next = mixer.clipAction(clip);
    const revived = fading.indexOf(next);
    if (revived >= 0) fading.splice(revived, 1);   // wanted again mid-fade-out
    next.reset();
    next.enabled = true;
    next.setEffectiveTimeScale(1);
    next.setEffectiveWeight(1);
    next.play();
    const prev = currentAction;
    if (prev && prev !== next) { prev.crossFadeTo(next, VRMA_FADE, false); fading.push(prev); }
    else next.fadeIn(VRMA_FADE);
    currentAction = next;
    currentVrmaName = name;
  }

  function stopVrma(): void {
    if (!currentAction) return;
    currentAction.fadeOut(VRMA_FADE);
    fading.push(currentAction);
    currentAction = null;
    currentVrmaName = null;
  }

  // Fully faded actions must be stop()ped so their bindings release the bones
  // back to the procedural clips.
  function reapFaded(): void {
    for (let i = fading.length - 1; i >= 0; i--) {
      const a = fading[i];
      if (a && a.getEffectiveWeight() <= 0.001) { a.stop(); fading.splice(i, 1); }
    }
  }

  /* ---- foot grounding (ported from apps/vcs vrmIK.js) ----
   * Two causes of a buried/ sliding body: (1) origin-CENTERED VRoid exports
   * stand with hips at y=0 and feet at ~-0.9, so a naive placement is
   * half-buried; (2) clips -- .vrma hips-translation tracks especially --
   * drop the feet below ground mid-motion, so no one-time offset holds.
   * Fix: a ROOT-level clamp on vrm.scene. VCS applies world-scale offsets
   * directly; here vrm.scene sits inside the SCALED wrapper, so every
   * world-space correction is divided by the wrapper's world scale before
   * being written to vrm.scene.position.y (and the model-space sole offsets
   * are multiplied by it when measuring). groundBase/groundOffset stay in
   * world units. Ground plane: deps.groundClearance. */
  let groundBase = 0;     // resting offset from snapGround (world units)
  let groundOffset = 0;   // current offset groundFeet eases (world units)
  const groundY = deps.groundClearance;
  const _sole = new THREE.Vector3();
  const _wScale = new THREE.Vector3();

  function worldScaleY(): number {
    return wrapper ? Math.max(1e-6, wrapper.getWorldScale(_wScale).y) : 1;
  }

  // Lowest sole-point Y of the posed skeleton (world space), or null. RAW
  // bones, not normalized: the raw skeleton is what the mesh actually wears.
  function lowestSole(): number | null {
    const h = vrm?.humanoid;
    if (!h) return null;
    const s = worldScaleY();
    let lowest = Infinity;
    for (const name of SOLE_BONES) {
      const b = h.getRawBoneNode(name);
      if (!b) continue;
      b.getWorldPosition(_sole);   // forces parent matrixWorld refresh
      const sole = _sole.y - (SOLE_OFFSET[name] ?? 0) * s;
      if (sole < lowest) lowest = sole;
    }
    return Number.isFinite(lowest) ? lowest : null;
  }

  // One-time exact plant at activation (after the first vrm.update(0) and the
  // wrapper scaling). The offset may be negative (authored floating) or
  // strongly positive (origin-centered export); it becomes the resting
  // baseline groundFeet eases back to.
  function snapGround(): void {
    const forVrm = vrm, w = wrapper;
    if (!forVrm || !w) return;
    w.updateWorldMatrix(true, true);
    const lowest = lowestSole();
    if (lowest == null) return;
    const offset = groundY - lowest;
    groundBase = offset;
    groundOffset = offset;
    forVrm.scene.position.y = offset / worldScaleY();
    forVrm.scene.updateMatrixWorld(true);
  }

  // Per-frame grounding, AFTER vrm.update(dt). Fast rise (penetration is
  // visibly wrong), slow settle (no pogo bounce) -- so intentional airtime
  // (the jump cycle) still reads as airtime.
  function groundFeet(dt: number): void {
    const forVrm = vrm;
    if (!forVrm) return;
    const lowest = lowestSole();
    if (lowest == null) return;
    // `lowest` was measured WITH the current offset applied; undo it to get
    // the animation's own pose. Lift above base only to fix penetration.
    const target = Math.max(groundBase, groundY - (lowest - groundOffset));
    const rate = target > groundOffset ? 20 : 6;
    groundOffset += (target - groundOffset) * Math.min(1, (dt || 0.016) * rate);
    forVrm.scene.position.y = groundOffset / worldScaleY();
  }

  /* ---- measurement ----
   * A VRM's skinned-mesh geometry bounding boxes are BIND-space data -- a
   * phantom column that matches neither her height nor her feet. The only
   * measure that matches what renders is the POSED skinned vertices, valid
   * only after the first vrm.update() has settled the skeleton. */
  function measurePosed(root: THREE.Object3D, frame: THREE.Object3D): { height: number; minY: number } {
    frame.updateWorldMatrix(true, true);
    const toLocal = new THREE.Matrix4().copy(frame.matrixWorld).invert();
    const box = new THREE.Box3();
    const v = new THREE.Vector3();
    root.traverse((o) => {
      const mesh = o as THREE.SkinnedMesh;
      if (!mesh.isSkinnedMesh || !mesh.geometry?.attributes?.position || !mesh.skeleton) return;
      mesh.skeleton.update();
      const pos = mesh.geometry.attributes.position;
      const step = Math.max(1, Math.floor(pos.count / MEASURE_SAMPLES));
      // Both spellings kept: applyBoneTransform is three r160+, boneTransform older.
      const m = mesh as unknown as {
        applyBoneTransform?: (i: number, v: THREE.Vector3) => THREE.Vector3;
        boneTransform?: (i: number, v: THREE.Vector3) => THREE.Vector3;
      };
      for (let k = 0; k < pos.count; k += step) {
        v.fromBufferAttribute(pos, k);
        if (m.applyBoneTransform) m.applyBoneTransform(k, v);
        else if (m.boneTransform) m.boneTransform(k, v);
        v.applyMatrix4(mesh.matrixWorld).applyMatrix4(toLocal);
        box.expandByPoint(v);
      }
    });
    if (box.isEmpty()) box.setFromObject(root).applyMatrix4(toLocal);  // non-skinned fallback
    const size = new THREE.Vector3();
    box.getSize(size);
    return { height: size.y > 0.1 ? size.y : 1.5, minY: box.min.y };
  }

  async function load(): Promise<boolean> {
    status = "loading";
    deps.onStatus("loading", "manifest", 0);
    try {
      const loaded = await withWatchdog(loadInner(), LOAD_WATCHDOG_MS,
        "VRM load timed out after 45s");
      const w = new THREE.Group();
      w.name = "alpecca-vrm";
      w.visible = false;   // hidden until the posed measurement has framed her
      w.add(loaded.scene);
      deps.parent.add(w);

      loaded.update(0);    // settles the normalized rig; bounds are real after this
      const { height } = measurePosed(loaded.scene, w);
      const scale = deps.targetHeight / Math.max(0.1, height);
      w.scale.setScalar(scale);

      vrm = loaded;
      wrapper = w;
      // Vertical alignment comes from snapGround on the raw sole bones, NOT
      // the vertex minY: a one-time vertex offset stops holding the moment
      // clips drive the root. The posed-vertex pass above still owns the
      // HEIGHT the scale factor is computed from.
      snapGround();
      if (status !== "loading") return true;   // deactivated mid-load: cache, stay hidden
      w.visible = true;
      status = "active";
      deps.onStatus("active");
      return true;
    } catch (err) {
      status = "failed";
      deps.onStatus("failed", err instanceof Error ? err.message : String(err));
      return false;
    }
  }

  async function loadInner(): Promise<VRM> {
    // Dynamic imports keep GLTFLoader + three-vrm(+animation) out of the
    // default chunk. Without an animationUrl the .vrma path never imports.
    const [gltfMod, vrmLib, vrmaMod] = await Promise.all([
      import("three/examples/jsm/loaders/GLTFLoader.js"),
      import("@pixiv/three-vrm"),
      deps.animationUrl ? import("@pixiv/three-vrm-animation") : Promise.resolve(null),
    ]);
    GLTFLoaderCtor = gltfMod.GLTFLoader;
    vrmaLib = vrmaMod;
    deepDispose = vrmLib.VRMUtils.deepDispose;

    const res = await fetch(deps.manifestUrl());
    if (!res.ok) throw new Error(`manifest fetch failed (HTTP ${res.status})`);
    const man = (await res.json()) as { vrm_mode?: boolean; model_file?: string | null };
    if (!man.vrm_mode || !man.model_file) throw new Error("no VRM body installed (manifest has no model_file)");
    const file = man.model_file;

    const loader = new gltfMod.GLTFLoader();
    loader.register((parser) => new vrmLib.VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(deps.modelUrl(file), (ev) => {
      const p = ev.lengthComputable && ev.total > 0 ? Math.min(1, ev.loaded / ev.total) : undefined;
      deps.onStatus("loading", file, p);
    });
    const loaded = gltf.userData.vrm as VRM | undefined;
    if (!loaded) throw new Error(`${file} is not a VRM file`);

    // VRM 0.x models face -Z; rotate them like the studio does. The clip math
    // is authored in the 1.0 frame, and rotateVRM0's 180deg turn inverts the
    // local x/z rotation senses -- update() negates them for 0.x (axisFlip).
    const meta = loaded.meta as { metaVersion?: string; title?: string };
    const isV0 = meta.metaVersion === "0" || !!meta.title;
    if (isV0) vrmLib.VRMUtils.rotateVRM0(loaded);
    axisFlip = isV0 ? -1 : 1;

    vrmLib.VRMUtils.removeUnnecessaryVertices(loaded.scene);
    vrmLib.VRMUtils.combineSkeletons(loaded.scene);
    loaded.scene.traverse((o) => { o.frustumCulled = false; });
    return loaded;
  }

  return {
    get status(): EmbodimentStatus {
      return status;
    },

    async activate(): Promise<boolean> {
      if (vrm && wrapper) {   // cached fast path: just re-show
        wrapper.visible = true;
        status = "active";
        deps.onStatus("active");
        return true;
      }
      if (!loadPromise) {
        loadPromise = load().then((ok) => {
          if (!ok) loadPromise = null;   // failed loads may be retried
          return ok;
        });
      }
      return loadPromise;
    },

    deactivate(): void {
      if (wrapper) wrapper.visible = false;
      status = "idle";
      deps.onStatus("idle");
    },

    dispose(): void {
      if (mixer) {
        mixer.stopAllAction();
        if (vrm) mixer.uncacheRoot(vrm.scene);
      }
      mixer = null;
      currentAction = null;
      currentVrmaName = null;
      fading.length = 0;
      vrmaClips.clear();   // clips were retargeted to this vrm instance
      vrmaLoading.clear();
      if (wrapper) deps.parent.remove(wrapper);
      if (vrm && deepDispose) deepDispose(vrm.scene);
      vrm = null;
      wrapper = null;
      loadPromise = null;
      deepDispose = null;
      groundBase = 0;
      groundOffset = 0;
      status = "idle";
    },

    setMood(label, d): void {
      moodLabel = label;
      if (d.love !== undefined) dims.love = d.love;
      if (d.compassion !== undefined) dims.compassion = d.compassion;
      if (d.fear !== undefined) dims.fear = d.fear;
      if (d.energy !== undefined) dims.energy = d.energy;
      exprTarget = expressionsForState(dims);
    },

    setSpriteState(name, moving, talking): void {
      spriteName = name;
      spriteMoving = moving;
      spriteTalking = talking;
    },

    update(dt, camera, engaged, distanceToPlayer = Infinity): void {
      if (status !== "active" || !vrm || !wrapper || !wrapper.visible) return;
      elapsed += dt;
      const next = resolveClip();
      if (next !== clipName) { clipName = next; clipTime = 0; }   // fresh cycle
      clipTime += dt;

      // Real .vrma motion when its clip is ready; procedural otherwise.
      // Locomotion is always procedural -- no walking/running .vrma exists,
      // the ported cycles carry it -- and while moving any playing action
      // fades out underneath the cycle.
      let vrmaDriven = false;
      const wantVrma: string | null = spriteMoving ? null : CLIP_VRMA[clipName] ?? null;
      if (wantVrma && deps.animationUrl && !vrmaFailed.has(wantVrma)) {
        const clip = vrmaClips.get(wantVrma);
        if (clip) {
          if (currentVrmaName !== wantVrma) playVrma(wantVrma, clip);
          vrmaDriven = true;
        } else {
          requestVrma(wantVrma);   // procedural carries this frame while it fetches
        }
      }
      if (!vrmaDriven) stopVrma();

      for (const s of MOUTH) setExpr(s, 0);
      setExpr("blink", 0);
      applyExpressions(dt);

      if (!vrmaDriven) {
        for (const n of BONES) { const b = bone(n); if (b) b.rotation.set(0, 0, 0); }
        const hips = bone("hips");
        if (hips) hips.position.set(0, 0, 0);
        relaxArms();
        (CLIPS[clipName] ?? idle)(clipTime);
        // Clip constants are in the 1.0 frame; 0.x normalized bones spin x/z
        // the other way (measured in web/vrm.html), so negate. Mixer-driven
        // frames skip all of this: resetting or posing bones would fight the
        // mixer, and the retargeted clip already handles VRM 0.x.
        if (axisFlip < 0) {
          for (const n of BONES) {
            const b = bone(n);
            if (b) { b.rotation.x *= -1; b.rotation.z *= -1; }
          }
        }
      }

      // Face: the clip's expression profile layers atLeast on top of the mood
      // weights; a clip that holds the eyes closed suppresses the auto-blink.
      applyClipExpressions(clipName, clipTime);
      if (!clipHoldsEyesClosed(clipName)) autoBlink(elapsed);

      // Senses: she looks at you when engaged, or simply when you come near
      // (mirrors the sprite's head-look awareness, in world units).
      if (vrm.lookAt) vrm.lookAt.target = engaged || distanceToPlayer < NOTICE_DISTANCE ? camera : null;
      // The mixer updates after any procedural writes so a fading action
      // blends from/into the procedural pose instead of hard-cutting.
      if (mixer) { mixer.update(dt); reapFaded(); }
      vrm.update(dt);
      groundFeet(dt);   // after vrm.update: clamp the posed soles to the floor
    },

    debug(): { groundBase: number; groundOffset: number; lowestSoleY: number | null } {
      return { groundBase, groundOffset, lowestSoleY: lowestSole() };
    },
  };
}

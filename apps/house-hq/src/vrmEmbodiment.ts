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

export const VRM_VOWELS = ["aa", "ih", "ou", "ee", "oh"] as const;
export type VrmVowel = (typeof VRM_VOWELS)[number];

export type VrmDebugPosition = Readonly<{ x: number; y: number; z: number }>;

export type VrmEmbodimentDebug = Readonly<{
  groundBase: number;
  groundOffset: number;
  lowestSoleY: number | null;
  springJoints: number;
  springColliders: number;
  face: Record<string, number>;
  vowels: Record<VrmVowel, number>;
  mouthCorrections: Record<string, number>;
  mouthCorrectionBindings: number;
  activeClip: string;
  activePose: string;
  activeMotion: string;
  activeMode: "procedural" | "loop" | "once" | "twice";
  rootPosition: VrmDebugPosition | null;
  rootLocalPosition: VrmDebugPosition | null;
  hipsPosition: VrmDebugPosition | null;
  hipsLocalPosition: VrmDebugPosition | null;
  handContactDistance: number | null;
  interactionPhase: "approach" | "reach" | "contact" | "retract";
  interactionTargetReachable: boolean;
}>;

export interface VrmEmbodimentDeps {
  parent: THREE.Group;
  targetHeight: number;
  groundClearance: number;
  manifestUrl: () => string;
  modelUrl: (file: string) => string;
  animationUrl?: (fileName: string) => string;   // absent -> procedural clips only
  onStatus: (status: EmbodimentStatus, detail?: string, progress?: number) => void;
}

export type VrmInteractionContactStatus = Readonly<{
  available: boolean;
  inContact: boolean;
  distance: number | null;
  threshold: number;
}>;

export interface VrmEmbodiment {
  readonly status: EmbodimentStatus;
  readonly interactionContactStatus: VrmInteractionContactStatus;
  activate(): Promise<boolean>;
  deactivate(): void;
  dispose(): void;
  setMood(label: string, dims: { love?: number; compassion?: number; fear?: number; energy?: number }): void;
  setSpriteState(name: string, moving: boolean, talking: boolean, forceOneShot?: boolean): void;
  setInteractionTarget(target: THREE.Vector3 | null, phase: "approach" | "reach" | "contact" | "retract"): void;
  update(dt: number, camera: THREE.Camera, engaged: boolean, distanceToPlayer?: number): void;
  debug(): VrmEmbodimentDebug;
}

type MoodDims = { love: number; compassion: number; fear: number; energy: number };

const c01 = (v: number): number => Math.max(0, Math.min(1, v));

type V4MoodExpression = "happy" | "sad" | "surprised" | "relaxed" | "angry";

const V4_MOOD_MOUTH_PROFILES: Readonly<Record<V4MoodExpression, Readonly<{
  all: string;
  brow: string;
  eye: string;
  mouth: string;
}>>> = {
  happy: { all: "Fcl_ALL_Joy", brow: "Fcl_BRW_Joy", eye: "Fcl_EYE_Joy", mouth: "Fcl_MTH_Joy" },
  sad: { all: "Fcl_ALL_Sorrow", brow: "Fcl_BRW_Sorrow", eye: "Fcl_EYE_Sorrow", mouth: "Fcl_MTH_Sorrow" },
  surprised: { all: "Fcl_ALL_Surprised", brow: "Fcl_BRW_Surprised", eye: "Fcl_EYE_Surprised", mouth: "Fcl_MTH_Surprised" },
  relaxed: { all: "Fcl_ALL_Fun", brow: "Fcl_BRW_Fun", eye: "Fcl_EYE_Fun", mouth: "Fcl_MTH_Fun" },
  angry: { all: "Fcl_ALL_Angry", brow: "Fcl_BRW_Angry", eye: "Fcl_EYE_Angry", mouth: "Fcl_MTH_Angry" },
};

export function vowelWeightsForSpeech(
  talking: boolean,
  shape: VrmVowel,
  weight: number,
): Record<VrmVowel, number> {
  const resolved = talking && Number.isFinite(weight) ? c01(weight) : 0;
  return {
    aa: shape === "aa" ? resolved : 0,
    ih: shape === "ih" ? resolved : 0,
    ou: shape === "ou" ? resolved : 0,
    ee: shape === "ee" ? resolved : 0,
    oh: shape === "oh" ? resolved : 0,
  };
}

export function v4MoodMouthCorrectionWeights(
  weights: Partial<Record<V4MoodExpression, number>>,
): Record<string, number> {
  const corrections: Record<string, number> = {};
  for (const [emotion, profile] of Object.entries(V4_MOOD_MOUTH_PROFILES) as Array<
    [V4MoodExpression, (typeof V4_MOOD_MOUTH_PROFILES)[V4MoodExpression]]
  >) {
    const weight = weights[emotion] ?? 0;
    corrections[profile.mouth] = -(Number.isFinite(weight) ? c01(weight) : 0);
  }
  return corrections;
}

export function isRotationOnlyVrmTrack(trackName: string): boolean {
  return trackName.endsWith(".quaternion");
}

export function shouldScheduleVrmPerformance(activeClip: string, finishedClip: string | null): boolean {
  return activeClip !== finishedClip;
}

export type TwoBoneReachSolution = Readonly<{
  valid: boolean;
  reachable: boolean;
  targetDistance: number;
  solvedDistance: number;
  minReach: number;
  maxReach: number;
  elbowAlong: number;
  elbowOffset: number;
}>;

const IK_EPSILON = 1e-5;

export function solveTwoBoneReach(
  upperLength: number,
  lowerLength: number,
  targetDistance: number,
): TwoBoneReachSolution {
  const valid = Number.isFinite(upperLength)
    && Number.isFinite(lowerLength)
    && Number.isFinite(targetDistance)
    && upperLength > IK_EPSILON
    && lowerLength > IK_EPSILON
    && targetDistance > IK_EPSILON;
  if (!valid) {
    return {
      valid: false,
      reachable: false,
      targetDistance: Number.isFinite(targetDistance) ? Math.max(0, targetDistance) : 0,
      solvedDistance: 0,
      minReach: 0,
      maxReach: 0,
      elbowAlong: 0,
      elbowOffset: 0,
    };
  }

  const minReach = Math.abs(upperLength - lowerLength);
  const maxReach = upperLength + lowerLength;
  const reachable = targetDistance >= minReach - IK_EPSILON
    && targetDistance <= maxReach + IK_EPSILON;
  const lowerBound = Math.min(maxReach - IK_EPSILON, minReach + IK_EPSILON);
  const upperBound = Math.max(lowerBound, maxReach - IK_EPSILON);
  const solvedDistance = THREE.MathUtils.clamp(targetDistance, lowerBound, upperBound);
  const elbowAlong = (
    upperLength * upperLength
    - lowerLength * lowerLength
    + solvedDistance * solvedDistance
  ) / (2 * solvedDistance);
  const elbowOffset = Math.sqrt(Math.max(0, upperLength * upperLength - elbowAlong * elbowAlong));
  return {
    valid: true,
    reachable,
    targetDistance,
    solvedDistance,
    minReach,
    maxReach,
    elbowAlong,
    elbowOffset,
  };
}

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
// no such .vrma exists, the procedural cycles carry it. Also absent by
// design: talking (procedural sway + visemes only -- a looping LookAround
// read as her ignoring you mid-sentence) and idle/idle_soft (the procedural
// sway is the resting base; IDLE_FLAVOR_VRMA one-shots decorate it).
const CLIP_VRMA: Record<string, string> = {
  sleep: "Sleepy",
  cry: "Sad",
  thinking: "Thinking",
  cheer: "Clapping",
  wave: "Hello",
  dance: "Jump",
  sit: "Relax",
  point: "PeaceSign",
};

// Idle flourishes: while she rests on the procedural idle base, one of these
// plays as a single one-shot every IDLE_FLOURISH_MIN..MAX seconds -- never
// the same one twice in a row -- then crossfades back to the procedural
// base. That randomized rotation is what keeps her from reading as a looping
// animatronic.
const IDLE_FLAVOR_VRMA = ["LookAround", "Thinking", "Relax"];
const IDLE_FLOURISH_MIN = 14;
const IDLE_FLOURISH_MAX = 32;
const nextFlourishDelay = (): number =>
  IDLE_FLOURISH_MIN + Math.random() * (IDLE_FLOURISH_MAX - IDLE_FLOURISH_MIN);

// How a .vrma action is scheduled: rest poses loop forever, idle flourishes
// play once, mood performances get at most two passes then settle.
type PlayMode = "loop" | "once" | "twice";
type VrmMotionPlayback = Readonly<{ name: string; mode: PlayMode }>;

export function resolveVrmMotionTelemetry(
  active: VrmMotionPlayback | null,
  fading: VrmMotionPlayback | null,
  proceduralPose: string,
): Pick<VrmEmbodimentDebug, "activeMotion" | "activeMode"> {
  if (active) return { activeMotion: active.name, activeMode: active.mode };
  if (fading) return { activeMotion: `fading:${fading.name}`, activeMode: fading.mode };
  return { activeMotion: `procedural:${proceduralPose}`, activeMode: "procedural" };
}

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
  "leftFoot", "rightFoot",
];

const MOUTH = VRM_VOWELS;
type MouthShape = VrmVowel;

const LOAD_WATCHDOG_MS = 45_000;
const MEASURE_SAMPLES = 1200;
const VRMA_FADE = 0.35;        // crossfade between mixer actions, like VCS
const NOTICE_DISTANCE = 4.5;   // she notices you approaching inside this range
const BLINK_INTERVAL_MIN = 2.8;
const BLINK_INTERVAL_MAX = 6.5;
const MAX_MOUTH_WEIGHT = 0.55;
const INTERACTION_REACH_WEIGHT = {
  approach: 0.28,
  reach: 1,
  contact: 1,
  retract: 0,
} as const;
const MAX_SHOULDER_IK_DELTA = 1.75;
const MAX_ELBOW_IK_DELTA = 2.45;
const MAX_WRIST_TURN = 0.16;
const INTERACTION_CONTACT_THRESHOLD = 0.2;

// A named action may remain selected longer than its performance. These caps
// stop the procedural fallback from waving/jumping/dancing forever while a
// state waits to change or a .vrma is unavailable.
const PROCEDURAL_PERFORMANCE_SECONDS: Partial<Record<string, number>> = {
  wave: 1.8,
  point: 1.6,
  cheer: 2.6,
  dance: 3.0,
  cry: 3.2,
  thinking: 3.8,
  jump: 1.4,
};

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

function collectionSize(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  const size = (value as { size?: unknown } | null)?.size;
  return typeof size === "number" && Number.isFinite(size) ? size : 0;
}

const roundTelemetry = (value: number): number => Math.round(value * 1000) / 1000;

type MorphTargetMesh = THREE.Mesh & {
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
};

type ExpressionMorphTargetBind = {
  primitives: readonly MorphTargetMesh[];
  index: number;
  weight: number;
};

type V4MouthCorrectionBinding = {
  emotion: V4MoodExpression;
  morphName: string;
  mesh: MorphTargetMesh;
  index: number;
  expressionScale: number;
};

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
  let v4MouthCorrectionBindings: V4MouthCorrectionBinding[] = [];
  const mouthCorrectionNow: Record<string, number> = {};

  let spriteName = "";
  let spriteMoving = false;
  let spriteTalking = false;

  // Terminal interaction is a world-space target copied from House HQ. The
  // arm remains procedural and bounded; it never translates the avatar root or
  // mutates the target supplied by the caller.
  let interactionTarget: THREE.Vector3 | null = null;
  let interactionPhase: "approach" | "reach" | "contact" | "retract" = "retract";
  let interactionWeight = 0;
  let interactionElapsed = 0;
  let interactionContactAvailable = false;
  let interactionInContact = false;
  let interactionContactDistance: number | null = null;
  let interactionTargetReachable = false;
  const interactionLookTarget = new THREE.Object3D();
  interactionLookTarget.name = "Alpecca terminal gaze target";
  const reachShoulderWorld = new THREE.Vector3();
  const reachElbowWorld = new THREE.Vector3();
  const reachTargetDirection = new THREE.Vector3();
  const reachCurrentDirection = new THREE.Vector3();
  const reachDesiredDirection = new THREE.Vector3();
  const reachBoneOriginWorld = new THREE.Vector3();
  const reachPoleWorld = new THREE.Vector3();
  const reachFallbackPoleWorld = new THREE.Vector3();
  const reachElbowTargetWorld = new THREE.Vector3();
  const reachHandTargetWorld = new THREE.Vector3();
  const reachParentWorld = new THREE.Quaternion();
  const reachBoneWorld = new THREE.Quaternion();
  const reachAim = new THREE.Quaternion();
  const reachLimitedAim = new THREE.Quaternion();
  const reachTargetWorld = new THREE.Quaternion();
  const reachTargetLocal = new THREE.Quaternion();
  const reachIdentity = new THREE.Quaternion();
  const reachWrist = new THREE.Quaternion();
  const reachEuler = new THREE.Euler();
  const interactionHandWorld = new THREE.Vector3();
  const debugPositionVector = new THREE.Vector3();

  let clipName = "idle";
  let activePoseName = "idle";
  let clipTime = 0;   // restarts when the resolved clip changes (fresh cycle)

  // Face timing is stateful instead of tied to a fixed modulo cycle. That
  // avoids synchronized machine-like blinking and gives speech short closures
  // between varied visemes rather than holding one mouth shape open.
  let blinkIn = nextBlinkDelay();
  let blinkElapsed = 0;
  let blinkDuration = 0.14;
  let blinkActive = false;
  let blinkFollowup = false;
  let blinkShouldFollow = false;
  let lipShape: MouthShape = "aa";
  let lipShapeIndex = 0;
  let lipTarget = 0;
  let lipNow = 0;
  let lipPhaseIn = 0;

  // .vrma playback: one persistent mixer, clips cached per motion name.
  let mixer: THREE.AnimationMixer | null = null;
  let currentAction: THREE.AnimationAction | null = null;
  let currentVrmaName: string | null = null;
  let currentPlayMode: PlayMode | null = null;
  const vrmaClips = new Map<string, THREE.AnimationClip>();
  const vrmaLoading = new Set<string>();
  const vrmaFailed = new Set<string>();   // never refetched; procedural covers them
  const fading: THREE.AnimationAction[] = [];
  const actionPlayback = new WeakMap<THREE.AnimationAction, VrmMotionPlayback>();

  // Anti-animatronic scheduling: a finished one-shot/twice performance must not
  // immediately replay (finishedForClip gates it until the state changes), and
  // idle gets randomized flourish one-shots instead of a permanent loop.
  let finishedForClip: string | null = null;
  let forcedReplayClip: "point" | "wave" | null = null;
  let flourishName: string | null = null;
  let lastFlourish = "";
  let flourishIn = nextFlourishDelay();

  // How each mapped .vrma is scheduled: rest poses hold forever; greetings and
  // points play once; mood performances get two passes then settle back to the
  // procedural base until the state or mood changes.
  const VRMA_MODE: Record<string, PlayMode> = {
    sleep: "loop", sit: "loop",
    wave: "once", point: "once",
    cheer: "twice", dance: "twice", cry: "twice", thinking: "twice",
  };

  function pickFlourish(): string {
    const pool = IDLE_FLAVOR_VRMA.filter((n) => n !== lastFlourish);
    const chosen = pool[Math.floor(Math.random() * pool.length)] ?? IDLE_FLAVOR_VRMA[0]!;
    lastFlourish = chosen;
    return chosen;
  }

  function onActionFinished(e: { action: THREE.AnimationAction }): void {
    if (e.action !== currentAction) return;
    if (flourishName && currentVrmaName === flourishName) {
      flourishName = null;
      flourishIn = nextFlourishDelay();
    } else {
      finishedForClip = clipName;
    }
    stopVrma();   // clampWhenFinished held the last frame; fade back to procedural
  }

  const bone = (n: VRMHumanBoneName): THREE.Object3D | null =>
    vrm ? vrm.humanoid.getNormalizedBoneNode(n) : null;

  function kneeFlex(amount: number): number {
    // VRM 1.0 faces +Z. On this rig, positive local X moves the ankle toward
    // -Z, so it is the anatomical knee-flex direction rather than a forward
    // hyperextension. Legacy VRM 0.x pose values are flipped in update().
    return axisFlip < 0 ? -amount : amount;
  }

  // Keep the sole roughly parallel to the floor as the leg swings: the foot is
  // a child of the shin, so a flexed knee would otherwise dangle it toe-down
  // (the "backward leg" look). Counter most of the thigh+shin pitch, minus a
  // little so it still rolls heel-to-toe. Same-frame values, so axisFlip is
  // already baked into lLoX/rLoX and needs no separate handling.
  function levelFoot(side: "left" | "right", upX: number, loX: number): void {
    const foot = bone(side === "left" ? "leftFoot" : "rightFoot");
    if (foot) foot.rotation.x = -(upX + loX) * 0.72;
  }

  function setExpr(name: string, v: number, atLeast = false): void {
    const em = vrm?.expressionManager;
    if (!em) return;
    const cur = em.getValue(name);
    if (cur == null) return;
    const value = c01(Number.isFinite(v) ? v : 0);
    em.setValue(name, atLeast ? Math.max(c01(cur), value) : value);
  }

  function expressionMorphBind(bind: unknown): ExpressionMorphTargetBind | null {
    const candidate = bind as Partial<ExpressionMorphTargetBind> | null;
    if (!candidate
      || !Array.isArray(candidate.primitives)
      || !Number.isInteger(candidate.index)
      || !Number.isFinite(candidate.weight)) return null;
    return candidate as ExpressionMorphTargetBind;
  }

  function discoverV4MouthCorrections(forVrm: VRM): V4MouthCorrectionBinding[] {
    const manager = forVrm.expressionManager;
    if (!manager) return [];

    // V4's measured VRoid morphs are exact component sums: ALL = BRW + EYE +
    // MTH. Only compensate when the authored emotion really binds that ALL
    // target and the matching component targets are present. The mouth target
    // must also be unbound so this never overwrites a generic VRM expression.
    const boundTargets = new Set<string>();
    for (const expression of manager.expressions) {
      for (const rawBind of expression.binds) {
        const bind = expressionMorphBind(rawBind);
        if (!bind) continue;
        for (const primitive of bind.primitives) {
          boundTargets.add(`${primitive.uuid}:${bind.index}`);
        }
      }
    }

    const corrections: V4MouthCorrectionBinding[] = [];
    for (const [emotion, profile] of Object.entries(V4_MOOD_MOUTH_PROFILES) as Array<
      [V4MoodExpression, (typeof V4_MOOD_MOUTH_PROFILES)[V4MoodExpression]]
    >) {
      const expression = manager.getExpression(emotion);
      if (!expression) continue;
      for (const rawBind of expression.binds) {
        const bind = expressionMorphBind(rawBind);
        if (!bind) continue;
        for (const mesh of bind.primitives) {
          const dictionary = mesh.morphTargetDictionary;
          const influences = mesh.morphTargetInfluences;
          if (!dictionary || !influences || dictionary[profile.all] !== bind.index) continue;
          const mouthIndex = dictionary[profile.mouth];
          if (!Number.isInteger(dictionary[profile.brow])
            || !Number.isInteger(dictionary[profile.eye])
            || !Number.isInteger(mouthIndex)
            || influences[mouthIndex] == null
            || boundTargets.has(`${mesh.uuid}:${mouthIndex}`)) continue;
          corrections.push({
            emotion,
            morphName: profile.mouth,
            mesh,
            index: mouthIndex,
            expressionScale: bind.weight,
          });
        }
      }
    }
    return corrections;
  }

  function clearV4MouthCorrections(): void {
    for (const binding of v4MouthCorrectionBindings) {
      const influences = binding.mesh.morphTargetInfluences;
      if (influences?.[binding.index] != null) influences[binding.index] = 0;
    }
    for (const profile of Object.values(V4_MOOD_MOUTH_PROFILES)) {
      mouthCorrectionNow[profile.mouth] = 0;
    }
  }

  function applyV4MouthCorrections(): void {
    const manager = vrm?.expressionManager;
    if (!manager || v4MouthCorrectionBindings.length === 0) return;
    const expressionWeights: Partial<Record<V4MoodExpression, number>> = {};
    for (const emotion of Object.keys(V4_MOOD_MOUTH_PROFILES) as V4MoodExpression[]) {
      expressionWeights[emotion] = manager.getExpression(emotion)?.outputWeight ?? 0;
    }
    const corrections = v4MoodMouthCorrectionWeights(expressionWeights);
    for (const binding of v4MouthCorrectionBindings) {
      const influences = binding.mesh.morphTargetInfluences;
      if (!influences || influences[binding.index] == null) continue;
      const correction = (corrections[binding.morphName] ?? 0) * binding.expressionScale;
      influences[binding.index] = correction;
      mouthCorrectionNow[binding.morphName] = correction;
    }
  }

  function nextBlinkDelay(): number {
    return BLINK_INTERVAL_MIN + Math.random() * (BLINK_INTERVAL_MAX - BLINK_INTERVAL_MIN);
  }

  function resetBlinkTiming(): void {
    blinkIn = nextBlinkDelay();
    blinkElapsed = 0;
    blinkDuration = 0.14;
    blinkActive = false;
    blinkFollowup = false;
    blinkShouldFollow = false;
  }

  function resetLipTiming(): void {
    lipShape = "aa";
    lipShapeIndex = 0;
    lipTarget = 0;
    lipNow = 0;
    lipPhaseIn = 0.04;
  }

  function resetFaceValues(): void {
    vrm?.expressionManager?.resetValues();
  }

  function setBlink(v: number): void {
    const em = vrm?.expressionManager;
    if (!em) return;
    const value = c01(v);
    if (em.getValue("blink") != null) {
      em.setValue("blink", value);
      return;
    }
    if (em.getValue("blinkLeft") != null) em.setValue("blinkLeft", value);
    if (em.getValue("blinkRight") != null) em.setValue("blinkRight", value);
  }

  function validInteractionTarget(target: THREE.Vector3 | null): target is THREE.Vector3 {
    return !!target
      && Number.isFinite(target.x)
      && Number.isFinite(target.y)
      && Number.isFinite(target.z);
  }

  function clearInteraction(): void {
    interactionTarget = null;
    interactionPhase = "retract";
    interactionWeight = 0;
    interactionElapsed = 0;
    interactionTargetReachable = false;
    invalidateInteractionContactStatus();
    if (vrm?.lookAt?.target === interactionLookTarget) {
      vrm.lookAt.target = null;
      vrm.lookAt.reset();
    }
  }

  function invalidateInteractionContactStatus(): void {
    interactionContactAvailable = false;
    interactionInContact = false;
    interactionContactDistance = null;
  }

  function updateInteractionContactStatus(): void {
    invalidateInteractionContactStatus();
    const target = interactionTarget;
    const hand = vrm?.humanoid.getRawBoneNode("rightHand") ?? null;
    if (!target || !hand) return;
    hand.getWorldPosition(interactionHandWorld);
    const distance = interactionHandWorld.distanceTo(target);
    if (!Number.isFinite(distance)) return;
    interactionContactAvailable = true;
    interactionContactDistance = distance;
    interactionInContact = interactionPhase === "contact"
      && interactionTargetReachable
      && distance <= INTERACTION_CONTACT_THRESHOLD;
  }

  function advanceInteraction(dt: number): boolean {
    const desired = interactionTarget ? INTERACTION_REACH_WEIGHT[interactionPhase] : 0;
    const response = interactionPhase === "retract" ? 9 : interactionPhase === "contact" ? 12 : 7;
    interactionWeight = THREE.MathUtils.damp(interactionWeight, desired, response, dt);
    interactionElapsed += dt;
    if ((interactionPhase === "retract" || !interactionTarget) && interactionWeight < 0.004) {
      interactionWeight = 0;
      interactionTarget = null;
      interactionTargetReachable = false;
    }
    return interactionTarget !== null && (interactionPhase !== "retract" || interactionWeight > 0);
  }

  function aimBoneTowardWorldPoint(
    targetBone: THREE.Object3D,
    currentChildWorld: THREE.Vector3,
    desiredChildWorld: THREE.Vector3,
    maxDelta: number,
    weight: number,
  ): boolean {
    const parent = targetBone.parent;
    if (!parent || weight <= 0) return false;
    targetBone.getWorldPosition(reachBoneOriginWorld);
    reachCurrentDirection.copy(currentChildWorld).sub(reachBoneOriginWorld);
    reachDesiredDirection.copy(desiredChildWorld).sub(reachBoneOriginWorld);
    if (reachCurrentDirection.lengthSq() < 1e-10 || reachDesiredDirection.lengthSq() < 1e-10) return false;
    reachCurrentDirection.normalize();
    reachDesiredDirection.normalize();
    reachAim.setFromUnitVectors(reachCurrentDirection, reachDesiredDirection);
    const angle = reachAim.angleTo(reachIdentity);
    reachLimitedAim.identity();
    if (angle > maxDelta) reachLimitedAim.slerp(reachAim, maxDelta / angle);
    else reachLimitedAim.copy(reachAim);

    targetBone.getWorldQuaternion(reachBoneWorld);
    reachTargetWorld.copy(reachLimitedAim).multiply(reachBoneWorld);
    parent.getWorldQuaternion(reachParentWorld).invert();
    reachTargetLocal.copy(reachParentWorld).multiply(reachTargetWorld).normalize();
    targetBone.quaternion.slerp(reachTargetLocal, c01(weight));
    targetBone.updateWorldMatrix(true, true);
    return true;
  }

  function applyInteractionReach(): void {
    const target = interactionTarget;
    interactionTargetReachable = false;
    if (!target || interactionWeight <= 0) return;
    const upper = bone("rightUpperArm");
    const lower = bone("rightLowerArm");
    const hand = bone("rightHand");
    const parent = upper?.parent;
    if (!upper || !lower || !hand || !parent) return;

    parent.updateWorldMatrix(true, true);
    upper.getWorldPosition(reachShoulderWorld);
    lower.getWorldPosition(reachElbowWorld);
    hand.getWorldPosition(interactionHandWorld);
    const upperLength = reachShoulderWorld.distanceTo(reachElbowWorld);
    const lowerLength = reachElbowWorld.distanceTo(interactionHandWorld);
    reachTargetDirection.copy(target).sub(reachShoulderWorld);
    const solution = solveTwoBoneReach(upperLength, lowerLength, reachTargetDirection.length());
    if (!solution.valid) return;
    interactionTargetReachable = solution.reachable;
    reachTargetDirection.normalize();

    // Keep the current elbow side when it is defined. A body-relative down/
    // forward pole handles a nearly straight source pose without a frame-to-
    // frame plane flip.
    reachPoleWorld.copy(reachElbowWorld).sub(reachShoulderWorld);
    reachPoleWorld.addScaledVector(reachTargetDirection, -reachPoleWorld.dot(reachTargetDirection));
    if (reachPoleWorld.lengthSq() < 1e-8) {
      parent.getWorldQuaternion(reachParentWorld);
      reachFallbackPoleWorld.set(0, -1, 0).applyQuaternion(reachParentWorld);
      reachPoleWorld.copy(reachFallbackPoleWorld)
        .addScaledVector(reachTargetDirection, -reachFallbackPoleWorld.dot(reachTargetDirection));
    }
    if (reachPoleWorld.lengthSq() < 1e-8) {
      reachFallbackPoleWorld.set(0, 0, 1).applyQuaternion(reachParentWorld);
      reachPoleWorld.copy(reachFallbackPoleWorld)
        .addScaledVector(reachTargetDirection, -reachFallbackPoleWorld.dot(reachTargetDirection));
    }
    if (reachPoleWorld.lengthSq() < 1e-8) return;
    reachPoleWorld.normalize();

    reachElbowTargetWorld.copy(reachShoulderWorld)
      .addScaledVector(reachTargetDirection, solution.elbowAlong)
      .addScaledVector(reachPoleWorld, solution.elbowOffset);
    reachHandTargetWorld.copy(reachShoulderWorld)
      .addScaledVector(reachTargetDirection, solution.solvedDistance);

    if (!aimBoneTowardWorldPoint(
      upper,
      reachElbowWorld,
      reachElbowTargetWorld,
      MAX_SHOULDER_IK_DELTA,
      interactionWeight,
    )) return;
    lower.getWorldPosition(reachElbowWorld);
    hand.getWorldPosition(interactionHandWorld);
    aimBoneTowardWorldPoint(
      lower,
      interactionHandWorld,
      reachHandTargetWorld,
      MAX_ELBOW_IK_DELTA,
      interactionWeight,
    );

    const contactSettle = interactionPhase === "contact"
      ? Math.sin(interactionElapsed * 2.4) * 0.012
      : 0;
    reachWrist.setFromEuler(reachEuler.set(
      -MAX_WRIST_TURN * 0.35,
      MAX_WRIST_TURN * 0.55,
      -MAX_WRIST_TURN * 0.4 + contactSettle,
    ));
    hand.quaternion.slerp(reachWrist, Math.min(1, interactionWeight * 0.72));
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
    for (const n of ["leftUpperLeg", "rightUpperLeg"] as const) {
      const b = bone(n); if (b) b.rotation.x = -1.5;
    }
    for (const n of ["leftLowerLeg", "rightLowerLeg"] as const) {
      const b = bone(n); if (b) b.rotation.x = kneeFlex(1.5);
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
  // Locomotion stays cyclic while she is actually moving, but a slow cadence
  // drift and restrained counter-motion keep every step from landing on the
  // exact same mechanical beat.
  function walk(t: number): void {
    const cadence = t * 3 + Math.sin(t * 0.47) * 0.12;
    const stride = 0.9 + Math.sin(t * 0.31) * 0.08;
    const swing = Math.sin(cadence) * stride;
    const lUp = bone("leftUpperLeg"), rUp = bone("rightUpperLeg");
    const lLo = bone("leftLowerLeg"), rLo = bone("rightLowerLeg");
    const luA = bone("leftUpperArm"), ruA = bone("rightUpperArm");
    const chest = bone("chest") ?? bone("upperChest");
    const head = bone("head");
    const hips = bone("hips");
    const lUpX = swing * 0.5, rUpX = -swing * 0.5;
    const lLoX = kneeFlex(Math.max(0, -swing) * 0.72), rLoX = kneeFlex(Math.max(0, swing) * 0.72);
    if (lUp) lUp.rotation.x = lUpX;
    if (rUp) rUp.rotation.x = rUpX;
    if (lLo) lLo.rotation.x = lLoX;
    if (rLo) rLo.rotation.x = rLoX;
    levelFoot("left", lUpX, lLoX);   // keep the sole near the floor so the
    levelFoot("right", rUpX, rLoX);  // flexed shin doesn't dangle a tiptoe
    if (luA) luA.rotation.x = -swing * 0.34;                 // opposite arm swing
    if (ruA) ruA.rotation.x = swing * 0.34;
    if (chest) chest.rotation.y = swing * 0.065;             // counter-rotation
    if (head) head.rotation.y = -swing * 0.025;
    if (hips) {
      hips.position.y = -Math.abs(Math.sin(cadence)) * 0.016;
      hips.rotation.y = -swing * 0.035;
    }
  }
  function run(t: number): void {
    const cadence = t * 5.6 + Math.sin(t * 0.62) * 0.14;
    const stride = 0.92 + Math.sin(t * 0.39) * 0.07;
    const swing = Math.sin(cadence) * stride;
    const lUp = bone("leftUpperLeg"), rUp = bone("rightUpperLeg");
    const lLo = bone("leftLowerLeg"), rLo = bone("rightLowerLeg");
    const luA = bone("leftUpperArm"), ruA = bone("rightUpperArm");
    const llA = bone("leftLowerArm"), rlA = bone("rightLowerArm");
    const spine = bone("spine");
    const chest = bone("chest") ?? bone("upperChest");
    const hips = bone("hips");
    const lUpX = swing * 0.86, rUpX = -swing * 0.86;
    const lLoX = kneeFlex(Math.max(0, -swing) * 1.35), rLoX = kneeFlex(Math.max(0, swing) * 1.35);
    if (lUp) lUp.rotation.x = lUpX;
    if (rUp) rUp.rotation.x = rUpX;
    if (lLo) lLo.rotation.x = lLoX;
    if (rLo) rLo.rotation.x = rLoX;
    levelFoot("left", lUpX, lLoX);
    levelFoot("right", rUpX, rLoX);
    // Arms stay down at the sides (relaxArms rest z), elbows bent ~90deg,
    // pumping forward/back opposite the legs.
    if (luA) luA.rotation.x = -0.18 + swing * 0.68;
    if (ruA) ruA.rotation.x = -0.18 - swing * 0.68;
    if (llA) llA.rotation.x = -1.4;
    if (rlA) rlA.rotation.x = -1.4;
    if (spine) spine.rotation.x = 0.14;   // forward lean
    if (chest) chest.rotation.y = swing * 0.11;
    if (hips) {
      hips.position.y = -Math.abs(Math.sin(cadence)) * 0.032;
      hips.rotation.y = -swing * 0.05;
    }
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
    const knee = kneeFlex(1.2 * crouch);
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

  // The clip profile merges on top of the mood face after resetValues() has
  // cleared every registered preset/custom expression. Speech uses short,
  // irregular viseme holds with frequent closures; it never leaves a previous
  // vowel latched after talking stops.
  function applyClipExpressions(clip: string, dt: number): void {
    const preset = CLIP_EXPRESSIONS[clip];
    if (preset) for (const name of Object.keys(preset)) setExpr(name, preset[name] ?? 0, true);
    if (clip === "talking") {
      lipPhaseIn -= dt;
      if (lipPhaseIn <= 0) {
        if (Math.random() < 0.24) {
          lipTarget = 0;
          lipPhaseIn = 0.04 + Math.random() * 0.09;
        } else {
          const jump = 1 + Math.floor(Math.random() * (MOUTH.length - 1));
          lipShapeIndex = (lipShapeIndex + jump) % MOUTH.length;
          lipShape = MOUTH[lipShapeIndex] ?? "aa";
          lipTarget = 0.18 + Math.random() * (MAX_MOUTH_WEIGHT - 0.18);
          lipPhaseIn = 0.07 + Math.random() * 0.11;
        }
      }
      const response = lipTarget > lipNow ? 24 : 32;
      lipNow += (lipTarget - lipNow) * (1 - Math.exp(-Math.max(0, dt) * response));
      setExpr(TALK_EMOTIONS[moodLabel] ?? "relaxed", 0.32, true);
    }
    // Write every vowel on every frame. The first frame after speech therefore
    // closes all five explicitly, independent of the prior active shape.
    const vowels = vowelWeightsForSpeech(
      clip === "talking",
      lipShape,
      lipNow > 0.008 ? Math.min(MAX_MOUTH_WEIGHT, lipNow) : 0,
    );
    for (const vowel of MOUTH) setExpr(vowel, vowels[vowel]);
  }

  function applyExpressions(dt: number): void {
    for (const k of Object.keys(exprTarget)) {
      const cur = exprNow[k] ?? 0;
      const next = cur + (c01(exprTarget[k] ?? 0) - cur) * (1 - Math.exp(-Math.max(0, dt) * 3));
      exprNow[k] = next;
      setExpr(k, next);
    }
  }
  // V.4's full-face mood presets include their own eye and mouth shapes. Keep
  // them supportive rather than dominant so a happy mood cannot hold the mouth
  // open or overpower blink/lip controls.
  function capEmotions(): void {
    const em = vrm?.expressionManager;
    if (!em) return;
    // Caps wide enough that the mood range is visible (joyful vs content must
    // differ) while stacked layers still cannot pin an uncanny extreme.
    const caps: Record<string, number> = {
      happy: 0.85,
      sad: 0.7,
      surprised: 0.55,
      angry: 0,
      relaxed: 0.7,
    };
    for (const [name, cap] of Object.entries(caps)) {
      const value = em.getValue(name);
      if (value != null) em.setValue(name, Math.min(cap, c01(value)));
    }
    const names = ["happy", "sad", "surprised", "angry"];
    const sum = names.reduce((s, n) => s + (em.getValue(n) ?? 0), 0);
    if (sum > 1) for (const n of names) em.setValue(n, (em.getValue(n) ?? 0) / sum);
  }

  function autoBlink(dt: number): void {
    if (!blinkActive) {
      blinkIn -= dt;
      if (blinkIn > 0) return;
      blinkActive = true;
      blinkElapsed = 0;
      blinkDuration = 0.11 + Math.random() * 0.06;
      const followup = blinkFollowup;
      blinkFollowup = false;
      blinkShouldFollow = !followup && Math.random() < 0.16;
    }

    blinkElapsed += dt;
    const local = c01(blinkElapsed / blinkDuration);
    const closeEnd = 0.34;
    const v = local < closeEnd
      ? Math.sin((local / closeEnd) * Math.PI * 0.5)
      : Math.cos(((local - closeEnd) / (1 - closeEnd)) * Math.PI * 0.5);
    setBlink(v);

    if (local >= 1) {
      blinkActive = false;
      blinkElapsed = 0;
      if (blinkShouldFollow) {
        blinkFollowup = true;
        blinkIn = 0.08 + Math.random() * 0.08;
      } else {
        blinkIn = nextBlinkDelay();
      }
      blinkShouldFollow = false;
    }
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

  function settledPoseFor(clip: string): string {
    return clip === "cry" || clip === "thinking" ? "idle_soft" : "idle";
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
        // so mixer-driven frames need no manual axisFlip. Every VRoid .vrma
        // carries a hips TRANSLATION track that would pin/displace her root
        // and fight the house's own roaming -- keep rotations only; position
        // belongs to the house (root motion) and the grounding clamp.
        const clip = lib.createVRMAnimationClip(anim, forVrm);
        clip.tracks = clip.tracks.filter((t) => isRotationOnlyVrmTrack(t.name));
        vrmaClips.set(name, clip);
      })
      .catch(() => {
        vrmaLoading.delete(name);
        vrmaFailed.add(name);   // procedural covers it permanently
      });
  }

  function playVrma(name: string, clip: THREE.AnimationClip, mode: PlayMode = "loop"): void {
    if (!vrm) return;
    if (!mixer) {
      mixer = new THREE.AnimationMixer(vrm.scene);
      mixer.addEventListener("finished", onActionFinished as never);
    }
    const next = mixer.clipAction(clip);
    const revived = fading.indexOf(next);
    if (revived >= 0) fading.splice(revived, 1);   // wanted again mid-fade-out
    next.reset();
    next.enabled = true;
    next.setEffectiveTimeScale(1);
    next.setEffectiveWeight(1);
    if (mode === "loop") next.setLoop(THREE.LoopRepeat, Infinity);
    else next.setLoop(THREE.LoopRepeat, mode === "twice" ? 2 : 1);
    next.clampWhenFinished = true;   // hold the last frame; the fade-out blends it away
    next.play();
    actionPlayback.set(next, { name, mode });
    const prev = currentAction;
    if (prev && prev !== next) { prev.crossFadeTo(next, VRMA_FADE, false); fading.push(prev); }
    else next.fadeIn(VRMA_FADE);
    currentAction = next;
    currentVrmaName = name;
    currentPlayMode = mode;
  }

  function stopVrma(): void {
    if (!currentAction) return;
    currentAction.fadeOut(VRMA_FADE);
    fading.push(currentAction);
    currentAction = null;
    currentVrmaName = null;
    currentPlayMode = null;
  }

  // Fully faded actions must be stop()ped so their bindings release the bones
  // back to the procedural clips.
  function reapFaded(): void {
    for (let i = fading.length - 1; i >= 0; i--) {
      const a = fading[i];
      if (a && a.getEffectiveWeight() <= 0.001) {
        a.stop();
        actionPlayback.delete(a);
        fading.splice(i, 1);
      }
    }
  }

  function latestFadingPlayback(): VrmMotionPlayback | null {
    for (let i = fading.length - 1; i >= 0; i--) {
      const action = fading[i];
      if (!action) continue;
      const playback = actionPlayback.get(action);
      if (playback) return playback;
    }
    return null;
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
      v4MouthCorrectionBindings = discoverV4MouthCorrections(loaded);
      clearV4MouthCorrections();
      resetFaceValues();
      resetBlinkTiming();
      resetLipTiming();
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
    if (res.status === 401) {
      // The auth boundary wants a session cookie; the legacy token query no
      // longer authorizes anything. Point at the fix instead of the symptom.
      throw new Error("authorization session needed - reopen through START_HERE or the launcher");
    }
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
    const meta = loaded.meta as { metaVersion?: string };
    const isV0 = meta.metaVersion === "0";
    if (isV0) vrmLib.VRMUtils.rotateVRM0(loaded);
    axisFlip = isV0 ? -1 : 1;

    vrmLib.VRMUtils.removeUnnecessaryVertices(loaded.scene);
    vrmLib.VRMUtils.combineSkeletons(loaded.scene);
    loaded.scene.traverse((o) => { o.frustumCulled = false; });
    return loaded;
  }

  function debugPositionOf(node: THREE.Object3D | null, world: boolean): VrmDebugPosition | null {
    if (!node) return null;
    if (world) node.getWorldPosition(debugPositionVector);
    else debugPositionVector.copy(node.position);
    return {
      x: roundTelemetry(debugPositionVector.x),
      y: roundTelemetry(debugPositionVector.y),
      z: roundTelemetry(debugPositionVector.z),
    };
  }

  return {
    get status(): EmbodimentStatus {
      return status;
    },

    get interactionContactStatus(): VrmInteractionContactStatus {
      return {
        available: interactionContactAvailable,
        inContact: interactionInContact,
        distance: interactionContactDistance,
        threshold: INTERACTION_CONTACT_THRESHOLD,
      };
    },

    async activate(): Promise<boolean> {
      if (vrm && wrapper) {   // cached fast path: just re-show
        resetFaceValues();
        clearV4MouthCorrections();
        resetBlinkTiming();
        resetLipTiming();
        clipTime = 0;
        finishedForClip = null;
        forcedReplayClip = null;
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
      resetFaceValues();
      clearV4MouthCorrections();
      resetBlinkTiming();
      resetLipTiming();
      clearInteraction();
      if (wrapper) wrapper.visible = false;
      status = "idle";
      deps.onStatus("idle");
    },

    dispose(): void {
      resetFaceValues();
      clearV4MouthCorrections();
      clearInteraction();
      if (mixer) {
        mixer.stopAllAction();
        if (vrm) mixer.uncacheRoot(vrm.scene);
      }
      mixer = null;
      currentAction = null;
      currentVrmaName = null;
      currentPlayMode = null;
      forcedReplayClip = null;
      fading.length = 0;
      vrmaClips.clear();   // clips were retargeted to this vrm instance
      vrmaLoading.clear();
      if (wrapper) deps.parent.remove(wrapper);
      if (vrm && deepDispose) deepDispose(vrm.scene);
      vrm = null;
      wrapper = null;
      v4MouthCorrectionBindings = [];
      for (const name of Object.keys(mouthCorrectionNow)) delete mouthCorrectionNow[name];
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

    setSpriteState(name, moving, talking, forceOneShot = false): void {
      spriteName = name;
      spriteMoving = moving;
      spriteTalking = talking;
      const requestedClip = resolveClip();
      if (forceOneShot && (requestedClip === "point" || requestedClip === "wave")) {
        clipTime = 0;
        finishedForClip = null;
        forcedReplayClip = requestedClip;
      }
    },

    setInteractionTarget(target, phase): void {
      invalidateInteractionContactStatus();
      if (phase === "retract") {
        if (interactionTarget && validInteractionTarget(target)) interactionTarget.copy(target);
        if (interactionPhase !== phase) interactionElapsed = 0;
        interactionPhase = phase;
        return;
      }
      if (!validInteractionTarget(target)) {
        if (interactionPhase !== "retract") interactionElapsed = 0;
        interactionPhase = "retract";
        return;
      }
      if (!interactionTarget) interactionTarget = new THREE.Vector3();
      interactionTarget.copy(target);
      if (interactionPhase !== phase) interactionElapsed = 0;
      interactionPhase = phase;
    },

    update(dt, camera, engaged, distanceToPlayer = Infinity): void {
      if (status !== "active" || !vrm || !wrapper || !wrapper.visible) return;
      dt = Math.max(0, Math.min(0.1, Number.isFinite(dt) ? dt : 0));
      const interactionActive = advanceInteraction(dt);
      const next = resolveClip();
      if (next !== clipName) {
        const previous = clipName;
        clipName = next;
        clipTime = 0;              // fresh cycle
        finishedForClip = null;    // a new state may perform again
        if (forcedReplayClip && forcedReplayClip !== next) forcedReplayClip = null;
        if (flourishName) { flourishName = null; flourishIn = nextFlourishDelay(); }
        if (previous === "talking" || next === "talking") resetLipTiming();
        if (clipHoldsEyesClosed(previous) || clipHoldsEyesClosed(next)) resetBlinkTiming();
      }
      clipTime += dt;

      // Real .vrma motion when its clip is ready; procedural otherwise.
      // Locomotion is always procedural -- no walking/running .vrma exists,
      // the ported cycles carry it -- and while moving any playing action
      // fades out underneath the cycle. Idle rests on the procedural base and
      // earns a randomized one-shot flourish every so often; finished one-shot
      // and twice performances settle back to procedural until the state
      // changes instead of looping like an animatronic.
      let vrmaDriven = false;
      let wantVrma: string | null = null;
      let wantMode: PlayMode = "loop";
      if (!spriteMoving && !interactionActive) {
        const mapped = CLIP_VRMA[clipName] ?? null;
        if (mapped && shouldScheduleVrmPerformance(clipName, finishedForClip)) {
          wantVrma = mapped;
          wantMode = VRMA_MODE[clipName] ?? "once";
        } else if (!mapped && (clipName === "idle" || clipName === "idle_soft")) {
          if (!flourishName) {
            flourishIn -= dt;
            if (flourishIn <= 0) flourishName = pickFlourish();
          }
          if (flourishName) {
            wantVrma = flourishName;
            wantMode = "once";
          }
        }
      }
      if (wantVrma && deps.animationUrl && !vrmaFailed.has(wantVrma)) {
        const clip = vrmaClips.get(wantVrma);
        if (clip) {
          const forceReplay = forcedReplayClip === clipName;
          if (currentVrmaName !== wantVrma || forceReplay) {
            playVrma(wantVrma, clip, wantMode);
            if (forceReplay) forcedReplayClip = null;
          }
          vrmaDriven = true;
        } else {
          requestVrma(wantVrma);   // procedural carries this frame while it fetches
        }
      } else if (wantVrma && vrmaFailed.has(wantVrma) && flourishName === wantVrma) {
        flourishName = null;       // unfetchable flourish: reschedule, stay procedural
        flourishIn = nextFlourishDelay();
      }
      if (!vrmaDriven) stopVrma();

      // The face belongs entirely to this frame. resetValues clears every
      // registered expression, including custom values an animation or prior
      // state may have left behind; the desired mood/clip/blink is then rebuilt.
      resetFaceValues();
      applyExpressions(dt);

      const performanceLimit = PROCEDURAL_PERFORMANCE_SECONDS[clipName];
      const performanceSettled = finishedForClip === clipName
        || (!vrmaDriven && performanceLimit !== undefined && clipTime >= performanceLimit);
      const resolvedPoseClip = performanceSettled ? settledPoseFor(clipName) : clipName;
      // A terminal solve owns the stationary right arm. Start it from the
      // stable idle skeleton instead of the procedural point/wave pose, whose
      // raised shoulder can put an otherwise reachable panel outside the
      // bounded IK delta. Walking approach frames keep their leg cycle.
      const poseClip = interactionActive && !spriteMoving ? "idle" : resolvedPoseClip;
      activePoseName = poseClip;

      if (!vrmaDriven) {
        for (const n of BONES) { const b = bone(n); if (b) b.rotation.set(0, 0, 0); }
        const hips = bone("hips");
        if (hips) hips.position.set(0, 0, 0);
        relaxArms();
        (CLIPS[poseClip] ?? idle)(clipTime);
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
      applyClipExpressions(poseClip, dt);
      if (clipHoldsEyesClosed(poseClip)) setBlink(1);
      else autoBlink(dt);
      capEmotions();   // stacked layers must never exceed a natural face

      // The mixer updates after any procedural writes so a fading action
      // blends from/into the procedural pose instead of hard-cutting.
      if (mixer) { mixer.update(dt); reapFaded(); }
      // Terminal contact owns only the right arm and gaze. Absolute bounded
      // targets are rebuilt after the mixer every frame, preventing additive
      // rotation drift while still allowing a fading clip to settle beneath it.
      if (interactionActive) applyInteractionReach();
      if (vrm.lookAt) {
        if (interactionActive && interactionTarget) {
          interactionLookTarget.position.copy(interactionTarget);
          vrm.lookAt.target = interactionLookTarget;
        } else {
          vrm.lookAt.target = engaged || distanceToPlayer < NOTICE_DISTANCE ? camera : null;
        }
      }
      clearV4MouthCorrections();
      vrm.update(dt);
      applyV4MouthCorrections();
      groundFeet(dt);   // after vrm.update: clamp the posed soles to the floor
      updateInteractionContactStatus();
    },

    debug(): VrmEmbodimentDebug {
      const springs = (vrm as unknown as {
        springBoneManager?: { joints?: unknown; colliders?: unknown };
      } | null)?.springBoneManager;
      const face: Record<string, number> = {};
      const vowels = vowelWeightsForSpeech(false, "aa", 0);
      const em = vrm?.expressionManager;
      if (em) {
        for (const name of [
          "blink", "blinkLeft", "blinkRight", "happy", "sad", "relaxed", "surprised", "angry", "neutral",
          ...MOUTH,
        ]) {
          const value = em.getValue(name);
          if (value != null) face[name] = roundTelemetry(value);
        }
        for (const vowel of MOUTH) vowels[vowel] = face[vowel] ?? 0;
      }
      const mouthCorrections = Object.fromEntries(
        Object.entries(mouthCorrectionNow).map(([name, value]) => [name, roundTelemetry(value)]),
      );
      const root = vrm?.scene ?? null;
      const rawHips = vrm?.humanoid.getRawBoneNode("hips") ?? null;
      const normalizedHips = bone("hips");
      const motionTelemetry = resolveVrmMotionTelemetry(
        currentVrmaName && currentPlayMode ? { name: currentVrmaName, mode: currentPlayMode } : null,
        latestFadingPlayback(),
        activePoseName,
      );
      return {
        groundBase,
        groundOffset,
        lowestSoleY: lowestSole(),
        springJoints: collectionSize(springs?.joints),
        springColliders: collectionSize(springs?.colliders),
        face,
        vowels,
        mouthCorrections,
        mouthCorrectionBindings: v4MouthCorrectionBindings.length,
        activeClip: clipName,
        activePose: activePoseName,
        ...motionTelemetry,
        rootPosition: debugPositionOf(root, true),
        rootLocalPosition: debugPositionOf(root, false),
        hipsPosition: debugPositionOf(rawHips, true),
        hipsLocalPosition: debugPositionOf(normalizedHips, false),
        handContactDistance: interactionContactDistance == null
          ? null
          : roundTelemetry(interactionContactDistance),
        interactionPhase,
        interactionTargetReachable,
      };
    },
  };
}

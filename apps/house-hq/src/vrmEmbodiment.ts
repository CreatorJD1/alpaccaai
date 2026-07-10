/* Alpecca's VRM embodiment inside the House HQ scene.
 *
 * Ports the working /vrm page driver (web/vrm.html) and her mood mapping
 * (alpecca/vrm.py) into a self-contained module: the caller owns the scene
 * and the sprite state machine; this module only wears the body. The heavy
 * deps (GLTFLoader, @pixiv/three-vrm) are dynamically imported inside
 * activate() so Vite code-splits them and the default bundle is unchanged.
 */
import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";

export type EmbodimentStatus = "idle" | "loading" | "active" | "failed";

export interface VrmEmbodimentDeps {
  parent: THREE.Group;
  targetHeight: number;
  groundClearance: number;
  manifestUrl: () => string;
  modelUrl: (file: string) => string;
  onStatus: (status: EmbodimentStatus, detail?: string, progress?: number) => void;
}

export interface VrmEmbodiment {
  readonly status: EmbodimentStatus;
  activate(): Promise<boolean>;
  deactivate(): void;
  dispose(): void;
  setMood(label: string, dims: { love?: number; compassion?: number; fear?: number; energy?: number }): void;
  setSpriteState(name: string, moving: boolean, talking: boolean): void;
  update(dt: number, camera: THREE.Camera, engaged: boolean): void;
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

  let moodLabel = "content";
  const dims: MoodDims = { love: 0.5, compassion: 0.5, fear: 0.2, energy: 0.5 };
  let exprTarget: Record<string, number> = expressionsForState(dims);
  const exprNow: Record<string, number> = {};

  let spriteName = "";
  let spriteMoving = false;
  let spriteTalking = false;
  let movePhase = 0;

  let clipName = "idle";
  let clipTime = 0;   // restarts when the resolved clip changes (fresh cycle)
  let elapsed = 0;    // monotonic while active; drives the blink cycle

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
    setExpr("blink", 1.0); setExpr("relaxed", 0.6, true);
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
  function talking(t: number): void {
    idle(t * 0.5);
    // Cycle mouth shapes at speech cadence; overlay the mood's talk emotion.
    const cyc = 0.28, idx = Math.floor(t / cyc), local = (t % cyc) / cyc;
    const env = Math.max(0, Math.sin(local * Math.PI) * (0.55 + 0.35 * Math.sin(t * 3.0)));
    MOUTH.forEach((s, i) => setExpr(s, i === idx % MOUTH.length ? env : 0));
    setExpr(TALK_EMOTIONS[moodLabel] ?? "relaxed", 0.55, true);
    const head = bone("head"); if (head) head.rotation.x += Math.sin(t * 4) * 0.02;
  }

  const CLIPS: Record<string, (t: number) => void> = {
    idle, idle_soft: idleSoft, wave, cheer, thinking, dance, sit, sleep, cry, talking,
  };

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

  // Which clip she performs right now: speech wins, then the sprite pose,
  // then locomotion (walk substitute), then her mood's clip.
  function resolveClip(): string {
    if (spriteTalking) return "talking";
    const n = spriteName.toLowerCase();
    if (n.startsWith("wave")) return "wave";
    if (n.startsWith("sit")) return "sit";
    if (n.startsWith("sleep")) return "sleep";
    if (n.startsWith("kneel") || n.startsWith("crouch")) return "thinking";
    if (spriteMoving) return "idle_soft";
    return MOOD_CLIPS[moodLabel] ?? "idle";
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
      const { height, minY } = measurePosed(loaded.scene, w);
      const scale = deps.targetHeight / Math.max(0.1, height);
      w.scale.setScalar(scale);
      w.position.y = -minY * scale + deps.groundClearance;

      vrm = loaded;
      wrapper = w;
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
    // Dynamic imports keep GLTFLoader + three-vrm out of the default chunk.
    const [{ GLTFLoader }, vrmLib] = await Promise.all([
      import("three/examples/jsm/loaders/GLTFLoader.js"),
      import("@pixiv/three-vrm"),
    ]);
    deepDispose = vrmLib.VRMUtils.deepDispose;

    const res = await fetch(deps.manifestUrl());
    if (!res.ok) throw new Error(`manifest fetch failed (HTTP ${res.status})`);
    const man = (await res.json()) as { vrm_mode?: boolean; model_file?: string | null };
    if (!man.vrm_mode || !man.model_file) throw new Error("no VRM body installed (manifest has no model_file)");
    const file = man.model_file;

    const loader = new GLTFLoader();
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
      if (wrapper) deps.parent.remove(wrapper);
      if (vrm && deepDispose) deepDispose(vrm.scene);
      vrm = null;
      wrapper = null;
      loadPromise = null;
      deepDispose = null;
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

    update(dt, camera, engaged): void {
      if (status !== "active" || !vrm || !wrapper || !wrapper.visible) return;
      elapsed += dt;
      const next = resolveClip();
      if (next !== clipName) { clipName = next; clipTime = 0; }   // fresh cycle
      clipTime += dt;
      if (spriteMoving) movePhase += dt * 6;

      for (const n of BONES) { const b = bone(n); if (b) b.rotation.set(0, 0, 0); }
      const hips = bone("hips");
      if (hips) hips.position.set(0, 0, 0);
      relaxArms();
      for (const s of MOUTH) setExpr(s, 0);
      setExpr("blink", 0);
      // Mood weights first, then the clip -- clips raise on top (atLeast), so
      // a sleeping blink or a talking emotion overlay is never overwritten.
      applyExpressions(dt);
      (CLIPS[clipName] ?? idle)(clipTime);
      if (spriteMoving) {
        // Walk substitute overlay: hip bob + a slight forward lean.
        if (hips) hips.position.y -= Math.abs(Math.sin(movePhase)) * 0.03;
        const chest = bone("chest") ?? bone("upperChest");
        if (chest) chest.rotation.x += 0.12;
      }
      // Clip constants are in the 1.0 frame; 0.x normalized bones spin x/z
      // the other way (measured in web/vrm.html), so negate.
      if (axisFlip < 0) {
        for (const n of BONES) {
          const b = bone(n);
          if (b) { b.rotation.x *= -1; b.rotation.z *= -1; }
        }
      }
      if (clipName !== "sleep") autoBlink(elapsed);
      if (vrm.lookAt) vrm.lookAt.target = engaged ? camera : null;
      vrm.update(dt);
    },
  };
}

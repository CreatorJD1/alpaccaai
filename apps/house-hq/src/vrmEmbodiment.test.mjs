import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";

import {
  applyVrmLookAtTransition,
  constrainVrmLowerBodyJoint,
  isNeutralVrmGaze,
  isConfirmedVrmInteractionContact,
  isVrmFootPlantWithinReach,
  isRotationOnlyVrmTrack,
  normalizeVrmEmotionWeights,
  resolveVrmBodyYawFromDisplacement,
  resolveVrmFootRoll,
  resolveVrmFootSwing,
  resolveVrmFootLiftHeight,
  resolveVrmFootContactY,
  resolveVrmLowestFootContactY,
  resolveVrmGroundTarget,
  resolveVrmGazeFollow,
  resolveVrmGazeTargetAngles,
  resolveVrmMotionTelemetry,
  resolveVrmKneeFlex,
  resolveVrmKneePole,
  resolveVrmPlayModeForQuaternionSeam,
  resolveVrmWalkGait,
  shouldBlendVrmProceduralTransition,
  shouldResetVrmBlinkTiming,
  shouldResetVrmGaitPhase,
  shouldScheduleVrmPerformance,
  shouldSettleProceduralPerformance,
  shouldStabilizeVrmSpringTransition,
  solveTwoBoneReach,
  strideDistanceForMotion,
  v4MoodMouthCorrectionWeights,
  v4MoodComponentCorrectionWeights,
  VRM_NEUTRAL_GAZE,
  vrmQuaternionEndpointSeamRadians,
  vowelWeightsForSpeech,
} from "./vrmEmbodiment.ts";

const near = (actual, expected, epsilon = 1e-9) => {
  assert.ok(Math.abs(actual - expected) <= epsilon, `${actual} != ${expected}`);
};
const radians = (degrees) => degrees * Math.PI / 180;

test("speech stop closes every vowel and cancels V4 mood mouth components", () => {
  const speaking = vowelWeightsForSpeech(true, "oh", 0.55);
  assert.equal(speaking.oh, 0.55);

  const stopped = vowelWeightsForSpeech(false, "oh", speaking.oh);
  assert.deepEqual(stopped, { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });

  const mood = { happy: 0.82, sad: 0.17, surprised: 0.31, relaxed: 0.44, angry: 0 };
  const correction = v4MoodMouthCorrectionWeights(mood);
  near(mood.happy + correction.Fcl_MTH_Joy, 0);
  near(mood.sad + correction.Fcl_MTH_Sorrow, 0);
  near(mood.surprised + correction.Fcl_MTH_Surprised, 0);
  near(mood.relaxed + correction.Fcl_MTH_Fun, 0);
  near(mood.angry + correction.Fcl_MTH_Angry, 0);
});

test("V4 mood eye corrections keep a small reactive eye component without pinning eyes closed", () => {
  const mood = { happy: 0.82, sad: 0.17, surprised: 0.31, relaxed: 0.7, angry: 0 };
  const correction = v4MoodComponentCorrectionWeights(mood, "eye");

  assert.ok(correction.Fcl_EYE_Fun < 0);
  assert.ok(mood.relaxed + correction.Fcl_EYE_Fun > 0);
  assert.ok(mood.relaxed + correction.Fcl_EYE_Fun < mood.relaxed);
  assert.ok(mood.surprised + correction.Fcl_EYE_Surprised > 0);
});

test("full-face mood presets share one budget including relaxed", () => {
  const normalized = normalizeVrmEmotionWeights({
    happy: 0.9,
    sad: 0.8,
    surprised: 0.7,
    relaxed: 0.9,
    angry: 0.6,
  });

  near(Object.values(normalized).reduce((sum, value) => sum + value, 0), 1);
  assert.equal(normalized.angry, 0);
  assert.ok(normalized.happy < 0.85);
  assert.ok(normalized.relaxed < 0.7, "relaxed cannot sit outside the shared face budget");
});

test("walk gait alternates swing-foot lift and uses stronger anatomical knee flex", () => {
  const rightSwing = resolveVrmWalkGait(Math.PI / 2);
  const leftSwing = resolveVrmWalkGait(-Math.PI / 2);

  assert.ok(rightSwing.rightLift > 0.99);
  assert.equal(rightSwing.leftLift, 0);
  assert.ok(rightSwing.rightKneeFlex > 1.1);
  assert.ok(rightSwing.rightUpperLegX < 0);
  assert.ok(leftSwing.leftLift > 0.99);
  assert.equal(leftSwing.rightLift, 0);
  assert.ok(leftSwing.leftKneeFlex > 1.1);
  assert.ok(leftSwing.leftUpperLegX < 0);
});

test("knee flex maps to the anatomical side for VRM 1.0 and legacy VRM 0.x", () => {
  assert.ok(resolveVrmKneeFlex(0.8, 1) > 0, "VRM 1.0 shin flexes on positive local X");
  assert.ok(resolveVrmKneeFlex(0.8, -1) < 0, "rotated VRM 0.x uses the opposite local axis");
  assert.equal(resolveVrmKneeFlex(-0.8, 1), 0, "knee flex never becomes hyperextension");
});

test("lower-body joint projection blocks inverted knees and excessive twist", () => {
  assert.deepEqual(
    constrainVrmLowerBodyJoint("lowerLeg", { x: -1.4, y: 0.8, z: -0.7 }, 1),
    { x: -0.03, y: 0.09, z: -0.09 },
  );
  assert.deepEqual(
    constrainVrmLowerBodyJoint("lowerLeg", { x: 1.4, y: -0.8, z: 0.7 }, -1),
    { x: 0.03, y: -0.09, z: 0.09 },
  );
  assert.deepEqual(
    constrainVrmLowerBodyJoint("upperLeg", { x: -4, y: 2, z: -2 }, 1),
    { x: -1.25, y: 0.42, z: -0.38 },
  );
});

test("stale planted feet are reacquired before the leg can split", () => {
  assert.equal(isVrmFootPlantWithinReach(0.2, 0.4), true);
  assert.equal(isVrmFootPlantWithinReach(0.31, 0.4), false);
  assert.equal(isVrmFootPlantWithinReach(Number.NaN, 0.4), false);
});

test("planted-leg IK uses the forward anatomical plane instead of folding laterally", () => {
  const target = new THREE.Vector3(0, -1, 0);
  const forward = new THREE.Vector3(0, 0, 1);
  const corrected = resolveVrmKneePole(new THREE.Vector3(0.8, -0.5, -0.2), target, forward);
  const retained = resolveVrmKneePole(new THREE.Vector3(-0.8, -0.5, 0.2), target, forward);
  assert.ok(corrected && corrected.z > 0.99);
  assert.ok(retained && retained.z > 0.99);
  near(corrected.x, 0);
  near(retained.x, 0);
});

test("planted-foot gait gives one foot a monotonic lifted swing while the other stays planted", () => {
  const rightLiftOff = resolveVrmFootSwing(0, "right");
  const rightMidSwing = resolveVrmFootSwing(Math.PI / 2, "right");
  const rightTouchdown = resolveVrmFootSwing(Math.PI, "right");
  const leftMidSwing = resolveVrmFootSwing(Math.PI * 1.5, "left");

  assert.deepEqual(rightLiftOff, { active: true, progress: 0, lift: 0 });
  assert.equal(rightMidSwing.active, true);
  near(rightMidSwing.progress, 0.5);
  assert.ok(rightMidSwing.lift > 0.99);
  assert.deepEqual(rightTouchdown, { active: false, progress: 0, lift: 0 });
  assert.equal(leftMidSwing.active, true);
  near(leftMidSwing.progress, 0.5);
  assert.ok(leftMidSwing.lift > 0.99);
});

test("stride distance remains synchronized to actual world movement", () => {
  near(strideDistanceForMotion(0.24, Math.PI * 2), 0.24);
  assert.equal(strideDistanceForMotion(0, Math.PI), 0);
  assert.equal(strideDistanceForMotion(0.8, 0.01), 0.5);
});

test("the walk-reference gait still lifts a foot with no horizontal stride", () => {
  near(resolveVrmFootLiftHeight(1, 0), 0.055);
  near(resolveVrmFootLiftHeight(1, 0.46), 0.1);
  assert.equal(resolveVrmFootLiftHeight(0, 0.46), 0);
});

test("foot roll is phase-locked: toe-off, airborne dorsiflexion, then heel-led contact", () => {
  const liftOff = resolveVrmFootRoll(resolveVrmFootSwing(0.04 * Math.PI, "right"));
  const midSwing = resolveVrmFootRoll(resolveVrmFootSwing(Math.PI / 2, "right"));
  const preContact = resolveVrmFootRoll(resolveVrmFootSwing(0.82 * Math.PI, "right"));
  const stance = resolveVrmFootRoll(resolveVrmFootSwing(Math.PI, "right"));

  assert.ok(liftOff.toeOff > 0.15);
  assert.ok(liftOff.pitch > 0);
  assert.ok(midSwing.dorsiflex > 0.13);
  assert.ok(midSwing.pitch < 0);
  assert.ok(preContact.heelStrike > 0.01);
  assert.ok(preContact.pitch < 0);
  assert.deepEqual(stance, { pitch: 0, toeOff: 0, dorsiflex: 0, heelStrike: 0 });
});

test("transformed V4 heel/toe contacts follow ankle roll instead of a fixed world-Y offset", () => {
  const ankleY = 0.12954;
  // Measured from V4's skinned heel and toe surface in their raw-bone frames.
  const heel = { y: -0.129752, z: -0.042824 };
  // The toe lives under the child toe bone; expressed in the ankle frame this
  // is its V4 pivot plus the measured toe-surface point.
  const toe = { y: -0.128275, z: 0.110473 };
  const flatHeel = resolveVrmFootContactY(ankleY, heel, 0);
  const flatToe = resolveVrmFootContactY(ankleY, toe, 0);
  const toeOffPitch = 0.2;
  const rolledHeel = resolveVrmFootContactY(ankleY, heel, toeOffPitch);
  const rolledToe = resolveVrmFootContactY(ankleY, toe, toeOffPitch);

  assert.ok(Math.abs(flatHeel) < 0.001);
  assert.ok(Math.abs(flatToe) < 0.002);
  assert.ok(rolledHeel > flatHeel + 0.005, "heel rises during toe-off");
  assert.ok(rolledToe < flatToe - 0.01, "toe becomes the lower contact during toe-off");
  near(resolveVrmLowestFootContactY(ankleY, heel, toe, toeOffPitch), rolledToe);
});

test("only locomotion-to-rest transitions receive the short procedural blend", () => {
  assert.equal(shouldBlendVrmProceduralTransition("walk", "idle"), true);
  assert.equal(shouldBlendVrmProceduralTransition("talking", "walk"), true);
  assert.equal(shouldBlendVrmProceduralTransition("walk", "wave"), false);
  assert.equal(shouldBlendVrmProceduralTransition("idle", "thinking"), false);
});

test("a stopped gait restarts from lift-off instead of resuming a stale mid-step phase", () => {
  let phase = 4.7;
  if (shouldResetVrmGaitPhase("idle", "walk")) phase = 0;
  assert.equal(phase, 0);

  phase += 0.42 * 2.45;
  const interruptedPhase = phase;
  if (shouldResetVrmGaitPhase("walk", "idle")) phase = 0;
  assert.equal(phase, interruptedPhase, "stopping does not fabricate another step");

  if (shouldResetVrmGaitPhase("idle", "walk")) phase = 0;
  assert.equal(phase, 0, "the next route starts at a deterministic lift-off boundary");
  assert.equal(shouldResetVrmGaitPhase("walk", "run"), false, "walk-to-run preserves a live stride");
  assert.equal(shouldResetVrmGaitPhase("wave", "walk"), true, "any fresh locomotion performance resets");
});

test("body yaw damps toward collision-resolved displacement and holds while blocked", () => {
  let yaw = 0;
  yaw = resolveVrmBodyYawFromDisplacement(yaw, 0.2, 0, 1 / 60);
  assert.ok(yaw > 0 && yaw < Math.PI / 2, "the first resolved step turns without snapping");
  for (let frame = 0; frame < 90; frame += 1) {
    yaw = resolveVrmBodyYawFromDisplacement(yaw, 0.2, 0, 1 / 60);
  }
  near(yaw, Math.PI / 2, 1e-7);
  assert.equal(resolveVrmBodyYawFromDisplacement(yaw, 0, 0, 1 / 60), yaw);
});

test("VRMA repeat modes are retained only across conservative quaternion endpoint seams", () => {
  const quaternionY = (degrees) => {
    const half = degrees * Math.PI / 360;
    return [0, Math.sin(half), 0, Math.cos(half)];
  };
  const identity = [0, 0, 0, 1];
  const safeTrack = {
    name: "Normalized_J_Bip_C_Hips.quaternion",
    values: new Float32Array([...identity, ...quaternionY(7)]),
  };
  const seamTrack = {
    name: "Normalized_J_Bip_C_Hips.quaternion",
    values: new Float32Array([...identity, ...quaternionY(12)]),
  };

  assert.ok(vrmQuaternionEndpointSeamRadians(safeTrack.values) < 8 * Math.PI / 180);
  assert.ok(vrmQuaternionEndpointSeamRadians(seamTrack.values) > 8 * Math.PI / 180);
  assert.equal(resolveVrmPlayModeForQuaternionSeam("loop", [safeTrack]), "loop");
  assert.equal(resolveVrmPlayModeForQuaternionSeam("twice", [safeTrack]), "twice");
  assert.equal(resolveVrmPlayModeForQuaternionSeam("loop", [safeTrack, seamTrack]), "once");
  assert.equal(resolveVrmPlayModeForQuaternionSeam("twice", [seamTrack]), "once");
  assert.equal(resolveVrmPlayModeForQuaternionSeam("once", [seamTrack]), "once");
  near(vrmQuaternionEndpointSeamRadians(new Float32Array([...identity, 0, 0, 0, -1])), 0);
});

test("gaze target angles follow the VRM 1.0 forward, right, and up axes", () => {
  const front = resolveVrmGazeTargetAngles({ x: 0, y: 0, z: 1 });
  const right = resolveVrmGazeTargetAngles({ x: 1, y: 0, z: 1 });
  const up = resolveVrmGazeTargetAngles({ x: 0, y: 1, z: 1 });

  near(front.yaw, 0);
  near(front.pitch, 0);
  near(right.yaw, Math.PI / 4);
  near(right.pitch, 0);
  near(up.yaw, 0);
  near(up.pitch, -Math.PI / 4);
  assert.equal(resolveVrmGazeTargetAngles({ x: 0, y: 0, z: 0 }), null);
  assert.equal(resolveVrmGazeTargetAngles({ x: Number.NaN, y: 0, z: 1 }), null);
});

test("eyes lead damped head and neck follow without snapping on target reversal", () => {
  const right = { yaw: radians(35), pitch: radians(-20) };
  const first = resolveVrmGazeFollow(VRM_NEUTRAL_GAZE, right, 1 / 60);

  assert.ok(first.eyeYaw > first.headYaw + first.neckYaw, "eyes should acquire the target first");
  assert.ok(first.eyePitch < first.headPitch + first.neckPitch, "eyes should lead upward too");
  assert.ok(first.eyeYaw < radians(22));
  assert.ok(first.headYaw < radians(14));
  assert.ok(first.neckYaw < radians(7));

  const reversed = resolveVrmGazeFollow(first, { yaw: -right.yaw, pitch: -right.pitch }, 1 / 60);
  assert.ok(reversed.eyeYaw < first.eyeYaw, "the eye begins reversing immediately");
  assert.ok(reversed.eyeYaw > -radians(22), "the eye cannot snap to the opposite clamp");
  assert.ok(reversed.headYaw > -radians(14), "the head cannot snap to the opposite clamp");
  assert.ok(reversed.neckYaw > -radians(7), "the neck cannot snap to the opposite clamp");
});

test("gaze follow settles at conservative asymmetric eye, head, and neck clamps", () => {
  let downRight = VRM_NEUTRAL_GAZE;
  for (let frame = 0; frame < 300; frame += 1) {
    downRight = resolveVrmGazeFollow(downRight, { yaw: Math.PI, pitch: Math.PI / 2 }, 1 / 60);
  }
  near(downRight.eyeYaw, radians(22), 1e-8);
  near(downRight.headYaw, radians(14), 1e-8);
  near(downRight.neckYaw, radians(7), 1e-8);
  near(downRight.eyePitch, radians(14), 1e-8);
  near(downRight.headPitch, radians(10), 1e-8);
  near(downRight.neckPitch, radians(5), 1e-8);

  let upLeft = downRight;
  for (let frame = 0; frame < 300; frame += 1) {
    upLeft = resolveVrmGazeFollow(upLeft, { yaw: -Math.PI, pitch: -Math.PI / 2 }, 1 / 60);
  }
  near(upLeft.eyeYaw, -radians(22), 1e-8);
  near(upLeft.headYaw, -radians(14), 1e-8);
  near(upLeft.neckYaw, -radians(7), 1e-8);
  near(upLeft.eyePitch, -radians(12), 1e-8);
  near(upLeft.headPitch, -radians(8), 1e-8);
  near(upLeft.neckPitch, -radians(4), 1e-8);
});

test("target loss returns smoothly and finishes at an exact neutral gaze", () => {
  let active = VRM_NEUTRAL_GAZE;
  for (let frame = 0; frame < 120; frame += 1) {
    active = resolveVrmGazeFollow(active, { yaw: radians(30), pitch: radians(12) }, 1 / 60);
  }

  const firstReturn = resolveVrmGazeFollow(active, null, 1 / 60);
  assert.ok(firstReturn.eyeYaw > 0 && firstReturn.eyeYaw < active.eyeYaw);
  assert.ok(firstReturn.headYaw > 0 && firstReturn.headYaw < active.headYaw);
  assert.ok(firstReturn.neckYaw > 0 && firstReturn.neckYaw < active.neckYaw);

  let sixtyFps = active;
  let thirtyFps = active;
  for (let frame = 0; frame < 30; frame += 1) sixtyFps = resolveVrmGazeFollow(sixtyFps, null, 1 / 60);
  for (let frame = 0; frame < 15; frame += 1) thirtyFps = resolveVrmGazeFollow(thirtyFps, null, 1 / 30);
  for (const component of Object.keys(VRM_NEUTRAL_GAZE)) {
    near(sixtyFps[component], thirtyFps[component], 1e-12);
  }

  let neutral = firstReturn;
  for (let frame = 0; frame < 240; frame += 1) neutral = resolveVrmGazeFollow(neutral, null, 1 / 60);
  assert.equal(isNeutralVrmGaze(neutral), true);
  assert.deepEqual(neutral, VRM_NEUTRAL_GAZE);
});

test("lookAt resets exactly once when an active target becomes null", () => {
  const camera = { id: "camera" };
  const terminal = { id: "terminal" };
  let resets = 0;
  const lookAt = { target: null, reset: () => { resets += 1; } };

  applyVrmLookAtTransition(lookAt, null);
  applyVrmLookAtTransition(lookAt, camera);
  applyVrmLookAtTransition(lookAt, terminal);
  assert.equal(resets, 0, "inactive and active-to-active frames do not reset gaze");
  applyVrmLookAtTransition(lookAt, null);
  assert.equal(resets, 1);
  applyVrmLookAtTransition(lookAt, null);
  assert.equal(resets, 1, "continued inactivity cannot repeat the reset");
});

test("completed and fallback one-shots stay complete", () => {
  assert.equal(shouldScheduleVrmPerformance("wave", null), true);
  assert.equal(shouldScheduleVrmPerformance("wave", "wave"), false);
  assert.equal(shouldScheduleVrmPerformance("point", "wave"), true);

  assert.equal(shouldSettleProceduralPerformance(1.79, 1.8, false), false);
  assert.equal(shouldSettleProceduralPerformance(1.8, 1.8, true), false);
  assert.equal(shouldSettleProceduralPerformance(1.8, 1.8, false), true);

  let finished = null;
  if (shouldSettleProceduralPerformance(1.8, 1.8, false)) finished = "wave";
  assert.equal(shouldScheduleVrmPerformance("wave", finished), false);
});

test("VRMA root translation is rejected while bone rotation is retained", () => {
  assert.equal(isRotationOnlyVrmTrack("Normalized_J_Bip_C_Hips.quaternion"), true);
  assert.equal(isRotationOnlyVrmTrack("Normalized_J_Bip_C_Hips.position"), false);
  assert.equal(isRotationOnlyVrmTrack("Root.position"), false);
  assert.equal(isRotationOnlyVrmTrack("Normalized_J_Bip_R_Hand.position"), false);
  assert.equal(isRotationOnlyVrmTrack("Root.scale"), false);
});

test("blink timing resets only when entering or leaving an eye-hold clip", () => {
  assert.equal(shouldResetVrmBlinkTiming("idle", "sleep"), true);
  assert.equal(shouldResetVrmBlinkTiming("sleep", "idle"), true);
  assert.equal(shouldResetVrmBlinkTiming("idle", "wave"), false);
});

test("grounding raises penetrated soles and preserves the resting base in airtime", () => {
  near(resolveVrmGroundTarget(0.12, 0, -0.04, 0.12), 0.16);
  near(resolveVrmGroundTarget(0.12, 0, 0.3, 0.12), 0.12);
  near(resolveVrmGroundTarget(0.12, 0, 0.3, 0.12, false), -0.18);
});

test("spring inertia is stabilized only while VRMA fades into procedural motion", () => {
  assert.equal(shouldStabilizeVrmSpringTransition(false, 1), true);
  assert.equal(shouldStabilizeVrmSpringTransition(false, 0), false);
  assert.equal(shouldStabilizeVrmSpringTransition(true, 1), false);
});

test("terminal contact requires contact phase, reachability, and measured distance", () => {
  assert.equal(isConfirmedVrmInteractionContact("contact", true, 0.2, 0.2), true);
  assert.equal(isConfirmedVrmInteractionContact("reach", true, 0.1, 0.2), false);
  assert.equal(isConfirmedVrmInteractionContact("contact", false, 0.1, 0.2), false);
  assert.equal(isConfirmedVrmInteractionContact("contact", true, 0.201, 0.2), false);
});

test("VRMA telemetry remains explicit until a fading action is reaped", () => {
  const active = { name: "Hello", mode: "once" };
  const fading = resolveVrmMotionTelemetry(null, active, "idle");
  assert.deepEqual(fading, { activeMotion: "fading:Hello", activeMode: "once" });

  const stopped = resolveVrmMotionTelemetry(null, null, "idle");
  assert.deepEqual(stopped, { activeMotion: "procedural:idle", activeMode: "procedural" });
});

test("two-bone reach solves reachable targets and flags unreachable targets", () => {
  const upper = 0.32;
  const lower = 0.27;
  const target = 0.45;
  const solution = solveTwoBoneReach(upper, lower, target);
  assert.equal(solution.valid, true);
  assert.equal(solution.reachable, true);

  const shoulderToElbow = Math.hypot(solution.elbowAlong, solution.elbowOffset);
  const elbowToTarget = Math.hypot(target - solution.elbowAlong, solution.elbowOffset);
  near(shoulderToElbow, upper);
  near(elbowToTarget, lower);

  const unreachable = solveTwoBoneReach(upper, lower, upper + lower + 0.08);
  assert.equal(unreachable.valid, true);
  assert.equal(unreachable.reachable, false);
  assert.ok(unreachable.solvedDistance < unreachable.maxReach);
});

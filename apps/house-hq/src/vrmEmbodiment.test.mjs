import assert from "node:assert/strict";
import test from "node:test";

import {
  isConfirmedVrmInteractionContact,
  isRotationOnlyVrmTrack,
  resolveVrmFootRoll,
  resolveVrmFootSwing,
  resolveVrmFootLiftHeight,
  resolveVrmFootContactY,
  resolveVrmLowestFootContactY,
  resolveVrmGroundTarget,
  resolveVrmMotionTelemetry,
  resolveVrmWalkGait,
  shouldBlendVrmProceduralTransition,
  shouldResetVrmBlinkTiming,
  shouldScheduleVrmPerformance,
  shouldSettleProceduralPerformance,
  solveTwoBoneReach,
  strideDistanceForMotion,
  v4MoodMouthCorrectionWeights,
  v4MoodComponentCorrectionWeights,
  vowelWeightsForSpeech,
} from "./vrmEmbodiment.ts";

const near = (actual, expected, epsilon = 1e-9) => {
  assert.ok(Math.abs(actual - expected) <= epsilon, `${actual} != ${expected}`);
};

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
  assert.ok(resolveVrmFootLiftHeight(1, 0.46) > 0.16);
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

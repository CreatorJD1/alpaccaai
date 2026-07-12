import assert from "node:assert/strict";
import test from "node:test";

import {
  isRotationOnlyVrmTrack,
  resolveVrmMotionTelemetry,
  shouldScheduleVrmPerformance,
  solveTwoBoneReach,
  v4MoodMouthCorrectionWeights,
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

test("completed one-shots stay complete and VRMA root translation is rejected", () => {
  assert.equal(shouldScheduleVrmPerformance("wave", null), true);
  assert.equal(shouldScheduleVrmPerformance("wave", "wave"), false);
  assert.equal(shouldScheduleVrmPerformance("point", "wave"), true);

  assert.equal(isRotationOnlyVrmTrack("Normalized_J_Bip_C_Hips.quaternion"), true);
  assert.equal(isRotationOnlyVrmTrack("Normalized_J_Bip_C_Hips.position"), false);
  assert.equal(isRotationOnlyVrmTrack("Root.scale"), false);
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

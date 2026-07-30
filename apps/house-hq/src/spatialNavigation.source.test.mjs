import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./main.ts", import.meta.url), "utf8");

function functionBody(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist`);
  const nextFunction = source.indexOf("\nfunction ", start + 10);
  return source.slice(start, nextFunction === -1 ? source.length : nextFunction);
}

test("a failed bounded detour never requeues its known-blocked destination", () => {
  const body = functionBody("expandBlockedAlpeccaRoute");
  const failedDetour = body.slice(body.indexOf("if (!detour?.length)"), body.indexOf("for (const point of detour)"));
  assert.match(failedDetour, /continue;/);
  assert.doesNotMatch(failedDetour, /pushAlpeccaRoutePoint/);
});

test("an entirely blocked authored route resolves to a stationary safe waypoint", () => {
  const body = functionBody("buildAlpeccaRoute");
  assert.match(body, /expanded\.length > 0 \? expanded : \[alpecca\.group\.position\.clone\(\)\]/);
});

test("player and Alpecca movement recover penetrated saved positions", () => {
  assert.match(functionBody("moveAlpeccaSafely"), /recoverAlpeccaFromScenePenetration\(\)/);
  assert.match(functionBody("movePlayer"), /recoverPlayerFromScenePenetration\(\)/);
});

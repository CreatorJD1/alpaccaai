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

test("VRM-first House startup never waits for a sprite atlas", () => {
  const createBody = functionBody("createAlpecca");
  const vrmBranch = createBody.slice(
    createBody.indexOf('if (alpeccaInitialEmbodimentPreference === "vrm")'),
    createBody.indexOf("} else {"),
  );
  assert.match(vrmBranch, /void activateAlpeccaVrm\(\);/);
  assert.match(vrmBranch, /createAlpeccaFallback\(\);/);
  assert.doesNotMatch(vrmBranch, /loadAlpeccaAnimation|ensureAlpeccaAnimation|preloadAlpeccaMovementAnimations/);
  assert.ok(
    vrmBranch.indexOf("activateAlpeccaVrm") < vrmBranch.indexOf("createAlpeccaFallback"),
    "3D activation should begin before the fallback portrait request",
  );
});

test("deferred VRM mode gates both urgent and background atlas queues", () => {
  assert.match(functionBody("queueAlpeccaAnimationLoad"), /canQueueFullSpriteAnimation\(alpeccaSpriteLibraryDeferred\)/);
  assert.match(functionBody("preloadAlpeccaMovementAnimations"), /canQueueFullSpriteAnimation\(alpeccaSpriteLibraryDeferred\)/);
  assert.match(functionBody("updateAlpeccaPreloadQueue"), /canQueueFullSpriteAnimation\(alpeccaSpriteLibraryDeferred\)/);
});

test("only the lightweight approved portrait is requested before an explicit 2D switch", () => {
  assert.match(source, /alpecca-avatar\/portraits\/idle\.png/);
  assert.doesNotMatch(functionBody("activateAlpeccaVrm"), /setItem\(alpeccaEmbodimentStorageKey, "sprite"\)/);
  assert.match(functionBody("deactivateAlpeccaVrm"), /requestFullAlpeccaSpriteLibrary\(\)/);
  assert.match(functionBody("requestFullAlpeccaSpriteLibrary"), /alpeccaSpriteLibraryDeferred = false/);
});


import assert from "node:assert/strict";
import test from "node:test";

import {
  canQueueFullSpriteAnimation,
  deferFullSpriteLibrary,
  spriteLibraryStatusLabel,
} from "./spriteLoadingPolicy.ts";

test("forced VRM launch defers the full 2D animation library", () => {
  assert.equal(deferFullSpriteLibrary("vrm"), true);
  assert.equal(canQueueFullSpriteAnimation(true), false);
  assert.equal(deferFullSpriteLibrary("sprite"), false);
  assert.equal(canQueueFullSpriteAnimation(false), true);
});

test("sprite status names deferred VRM loading instead of reporting a misleading zero count", () => {
  assert.equal(
    spriteLibraryStatusLabel({ deferred: true, embodiment: "loading", loaded: 0, total: 45 }),
    "Alpecca sprites: deferred - 3D model loading",
  );
  assert.equal(
    spriteLibraryStatusLabel({ deferred: true, embodiment: "vrm", loaded: 0, total: 45 }),
    "Alpecca sprites: deferred - 3D model active",
  );
  assert.equal(
    spriteLibraryStatusLabel({ deferred: false, embodiment: "sprite", loaded: 6, total: 45 }),
    "Alpecca sprites: 6/45",
  );
});


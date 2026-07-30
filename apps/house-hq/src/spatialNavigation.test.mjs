import assert from "node:assert/strict";
import test from "node:test";

import {
  circleIntersectsAnyRect,
  depenetrateCircle,
  findGridRoute,
  orientedRectFootprint,
  segmentClearsRects,
} from "./spatialNavigation.ts";

test("a restored body inside furniture is moved to the nearest clear edge", () => {
  const furniture = [{ minX: -0.5, maxX: 0.5, minZ: -0.4, maxZ: 0.4 }];
  const recovered = depenetrateCircle({ x: 0, z: 0 }, 0.3, furniture);

  assert.equal(recovered.moved, true);
  assert.equal(recovered.clear, true);
  assert.equal(circleIntersectsAnyRect(recovered, 0.3, furniture), false);
  assert.ok(Math.hypot(recovered.x, recovered.z) < 0.81);
});

test("depenetration clears overlapping furniture footprints without oscillating", () => {
  const furniture = [
    { minX: -0.8, maxX: 0.25, minZ: -0.5, maxZ: 0.5 },
    { minX: -0.2, maxX: 0.8, minZ: -0.5, maxZ: 0.5 },
  ];
  const recovered = depenetrateCircle({ x: 0, z: 0 }, 0.3, furniture);

  assert.equal(recovered.clear, true);
  assert.equal(circleIntersectsAnyRect(recovered, 0.3, furniture), false);
  assert.ok(recovered.iterations <= 2);
});

test("rotated furniture receives the correct world-space footprint", () => {
  const footprint = orientedRectFootprint({ x: 3, z: -2 }, 2, 0.5, Math.PI / 2);

  assert.ok(Math.abs(footprint.minX - 2.75) < 1e-10);
  assert.ok(Math.abs(footprint.maxX - 3.25) < 1e-10);
  assert.ok(Math.abs(footprint.minZ - -3) < 1e-10);
  assert.ok(Math.abs(footprint.maxZ - -1) < 1e-10);
});

test("blocked authored movement is routed around furniture with clear segments", () => {
  const furniture = [{ minX: -0.55, maxX: 0.55, minZ: -0.9, maxZ: 0.9 }];
  const start = { x: -2, z: 0 };
  const goal = { x: 2, z: 0 };
  const route = findGridRoute(
    start,
    goal,
    0.3,
    furniture,
    { minX: -2.5, maxX: 2.5, minZ: -2.5, maxZ: 2.5 },
  );

  assert.ok(route);
  assert.ok(route.length >= 2);
  let previous = start;
  for (const waypoint of route) {
    assert.equal(segmentClearsRects(previous, waypoint, 0.3, furniture), true);
    previous = waypoint;
  }
  assert.deepEqual(route.at(-1), goal);
});

test("grid routing fails closed when a wall seals the whole bounded space", () => {
  const wall = [{ minX: -0.2, maxX: 0.2, minZ: -2, maxZ: 2 }];
  const route = findGridRoute(
    { x: -1, z: 0 },
    { x: 1, z: 0 },
    0.3,
    wall,
    { minX: -1.5, maxX: 1.5, minZ: -1.5, maxZ: 1.5 },
  );

  assert.equal(route, null);
});


import assert from "node:assert/strict";
import test from "node:test";

import {
  VIDEO_COMPANION_ENDPOINTS,
  VIDEO_COMPANION_SCHEMA,
  VideoCompanionController,
  normalizeVideoCompanionState,
  renderVideoObservatorySection,
} from "./videoCompanion.ts";

const actor = { actorId: "creator", kind: "creator", displayName: "CreatorJD" };
const authorization = {
  state: "authorized",
  principal: "creator",
  mechanism: "house-session",
  scopes: ["video.session.create", "video.status.read", "video.playback.control"],
  evidenceIds: ["house-proof-1"],
  expiresAt: 20_000,
};

const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json" },
});

function harness(responses, options = {}) {
  const requests = [];
  const queue = [...responses];
  const controller = new VideoCompanionController({
    actor,
    authorization,
    ...options,
    fetchImpl: async (input, init) => {
      requests.push({ endpoint: String(input), init, body: JSON.parse(String(init.body)) });
      return jsonResponse(queue.shift() ?? {});
    },
  });
  return { controller, requests };
}

const created = (surface = "house_hq", sourceKind = "file") => ({
  schema: VIDEO_COMPANION_SCHEMA,
  type: "create_session.response",
  accepted: true,
  session_id: "video-session-1",
  source_kind: sourceKind,
  surface,
  status: "active",
  detail: "Watching together.",
});

test("House HQ is the default primary surface and file creation has no URL field", async () => {
  const { controller, requests } = harness([created()]);
  const state = await controller.create({
    requestId: "create-1",
    source: { sourceId: "local-file-1", kind: "file", label: "Selected file" },
  });

  assert.equal(requests[0].endpoint, VIDEO_COMPANION_ENDPOINTS.create);
  assert.equal(requests[0].body.surface, "house_hq");
  assert.deepEqual(requests[0].body.source, {
    source_id: "local-file-1",
    source_kind: "file",
    label: "Selected file",
  });
  assert.equal("url" in requests[0].body.source, false);
  assert.equal(state.surface, "house_hq");
  assert.equal(state.sourceKind, "file");
});

test("screen and file sources share state while screen maps to neutral live transport", async () => {
  const { controller, requests } = harness([created("house_hq", "live")]);
  const state = await controller.create({
    requestId: "create-screen",
    source: { sourceId: "display-1", kind: "screen", label: "Shared screen" },
  });

  assert.equal(requests[0].body.source.source_kind, "live");
  assert.equal(state.sourceKind, "screen");
  assert.equal(state.sourceId, "display-1");
});

test("Discord uses the same controller contracts only by changing surface metadata", async () => {
  const { controller, requests } = harness([created("discord", "live")], { surface: "discord" });
  await controller.create({
    requestId: "create-discord",
    source: { sourceId: "discord-screen-1", kind: "screen" },
  });

  assert.equal(requests[0].body.surface, "discord");
  assert.equal(requests[0].endpoint, VIDEO_COMPANION_ENDPOINTS.create);
});

test("status transcript visual and playback operations use typed endpoint envelopes", async () => {
  const responses = [
    created(),
    { session_state: "active", playback_state: "playing", position: 2 },
    { session_state: "active" },
    { session_state: "active" },
    { session_state: "active", playback_state: "playing", position: 4 },
  ];
  const { controller, requests } = harness(responses);
  await controller.create({ requestId: "create-1", source: { sourceId: "file-1", kind: "file" } });
  await controller.status({ turnId: "turn-1", mediaTimestamp: 2 });
  await controller.transcript({
    turnId: "turn-1", mediaTimestamp: 2.5, text: "A meaningful line", final: true, language: "en-US",
  });
  await controller.visual({
    turnId: "turn-1", mediaTimestamp: 3, descriptor: "A door opens", confidence: 0.9, labels: ["door"],
  });
  await controller.playback({
    turnId: "turn-1", mediaTimestamp: 4, position: 4, state: "playing", duration: 120,
  });

  assert.deepEqual(requests.slice(1).map((request) => request.endpoint), [
    VIDEO_COMPANION_ENDPOINTS.status,
    VIDEO_COMPANION_ENDPOINTS.transcript,
    VIDEO_COMPANION_ENDPOINTS.visual,
    VIDEO_COMPANION_ENDPOINTS.playback,
  ]);
  assert.deepEqual(requests.slice(1).map((request) => request.body.type), [
    "status.request", "transcript.event", "visual_descriptor.event", "playback.event",
  ]);
  assert.deepEqual(requests.slice(1).map((request) => request.body.seq), [1, 2, 3, 4]);
  for (const request of requests) {
    assert.equal(request.init.method, "POST");
    assert.equal(request.init.credentials, "same-origin");
  }
});

test("pause resume and stop share explicit playback control without timing gates", async () => {
  const { controller, requests } = harness([
    created(),
    { session_state: "paused", playback_state: "paused" },
    { session_state: "active", playback_state: "playing" },
    { session_state: "stopped", playback_state: "stopped" },
  ]);
  await controller.create({ requestId: "create-1", source: { sourceId: "file-1", kind: "file" } });
  await controller.pause({ requestId: "pause-1", turnId: "turn-1", mediaTimestamp: 5 });
  await controller.resume({ requestId: "resume-1", turnId: "turn-1", mediaTimestamp: 5 });
  const stopped = await controller.stop({ requestId: "stop-1", turnId: "turn-1", mediaTimestamp: 5 });

  assert.deepEqual(requests.slice(1).map((request) => request.endpoint), [
    VIDEO_COMPANION_ENDPOINTS.control,
    VIDEO_COMPANION_ENDPOINTS.control,
    VIDEO_COMPANION_ENDPOINTS.control,
  ]);
  assert.deepEqual(requests.slice(1).map((request) => request.body.action), ["pause", "resume", "stop"]);
  assert.equal(stopped.sessionState, "stopped");
});

test("deferred and technical backpressure responses remain explicit", () => {
  const deferred = normalizeVideoCompanionState({
    session_id: "video-1",
    session_state: "active",
    deferred: true,
    defer_reason: "user_interruption",
  });
  const pressured = normalizeVideoCompanionState({
    session_id: "video-1",
    session_state: "active",
    backpressure: { active: true, reason: "decoder unavailable" },
  }, deferred);

  assert.equal(deferred.availability, "deferred");
  assert.equal(deferred.deferred, true);
  assert.equal(deferred.deferReason, "user_interruption");
  assert.equal(pressured.availability, "backpressure");
  assert.equal(pressured.backpressure, true);
  assert.equal(pressured.backpressureReason, "decoder unavailable");
  assert.equal(pressured.deferred, false, "a newer response clears an old deferral");
});

test("controller retains status metadata but never transcript or visual request content", async () => {
  const { controller } = harness([created(), { session_state: "active" }, { session_state: "active" }]);
  await controller.create({ requestId: "create-1", source: { sourceId: "file-1", kind: "file" } });
  await controller.transcript({
    turnId: "turn-1", mediaTimestamp: 1, text: "content that must be released", final: true,
  });
  await controller.visual({
    turnId: "turn-1", mediaTimestamp: 2, descriptor: "private derived visual", confidence: 0.8,
  });

  const retained = JSON.stringify(controller.state);
  assert.doesNotMatch(retained, /content that must be released|private derived visual/);
  assert.equal(Object.isFrozen(controller.state), true);
});

test("runtime raw media injection is rejected before fetch", async () => {
  let calls = 0;
  const controller = new VideoCompanionController({
    actor,
    authorization,
    fetchImpl: async () => {
      calls += 1;
      return jsonResponse(created());
    },
  });
  await assert.rejects(
    controller.create({
      requestId: "create-raw",
      source: { sourceId: new Uint8Array([1, 2, 3]), kind: "file" },
    }),
    /metadata only/,
  );
  assert.equal(calls, 0);
  assert.equal(controller.state.sourceId, null);
  assert.doesNotMatch(JSON.stringify(controller.state), /0":1|0":2|0":3/);
});

test("Observatory renderer is compact, exposes controls and has no nested cards or URL input", () => {
  const state = normalizeVideoCompanionState({
    session_id: "video-1",
    source_id: "display-1",
    source_kind: "live",
    session_state: "paused",
    playback_state: "paused",
    backpressure: "GPU worker busy",
  });
  const markup = renderVideoObservatorySection(state);

  assert.match(markup, /Observatory/);
  assert.match(markup, /Video Companion/);
  assert.match(markup, /Screen \/ display-1/);
  assert.match(markup, /Backpressure: GPU worker busy/);
  assert.match(markup, /data-video-action="pause"/);
  assert.match(markup, /data-video-action="resume"/);
  assert.match(markup, /data-video-action="stop"/);
  assert.equal((markup.match(/<section/g) ?? []).length, 1);
  assert.doesNotMatch(markup, /class="[^"]*card|type="url"|name="url"/i);
});

test("renderer escapes server detail instead of creating markup", () => {
  const state = normalizeVideoCompanionState({
    session_state: "active",
    detail: '<img src=x onerror="alert(1)">',
  });
  const markup = renderVideoObservatorySection(state);

  assert.doesNotMatch(markup, /<img/);
  assert.match(markup, /&lt;img/);
});

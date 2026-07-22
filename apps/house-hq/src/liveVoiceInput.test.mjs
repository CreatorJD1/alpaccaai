import assert from "node:assert/strict";
import test from "node:test";

import {
  AdaptiveVoiceGate,
  LiveVoiceInput,
  LiveVoiceBackpressureError,
  MAX_SEGMENT_MS,
  encodePcm16Wav,
} from "./liveVoiceInput.ts";

const frame = (length, amplitude) => Float32Array.from({ length }, (_, index) => (
  amplitude === 0 ? 0 : (index % 2 === 0 ? amplitude : -amplitude)
));

test("adaptive gate retains 300-500ms pre-roll and endpoints after silence", () => {
  const gate = new AdaptiveVoiceGate({
    sampleRate: 1_000,
    preRollMs: 400,
    silenceMs: 300,
    speechStartFrames: 2,
  });
  for (let index = 0; index < 5; index += 1) gate.push(frame(100, 0.002));
  const firstVoice = gate.push(frame(100, 0.1));
  const secondVoice = gate.push(frame(100, 0.1));
  gate.push(frame(100, 0));
  gate.push(frame(100, 0));
  const endpoint = gate.push(frame(100, 0));

  assert.equal(firstVoice.speechStarted, false);
  assert.equal(secondVoice.speechStarted, true);
  assert.equal(endpoint.segments.length, 1);
  assert.equal(endpoint.segments[0].reason, "silence");
  assert.equal(endpoint.segments[0].samples.length, 700, "400ms pre-roll plus 300ms trailing silence");
  assert.equal(gate.active, false);
});

test("noise floor adapts to steady background before louder speech opens the gate", () => {
  const gate = new AdaptiveVoiceGate({ sampleRate: 1_000, preRollMs: 300, speechStartFrames: 2 });
  for (let index = 0; index < 30; index += 1) {
    const update = gate.push(frame(50, 0.008));
    assert.equal(update.speechStarted, false);
  }
  const before = gate.noiseFloor;
  gate.push(frame(50, 0.08));
  const speech = gate.push(frame(50, 0.08));

  assert.ok(before > 0.003);
  assert.equal(speech.speechStarted, true);
});

test("segment cap is hard at 12 seconds including pre-roll", () => {
  const sampleRate = 100;
  const gate = new AdaptiveVoiceGate({
    sampleRate,
    preRollMs: 300,
    maxSegmentMs: MAX_SEGMENT_MS,
    speechStartFrames: 1,
  });
  let capped = null;
  for (let index = 0; index < 20 && !capped; index += 1) {
    const update = gate.push(frame(100, 0.2));
    capped = update.segments[0] ?? null;
  }

  assert.ok(capped);
  assert.equal(capped.reason, "max_duration");
  assert.equal(capped.samples.length, sampleRate * 12);
});

test("gate copies browser frames and reset zeroes retained raw PCM", () => {
  const gate = new AdaptiveVoiceGate({ sampleRate: 1_000, preRollMs: 300, speechStartFrames: 1 });
  const browserFrame = frame(100, 0.2);
  gate.push(browserFrame);
  browserFrame.fill(0.9);
  const segment = gate.flush();

  assert.ok(segment);
  assert.ok(Math.abs(segment.samples[0] - 0.2) < 1e-6);
  gate.reset();
});

test("PCM16 WAV encoder writes a valid mono header and clipped samples", () => {
  const wav = encodePcm16Wav(Float32Array.from([-2, -1, 0, 1, 2]), 16_000);
  const view = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
  const text = (offset, length) => String.fromCharCode(...wav.slice(offset, offset + length));

  assert.equal(text(0, 4), "RIFF");
  assert.equal(text(8, 4), "WAVE");
  assert.equal(text(12, 4), "fmt ");
  assert.equal(text(36, 4), "data");
  assert.equal(view.getUint16(20, true), 1);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 16_000);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), 10);
  assert.equal(view.getInt16(44, true), -32768);
  assert.equal(view.getInt16(52, true), 32767);
});

class FakeTrack {
  stopped = false;
  onended = null;
  stop() { this.stopped = true; }
  end() { this.stopped = true; this.onended?.(); }
}

class FakeStream {
  track = new FakeTrack();
  getTracks() { return [this.track]; }
}

class FakeNode {
  connections = [];
  disconnected = false;
  connect(node) { this.connections.push(node); return node; }
  disconnect() { this.disconnected = true; }
}

class FakeProcessor extends FakeNode {
  onaudioprocess = null;
  push(samples) {
    const output = new Float32Array(samples.length).fill(0.5);
    this.onaudioprocess?.({
      inputBuffer: { getChannelData: () => samples },
      outputBuffer: { getChannelData: () => output },
    });
    assert.ok(output.every((sample) => sample === 0), "capture output remains silent");
  }
}

class FakeAudioContext {
  sampleRate = 1_000;
  state = "running";
  destination = {};
  source = new FakeNode();
  processor = new FakeProcessor();
  closeCalls = 0;
  createMediaStreamSource(stream) { this.stream = stream; return this.source; }
  createScriptProcessor(size, inputs, outputs) {
    this.processorConfig = { size, inputs, outputs };
    return this.processor;
  }
  async resume() { this.state = "running"; }
  async close() { this.closeCalls += 1; this.state = "closed"; }
}

function runtimeHarness(options = {}) {
  const stream = new FakeStream();
  const context = new FakeAudioContext();
  const constraints = [];
  const states = [];
  const mediaDevices = {
    async getUserMedia(value) {
      constraints.push(value);
      return stream;
    },
  };
  const segments = [];
  const starts = [];
  const input = new LiveVoiceInput({
    mediaDevices,
    audioContextFactory: () => context,
    onSegment: async (wav, metadata) => { segments.push({ wav, metadata }); },
    onSpeechStart: () => starts.push("start"),
    onStateChange: (state) => states.push(state),
    gate: { preRollMs: 300, silenceMs: 300, speechStartFrames: 2 },
    processorBufferSize: 256,
    ...options,
  });
  return { input, stream, context, constraints, states, segments, starts };
}

test("one start keeps one mic stream and Web Audio graph across utterances", async () => {
  const runtime = runtimeHarness();
  await Promise.all([runtime.input.start(), runtime.input.start()]);

  assert.equal(runtime.constraints.length, 1);
  assert.deepEqual(runtime.constraints[0], {
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });
  assert.equal(runtime.input.state, "live");
  assert.equal(runtime.context.source.connections[0], runtime.context.processor);
  assert.equal(runtime.context.processor.connections[0], runtime.context.destination);

  for (let utterance = 0; utterance < 2; utterance += 1) {
    runtime.context.processor.push(frame(100, 0.1));
    runtime.context.processor.push(frame(100, 0.1));
    runtime.context.processor.push(frame(100, 0));
    runtime.context.processor.push(frame(100, 0));
    runtime.context.processor.push(frame(100, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  }

  assert.equal(runtime.constraints.length, 1, "utterance endpoints do not reacquire the mic");
  assert.equal(runtime.starts.length, 2, "speech start is exposed for barge-in");
  assert.equal(runtime.segments.length, 2);
  assert.equal(runtime.stream.track.stopped, false);
  await runtime.input.stop();
  assert.equal(runtime.stream.track.stopped, true);
  assert.equal(runtime.context.closeCalls, 1);
  assert.equal(runtime.input.state, "idle");
});

test("WAV bytes are zeroed and removed from pending delivery after callback settles", async () => {
  let releaseCallback;
  const callbackDone = new Promise((resolve) => { releaseCallback = resolve; });
  let deliveredBytes;
  const runtime = runtimeHarness({
    onSegment: async (wav) => {
      deliveredBytes = wav;
      await callbackDone;
    },
  });
  await runtime.input.start();
  runtime.context.processor.push(frame(100, 0.1));
  runtime.context.processor.push(frame(100, 0.1));
  runtime.context.processor.push(frame(100, 0));
  runtime.context.processor.push(frame(100, 0));
  runtime.context.processor.push(frame(100, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.ok(deliveredBytes.some((byte) => byte !== 0));
  assert.equal(runtime.input.pendingDeliveries, 1);
  releaseCallback();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(deliveredBytes.every((byte) => byte === 0));
  assert.equal(runtime.input.pendingDeliveries, 0);
  await runtime.input.stop();
});

test("stop discards partial speech, tears down capture, and toggle starts again", async () => {
  const runtime = runtimeHarness();
  await runtime.input.toggle();
  runtime.context.processor.push(frame(100, 0.1));
  runtime.context.processor.push(frame(100, 0.1));
  await runtime.input.toggle();

  assert.equal(runtime.segments.length, 0, "ending a call does not upload unfinished speech");
  assert.equal(runtime.input.state, "idle");
  assert.equal(runtime.stream.track.stopped, true);
});

test("stop cancels a pending microphone grant and releases the stale stream", async () => {
  let resolvePermission;
  const permission = new Promise((resolve) => { resolvePermission = resolve; });
  const stream = new FakeStream();
  const states = [];
  const input = new LiveVoiceInput({
    mediaDevices: { getUserMedia: () => permission },
    audioContextFactory: () => new FakeAudioContext(),
    onSegment: () => undefined,
    onStateChange: (state) => states.push(state),
  });

  const starting = input.start();
  const stopping = input.stop();
  assert.equal(input.state, "stopping");
  resolvePermission(stream);
  await Promise.all([starting, stopping]);

  assert.equal(stream.track.stopped, true);
  assert.equal(input.state, "idle");
  assert.deepEqual(states, ["starting", "stopping", "idle"]);
});

test("an ended microphone track tears down the live session", async () => {
  const runtime = runtimeHarness();
  await runtime.input.start();
  runtime.stream.track.end();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(runtime.input.state, "idle");
  assert.equal(runtime.context.closeCalls, 1);
  assert.equal(runtime.context.processor.onaudioprocess, null);
});

test("stop immediately zeroes WAV bytes even when delivery remains pending", async () => {
  let deliveredBytes;
  let releaseCallback;
  const callbackDone = new Promise((resolve) => { releaseCallback = resolve; });
  const runtime = runtimeHarness({
    onSegment: async (wav) => {
      deliveredBytes = wav;
      await callbackDone;
    },
  });
  await runtime.input.start();
  runtime.context.processor.push(frame(100, 0.1));
  runtime.context.processor.push(frame(100, 0.1));
  runtime.context.processor.push(frame(100, 0));
  runtime.context.processor.push(frame(100, 0));
  runtime.context.processor.push(frame(100, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  await runtime.input.stop();
  assert.ok(deliveredBytes.every((byte) => byte === 0));
  assert.equal(runtime.input.state, "idle");
  releaseCallback();
  await new Promise((resolve) => setTimeout(resolve, 0));
});

test("pending segment backpressure is bounded and explicitly reported", async () => {
  const releases = [];
  const errors = [];
  const runtime = runtimeHarness({
    maxPendingSegments: 1,
    onSegment: () => new Promise((resolve) => releases.push(resolve)),
    onError: (error) => errors.push(error),
  });
  await runtime.input.start();
  for (let utterance = 0; utterance < 2; utterance += 1) {
    runtime.context.processor.push(frame(100, 0.1));
    runtime.context.processor.push(frame(100, 0.1));
    runtime.context.processor.push(frame(100, 0));
    runtime.context.processor.push(frame(100, 0));
    runtime.context.processor.push(frame(100, 0));
  }
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(runtime.input.pendingDeliveries, 1);
  assert.equal(errors.length, 1);
  assert.ok(errors[0] instanceof LiveVoiceBackpressureError);
  assert.equal(errors[0].pendingSegments, 1);
  releases[0]();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await runtime.input.stop();
});

test("partial Web Audio startup failure releases the acquired microphone", async () => {
  const runtime = runtimeHarness();
  runtime.context.state = "suspended";
  runtime.context.resume = async () => { throw new Error("resume failed"); };

  await assert.rejects(runtime.input.start(), /resume failed/);
  assert.equal(runtime.input.state, "unavailable");
  assert.equal(runtime.stream.track.stopped, true);
  assert.equal(runtime.context.closeCalls, 1);
  assert.equal(runtime.context.processor.onaudioprocess, null);
});

test("pre-roll and maximum segment configuration enforce hard bounds", () => {
  assert.throws(() => new AdaptiveVoiceGate({ sampleRate: 1_000, preRollMs: 299 }), /preRollMs/);
  assert.throws(() => new AdaptiveVoiceGate({ sampleRate: 1_000, preRollMs: 501 }), /preRollMs/);
  assert.throws(() => new AdaptiveVoiceGate({ sampleRate: 1_000, maxSegmentMs: 12_001 }), /maxSegmentMs/);
});

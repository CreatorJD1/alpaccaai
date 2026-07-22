import assert from "node:assert/strict";
import test from "node:test";

import {
  createHouseVoiceSessionCoordinator,
  createVoiceAvatarPlaybackSignal,
  splitVoiceSpeechSegments,
} from "./voiceSession.ts";

test("spoken replies are segmented without changing or dropping their words", () => {
  const text = "First short thought. Second thought has enough detail to stand alone! Third?";
  const segments = splitVoiceSpeechSegments(text, 80);

  assert.deepEqual(segments, [
    "First short thought. Second thought has enough detail to stand alone! Third?",
  ]);
  assert.equal(segments.join(" "), text);

  const long = `One sentence ${"with repeated words ".repeat(12)}at the end.`.replace(/\s+/g, " ");
  const longSegments = splitVoiceSpeechSegments(long, 90);
  assert.ok(longSegments.length > 1);
  assert.ok(longSegments.every((segment) => segment.length <= 90));
  assert.equal(longSegments.join(" "), long);
});

class FakeAudio extends EventTarget {
  currentTime = 0;
  duration = 4;
  ended = false;
  paused = true;
  defaultPlaybackRate = 1;
  preservesPitch = true;
  webkitPreservesPitch = true;
  playCalls = 0;
  pauseCalls = 0;
  #playbackRate = 1;

  get playbackRate() {
    return this.#playbackRate;
  }

  set playbackRate(value) {
    this.#playbackRate = value;
    this.dispatchEvent(new Event("ratechange"));
  }

  play() {
    this.playCalls += 1;
    this.paused = false;
    this.dispatchEvent(new Event("playing"));
    return Promise.resolve();
  }

  pause() {
    this.pauseCalls += 1;
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  }

  finish() {
    this.ended = true;
    this.paused = true;
    this.dispatchEvent(new Event("ended"));
  }
}

async function settlePlayback() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("speech playback starts cleanly at native speed and restores pitch preservation", async () => {
  const audio = new FakeAudio();
  audio.currentTime = 1.75;
  audio.defaultPlaybackRate = 0.8;
  audio.preservesPitch = false;
  audio.webkitPreservesPitch = false;
  audio.playbackRate = 0.72;
  audio.paused = false;

  const session = createHouseVoiceSessionCoordinator();
  const speech = session.enqueueSpeech({ preparePlayback: () => audio });
  await settlePlayback();

  assert.equal(audio.playCalls, 1);
  assert.equal(audio.pauseCalls, 1, "a reused element is stopped before this session starts it");
  assert.equal(audio.currentTime, 0);
  assert.equal(audio.defaultPlaybackRate, 1);
  assert.equal(audio.playbackRate, 1);
  assert.equal(audio.preservesPitch, true);
  assert.equal(audio.webkitPreservesPitch, true);
  assert.equal(session.state, "speaking");

  audio.defaultPlaybackRate = 0.6;
  audio.preservesPitch = false;
  audio.webkitPreservesPitch = false;
  audio.playbackRate = 0.65;
  assert.equal(audio.defaultPlaybackRate, 1, "ratechange restores the default playback rate");
  assert.equal(audio.playbackRate, 1, "ratechange restores the active playback rate");
  assert.equal(audio.preservesPitch, true, "ratechange restores pitch preservation");
  assert.equal(audio.webkitPreservesPitch, true, "ratechange restores WebKit pitch preservation");

  audio.finish();
  assert.equal((await speech.completion).outcome, "completed");
});

test("an interruption pauses the active element before the next speech starts", async () => {
  const first = new FakeAudio();
  const second = new FakeAudio();
  const session = createHouseVoiceSessionCoordinator();
  const firstSpeech = session.enqueueSpeech({ preparePlayback: () => first });
  await settlePlayback();

  session.interrupt({ reason: "new reply" });
  const secondSpeech = session.enqueueSpeech({ preparePlayback: () => second });
  await settlePlayback();

  assert.equal((await firstSpeech.completion).outcome, "interrupted");
  assert.equal(first.paused, true);
  assert.equal(second.playCalls, 1);
  assert.equal(session.activeRequestId, secondSpeech.id);

  second.finish();
  assert.equal((await secondSpeech.completion).outcome, "completed");
});

test("speech segments stay FIFO when later preparation would resolve first", async () => {
  const order = [];
  const first = new FakeAudio();
  const second = new FakeAudio();
  const session = createHouseVoiceSessionCoordinator();
  const firstSpeech = session.enqueueSpeech({
    preparePlayback: async () => {
      order.push("prepare:first");
      return first;
    },
  });
  const secondSpeech = session.enqueueSpeech({
    preparePlayback: async () => {
      order.push("prepare:second");
      return second;
    },
  });

  await settlePlayback();
  assert.deepEqual(order, ["prepare:first"]);
  first.finish();
  await firstSpeech.completion;
  await settlePlayback();
  assert.deepEqual(order, ["prepare:first", "prepare:second"]);
  second.finish();
  assert.equal((await secondSpeech.completion).outcome, "completed");
});

const MOUTH_CHANNELS = ["aa", "ih", "ou", "ee", "oh", "sprite", "profile"];

class LifecycleAudio extends FakeAudio {
  duration = Number.NaN;
  error = null;

  play() {
    this.playCalls += 1;
    this.paused = false;
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  }

  pause() {
    this.pauseCalls += 1;
    if (this.paused) return;
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  }

  beginPlaying() {
    this.ended = false;
    this.paused = false;
    this.dispatchEvent(new Event("playing"));
  }

  suspend(type) {
    this.dispatchEvent(new Event(type));
  }

  fail(message = "media decode failed") {
    this.error = new Error(message);
    this.dispatchEvent(new Event("error"));
  }
}

function fillMouth(mouth, value = 0.7) {
  for (const channel of MOUTH_CHANNELS) mouth[channel] = value;
}

function assertMouthClosed(mouth) {
  assert.deepEqual(mouth, Object.fromEntries(MOUTH_CHANNELS.map((channel) => [channel, 0])));
}

function createPlaybackSignalHarness() {
  const mouth = Object.fromEntries(MOUTH_CHANNELS.map((channel) => [channel, 0]));
  const changes = [];
  const resets = [];
  const failures = [];
  const signal = createVoiceAvatarPlaybackSignal({
    onChange: (state) => changes.push(state),
    onMouthReset: (state) => {
      fillMouth(mouth, 0);
      resets.push(state);
    },
  });
  const session = createHouseVoiceSessionCoordinator({
    onPlaybackStart: (moment) => signal.start(moment),
    onPlaybackStop: (moment) => signal.stop(moment),
    onUnavailable: (failure) => {
      failures.push(failure);
      signal.reset(failure.reason);
    },
  });
  return { mouth, changes, resets, failures, signal, session };
}

test("avatar signal follows playing, buffering, resume, and end without a duration clock", async () => {
  const audio = new LifecycleAudio();
  const harness = createPlaybackSignalHarness();
  const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
  await settlePlayback();

  assert.equal(audio.paused, false, "play() has been requested");
  assert.equal(harness.signal.talking, false, "the play event alone is not active playback");

  audio.duration = 0.001;
  audio.currentTime = 999;
  audio.beginPlaying();
  assert.equal(harness.signal.talking, true, "duration metadata cannot expire the signal");

  fillMouth(harness.mouth);
  audio.suspend("waiting");
  assert.equal(harness.signal.talking, false);
  assertMouthClosed(harness.mouth);

  audio.beginPlaying();
  fillMouth(harness.mouth);
  audio.suspend("stalled");
  assert.equal(harness.signal.talking, false);
  assertMouthClosed(harness.mouth);

  audio.beginPlaying();
  fillMouth(harness.mouth);
  audio.finish();
  assert.equal((await speech.completion).outcome, "completed");
  assert.equal(harness.signal.talking, false);
  assertMouthClosed(harness.mouth);
  assert.deepEqual(
    harness.changes.map((state) => state.talking),
    [true, false, true, false, true, false],
  );
});

test("pause, media error, and reconnect reset every avatar mouth channel", async (t) => {
  await t.test("pause", async () => {
    const audio = new LifecycleAudio();
    const harness = createPlaybackSignalHarness();
    const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
    await settlePlayback();
    audio.beginPlaying();
    fillMouth(harness.mouth);

    audio.pause();

    assert.equal((await speech.completion).outcome, "interrupted");
    assert.equal(harness.signal.talking, false);
    assertMouthClosed(harness.mouth);
    assert.equal(harness.resets.at(-1).sourceEvent, "pause");
  });

  await t.test("media error", async () => {
    const audio = new LifecycleAudio();
    const harness = createPlaybackSignalHarness();
    const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
    await settlePlayback();
    audio.beginPlaying();
    fillMouth(harness.mouth);

    audio.fail();

    assert.equal((await speech.completion).outcome, "unavailable");
    assert.equal(harness.failures.length, 1);
    assert.equal(harness.signal.talking, false);
    assertMouthClosed(harness.mouth);
  });

  await t.test("reconnect", async () => {
    const audio = new LifecycleAudio();
    const harness = createPlaybackSignalHarness();
    const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
    await settlePlayback();
    audio.beginPlaying();
    fillMouth(harness.mouth);

    harness.session.interrupt({ clearQueue: true, reason: "backend disconnected" });
    harness.signal.reset("backend connected");

    assert.equal((await speech.completion).outcome, "interrupted");
    assert.equal(harness.signal.talking, false);
    assertMouthClosed(harness.mouth);
    assert.equal(harness.signal.getSnapshot().sourceEvent, "reset");
  });
});

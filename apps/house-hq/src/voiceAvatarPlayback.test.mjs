import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  createHouseVoiceSessionCoordinator,
  createVoiceAvatarPlaybackSignal,
} from "./voiceSession.ts";

const MOUTH_CHANNELS = ["aa", "ih", "ou", "ee", "oh", "sprite", "profile"];

class ControlledAudio extends EventTarget {
  currentTime = 0;
  duration = Number.NaN;
  ended = false;
  paused = true;
  error = null;
  defaultPlaybackRate = 1;
  playbackRate = 1;
  preservesPitch = true;
  playCalls = 0;
  pauseCalls = 0;

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

  finish() {
    this.ended = true;
    this.paused = true;
    this.dispatchEvent(new Event("ended"));
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

function createHarness() {
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

async function letPlaybackPrepare() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("avatar speech follows playing, buffering, resume, and ended events without a duration clock", async () => {
  const audio = new ControlledAudio();
  const harness = createHarness();
  const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
  await letPlaybackPrepare();

  assert.equal(audio.playCalls, 1);
  assert.equal(audio.paused, false, "play() has been requested");
  assert.equal(harness.session.playbackActive, false, "the play event alone is not audible playback");
  assert.equal(harness.signal.talking, false);

  audio.duration = 0.001;
  audio.currentTime = 999;
  audio.beginPlaying();
  assert.equal(harness.session.playbackActive, true);
  assert.equal(harness.signal.talking, true, "duration metadata cannot expire the signal");

  fillMouth(harness.mouth);
  audio.suspend("waiting");
  assert.equal(harness.session.playbackActive, false);
  assert.equal(harness.signal.talking, false);
  assertMouthClosed(harness.mouth);

  audio.beginPlaying();
  assert.equal(harness.signal.talking, true, "a resumed playing event reopens the signal");
  fillMouth(harness.mouth);
  audio.suspend("stalled");
  assert.equal(harness.signal.talking, false);
  assertMouthClosed(harness.mouth);

  audio.beginPlaying();
  fillMouth(harness.mouth);
  audio.finish();
  assert.equal((await speech.completion).outcome, "completed");
  assert.equal(harness.session.playbackActive, false);
  assert.equal(harness.signal.talking, false);
  assertMouthClosed(harness.mouth);
  assert.deepEqual(
    harness.changes.map((state) => state.talking),
    [true, false, true, false, true, false],
  );
});

test("pause, media error, and reconnect reset every avatar mouth channel", async (t) => {
  await t.test("pause", async () => {
    const audio = new ControlledAudio();
    const harness = createHarness();
    const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
    await letPlaybackPrepare();
    audio.beginPlaying();
    fillMouth(harness.mouth);

    audio.pause();

    assert.equal((await speech.completion).outcome, "interrupted");
    assert.equal(harness.signal.talking, false);
    assertMouthClosed(harness.mouth);
    assert.equal(harness.resets.at(-1).sourceEvent, "pause");
  });

  await t.test("media error", async () => {
    const audio = new ControlledAudio();
    const harness = createHarness();
    const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
    await letPlaybackPrepare();
    audio.beginPlaying();
    fillMouth(harness.mouth);

    audio.fail();

    assert.equal((await speech.completion).outcome, "unavailable");
    assert.equal(harness.failures.length, 1);
    assert.equal(harness.signal.talking, false);
    assertMouthClosed(harness.mouth);
  });

  await t.test("backend reconnect", async () => {
    const audio = new ControlledAudio();
    const harness = createHarness();
    const speech = harness.session.enqueueSpeech({ preparePlayback: () => audio });
    await letPlaybackPrepare();
    audio.beginPlaying();
    fillMouth(harness.mouth);

    harness.session.interrupt({ clearQueue: true, reason: "backend disconnected" });
    harness.signal.reset("backend connected");

    assert.equal((await speech.completion).outcome, "interrupted");
    assert.equal(harness.signal.talking, false);
    assertMouthClosed(harness.mouth);
    assert.equal(harness.signal.getSnapshot().reason, "backend connected");
    assert.equal(harness.signal.getSnapshot().sourceEvent, "reset");
  });
});

test("House consumes the event signal without a text-duration fallback", async () => {
  const source = await readFile(new URL("./main.ts", import.meta.url), "utf8");

  assert.match(source, /createVoiceAvatarPlaybackSignal\(\{/);
  assert.match(source, /onPlaybackStart:\s*\(moment\) => alpeccaAvatarPlaybackSignal\.start\(moment\)/);
  assert.match(source, /onPlaybackStop:\s*\(moment\) => alpeccaAvatarPlaybackSignal\.stop\(moment\)/);
  assert.match(source, /return alpeccaAvatarPlaybackSignal\.talking;/);
  assert.match(source, /alpecca\.mouthOpen = 0;/);
  assert.match(source, /alpeccaProfileTalkFrame = "";/);
  assert.match(source, /setSpriteState\([\s\S]*?active,[\s\S]*?alpeccaLastMove,/);
  assert.doesNotMatch(source, /alpeccaSpeechDuration|alpeccaPlaybackRemaining|alpeccaFallbackDuration/);
});

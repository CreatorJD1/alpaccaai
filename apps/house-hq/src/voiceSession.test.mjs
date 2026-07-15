import assert from "node:assert/strict";
import test from "node:test";

import { createHouseVoiceSessionCoordinator } from "./voiceSession.ts";

class FakeAudio extends EventTarget {
  currentTime = 0;
  duration = 4;
  ended = false;
  paused = true;
  defaultPlaybackRate = 1;
  preservesPitch = true;
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
  assert.equal(session.state, "speaking");

  audio.defaultPlaybackRate = 0.6;
  audio.preservesPitch = false;
  audio.playbackRate = 0.65;
  assert.equal(audio.defaultPlaybackRate, 1, "ratechange restores the default playback rate");
  assert.equal(audio.playbackRate, 1, "ratechange restores the active playback rate");
  assert.equal(audio.preservesPitch, true, "ratechange restores pitch preservation");

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

"""Focused contract and behavior tests for the standalone House voice queue."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
VOICE_SESSION = ROOT / "apps" / "house-hq" / "src" / "voiceSession.ts"
NODE = shutil.which("node")


def _run_node(body: str) -> None:
    if NODE is None:
        pytest.skip("Node is required by the House frontend")
    module_url = json.dumps(VOICE_SESSION.as_uri())
    script = f"""
import assert from "node:assert/strict";

const voiceModule = await import({module_url});
const {{
  HouseVoiceSessionCoordinator,
  VoiceQueueFullError,
  VOICE_SESSION_STATES,
}} = voiceModule;

const flush = async () => {{
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}};

class FakeAudio {{
  constructor(rejection = null) {{
    this.currentTime = 0;
    this.duration = 2;
    this.paused = true;
    this.ended = false;
    this.error = null;
    this.playCalls = 0;
    this.pauseCalls = 0;
    this.rejection = rejection;
    this.listeners = new Map();
  }}

  addEventListener(type, listener) {{
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }}

  removeEventListener(type, listener) {{
    this.listeners.get(type)?.delete(listener);
  }}

  emit(type) {{
    if (type === "playing") {{
      this.paused = false;
      this.ended = false;
    }} else if (type === "ended") {{
      this.paused = true;
      this.ended = true;
    }}
    const event = {{ type }};
    for (const listener of [...(this.listeners.get(type) || [])]) listener(event);
  }}

  play() {{
    this.playCalls += 1;
    this.paused = false;
    return this.rejection ? Promise.reject(this.rejection) : Promise.resolve();
  }}

  pause() {{
    this.pauseCalls += 1;
    this.paused = true;
  }}
}}

{body}
"""
    completed = subprocess.run(
        [NODE, "--no-warnings", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_voice_session_source_has_explicit_states_and_no_unlock_side_effects() -> None:
    source = VOICE_SESSION.read_text(encoding="utf-8")
    for state in (
        "idle",
        "listening",
        "thinking",
        "speaking",
        "interrupted",
        "warming",
        "unavailable",
    ):
        assert f'"{state}"' in source
    assert "AudioContext" not in source
    assert "webkitAudioContext" not in source
    assert "createBufferSource" not in source
    assert 'listen("playing"' in source
    assert 'listen("timeupdate"' in source
    assert 'listen("ended"' in source


def test_queue_is_bounded_and_starts_only_one_audio_at_a_time() -> None:
    _run_node(
        """
assert.deepEqual([...VOICE_SESSION_STATES], [
  "idle", "listening", "thinking", "speaking", "interrupted", "warming", "unavailable",
]);

const coordinator = new HouseVoiceSessionCoordinator({ maxQueueSize: 2 });
const firstAudio = new FakeAudio();
const secondAudio = new FakeAudio();
let secondPreparations = 0;
const first = coordinator.enqueueSpeech({ preparePlayback: async () => firstAudio });
const second = coordinator.enqueueSpeech({
  preparePlayback: async () => {
    secondPreparations += 1;
    return secondAudio;
  },
});
assert.throws(
  () => coordinator.enqueueSpeech({ preparePlayback: async () => new FakeAudio() }),
  VoiceQueueFullError,
);

await flush();
assert.equal(firstAudio.playCalls, 1);
assert.equal(secondPreparations, 0);
assert.equal(coordinator.queueSize, 2);

firstAudio.emit("playing");
firstAudio.emit("ended");
assert.equal((await first.completion).outcome, "completed");
await flush();
assert.equal(secondPreparations, 1);
assert.equal(secondAudio.playCalls, 1);

secondAudio.emit("playing");
secondAudio.emit("ended");
assert.equal((await second.completion).outcome, "completed");
assert.equal(coordinator.state, "idle");
assert.equal(coordinator.queueSize, 0);
"""
    )


def test_playback_callbacks_follow_real_audio_events_for_mouth_timing() -> None:
    _run_node(
        """
const starts = [];
const progress = [];
const stops = [];
const states = [];
const coordinator = new HouseVoiceSessionCoordinator({
  onStateChange: (change) => states.push(change.current),
  onPlaybackStart: (moment) => starts.push(moment.sourceEvent),
  onPlaybackProgress: (moment) => progress.push(moment.currentTime),
  onPlaybackStop: (moment) => stops.push(moment.reason),
});
const audio = new FakeAudio();
const speech = coordinator.enqueueSpeech({ preparePlayback: async () => audio });
await flush();

assert.equal(coordinator.state, "warming");
assert.deepEqual(starts, []);
audio.emit("playing");
assert.equal(coordinator.state, "speaking");
assert.deepEqual(starts, ["playing"]);

audio.currentTime = 0.75;
audio.emit("timeupdate");
assert.deepEqual(progress, [0.75]);
audio.emit("waiting");
assert.equal(coordinator.state, "warming");
assert.deepEqual(stops, ["waiting"]);
audio.emit("playing");
assert.deepEqual(starts, ["playing", "playing"]);

audio.emit("ended");
assert.equal((await speech.completion).outcome, "completed");
assert.deepEqual(stops, ["waiting", "ended"]);
assert.equal(coordinator.state, "idle");
assert.deepEqual(states, ["warming", "speaking", "warming", "speaking", "idle"]);
"""
    )


def test_interruption_aborts_work_and_suppresses_stale_preparation() -> None:
    _run_node(
        """
let resolveOld;
let oldSignal;
let oldReleases = 0;
const oldAudio = new FakeAudio();
const oldPrepared = new Promise((resolve) => { resolveOld = resolve; });
const coordinator = new HouseVoiceSessionCoordinator({ maxQueueSize: 2 });
const oldSpeech = coordinator.enqueueSpeech({
  preparePlayback: ({ signal }) => {
    oldSignal = signal;
    return oldPrepared;
  },
  releasePlayback: () => { oldReleases += 1; },
});
await flush();
coordinator.interrupt({ reason: "newer turn", clearQueue: true });
assert.equal((await oldSpeech.completion).outcome, "interrupted");
assert.equal(oldSignal.aborted, true);
assert.equal(coordinator.state, "interrupted");

const currentAudio = new FakeAudio();
const currentSpeech = coordinator.enqueueSpeech({ preparePlayback: async () => currentAudio });
await flush();
assert.equal(currentAudio.playCalls, 1);

resolveOld(oldAudio);
await flush();
assert.equal(oldAudio.playCalls, 0);
assert.equal(oldAudio.pauseCalls, 1);
assert.equal(oldReleases, 1);

currentAudio.emit("playing");
currentAudio.emit("ended");
assert.equal((await currentSpeech.completion).outcome, "completed");
assert.equal(coordinator.state, "idle");
"""
    )


def test_blocked_playback_becomes_unavailable_without_unlock_fallback() -> None:
    _run_node(
        """
const failures = [];
const coordinator = new HouseVoiceSessionCoordinator({
  onUnavailable: (failure) => failures.push(failure),
});
const blocked = new FakeAudio(new Error("NotAllowedError: user gesture required"));
const speech = coordinator.enqueueSpeech({ preparePlayback: async () => blocked });
const result = await speech.completion;

assert.equal(result.outcome, "unavailable");
assert.equal(coordinator.state, "unavailable");
assert.equal(failures.length, 1);
assert.equal(failures[0].phase, "playback");
assert.match(failures[0].reason, /user gesture required/);
"""
    )

export const VOICE_SESSION_STATES = Object.freeze([
  "idle",
  "listening",
  "thinking",
  "speaking",
  "interrupted",
  "warming",
  "unavailable",
] as const);

export type VoiceSessionState = (typeof VOICE_SESSION_STATES)[number];
export type VoiceConversationState = Extract<VoiceSessionState, "idle" | "listening" | "thinking">;
export type VoiceSpeechOutcome = "completed" | "cancelled" | "interrupted" | "unavailable";
export type VoicePlaybackStopReason =
  | "waiting"
  | "stalled"
  | "paused"
  | "ended"
  | "cancelled"
  | "interrupted"
  | "unavailable";

export const DEFAULT_VOICE_QUEUE_SIZE = 4;
export const MAX_VOICE_QUEUE_SIZE = 32;

export interface VoicePlaybackPreparation {
  readonly requestId: number;
  readonly signal: AbortSignal;
}

export interface VoiceSpeechRequest {
  readonly label?: string;
  readonly preparePlayback: (
    preparation: VoicePlaybackPreparation,
  ) => HTMLAudioElement | Promise<HTMLAudioElement>;
  readonly releasePlayback?: (audio: HTMLAudioElement) => void;
}

export interface VoiceSpeechResult {
  readonly requestId: number;
  readonly outcome: VoiceSpeechOutcome;
  readonly reason: string;
  readonly error?: unknown;
}

export interface VoiceSpeechHandle {
  readonly id: number;
  readonly completion: Promise<VoiceSpeechResult>;
  cancel(reason?: string): boolean;
}

export interface VoiceSessionStateChange {
  readonly previous: VoiceSessionState;
  readonly current: VoiceSessionState;
  readonly requestId: number | null;
  readonly reason: string;
}

export interface VoiceQueueSnapshot {
  readonly state: VoiceSessionState;
  readonly activeRequestId: number | null;
  readonly queuedRequestIds: readonly number[];
  readonly size: number;
  readonly maxSize: number;
}

export interface VoicePlaybackMoment {
  readonly requestId: number;
  readonly audio: HTMLAudioElement;
  readonly currentTime: number;
  readonly duration: number | null;
  readonly sourceEvent: "playing" | "timeupdate" | "waiting" | "stalled" | "pause" | "ended" | "error" | "abort" | "coordinator";
  readonly nativeEvent: Event | null;
}

export interface VoicePlaybackStop extends VoicePlaybackMoment {
  readonly reason: VoicePlaybackStopReason;
}

export interface VoiceSessionFailure {
  readonly requestId: number;
  readonly phase: "prepare" | "playback";
  readonly reason: string;
  readonly error: unknown;
}

export interface VoiceSessionCoordinatorOptions {
  readonly maxQueueSize?: number;
  readonly onStateChange?: (change: VoiceSessionStateChange) => void;
  readonly onQueueChange?: (snapshot: VoiceQueueSnapshot) => void;
  readonly onPlaybackStart?: (moment: VoicePlaybackMoment) => void;
  readonly onPlaybackProgress?: (moment: VoicePlaybackMoment) => void;
  readonly onPlaybackStop?: (moment: VoicePlaybackStop) => void;
  readonly onUnavailable?: (failure: VoiceSessionFailure) => void;
}

export interface VoiceInterruptionOptions {
  readonly clearQueue?: boolean;
  readonly reason?: string;
}

interface QueuedVoiceSpeech {
  readonly id: number;
  readonly request: VoiceSpeechRequest;
  readonly resolve: (result: VoiceSpeechResult) => void;
  settled: boolean;
}

interface ActiveVoiceSpeech {
  readonly entry: QueuedVoiceSpeech;
  readonly generation: number;
  readonly controller: AbortController;
  audio: HTMLAudioElement | null;
  detachAudioEvents: (() => void) | null;
  finishing: boolean;
  mouthActive: boolean;
  playbackReleased: boolean;
}

export class VoiceQueueFullError extends Error {
  readonly maxQueueSize: number;

  constructor(maxQueueSize: number) {
    super(`Voice queue is full (maximum ${maxQueueSize} active or queued requests).`);
    this.name = "VoiceQueueFullError";
    this.maxQueueSize = maxQueueSize;
  }
}

export class VoiceSessionClosedError extends Error {
  constructor() {
    super("Voice session coordinator is closed.");
    this.name = "VoiceSessionClosedError";
  }
}

function normalizedReason(reason: string | undefined, fallback: string): string {
  const clean = reason?.trim();
  return clean || fallback;
}

function errorReason(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() ? error.message.trim() : fallback;
}

function isPlayableAudio(value: unknown): value is HTMLAudioElement {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<HTMLAudioElement>;
  return typeof candidate.play === "function"
    && typeof candidate.pause === "function"
    && typeof candidate.addEventListener === "function"
    && typeof candidate.removeEventListener === "function";
}

function safeCallback<T>(callback: ((value: T) => void) | undefined, value: T): void {
  if (!callback) return;
  try {
    callback(value);
  } catch {
    // Observer failures must not strand playback or the bounded queue.
  }
}

function safePause(audio: HTMLAudioElement): void {
  try {
    audio.pause();
  } catch {
    // A detached media element may reject pause during teardown.
  }
}

type PitchPreservingAudio = HTMLAudioElement & {
  preservesPitch?: boolean;
  webkitPreservesPitch?: boolean;
  mozPreservesPitch?: boolean;
};

function restoreNativeSpeechPlayback(audio: HTMLAudioElement): void {
  const speechAudio = audio as PitchPreservingAudio;
  try {
    if (audio.defaultPlaybackRate !== 1) audio.defaultPlaybackRate = 1;
  } catch {
    // Some browser media implementations expose a read-only default rate.
  }
  try {
    if (audio.playbackRate !== 1) audio.playbackRate = 1;
  } catch {
    // Playback can still proceed at the browser's native rate when this is unavailable.
  }
  for (const property of ["preservesPitch", "webkitPreservesPitch", "mozPreservesPitch"] as const) {
    if (!(property in speechAudio) || speechAudio[property] === true) continue;
    try {
      speechAudio[property] = true;
    } catch {
      // Preserve compatibility with engines that expose a read-only pitch switch.
    }
  }
}

function prepareSpeechPlayback(audio: HTMLAudioElement): void {
  // A preparation callback may hand back a paused or previously-started element.
  // Stop it before attaching lifecycle handlers so it cannot overlap this session.
  safePause(audio);
  try {
    if (finiteTime(audio.currentTime) > 0) audio.currentTime = 0;
  } catch {
    // Resetting an unloaded media element is optional; native playback remains usable.
  }
  restoreNativeSpeechPlayback(audio);
}

function finiteTime(value: number): number {
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

function finiteDuration(value: number): number | null {
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/**
 * Coordinates synthesized House speech without performing browser audio unlock.
 * Callers must satisfy that user-gesture prerequisite before enqueueing speech.
 */
export class HouseVoiceSessionCoordinator {
  readonly maxQueueSize: number;

  private readonly options: VoiceSessionCoordinatorOptions;
  private readonly queue: QueuedVoiceSpeech[] = [];
  private currentState: VoiceSessionState = "idle";
  private active: ActiveVoiceSpeech | null = null;
  private requestSequence = 0;
  private generation = 0;
  private closed = false;

  constructor(options: VoiceSessionCoordinatorOptions = {}) {
    const maxQueueSize = options.maxQueueSize ?? DEFAULT_VOICE_QUEUE_SIZE;
    if (!Number.isInteger(maxQueueSize) || maxQueueSize < 1 || maxQueueSize > MAX_VOICE_QUEUE_SIZE) {
      throw new RangeError(`maxQueueSize must be an integer from 1 to ${MAX_VOICE_QUEUE_SIZE}.`);
    }
    this.maxQueueSize = maxQueueSize;
    this.options = { ...options, maxQueueSize };
  }

  get state(): VoiceSessionState {
    return this.currentState;
  }

  get activeRequestId(): number | null {
    return this.active?.entry.id ?? null;
  }

  get queueSize(): number {
    return this.queue.length + (this.active ? 1 : 0);
  }

  getSnapshot(): VoiceQueueSnapshot {
    return Object.freeze({
      state: this.currentState,
      activeRequestId: this.activeRequestId,
      queuedRequestIds: Object.freeze(this.queue.map((entry) => entry.id)),
      size: this.queueSize,
      maxSize: this.maxQueueSize,
    });
  }

  setConversationState(state: VoiceConversationState, reason = "conversation state changed"): boolean {
    if (!(["idle", "listening", "thinking"] as readonly string[]).includes(state)) {
      throw new TypeError("Conversation state must be idle, listening, or thinking.");
    }
    if (this.closed || this.active || this.queue.length) return false;
    this.transition(state, normalizedReason(reason, "conversation state changed"), null);
    return true;
  }

  enqueueSpeech(request: VoiceSpeechRequest): VoiceSpeechHandle {
    if (this.closed) throw new VoiceSessionClosedError();
    if (!request || typeof request.preparePlayback !== "function") {
      throw new TypeError("Voice speech requests require preparePlayback().");
    }
    if (this.queueSize >= this.maxQueueSize) throw new VoiceQueueFullError(this.maxQueueSize);

    const id = ++this.requestSequence;
    let resolveResult: (result: VoiceSpeechResult) => void = () => undefined;
    const completion = new Promise<VoiceSpeechResult>((resolve) => {
      resolveResult = resolve;
    });
    const entry: QueuedVoiceSpeech = {
      id,
      request,
      resolve: resolveResult,
      settled: false,
    };
    this.queue.push(entry);
    const handle: VoiceSpeechHandle = Object.freeze({
      id,
      completion,
      cancel: (reason?: string) => this.cancelSpeech(id, reason),
    });
    this.emitQueueChange();
    this.pump();
    return handle;
  }

  cancelSpeech(requestId: number, reason = "speech cancelled"): boolean {
    const cleanReason = normalizedReason(reason, "speech cancelled");
    const queuedIndex = this.queue.findIndex((entry) => entry.id === requestId);
    if (queuedIndex >= 0) {
      const [entry] = this.queue.splice(queuedIndex, 1);
      this.settle(entry, "cancelled", cleanReason);
      this.emitQueueChange();
      return true;
    }

    const active = this.active;
    if (!active || active.entry.id !== requestId) return false;
    this.finishActive(active, "cancelled", cleanReason, "interrupted", {
      reason: "cancelled",
      sourceEvent: "coordinator",
      nativeEvent: null,
    });
    return true;
  }

  interrupt(options: VoiceInterruptionOptions = {}): void {
    const reason = normalizedReason(options.reason, "speech interrupted");
    if (options.clearQueue !== false) {
      const queued = this.queue.splice(0);
      for (const entry of queued) this.settle(entry, "interrupted", reason);
      if (queued.length) this.emitQueueChange();
    }

    const active = this.active;
    if (active) {
      this.finishActive(active, "interrupted", reason, "interrupted", {
        reason: "interrupted",
        sourceEvent: "coordinator",
        nativeEvent: null,
      });
      return;
    }
    this.transition("interrupted", reason, null);
  }

  markUnavailable(reason = "voice unavailable"): void {
    const cleanReason = normalizedReason(reason, "voice unavailable");
    const queued = this.queue.splice(0);
    for (const entry of queued) this.settle(entry, "unavailable", cleanReason);
    if (queued.length) this.emitQueueChange();

    const active = this.active;
    if (active) {
      this.finishActive(active, "unavailable", cleanReason, "unavailable", {
        reason: "unavailable",
        sourceEvent: "coordinator",
        nativeEvent: null,
      });
      return;
    }
    this.transition("unavailable", cleanReason, null);
  }

  reset(state: VoiceConversationState = "idle", reason = "voice session reset"): boolean {
    if (this.closed || this.active || this.queue.length) return false;
    return this.setConversationState(state, reason);
  }

  close(reason = "voice session closed"): void {
    if (this.closed) return;
    this.interrupt({ clearQueue: true, reason });
    this.closed = true;
    this.transition("idle", reason, null);
  }

  private pump(): void {
    if (this.closed || this.active) return;
    const entry = this.queue.shift();
    if (!entry) return;

    const active: ActiveVoiceSpeech = {
      entry,
      generation: ++this.generation,
      controller: new AbortController(),
      audio: null,
      detachAudioEvents: null,
      finishing: false,
      mouthActive: false,
      playbackReleased: false,
    };
    this.active = active;
    this.emitQueueChange();
    this.transition("warming", "preparing speech playback", entry.id);
    void this.prepareAndPlay(active);
  }

  private async prepareAndPlay(active: ActiveVoiceSpeech): Promise<void> {
    let phase: VoiceSessionFailure["phase"] = "prepare";
    try {
      const audio = await active.entry.request.preparePlayback({
        requestId: active.entry.id,
        signal: active.controller.signal,
      });
      if (!this.isCurrent(active)) {
        this.releasePreparedAudio(active, audio);
        return;
      }
      if (!isPlayableAudio(audio)) throw new TypeError("preparePlayback() did not return an audio element.");

      active.audio = audio;
      prepareSpeechPlayback(audio);
      active.detachAudioEvents = this.attachAudioEvents(active, audio);
      phase = "playback";
      await Promise.resolve(audio.play());
      // "speaking" is entered only by the audio element's real playing event.
      if (!this.isCurrent(active)) this.releaseActiveAudio(active, true);
    } catch (error) {
      if (!this.isCurrent(active)) return;
      const reason = errorReason(error, phase === "prepare" ? "voice preparation failed" : "audio playback failed");
      safeCallback(this.options.onUnavailable, {
        requestId: active.entry.id,
        phase,
        reason,
        error,
      });
      this.finishActive(active, "unavailable", reason, "unavailable", {
        reason: "unavailable",
        sourceEvent: "coordinator",
        nativeEvent: null,
      }, error);
    }
  }

  private attachAudioEvents(active: ActiveVoiceSpeech, audio: HTMLAudioElement): () => void {
    const listeners: Array<readonly [string, EventListener]> = [];
    const listen = (type: string, listener: EventListener) => {
      listeners.push([type, listener]);
      audio.addEventListener(type, listener);
    };

    listen("playing", (event) => {
      if (!this.isCurrent(active)) return;
      this.transition("speaking", "audio playing", active.entry.id);
      if (active.mouthActive) return;
      active.mouthActive = true;
      safeCallback(this.options.onPlaybackStart, this.playbackMoment(active, "playing", event));
    });
    listen("timeupdate", (event) => {
      if (!this.isCurrent(active)) return;
      safeCallback(this.options.onPlaybackProgress, this.playbackMoment(active, "timeupdate", event));
    });
    listen("ratechange", () => {
      if (!this.isCurrent(active)) return;
      restoreNativeSpeechPlayback(audio);
    });
    for (const type of ["waiting", "stalled"] as const) {
      listen(type, (event) => {
        if (!this.isCurrent(active)) return;
        this.transition("warming", `audio ${type}`, active.entry.id);
        if (!active.mouthActive) return;
        active.mouthActive = false;
        safeCallback(this.options.onPlaybackStop, {
          ...this.playbackMoment(active, type, event),
          reason: type,
        });
      });
    }
    listen("pause", (event) => {
      if (!this.isCurrent(active) || audio.ended) return;
      this.finishActive(active, "interrupted", "audio paused", "interrupted", {
        reason: "paused",
        sourceEvent: "pause",
        nativeEvent: event,
      });
    });
    listen("ended", (event) => {
      if (!this.isCurrent(active)) return;
      this.finishActive(active, "completed", "playback ended", null, {
        reason: "ended",
        sourceEvent: "ended",
        nativeEvent: event,
      });
    });
    for (const type of ["error", "abort"] as const) {
      listen(type, (event) => {
        if (!this.isCurrent(active)) return;
        const error = audio.error ?? new Error(`audio ${type}`);
        const reason = errorReason(error, `audio ${type}`);
        safeCallback(this.options.onUnavailable, {
          requestId: active.entry.id,
          phase: "playback",
          reason,
          error,
        });
        this.finishActive(active, "unavailable", reason, "unavailable", {
          reason: "unavailable",
          sourceEvent: type,
          nativeEvent: event,
        }, error);
      });
    }

    return () => {
      for (const [type, listener] of listeners) audio.removeEventListener(type, listener);
    };
  }

  private finishActive(
    active: ActiveVoiceSpeech,
    outcome: VoiceSpeechOutcome,
    reason: string,
    terminalState: Extract<VoiceSessionState, "interrupted" | "unavailable"> | null,
    stop: {
      readonly reason: VoicePlaybackStopReason;
      readonly sourceEvent: VoicePlaybackMoment["sourceEvent"];
      readonly nativeEvent: Event | null;
    },
    error?: unknown,
  ): void {
    if (this.active !== active || active.finishing) return;
    active.finishing = true;
    this.generation += 1;
    if (terminalState) this.transition(terminalState, reason, active.entry.id);

    if (active.audio) {
      active.mouthActive = false;
      safeCallback(this.options.onPlaybackStop, {
        ...this.playbackMoment(active, stop.sourceEvent, stop.nativeEvent),
        reason: stop.reason,
      });
    }
    if (outcome !== "completed") active.controller.abort();
    this.releaseActiveAudio(active, outcome !== "completed");
    this.active = null;
    this.settle(active.entry, outcome, reason, error);
    this.emitQueueChange();

    if (!this.closed && this.queue.length) {
      this.pump();
    } else if (outcome === "completed") {
      this.transition("idle", "speech queue drained", null);
    }
  }

  private playbackMoment(
    active: ActiveVoiceSpeech,
    sourceEvent: VoicePlaybackMoment["sourceEvent"],
    nativeEvent: Event | null,
  ): VoicePlaybackMoment {
    const audio = active.audio;
    if (!audio) throw new Error("Playback lifecycle event has no audio element.");
    return Object.freeze({
      requestId: active.entry.id,
      audio,
      currentTime: finiteTime(audio.currentTime),
      duration: finiteDuration(audio.duration),
      sourceEvent,
      nativeEvent,
    });
  }

  private releasePreparedAudio(active: ActiveVoiceSpeech, value: unknown): void {
    if (!isPlayableAudio(value) || active.playbackReleased) return;
    active.audio = value;
    this.releaseActiveAudio(active, true);
  }

  private releaseActiveAudio(active: ActiveVoiceSpeech, pause: boolean): void {
    if (active.playbackReleased) return;
    active.detachAudioEvents?.();
    active.detachAudioEvents = null;
    const audio = active.audio;
    if (!audio) return;
    active.playbackReleased = true;
    if (pause) safePause(audio);
    try {
      active.entry.request.releasePlayback?.(audio);
    } catch {
      // Resource-release failures do not reopen or block a settled request.
    }
  }

  private isCurrent(active: ActiveVoiceSpeech): boolean {
    return this.active === active
      && !active.finishing
      && active.generation === this.generation
      && !active.controller.signal.aborted;
  }

  private settle(
    entry: QueuedVoiceSpeech,
    outcome: VoiceSpeechOutcome,
    reason: string,
    error?: unknown,
  ): void {
    if (entry.settled) return;
    entry.settled = true;
    entry.resolve(Object.freeze({
      requestId: entry.id,
      outcome,
      reason,
      ...(error === undefined ? {} : { error }),
    }));
  }

  private transition(state: VoiceSessionState, reason: string, requestId: number | null): void {
    if (state === this.currentState) return;
    const previous = this.currentState;
    this.currentState = state;
    safeCallback(this.options.onStateChange, Object.freeze({
      previous,
      current: state,
      requestId,
      reason,
    }));
  }

  private emitQueueChange(): void {
    safeCallback(this.options.onQueueChange, this.getSnapshot());
  }
}

export { HouseVoiceSessionCoordinator as VoiceSessionCoordinator };

export function createHouseVoiceSessionCoordinator(
  options: VoiceSessionCoordinatorOptions = {},
): HouseVoiceSessionCoordinator {
  return new HouseVoiceSessionCoordinator(options);
}

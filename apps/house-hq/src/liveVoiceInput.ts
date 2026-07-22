export const MIN_PRE_ROLL_MS = 300;
export const MAX_PRE_ROLL_MS = 500;
export const DEFAULT_PRE_ROLL_MS = 400;
export const MAX_SEGMENT_MS = 12_000;
export const DEFAULT_MAX_PENDING_SEGMENTS = 4;
export const MAX_PENDING_SEGMENTS = 8;

export type VoiceEndpointReason = "silence" | "max_duration" | "session_stop";
export type LiveVoiceState = "idle" | "starting" | "live" | "stopping" | "unavailable";

export type VoiceGateOptions = Readonly<{
  sampleRate: number;
  preRollMs?: number;
  silenceMs?: number;
  maxSegmentMs?: number;
  minimumVoiceRms?: number;
  startNoiseRatio?: number;
  endNoiseRatio?: number;
  speechStartFrames?: number;
}>;

export type VoiceGateSegment = Readonly<{
  samples: Float32Array;
  reason: VoiceEndpointReason;
}>;

export type VoiceGateUpdate = Readonly<{
  speechStarted: boolean;
  segments: readonly VoiceGateSegment[];
  active: boolean;
  rms: number;
  noiseFloor: number;
  startThreshold: number;
  endThreshold: number;
}>;

export type EncodedVoiceMetadata = Readonly<{
  sampleRate: number;
  sampleCount: number;
  durationMs: number;
  reason: VoiceEndpointReason;
}>;

export type LiveVoiceInputOptions = Readonly<{
  onSegment: (wavBytes: Uint8Array, metadata: EncodedVoiceMetadata) => void | Promise<void>;
  onSpeechStart?: () => void;
  onStateChange?: (state: LiveVoiceState) => void;
  onError?: (error: unknown) => void;
  mediaDevices?: Pick<MediaDevices, "getUserMedia">;
  audioContextFactory?: () => AudioContext;
  gate?: Omit<VoiceGateOptions, "sampleRate">;
  processorBufferSize?: 256 | 512 | 1024 | 2048 | 4096 | 8192 | 16384;
  maxPendingSegments?: number;
}>;

export class LiveVoiceBackpressureError extends Error {
  readonly pendingSegments: number;

  constructor(pendingSegments: number) {
    super(`Live voice deferred a segment because ${pendingSegments} deliveries are still pending.`);
    this.name = "LiveVoiceBackpressureError";
    this.pendingSegments = pendingSegments;
  }
}

const DEFAULT_SILENCE_MS = 650;
const DEFAULT_MINIMUM_VOICE_RMS = 0.012;
const DEFAULT_START_NOISE_RATIO = 3;
const DEFAULT_END_NOISE_RATIO = 1.8;
const DEFAULT_SPEECH_START_FRAMES = 2;

function boundedNumber(
  value: number,
  name: string,
  minimum: number,
  maximum: number,
): number {
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new RangeError(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

function frameRms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = samples[index];
    if (!Number.isFinite(sample)) throw new RangeError("Voice gate PCM must contain finite samples.");
    sum += sample * sample;
  }
  return Math.sqrt(sum / samples.length);
}

function concatenate(chunks: readonly Float32Array[], total: number): Float32Array {
  const result = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}

export class AdaptiveVoiceGate {
  readonly sampleRate: number;
  readonly preRollSamples: number;
  readonly silenceSamples: number;
  readonly maxSegmentSamples: number;
  readonly minimumVoiceRms: number;
  readonly startNoiseRatio: number;
  readonly endNoiseRatio: number;
  readonly speechStartFrames: number;

  #noiseFloor = 0.003;
  #preRoll: Float32Array[] = [];
  #preRollLength = 0;
  #segment: Float32Array[] = [];
  #segmentLength = 0;
  #silenceLength = 0;
  #speechFrames = 0;
  #active = false;

  constructor(options: VoiceGateOptions) {
    this.sampleRate = boundedNumber(options.sampleRate, "sampleRate", 1, 384_000);
    const preRollMs = boundedNumber(
      options.preRollMs ?? DEFAULT_PRE_ROLL_MS,
      "preRollMs",
      MIN_PRE_ROLL_MS,
      MAX_PRE_ROLL_MS,
    );
    const silenceMs = boundedNumber(options.silenceMs ?? DEFAULT_SILENCE_MS, "silenceMs", 100, 5_000);
    const maxSegmentMs = boundedNumber(
      options.maxSegmentMs ?? MAX_SEGMENT_MS,
      "maxSegmentMs",
      250,
      MAX_SEGMENT_MS,
    );
    this.minimumVoiceRms = boundedNumber(
      options.minimumVoiceRms ?? DEFAULT_MINIMUM_VOICE_RMS,
      "minimumVoiceRms",
      0.0001,
      1,
    );
    this.startNoiseRatio = boundedNumber(
      options.startNoiseRatio ?? DEFAULT_START_NOISE_RATIO,
      "startNoiseRatio",
      1.1,
      20,
    );
    this.endNoiseRatio = boundedNumber(
      options.endNoiseRatio ?? DEFAULT_END_NOISE_RATIO,
      "endNoiseRatio",
      1,
      this.startNoiseRatio,
    );
    this.speechStartFrames = Math.trunc(boundedNumber(
      options.speechStartFrames ?? DEFAULT_SPEECH_START_FRAMES,
      "speechStartFrames",
      1,
      8,
    ));
    this.preRollSamples = Math.ceil(this.sampleRate * preRollMs / 1_000);
    this.silenceSamples = Math.ceil(this.sampleRate * silenceMs / 1_000);
    this.maxSegmentSamples = Math.ceil(this.sampleRate * maxSegmentMs / 1_000);
  }

  get active(): boolean {
    return this.#active;
  }

  get noiseFloor(): number {
    return this.#noiseFloor;
  }

  push(input: Float32Array): VoiceGateUpdate {
    if (!(input instanceof Float32Array)) throw new TypeError("Voice gate input must be Float32Array PCM.");
    const frame = input.slice();
    const rms = frameRms(frame);
    const startThreshold = Math.max(this.minimumVoiceRms, this.#noiseFloor * this.startNoiseRatio);
    const endThreshold = Math.max(this.minimumVoiceRms * 0.6, this.#noiseFloor * this.endNoiseRatio);
    const segments: VoiceGateSegment[] = [];
    let speechStarted = false;

    if (!this.#active) {
      this.#appendPreRoll(frame);
      if (rms >= startThreshold) {
        this.#speechFrames += 1;
      } else {
        this.#speechFrames = 0;
        this.#noiseFloor = Math.max(0.0001, this.#noiseFloor * 0.94 + rms * 0.06);
      }
      if (this.#speechFrames >= this.speechStartFrames) {
        this.#active = true;
        speechStarted = true;
        this.#segment = this.#preRoll;
        this.#segmentLength = this.#preRollLength;
        this.#preRoll = [];
        this.#preRollLength = 0;
        this.#silenceLength = rms < endThreshold ? frame.length : 0;
        this.#speechFrames = 0;
        if (this.#segmentLength >= this.maxSegmentSamples) {
          segments.push(this.#emitAtCap());
        }
      }
    } else {
      this.#appendActive(frame, segments);
      if (this.#active) {
        this.#silenceLength = rms < endThreshold ? this.#silenceLength + frame.length : 0;
        if (this.#silenceLength >= this.silenceSamples) {
          segments.push(this.#emit("silence"));
        }
      }
    }

    return Object.freeze({
      speechStarted,
      segments: Object.freeze(segments),
      active: this.#active,
      rms,
      noiseFloor: this.#noiseFloor,
      startThreshold,
      endThreshold,
    });
  }

  flush(): VoiceGateSegment | null {
    if (!this.#active || this.#segmentLength === 0) {
      this.reset();
      return null;
    }
    return this.#emit("session_stop");
  }

  reset(): void {
    for (const chunk of this.#preRoll) chunk.fill(0);
    for (const chunk of this.#segment) chunk.fill(0);
    this.#preRoll = [];
    this.#segment = [];
    this.#preRollLength = 0;
    this.#segmentLength = 0;
    this.#silenceLength = 0;
    this.#speechFrames = 0;
    this.#active = false;
  }

  #appendPreRoll(frame: Float32Array): void {
    this.#preRoll.push(frame);
    this.#preRollLength += frame.length;
    while (this.#preRollLength > this.preRollSamples && this.#preRoll.length > 0) {
      const excess = this.#preRollLength - this.preRollSamples;
      const first = this.#preRoll[0];
      if (first.length <= excess) {
        this.#preRoll.shift();
        this.#preRollLength -= first.length;
        first.fill(0);
      } else {
        const retained = first.slice(excess);
        first.fill(0);
        this.#preRoll[0] = retained;
        this.#preRollLength -= excess;
      }
    }
  }

  #appendActive(frame: Float32Array, segments: VoiceGateSegment[]): void {
    const remaining = this.maxSegmentSamples - this.#segmentLength;
    if (frame.length <= remaining) {
      this.#segment.push(frame);
      this.#segmentLength += frame.length;
      if (this.#segmentLength === this.maxSegmentSamples) segments.push(this.#emit("max_duration"));
      return;
    }
    if (remaining > 0) {
      this.#segment.push(frame.slice(0, remaining));
      this.#segmentLength += remaining;
    }
    segments.push(this.#emit("max_duration"));
    const tail = frame.slice(remaining);
    this.#appendPreRoll(tail);
    this.#speechFrames = 1;
    frame.fill(0);
  }

  #emitAtCap(): VoiceGateSegment {
    const all = concatenate(this.#segment, this.#segmentLength);
    const kept = all.slice(0, this.maxSegmentSamples);
    const tail = all.slice(this.maxSegmentSamples);
    all.fill(0);
    for (const chunk of this.#segment) chunk.fill(0);
    this.#clearActive();
    if (tail.length > 0) {
      this.#appendPreRoll(tail);
      this.#speechFrames = 1;
    }
    return Object.freeze({ samples: kept, reason: "max_duration" });
  }

  #emit(reason: VoiceEndpointReason): VoiceGateSegment {
    const samples = concatenate(this.#segment, this.#segmentLength);
    for (const chunk of this.#segment) chunk.fill(0);
    this.#clearActive();
    return Object.freeze({ samples, reason });
  }

  #clearActive(): void {
    this.#segment = [];
    this.#segmentLength = 0;
    this.#silenceLength = 0;
    this.#speechFrames = 0;
    this.#active = false;
  }
}

export function encodePcm16Wav(samples: Float32Array, sampleRate: number): Uint8Array {
  if (!(samples instanceof Float32Array)) throw new TypeError("samples must be Float32Array PCM.");
  boundedNumber(sampleRate, "sampleRate", 1, 384_000);
  const bytes = new Uint8Array(44 + samples.length * 2);
  const view = new DataView(bytes.buffer);
  const ascii = (offset: number, value: string): void => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return bytes;
}

function safeNotify(callback: (() => void) | undefined): void {
  if (!callback) return;
  try {
    callback();
  } catch {
    // Barge-in observers cannot break capture.
  }
}

export class LiveVoiceInput {
  readonly #options: LiveVoiceInputOptions;
  readonly #maxPendingSegments: number;
  #state: LiveVoiceState = "idle";
  #stream: MediaStream | null = null;
  #context: AudioContext | null = null;
  #source: MediaStreamAudioSourceNode | null = null;
  #processor: ScriptProcessorNode | null = null;
  #gate: AdaptiveVoiceGate | null = null;
  #startPromise: Promise<void> | null = null;
  #stopPromise: Promise<void> | null = null;
  #lifecycleGeneration = 0;
  #deliveries = new Set<Promise<void>>();
  #deliveryBuffers = new Set<Uint8Array>();

  constructor(options: LiveVoiceInputOptions) {
    this.#options = options;
    this.#maxPendingSegments = Math.trunc(boundedNumber(
      options.maxPendingSegments ?? DEFAULT_MAX_PENDING_SEGMENTS,
      "maxPendingSegments",
      1,
      MAX_PENDING_SEGMENTS,
    ));
  }

  get state(): LiveVoiceState {
    return this.#state;
  }

  get live(): boolean {
    return this.#state === "live";
  }

  get pendingDeliveries(): number {
    return this.#deliveries.size;
  }

  start(): Promise<void> {
    if (this.#state === "live") return Promise.resolve();
    if (this.#startPromise) return this.#startPromise;
    if (this.#stopPromise) return this.#stopPromise.then(() => this.start());
    this.#setState("starting");
    const generation = ++this.#lifecycleGeneration;
    const task = this.#startCapture(generation);
    this.#startPromise = task.finally(() => {
      this.#startPromise = null;
    });
    return this.#startPromise;
  }

  async stop(): Promise<void> {
    if (this.#stopPromise) return this.#stopPromise;
    const task = this.#stopCapture();
    this.#stopPromise = task.finally(() => {
      this.#stopPromise = null;
    });
    return this.#stopPromise;
  }

  async #stopCapture(): Promise<void> {
    ++this.#lifecycleGeneration;
    if (this.#state === "idle" || this.#state === "unavailable") return;
    this.#setState("stopping");
    const starting = this.#startPromise;
    if (starting) {
      try {
        await starting;
      } catch {
        // Startup cleanup already reported the authoritative error.
      }
    }
    if (this.#processor) {
      this.#processor.onaudioprocess = null;
      this.#processor.disconnect();
    }
    this.#source?.disconnect();
    for (const track of this.#stream?.getTracks() ?? []) {
      track.onended = null;
      track.stop();
    }
    const context = this.#context;
    this.#processor = null;
    this.#source = null;
    this.#stream = null;
    this.#context = null;
    this.#gate?.reset();
    this.#gate = null;
    for (const wav of this.#deliveryBuffers) wav.fill(0);
    if (context && context.state !== "closed") {
      try {
        await context.close();
      } catch (error) {
        this.#reportError(error);
      }
    }
    this.#setState("idle");
  }

  async toggle(): Promise<LiveVoiceState> {
    if (this.#state === "live" || this.#state === "starting") await this.stop();
    else await this.start();
    return this.#state;
  }

  async #startCapture(generation: number): Promise<void> {
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let processor: ScriptProcessorNode | null = null;
    let gate: AdaptiveVoiceGate | null = null;
    try {
      const mediaDevices = this.#options.mediaDevices ?? navigator.mediaDevices;
      stream = await mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      if (generation !== this.#lifecycleGeneration) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      context = this.#options.audioContextFactory
        ? this.#options.audioContextFactory()
        : new AudioContext();
      source = context.createMediaStreamSource(stream);
      processor = context.createScriptProcessor(this.#options.processorBufferSize ?? 2048, 1, 1);
      gate = new AdaptiveVoiceGate({ sampleRate: context.sampleRate, ...this.#options.gate });
      const activeGate = gate;
      processor.onaudioprocess = (event): void => {
        const input = event.inputBuffer.getChannelData(0);
        const output = event.outputBuffer.getChannelData(0);
        output.fill(0);
        const update = activeGate.push(input);
        if (update.speechStarted) safeNotify(this.#options.onSpeechStart);
        for (const segment of update.segments) this.#deliver(segment);
      };
      source.connect(processor);
      processor.connect(context.destination);
      this.#stream = stream;
      this.#context = context;
      this.#source = source;
      this.#processor = processor;
      this.#gate = gate;
      if (context.state === "suspended") await context.resume();
      if (generation !== this.#lifecycleGeneration) {
        throw new DOMException("Live voice startup was cancelled.", "AbortError");
      }
      for (const track of stream.getTracks()) {
        track.onended = () => {
          if (generation === this.#lifecycleGeneration && this.#state === "live") void this.stop();
        };
      }
      this.#setState("live");
    } catch (error) {
      if (processor) {
        processor.onaudioprocess = null;
        processor.disconnect();
      }
      source?.disconnect();
      gate?.reset();
      for (const track of stream?.getTracks() ?? []) {
        track.onended = null;
        track.stop();
      }
      if (context && context.state !== "closed") {
        try {
          await context.close();
        } catch {
          // The original startup error remains authoritative.
        }
      }
      this.#stream = null;
      this.#context = null;
      this.#source = null;
      this.#processor = null;
      this.#gate = null;
      if (generation !== this.#lifecycleGeneration) return;
      this.#setState("unavailable");
      this.#reportError(error);
      throw error;
    }
  }

  #deliver(segment: VoiceGateSegment): void {
    const samples = segment.samples;
    if (this.#deliveries.size >= this.#maxPendingSegments) {
      samples.fill(0);
      this.#reportError(new LiveVoiceBackpressureError(this.#deliveries.size));
      return;
    }
    const wav = encodePcm16Wav(samples, this.#gate?.sampleRate ?? this.#context?.sampleRate ?? 1);
    const metadata = Object.freeze({
      sampleRate: this.#gate?.sampleRate ?? this.#context?.sampleRate ?? 1,
      sampleCount: samples.length,
      durationMs: samples.length * 1_000 / (this.#gate?.sampleRate ?? this.#context?.sampleRate ?? 1),
      reason: segment.reason,
    });
    samples.fill(0);
    this.#deliveryBuffers.add(wav);
    let delivery: Promise<void>;
    delivery = Promise.resolve()
      .then(() => this.#options.onSegment(wav, metadata))
      .catch((error) => this.#reportError(error))
      .then(() => undefined)
      .finally(() => {
        wav.fill(0);
        this.#deliveryBuffers.delete(wav);
        this.#deliveries.delete(delivery);
      });
    this.#deliveries.add(delivery);
  }

  #reportError(error: unknown): void {
    try {
      this.#options.onError?.(error);
    } catch {
      // Error observers cannot retain buffers or disrupt capture cleanup.
    }
  }

  #setState(state: LiveVoiceState): void {
    this.#state = state;
    try {
      this.#options.onStateChange?.(state);
    } catch {
      // State observers cannot alter capture lifecycle.
    }
  }
}

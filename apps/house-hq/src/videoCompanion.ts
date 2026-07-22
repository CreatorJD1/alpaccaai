export const VIDEO_COMPANION_SCHEMA = "alpecca.video-companion.api.v1";

export const VIDEO_COMPANION_ENDPOINTS = Object.freeze({
  create: "/video-companion/create",
  status: "/video-companion/status",
  transcript: "/video-companion/transcript",
  visual: "/video-companion/visual",
  playback: "/video-companion/playback",
  control: "/video-companion/control",
} as const);

export type VideoCompanionSurface = "house_hq" | "discord";
export type VideoSourceKind = "file" | "screen";
export type VideoContractSourceKind = "file" | "live";
export type VideoSessionState = "idle" | "creating" | "active" | "paused" | "stopped" | "completed" | "failed";
export type VideoPlaybackState = "playing" | "paused" | "buffering" | "stopped" | "ended";
export type VideoAvailability = "idle" | "live" | "deferred" | "backpressure" | "error";

export type VideoActor = Readonly<{
  actorId: string;
  kind: "creator" | "alpecca" | "guest" | "system" | "adapter";
  displayName?: string | null;
}>;

export type VideoAuthorization = Readonly<{
  state: "authorized" | "denied" | "not_required";
  principal: string | null;
  mechanism: string;
  scopes: readonly string[];
  evidenceIds: readonly string[];
  expiresAt: number | null;
}>;

export type VideoSource = Readonly<{
  sourceId: string;
  kind: VideoSourceKind;
  label?: string | null;
}>;

export type VideoCompanionState = Readonly<{
  surface: VideoCompanionSurface;
  sessionId: string | null;
  sourceId: string | null;
  sourceKind: VideoSourceKind | null;
  sessionState: VideoSessionState;
  playbackState: VideoPlaybackState;
  position: number;
  detail: string;
  availability: VideoAvailability;
  deferred: boolean;
  deferReason: string | null;
  backpressure: boolean;
  backpressureReason: string | null;
}>;

export type CreateVideoCompanionInput = Readonly<{
  requestId: string;
  source: VideoSource;
}>;

export type VideoEventInput = Readonly<{
  turnId: string;
  mediaTimestamp: number;
}>;

export type TranscriptInput = VideoEventInput & Readonly<{
  text: string;
  final: boolean;
  language?: string | null;
}>;

export type VisualInput = VideoEventInput & Readonly<{
  descriptor: string;
  confidence: number;
  labels?: readonly string[];
}>;

export type PlaybackInput = VideoEventInput & Readonly<{
  position: number;
  state: VideoPlaybackState;
  duration?: number | null;
}>;

export type PlaybackControlInput = VideoEventInput & Readonly<{
  requestId: string;
}>;

export type VideoCompanionControllerOptions = Readonly<{
  actor: VideoActor;
  authorization: VideoAuthorization;
  surface?: VideoCompanionSurface;
  fetchImpl?: typeof fetch;
}>;

type JsonRecord = Record<string, unknown>;

const SESSION_STATES = new Set<VideoSessionState>([
  "idle", "creating", "active", "paused", "stopped", "completed", "failed",
]);
const PLAYBACK_STATES = new Set<VideoPlaybackState>([
  "playing", "paused", "buffering", "stopped", "ended",
]);

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : {};
}

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : fallback;
}

function contractSourceKind(kind: VideoSourceKind): VideoContractSourceKind {
  return kind === "screen" ? "live" : "file";
}

function clientSourceKind(kind: unknown): VideoSourceKind | null {
  if (kind === "file") return "file";
  if (kind === "live") return "screen";
  return null;
}

function actorPayload(actor: VideoActor): JsonRecord {
  return {
    actor_id: actor.actorId,
    kind: actor.kind,
    display_name: actor.displayName ?? null,
  };
}

function authorizationPayload(authorization: VideoAuthorization): JsonRecord {
  return {
    state: authorization.state,
    principal: authorization.principal,
    mechanism: authorization.mechanism,
    scopes: [...authorization.scopes],
    evidence_ids: [...authorization.evidenceIds],
    expires_at: authorization.expiresAt,
  };
}

function containsRawMedia(value: unknown, seen = new Set<object>()): boolean {
  if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) return true;
  if (typeof Blob !== "undefined" && value instanceof Blob) return true;
  if (value === null || typeof value !== "object") return false;
  if (seen.has(value)) return false;
  seen.add(value);
  if (Array.isArray(value)) return value.some((item) => containsRawMedia(item, seen));
  return Object.values(value as JsonRecord).some((item) => containsRawMedia(item, seen));
}

function immutableState(value: VideoCompanionState): VideoCompanionState {
  return Object.freeze({ ...value });
}

function initialState(surface: VideoCompanionSurface): VideoCompanionState {
  return immutableState({
    surface,
    sessionId: null,
    sourceId: null,
    sourceKind: null,
    sessionState: "idle",
    playbackState: "stopped",
    position: 0,
    detail: "No video companion session.",
    availability: "idle",
    deferred: false,
    deferReason: null,
    backpressure: false,
    backpressureReason: null,
  });
}

function eventEnvelope(
  state: VideoCompanionState,
  actor: VideoActor,
  seq: number,
  input: VideoEventInput,
): JsonRecord {
  if (!state.sessionId || !state.sourceKind) throw new Error("No active Video Companion session.");
  return {
    session_id: state.sessionId,
    seq,
    turn_id: input.turnId,
    media_timestamp: input.mediaTimestamp,
    source_kind: contractSourceKind(state.sourceKind),
    surface: state.surface,
    actor: actorPayload(actor),
  };
}

function responseBackpressure(value: JsonRecord): { active: boolean; reason: string | null } {
  const raw = value.backpressure;
  if (raw === true) {
    return { active: true, reason: cleanText(value.backpressure_reason) || "technical_backpressure" };
  }
  if (typeof raw === "string" && raw.trim()) return { active: true, reason: raw.trim() };
  const detail = record(raw);
  if (detail.active === true) {
    return { active: true, reason: cleanText(detail.reason) || "technical_backpressure" };
  }
  return { active: false, reason: null };
}

export function normalizeVideoCompanionState(
  value: unknown,
  previous: VideoCompanionState = initialState("house_hq"),
): VideoCompanionState {
  const body = record(value);
  const rawSessionState = cleanText(body.session_state || body.status);
  const sessionState = SESSION_STATES.has(rawSessionState as VideoSessionState)
    ? rawSessionState as VideoSessionState
    : previous.sessionState;
  const rawPlaybackState = cleanText(body.playback_state || body.state);
  const playbackState = PLAYBACK_STATES.has(rawPlaybackState as VideoPlaybackState)
    ? rawPlaybackState as VideoPlaybackState
    : previous.playbackState;
  const backpressure = responseBackpressure(body);
  const deferReason = cleanText(body.defer_reason || body.deferred_reason) || null;
  const deferred = body.deferred === true || deferReason !== null;
  const failed = body.accepted === false || sessionState === "failed";
  const availability: VideoAvailability = failed
    ? "error"
    : backpressure.active
      ? "backpressure"
      : deferred
        ? "deferred"
        : sessionState === "idle"
          ? "idle"
          : "live";
  const responseSurface = body.surface === "discord" || body.surface === "house_hq"
    ? body.surface
    : previous.surface;
  return immutableState({
    surface: responseSurface,
    sessionId: cleanText(body.session_id) || previous.sessionId,
    sourceId: cleanText(body.source_id) || previous.sourceId,
    sourceKind: clientSourceKind(body.source_kind) || previous.sourceKind,
    sessionState,
    playbackState,
    position: finiteNumber(body.position, previous.position),
    detail: cleanText(body.detail || body.reason) || previous.detail,
    availability,
    deferred,
    deferReason,
    backpressure: backpressure.active,
    backpressureReason: backpressure.reason,
  });
}

export class VideoCompanionController {
  readonly #actor: VideoActor;
  readonly #authorization: VideoAuthorization;
  readonly #fetch: typeof fetch;
  #state: VideoCompanionState;
  #sequence = 0;

  constructor(options: VideoCompanionControllerOptions) {
    if (containsRawMedia(options)) throw new TypeError("Video Companion options retain metadata only.");
    this.#actor = Object.freeze({ ...options.actor });
    this.#authorization = Object.freeze({
      ...options.authorization,
      scopes: Object.freeze([...options.authorization.scopes]),
      evidenceIds: Object.freeze([...options.authorization.evidenceIds]),
    });
    this.#fetch = options.fetchImpl ?? fetch;
    this.#state = initialState(options.surface ?? "house_hq");
  }

  get state(): VideoCompanionState {
    return this.#state;
  }

  async create(input: CreateVideoCompanionInput): Promise<VideoCompanionState> {
    if (containsRawMedia(input)) throw new TypeError("Video Companion requests retain metadata only.");
    const sourceKind = contractSourceKind(input.source.kind);
    this.#state = immutableState({
      ...this.#state,
      sourceId: input.source.sourceId,
      sourceKind: input.source.kind,
      sessionState: "creating",
      availability: "live",
      detail: "Creating Video Companion session.",
    });
    const body = {
      schema: VIDEO_COMPANION_SCHEMA,
      type: "create_session.request",
      request_id: input.requestId,
      source: {
        source_id: input.source.sourceId,
        source_kind: sourceKind,
        label: input.source.label ?? null,
      },
      surface: this.#state.surface,
      actor: actorPayload(this.#actor),
      authorization: authorizationPayload(this.#authorization),
    };
    return this.#send(VIDEO_COMPANION_ENDPOINTS.create, body);
  }

  status(input: VideoEventInput): Promise<VideoCompanionState> {
    return this.#event(VIDEO_COMPANION_ENDPOINTS.status, "status.request", input, {
      authorization: authorizationPayload(this.#authorization),
    });
  }

  transcript(input: TranscriptInput): Promise<VideoCompanionState> {
    return this.#event(VIDEO_COMPANION_ENDPOINTS.transcript, "transcript.event", input, {
      text: input.text,
      final: input.final,
      language: input.language ?? null,
    });
  }

  visual(input: VisualInput): Promise<VideoCompanionState> {
    return this.#event(VIDEO_COMPANION_ENDPOINTS.visual, "visual_descriptor.event", input, {
      descriptor: input.descriptor,
      confidence: input.confidence,
      labels: [...(input.labels ?? [])],
    });
  }

  playback(input: PlaybackInput): Promise<VideoCompanionState> {
    return this.#event(VIDEO_COMPANION_ENDPOINTS.playback, "playback.event", input, {
      position: input.position,
      state: input.state,
      duration: input.duration ?? null,
    });
  }

  pause(input: PlaybackControlInput): Promise<VideoCompanionState> {
    return this.#control("pause", input);
  }

  resume(input: PlaybackControlInput): Promise<VideoCompanionState> {
    return this.#control("resume", input);
  }

  stop(input: PlaybackControlInput): Promise<VideoCompanionState> {
    return this.#control("stop", input);
  }

  #control(action: "pause" | "resume" | "stop", input: PlaybackControlInput): Promise<VideoCompanionState> {
    return this.#event(VIDEO_COMPANION_ENDPOINTS.control, "playback_control.request", input, {
      request_id: input.requestId,
      action,
      authorization: authorizationPayload(this.#authorization),
    });
  }

  #event(
    endpoint: string,
    type: string,
    input: VideoEventInput,
    fields: JsonRecord,
  ): Promise<VideoCompanionState> {
    const body = {
      schema: VIDEO_COMPANION_SCHEMA,
      type,
      ...eventEnvelope(this.#state, this.#actor, ++this.#sequence, input),
      ...fields,
    };
    return this.#send(endpoint, body);
  }

  async #send(endpoint: string, payload: JsonRecord): Promise<VideoCompanionState> {
    if (containsRawMedia(payload)) throw new TypeError("Video Companion requests retain metadata only.");
    const response = await this.#fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    let value: unknown = {};
    try {
      value = await response.json();
    } catch {
      if (response.ok) throw new Error("Video Companion returned a non-JSON response.");
    }
    if (!response.ok) {
      const reason = cleanText(record(value).detail || record(value).reason);
      this.#state = immutableState({
        ...this.#state,
        availability: "error",
        detail: reason || `Video Companion request failed (${response.status}).`,
      });
      throw new Error(this.#state.detail);
    }
    this.#state = normalizeVideoCompanionState(value, this.#state);
    return this.#state;
  }
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderVideoObservatorySection(state: VideoCompanionState): string {
  const source = state.sourceKind
    ? `${state.sourceKind === "screen" ? "Screen" : "File"} / ${state.sourceId || "unidentified"}`
    : "No source";
  const pressure = state.backpressure
    ? `Backpressure: ${state.backpressureReason || "technical work deferred"}`
    : state.deferred
      ? `Deferred: ${state.deferReason || "awaiting capacity"}`
      : state.detail;
  const canPause = state.sessionState === "active" && state.playbackState !== "paused";
  const canResume = state.sessionState === "paused" || state.playbackState === "paused";
  const canStop = state.sessionId !== null && !["stopped", "completed"].includes(state.sessionState);
  return `<section class="observatory-video" aria-labelledby="observatory-video-title" data-video-availability="${escapeHtml(state.availability)}">
  <header class="observatory-video__header">
    <div><span class="observatory-video__eyebrow">Observatory</span><h3 id="observatory-video-title">Video Companion</h3></div>
    <output aria-live="polite">${escapeHtml(state.availability)}</output>
  </header>
  <dl class="observatory-video__status">
    <div><dt>Source</dt><dd>${escapeHtml(source)}</dd></div>
    <div><dt>Session</dt><dd>${escapeHtml(state.sessionState)}</dd></div>
    <div><dt>Playback</dt><dd>${escapeHtml(state.playbackState)}</dd></div>
  </dl>
  <p class="observatory-video__detail">${escapeHtml(pressure)}</p>
  <div class="observatory-video__controls" role="group" aria-label="Video Companion controls">
    <button type="button" data-video-action="pause"${canPause ? "" : " disabled"} aria-label="Pause video">Pause</button>
    <button type="button" data-video-action="resume"${canResume ? "" : " disabled"} aria-label="Resume video">Resume</button>
    <button type="button" data-video-action="stop"${canStop ? "" : " disabled"} aria-label="Stop video">Stop</button>
  </div>
</section>`;
}

export function renderVideoObservatoryInto(
  container: HTMLElement,
  state: VideoCompanionState,
): void {
  container.innerHTML = renderVideoObservatorySection(state);
}

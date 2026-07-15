import { DurableObject } from "cloudflare:workers";

import {
  AUTHORITY_NAME,
  DEFAULT_AUDIT_LIMIT,
  DEFAULT_TTL_SECONDS,
  MAX_AUDIT_ENTRIES,
  MAX_AUDIT_LIMIT,
  MAX_REQUEST_BYTES,
  MAX_TTL_SECONDS,
  SCHEMA_VERSION,
  type AuthorityCommand,
  type AuthorityReply,
  type AuthorityRpcReply,
  type JsonObject,
  type JsonValue,
} from "./contracts";

const IDENTIFIER_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const CLOUD_STANDBY_PREFIX = "cloud-standby:";
const MAX_SAFE_EPOCH = Number.MAX_SAFE_INTEGER;

interface StateRow {
  [key: string]: SqlStorageValue;
  singleton: number;
  highestEpoch: number;
  lastNowMs: number;
  activeLeaseId: string | null;
  activeHolderNodeId: string | null;
  activeFencingEpoch: number | null;
  activeIssuedAtMs: number | null;
  activeExpiresAtMs: number | null;
  localOwnerNodeId: string | null;
  localObservedAtMs: number | null;
  localValidUntilMs: number | null;
  endpointUrl: string | null;
  endpointLeaseId: string | null;
  endpointFencingEpoch: number | null;
  endpointPublishedAtMs: number | null;
}

interface AuditRow {
  [key: string]: SqlStorageValue;
  sequence: number;
  auditId: string;
  occurredAtMs: number;
  eventType: string;
  outcome: string;
  actorNodeId: string | null;
  requestId: string | null;
  detailsJson: string;
}

interface FenceInput {
  holderNodeId: string;
  leaseId: string;
  fencingEpoch: number;
  requestId: string | null;
}

class InputError extends Error {}
class EpochExhaustedError extends Error {}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireExactKeys(
  value: JsonObject,
  required: readonly string[],
  optional: readonly string[] = [],
): void {
  const allowed = new Set([...required, ...optional]);
  const actual = Object.keys(value);
  const missing = required.filter((key) => !(key in value));
  const unknown = actual.filter((key) => !allowed.has(key));
  if (missing.length > 0 || unknown.length > 0) {
    throw new InputError("invalid request fields");
  }
}

function requireIdentifier(value: JsonValue | undefined, field: string): string {
  if (typeof value !== "string" || !IDENTIFIER_RE.test(value)) {
    throw new InputError(`${field} must be a valid identifier`);
  }
  return value;
}

function requireRequestId(payload: JsonObject): string | null {
  return payload.requestId === undefined
    ? null
    : requireIdentifier(payload.requestId, "requestId");
}

function requireTtl(payload: JsonObject): number {
  const value = payload.ttlSeconds ?? DEFAULT_TTL_SECONDS;
  if (!Number.isSafeInteger(value) || typeof value !== "number") {
    throw new InputError("ttlSeconds must be an integer");
  }
  if (value < 1 || value > MAX_TTL_SECONDS) {
    throw new InputError(`ttlSeconds must be between 1 and ${MAX_TTL_SECONDS}`);
  }
  return value;
}

function requireFencingEpoch(value: JsonValue | undefined): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < 1 ||
    value > MAX_SAFE_EPOCH
  ) {
    throw new InputError("fencingEpoch must be a positive safe integer");
  }
  return value;
}

function requireFence(payload: JsonObject, allowTtl: boolean): FenceInput {
  requireExactKeys(
    payload,
    ["holderNodeId", "leaseId", "fencingEpoch"],
    allowTtl ? ["ttlSeconds", "requestId"] : ["requestId"],
  );
  return {
    holderNodeId: requireIdentifier(payload.holderNodeId, "holderNodeId"),
    leaseId: requireIdentifier(payload.leaseId, "leaseId"),
    fencingEpoch: requireFencingEpoch(payload.fencingEpoch),
    requestId: requireRequestId(payload),
  };
}

function requireEndpoint(value: JsonValue | undefined): URL {
  if (typeof value !== "string" || value.length < 1 || value.length > 2_048) {
    throw new InputError("endpoint must be a bounded HTTPS URL");
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new InputError("endpoint must be a valid HTTPS URL");
  }
  if (
    parsed.protocol !== "https:" ||
    !parsed.hostname ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new InputError(
      "endpoint must use HTTPS and cannot contain credentials, query, or fragment",
    );
  }
  return parsed;
}

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

function nextEpoch(current: number): number {
  if (!Number.isSafeInteger(current) || current < 0 || current >= MAX_SAFE_EPOCH) {
    throw new EpochExhaustedError("fencing epoch is unavailable");
  }
  return current + 1;
}

function errorReply(status: number, error: string): AuthorityReply {
  return {
    status,
    body: {
      ok: false,
      schemaVersion: SCHEMA_VERSION,
      error,
    },
  };
}

export class ContinuityLeaseAuthority extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec(`
        CREATE TABLE IF NOT EXISTS authority_state (
          singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
          highest_epoch INTEGER NOT NULL DEFAULT 0
            CHECK (highest_epoch >= 0 AND highest_epoch <= 9007199254740991),
          last_now_ms INTEGER NOT NULL DEFAULT 0 CHECK (last_now_ms >= 0),
          active_lease_id TEXT,
          active_holder_node_id TEXT,
          active_fencing_epoch INTEGER,
          active_issued_at_ms INTEGER,
          active_expires_at_ms INTEGER,
          local_owner_node_id TEXT,
          local_observed_at_ms INTEGER,
          local_valid_until_ms INTEGER,
          endpoint_url TEXT,
          endpoint_lease_id TEXT,
          endpoint_fencing_epoch INTEGER,
          endpoint_published_at_ms INTEGER,
          CHECK (
            (active_lease_id IS NULL AND active_holder_node_id IS NULL
              AND active_fencing_epoch IS NULL AND active_issued_at_ms IS NULL
              AND active_expires_at_ms IS NULL)
            OR
            (active_lease_id IS NOT NULL AND active_holder_node_id IS NOT NULL
              AND active_fencing_epoch IS NOT NULL AND active_issued_at_ms IS NOT NULL
              AND active_expires_at_ms IS NOT NULL
              AND active_fencing_epoch = highest_epoch
              AND active_expires_at_ms > active_issued_at_ms)
          ),
          CHECK (
            (local_owner_node_id IS NULL AND local_observed_at_ms IS NULL
              AND local_valid_until_ms IS NULL)
            OR
            (local_owner_node_id IS NOT NULL AND local_observed_at_ms IS NOT NULL
              AND local_valid_until_ms IS NOT NULL
              AND local_valid_until_ms > local_observed_at_ms)
          ),
          CHECK (
            (endpoint_url IS NULL AND endpoint_lease_id IS NULL
              AND endpoint_fencing_epoch IS NULL AND endpoint_published_at_ms IS NULL)
            OR
            (endpoint_url IS NOT NULL AND endpoint_lease_id = active_lease_id
              AND endpoint_fencing_epoch = active_fencing_epoch
              AND endpoint_published_at_ms IS NOT NULL)
          )
        );

        CREATE TABLE IF NOT EXISTS audit_log (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          audit_id TEXT NOT NULL UNIQUE,
          occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
          event_type TEXT NOT NULL,
          outcome TEXT NOT NULL,
          actor_node_id TEXT,
          request_id TEXT,
          details_json TEXT NOT NULL CHECK (json_valid(details_json))
        );

        CREATE INDEX IF NOT EXISTS audit_log_occurred_at
          ON audit_log (occurred_at_ms DESC, sequence DESC);

        INSERT OR IGNORE INTO authority_state (singleton) VALUES (1);
      `);
    });
  }

  handle(action: string, payloadJson: string, auditLimit = 0): AuthorityRpcReply {
    try {
      if (payloadJson.length > MAX_REQUEST_BYTES * 2) {
        throw new InputError("invalid authority command");
      }
      const parsed: unknown = JSON.parse(payloadJson);
      if (!isPlainObject(parsed)) {
        throw new InputError("invalid authority command");
      }
      const command: AuthorityCommand = {
        action: action as AuthorityCommand["action"],
        payload: parsed as JsonObject,
        ...(auditLimit === 0 ? {} : { auditLimit }),
      };
      return this.rpcReply(this.dispatch(command));
    } catch (error) {
      if (error instanceof InputError || error instanceof SyntaxError) {
        return this.rpcReply(errorReply(400, "invalid authority command"));
      }
      if (error instanceof EpochExhaustedError) {
        return this.rpcReply(errorReply(503, "fencing epoch unavailable"));
      }
      throw error;
    }
  }

  private dispatch(command: AuthorityCommand): AuthorityReply {
    try {
      switch (command.action) {
        case "health":
          return this.health();
        case "status":
          return this.status();
        case "heartbeat":
          return this.heartbeat(command.payload);
        case "acquire":
          return this.acquire(command.payload);
        case "renew":
          return this.renew(command.payload);
        case "release":
          return this.release(command.payload);
        case "publish-endpoint":
          return this.publishEndpoint(command.payload);
        case "get-endpoint":
          return this.getEndpoint();
        case "audit":
          return this.audit(command.auditLimit ?? DEFAULT_AUDIT_LIMIT);
        default:
          return errorReply(400, "unknown authority action");
      }
    } catch (error) {
      if (error instanceof InputError) {
        return errorReply(400, error.message);
      }
      if (error instanceof EpochExhaustedError) {
        return errorReply(503, "fencing epoch unavailable");
      }
      throw error;
    }
  }

  private rpcReply(reply: AuthorityReply): AuthorityRpcReply {
    return { status: reply.status, bodyJson: JSON.stringify(reply.body) };
  }

  private health(): AuthorityReply {
    const row = this.readState();
    return {
      status: 200,
      body: {
        ok: true,
        schemaVersion: SCHEMA_VERSION,
        service: "alpecca-continuity-lease-authority",
        authority: AUTHORITY_NAME,
        storage: "sqlite-durable-object",
        highestFencingEpoch: row.highestEpoch,
      },
    };
  }

  private status(): AuthorityReply {
    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      const state = prepared.state;
      return {
        status: 200,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          authority: AUTHORITY_NAME,
          now: iso(nowMs),
          highestFencingEpoch: state.highestEpoch,
          activeLeaseCount: state.activeLeaseId === null ? 0 : 1,
          activeLease: this.leaseView(state, nowMs),
          localHeartbeat: this.heartbeatView(state, nowMs),
          localPrimaryPreferred: this.localHeartbeatFresh(state, nowMs),
          publishedEndpoint: this.endpointView(state),
          recentAudit: this.listAudit(20),
        },
      };
    });
  }

  private heartbeat(payload: JsonObject): AuthorityReply {
    requireExactKeys(payload, ["ownerNodeId"], ["ttlSeconds", "requestId"]);
    const ownerNodeId = requireIdentifier(payload.ownerNodeId, "ownerNodeId");
    const ttlSeconds = requireTtl(payload);
    const requestId = requireRequestId(payload);

    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      const state = prepared.state;
      if (
        this.localHeartbeatFresh(state, nowMs) &&
        state.localOwnerNodeId !== ownerNodeId
      ) {
        return this.denied(
          state,
          nowMs,
          "local.heartbeat.denied",
          ownerNodeId,
          requestId,
          "fresh-local-heartbeat-owned-by-another-node",
          { currentOwnerNodeId: state.localOwnerNodeId },
        );
      }

      const validUntilMs = nowMs + ttlSeconds * 1_000;
      this.ctx.storage.sql.exec(
        `UPDATE authority_state
         SET local_owner_node_id = ?, local_observed_at_ms = ?, local_valid_until_ms = ?
         WHERE singleton = 1`,
        ownerNodeId,
        nowMs,
        validUntilMs,
      );
      const audit = this.insertAudit(
        nowMs,
        "local.heartbeat.accepted",
        "accepted",
        ownerNodeId,
        requestId,
        { ttlSeconds, validUntil: iso(validUntilMs) },
      );
      return {
        status: 200,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          decision: "accepted",
          heartbeat: {
            ownerNodeId,
            observedAt: iso(nowMs),
            validUntil: iso(validUntilMs),
            fresh: true,
          },
          audit,
        },
      };
    });
  }

  private acquire(payload: JsonObject): AuthorityReply {
    requireExactKeys(payload, ["holderNodeId"], ["ttlSeconds", "requestId"]);
    const holderNodeId = requireIdentifier(payload.holderNodeId, "holderNodeId");
    const ttlSeconds = requireTtl(payload);
    const requestId = requireRequestId(payload);

    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      const state = prepared.state;
      if (state.activeLeaseId !== null) {
        return this.denied(
          state,
          nowMs,
          "lease.acquire.denied",
          holderNodeId,
          requestId,
          "lease-already-active",
          { activeHolderNodeId: state.activeHolderNodeId },
        );
      }
      if (
        this.localHeartbeatFresh(state, nowMs) &&
        state.localOwnerNodeId !== holderNodeId
      ) {
        return this.denied(
          state,
          nowMs,
          "lease.acquire.denied",
          holderNodeId,
          requestId,
          "fresh-local-heartbeat",
          { preferredHolderNodeId: state.localOwnerNodeId },
        );
      }

      const fencingEpoch = nextEpoch(state.highestEpoch);
      const leaseId = crypto.randomUUID();
      const expiresAtMs = nowMs + ttlSeconds * 1_000;
      this.ctx.storage.sql.exec(
        `UPDATE authority_state
         SET highest_epoch = ?, active_lease_id = ?, active_holder_node_id = ?,
             active_fencing_epoch = ?, active_issued_at_ms = ?, active_expires_at_ms = ?,
             endpoint_url = NULL, endpoint_lease_id = NULL,
             endpoint_fencing_epoch = NULL, endpoint_published_at_ms = NULL
         WHERE singleton = 1`,
        fencingEpoch,
        leaseId,
        holderNodeId,
        fencingEpoch,
        nowMs,
        expiresAtMs,
      );
      const updated = this.readState();
      const audit = this.insertAudit(
        nowMs,
        "lease.acquire.granted",
        "granted",
        holderNodeId,
        requestId,
        { leaseId, fencingEpoch, ttlSeconds },
      );
      return {
        status: 201,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          decision: "granted",
          lease: this.leaseView(updated, nowMs),
          audit,
        },
      };
    });
  }

  private renew(payload: JsonObject): AuthorityReply {
    const fence = requireFence(payload, true);
    const ttlSeconds = requireTtl(payload);

    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      const state = prepared.state;
      if (!this.exactFence(state, fence)) {
        return this.denied(
          state,
          nowMs,
          "lease.renew.denied",
          fence.holderNodeId,
          fence.requestId,
          "stale-or-non-owner-fence",
          { suppliedLeaseId: fence.leaseId, suppliedFencingEpoch: fence.fencingEpoch },
        );
      }
      if (
        fence.holderNodeId.startsWith(CLOUD_STANDBY_PREFIX) &&
        this.localHeartbeatFresh(state, nowMs) &&
        state.localOwnerNodeId !== fence.holderNodeId
      ) {
        return this.denied(
          state,
          nowMs,
          "lease.renew.denied",
          fence.holderNodeId,
          fence.requestId,
          "fresh-local-heartbeat-requires-cloud-failback",
          { preferredHolderNodeId: state.localOwnerNodeId },
        );
      }

      const expiresAtMs = nowMs + ttlSeconds * 1_000;
      this.ctx.storage.sql.exec(
        `UPDATE authority_state
         SET active_issued_at_ms = ?, active_expires_at_ms = ?
         WHERE singleton = 1`,
        nowMs,
        expiresAtMs,
      );
      const updated = this.readState();
      const audit = this.insertAudit(
        nowMs,
        "lease.renew.accepted",
        "renewed",
        fence.holderNodeId,
        fence.requestId,
        {
          leaseId: fence.leaseId,
          fencingEpoch: fence.fencingEpoch,
          ttlSeconds,
        },
      );
      return {
        status: 200,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          decision: "renewed",
          lease: this.leaseView(updated, nowMs),
          audit,
        },
      };
    });
  }

  private release(payload: JsonObject): AuthorityReply {
    const fence = requireFence(payload, false);

    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      const state = prepared.state;
      if (!this.exactFence(state, fence)) {
        return this.denied(
          state,
          nowMs,
          "lease.release.denied",
          fence.holderNodeId,
          fence.requestId,
          "stale-or-non-owner-fence",
          { suppliedLeaseId: fence.leaseId, suppliedFencingEpoch: fence.fencingEpoch },
        );
      }

      const releasedLease = this.leaseView(state, nowMs);
      const invalidatedThroughEpoch = nextEpoch(state.highestEpoch);
      this.clearActiveLease(invalidatedThroughEpoch);
      const audit = this.insertAudit(
        nowMs,
        "lease.release.accepted",
        "released",
        fence.holderNodeId,
        fence.requestId,
        {
          leaseId: fence.leaseId,
          releasedFencingEpoch: fence.fencingEpoch,
          invalidatedThroughEpoch,
        },
      );
      return {
        status: 200,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          decision: "released",
          releasedLease,
          highestFencingEpoch: invalidatedThroughEpoch,
          activeLease: null,
          audit,
        },
      };
    });
  }

  private publishEndpoint(payload: JsonObject): AuthorityReply {
    requireExactKeys(
      payload,
      ["holderNodeId", "leaseId", "fencingEpoch", "endpoint"],
      ["requestId"],
    );
    const fence: FenceInput = {
      holderNodeId: requireIdentifier(payload.holderNodeId, "holderNodeId"),
      leaseId: requireIdentifier(payload.leaseId, "leaseId"),
      fencingEpoch: requireFencingEpoch(payload.fencingEpoch),
      requestId: requireRequestId(payload),
    };
    const endpoint = requireEndpoint(payload.endpoint);

    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      const state = prepared.state;
      if (!this.exactFence(state, fence)) {
        return this.denied(
          state,
          nowMs,
          "endpoint.publish.denied",
          fence.holderNodeId,
          fence.requestId,
          "stale-or-non-owner-fence",
          { suppliedLeaseId: fence.leaseId, suppliedFencingEpoch: fence.fencingEpoch },
        );
      }

      const normalizedEndpoint = endpoint.toString();
      this.ctx.storage.sql.exec(
        `UPDATE authority_state
         SET endpoint_url = ?, endpoint_lease_id = ?, endpoint_fencing_epoch = ?,
             endpoint_published_at_ms = ?
         WHERE singleton = 1`,
        normalizedEndpoint,
        fence.leaseId,
        fence.fencingEpoch,
        nowMs,
      );
      const updated = this.readState();
      const audit = this.insertAudit(
        nowMs,
        "endpoint.publish.accepted",
        "published",
        fence.holderNodeId,
        fence.requestId,
        {
          leaseId: fence.leaseId,
          fencingEpoch: fence.fencingEpoch,
          endpointOrigin: endpoint.origin,
        },
      );
      return {
        status: 200,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          decision: "published",
          publishedEndpoint: this.endpointView(updated),
          audit,
        },
      };
    });
  }

  private getEndpoint(): AuthorityReply {
    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      return {
        status: 200,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          endpoint: this.endpointView(prepared.state),
        },
      };
    });
  }

  private audit(limit: number): AuthorityReply {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_AUDIT_LIMIT) {
      throw new InputError(`audit limit must be between 1 and ${MAX_AUDIT_LIMIT}`);
    }
    return this.ctx.storage.transactionSync(() => {
      const nowMs = Date.now();
      const prepared = this.prepare(nowMs);
      if (prepared.reply) return prepared.reply;
      return {
        status: 200,
        body: {
          ok: true,
          schemaVersion: SCHEMA_VERSION,
          entries: this.listAudit(limit),
        },
      };
    });
  }

  private prepare(
    nowMs: number,
  ): { state: StateRow; reply: null } | { state: StateRow; reply: AuthorityReply } {
    let state = this.readState();
    if (nowMs < state.lastNowMs) {
      return {
        state,
        reply: errorReply(503, "authority clock moved backwards"),
      };
    }
    this.ctx.storage.sql.exec(
      "UPDATE authority_state SET last_now_ms = ? WHERE singleton = 1",
      nowMs,
    );
    if (state.activeExpiresAtMs !== null && nowMs >= state.activeExpiresAtMs) {
      const invalidatedThroughEpoch = nextEpoch(state.highestEpoch);
      const expiredLeaseId = state.activeLeaseId;
      const expiredHolderNodeId = state.activeHolderNodeId;
      const expiredFencingEpoch = state.activeFencingEpoch;
      this.clearActiveLease(invalidatedThroughEpoch);
      this.insertAudit(
        nowMs,
        "lease.expired",
        "expired",
        expiredHolderNodeId,
        null,
        {
          leaseId: expiredLeaseId,
          expiredFencingEpoch,
          invalidatedThroughEpoch,
        },
      );
    }
    state = this.readState();
    return { state, reply: null };
  }

  private denied(
    state: StateRow,
    nowMs: number,
    eventType: string,
    actorNodeId: string,
    requestId: string | null,
    reason: string,
    details: JsonObject,
  ): AuthorityReply {
    const audit = this.insertAudit(
      nowMs,
      eventType,
      "denied",
      actorNodeId,
      requestId,
      { reason, ...details },
    );
    return {
      status: 409,
      body: {
        ok: false,
        schemaVersion: SCHEMA_VERSION,
        decision: "denied",
        reason,
        highestFencingEpoch: state.highestEpoch,
        activeLease: this.leaseView(state, nowMs),
        audit,
      },
    };
  }

  private exactFence(state: StateRow, fence: FenceInput): boolean {
    return (
      state.activeLeaseId === fence.leaseId &&
      state.activeHolderNodeId === fence.holderNodeId &&
      state.activeFencingEpoch === fence.fencingEpoch &&
      state.highestEpoch === fence.fencingEpoch
    );
  }

  private localHeartbeatFresh(state: StateRow, nowMs: number): boolean {
    return state.localValidUntilMs !== null && nowMs < state.localValidUntilMs;
  }

  private clearActiveLease(highestEpoch: number): void {
    this.ctx.storage.sql.exec(
      `UPDATE authority_state
       SET highest_epoch = ?, active_lease_id = NULL, active_holder_node_id = NULL,
           active_fencing_epoch = NULL, active_issued_at_ms = NULL,
           active_expires_at_ms = NULL, endpoint_url = NULL,
           endpoint_lease_id = NULL, endpoint_fencing_epoch = NULL,
           endpoint_published_at_ms = NULL
       WHERE singleton = 1`,
      highestEpoch,
    );
  }

  private leaseView(state: StateRow, nowMs: number): JsonObject | null {
    if (
      state.activeLeaseId === null ||
      state.activeHolderNodeId === null ||
      state.activeFencingEpoch === null ||
      state.activeIssuedAtMs === null ||
      state.activeExpiresAtMs === null
    ) {
      return null;
    }
    return {
      leaseId: state.activeLeaseId,
      holderNodeId: state.activeHolderNodeId,
      fencingEpoch: state.activeFencingEpoch,
      issuedAt: iso(state.activeIssuedAtMs),
      expiresAt: iso(state.activeExpiresAtMs),
      ttlRemainingSeconds: Math.max(
        0,
        Math.ceil((state.activeExpiresAtMs - nowMs) / 1_000),
      ),
    };
  }

  private heartbeatView(state: StateRow, nowMs: number): JsonObject | null {
    if (
      state.localOwnerNodeId === null ||
      state.localObservedAtMs === null ||
      state.localValidUntilMs === null
    ) {
      return null;
    }
    return {
      ownerNodeId: state.localOwnerNodeId,
      observedAt: iso(state.localObservedAtMs),
      validUntil: iso(state.localValidUntilMs),
      fresh: this.localHeartbeatFresh(state, nowMs),
    };
  }

  private endpointView(state: StateRow): JsonObject | null {
    if (
      state.endpointUrl === null ||
      state.endpointLeaseId === null ||
      state.endpointFencingEpoch === null ||
      state.endpointPublishedAtMs === null ||
      state.activeHolderNodeId === null
    ) {
      return null;
    }
    return {
      url: state.endpointUrl,
      leaseId: state.endpointLeaseId,
      holderNodeId: state.activeHolderNodeId,
      fencingEpoch: state.endpointFencingEpoch,
      publishedAt: iso(state.endpointPublishedAtMs),
    };
  }

  private readState(): StateRow {
    const row = this.ctx.storage.sql
      .exec<StateRow>(`
        SELECT singleton,
          highest_epoch AS highestEpoch,
          last_now_ms AS lastNowMs,
          active_lease_id AS activeLeaseId,
          active_holder_node_id AS activeHolderNodeId,
          active_fencing_epoch AS activeFencingEpoch,
          active_issued_at_ms AS activeIssuedAtMs,
          active_expires_at_ms AS activeExpiresAtMs,
          local_owner_node_id AS localOwnerNodeId,
          local_observed_at_ms AS localObservedAtMs,
          local_valid_until_ms AS localValidUntilMs,
          endpoint_url AS endpointUrl,
          endpoint_lease_id AS endpointLeaseId,
          endpoint_fencing_epoch AS endpointFencingEpoch,
          endpoint_published_at_ms AS endpointPublishedAtMs
        FROM authority_state WHERE singleton = 1
      `)
      .one();
    this.assertState(row);
    return row;
  }

  private assertState(row: StateRow): void {
    if (
      row.singleton !== 1 ||
      !Number.isSafeInteger(row.highestEpoch) ||
      row.highestEpoch < 0 ||
      !Number.isSafeInteger(row.lastNowMs) ||
      row.lastNowMs < 0
    ) {
      throw new Error("continuity authority state is invalid");
    }
    const active = [
      row.activeLeaseId,
      row.activeHolderNodeId,
      row.activeFencingEpoch,
      row.activeIssuedAtMs,
      row.activeExpiresAtMs,
    ];
    const activePresent = active.every((value) => value !== null);
    if (!activePresent && active.some((value) => value !== null)) {
      throw new Error("continuity authority active lease is incomplete");
    }
    if (
      activePresent &&
      (row.activeFencingEpoch !== row.highestEpoch ||
        (row.activeExpiresAtMs as number) <= (row.activeIssuedAtMs as number))
    ) {
      throw new Error("continuity authority active lease is inconsistent");
    }
    const endpoint = [
      row.endpointUrl,
      row.endpointLeaseId,
      row.endpointFencingEpoch,
      row.endpointPublishedAtMs,
    ];
    const endpointPresent = endpoint.every((value) => value !== null);
    if (!endpointPresent && endpoint.some((value) => value !== null)) {
      throw new Error("continuity authority endpoint is incomplete");
    }
    if (
      endpointPresent &&
      (!activePresent ||
        row.endpointLeaseId !== row.activeLeaseId ||
        row.endpointFencingEpoch !== row.activeFencingEpoch)
    ) {
      throw new Error("continuity authority endpoint fence is invalid");
    }
  }

  private insertAudit(
    occurredAtMs: number,
    eventType: string,
    outcome: string,
    actorNodeId: string | null,
    requestId: string | null,
    details: JsonObject,
  ): JsonObject {
    const auditId = crypto.randomUUID();
    const row = this.ctx.storage.sql
      .exec<{ sequence: number }>(
        `INSERT INTO audit_log (
           audit_id, occurred_at_ms, event_type, outcome,
           actor_node_id, request_id, details_json
         ) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING sequence`,
        auditId,
        occurredAtMs,
        eventType,
        outcome,
        actorNodeId,
        requestId,
        JSON.stringify(details),
      )
      .one();
    this.ctx.storage.sql.exec(
      `DELETE FROM audit_log
       WHERE sequence <= (SELECT COALESCE(MAX(sequence), 0) - ? FROM audit_log)`,
      MAX_AUDIT_ENTRIES,
    );
    return {
      sequence: row.sequence,
      auditId,
      occurredAt: iso(occurredAtMs),
      type: eventType,
      outcome,
      actorNodeId,
      requestId,
      details,
    };
  }

  private listAudit(limit: number): JsonValue[] {
    return this.ctx.storage.sql
      .exec<AuditRow>(
        `SELECT sequence,
           audit_id AS auditId,
           occurred_at_ms AS occurredAtMs,
           event_type AS eventType,
           outcome,
           actor_node_id AS actorNodeId,
           request_id AS requestId,
           details_json AS detailsJson
         FROM audit_log
         ORDER BY sequence DESC
         LIMIT ?`,
        limit,
      )
      .toArray()
      .map((row) => {
        const details: unknown = JSON.parse(row.detailsJson);
        if (!isPlainObject(details)) {
          throw new Error("continuity authority audit JSON is invalid");
        }
        return {
          sequence: row.sequence,
          auditId: row.auditId,
          occurredAt: iso(row.occurredAtMs),
          type: row.eventType,
          outcome: row.outcome,
          actorNodeId: row.actorNodeId,
          requestId: row.requestId,
          details: details as JsonObject,
        };
      });
  }
}

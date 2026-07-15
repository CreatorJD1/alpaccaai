import { env } from "cloudflare:workers";
import {
  SELF,
  evictDurableObject,
  runInDurableObject,
} from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

const AUTH_TOKEN = "test-only-continuity-token-000000000000000000000000";
const BASE_URL = "https://lease.test";

interface LeaseBody {
  leaseId: string;
  holderNodeId: string;
  fencingEpoch: number;
  issuedAt: string;
  expiresAt: string;
  ttlRemainingSeconds: number;
}

interface AuditBody {
  sequence: number;
  auditId: string;
  occurredAt: string;
  type: string;
  outcome: string;
  actorNodeId: string | null;
  requestId: string | null;
  details: Record<string, unknown>;
}

interface ApiBody {
  ok: boolean;
  authority?: string;
  storage?: string;
  decision?: string;
  error?: string;
  reason?: string;
  highestFencingEpoch?: number;
  activeLeaseCount?: number;
  activeLease?: LeaseBody | null;
  lease?: LeaseBody;
  releasedLease?: LeaseBody;
  endpoint?: Record<string, unknown> | null;
  publishedEndpoint?: Record<string, unknown> | null;
  localPrimaryPreferred?: boolean;
  recentAudit?: AuditBody[];
  entries?: AuditBody[];
}

interface ApiResult {
  response: Response;
  body: ApiBody;
}

async function request(
  path: string,
  options: {
    method?: string;
    body?: Record<string, unknown>;
    token?: string | null;
    rawBody?: string;
  } = {},
): Promise<ApiResult> {
  const headers = new Headers();
  if (options.token !== null) {
    headers.set("authorization", `Bearer ${options.token ?? AUTH_TOKEN}`);
  }
  let body: string | undefined;
  if (options.body !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(options.body);
  } else if (options.rawBody !== undefined) {
    headers.set("content-type", "application/json");
    body = options.rawBody;
  }
  const response = await SELF.fetch(`${BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body,
  });
  return { response, body: (await response.json()) as ApiBody };
}

async function acquire(holderNodeId: string, ttlSeconds = 35): Promise<ApiResult> {
  return request("/v1/lease/acquire", {
    method: "POST",
    body: { holderNodeId, ttlSeconds },
  });
}

function exactFence(lease: LeaseBody): Record<string, unknown> {
  return {
    holderNodeId: lease.holderNodeId,
    leaseId: lease.leaseId,
    fencingEpoch: lease.fencingEpoch,
  };
}

beforeEach(async () => {
  await request("/health");
  const stub = env.IDENTITY.getByName("identity");
  await runInDurableObject(stub, (_instance, state) => {
    state.storage.transactionSync(() => {
      state.storage.sql.exec(`
        UPDATE authority_state
        SET highest_epoch = 0, last_now_ms = 0,
            active_lease_id = NULL, active_holder_node_id = NULL,
            active_fencing_epoch = NULL, active_issued_at_ms = NULL,
            active_expires_at_ms = NULL, local_owner_node_id = NULL,
            local_observed_at_ms = NULL, local_valid_until_ms = NULL,
            endpoint_url = NULL, endpoint_lease_id = NULL,
            endpoint_fencing_epoch = NULL, endpoint_published_at_ms = NULL
        WHERE singleton = 1
      `);
      state.storage.sql.exec("DELETE FROM audit_log");
    });
  });
});

describe("authenticated authority routes", () => {
  it("requires the bearer token even for health and status", async () => {
    const missing = await request("/health", { token: null });
    expect(missing.response.status).toBe(401);
    expect(missing.response.headers.get("www-authenticate")).toContain("Bearer");

    const wrong = await request("/v1/status", { token: "wrong-token" });
    expect(wrong.response.status).toBe(401);

    const health = await request("/health");
    expect(health.response.status).toBe(200);
    expect(health.body).toMatchObject({
      ok: true,
      authority: "identity",
      storage: "sqlite-durable-object",
      highestFencingEpoch: 0,
    });
  });

  it("exposes only the current fenced endpoint without a bearer token", async () => {
    const endpoint = await request("/v1/endpoint", { token: null });
    expect(endpoint.response.status).toBe(200);
    expect(endpoint.body).toMatchObject({ ok: true, endpoint: null });

    const status = await request("/v1/status", { token: null });
    expect(status.response.status).toBe(401);
  });

  it("rejects oversized and malformed mutation bodies before the authority", async () => {
    const oversized = await request("/v1/lease/acquire", {
      method: "POST",
      rawBody: JSON.stringify({ holderNodeId: `node-${"x".repeat(5_000)}` }),
    });
    expect(oversized.response.status).toBe(413);
    expect(oversized.body.error).toBe("request-too-large");

    const malformed = await request("/v1/lease/acquire", {
      method: "POST",
      rawBody: "{",
    });
    expect(malformed.response.status).toBe(400);
    expect(malformed.body.error).toBe("invalid-json");
  });
});

describe("singleton lease policy", () => {
  it("reserves acquisition for the fresh local heartbeat owner", async () => {
    const invalidTtl = await request("/v1/heartbeat/local", {
      method: "POST",
      body: { ownerNodeId: "windows-primary", ttlSeconds: 36 },
    });
    expect(invalidTtl.response.status).toBe(400);

    const heartbeat = await request("/v1/heartbeat/local", {
      method: "POST",
      body: {
        ownerNodeId: "windows-primary",
        ttlSeconds: 35,
        requestId: "heartbeat-001",
      },
    });
    expect(heartbeat.response.status).toBe(200);
    expect(heartbeat.body.decision).toBe("accepted");

    const standby = await acquire("ubuntu-standby");
    expect(standby.response.status).toBe(409);
    expect(standby.body.reason).toBe("fresh-local-heartbeat");

    const local = await acquire("windows-primary");
    expect(local.response.status).toBe(201);
    expect(local.body.lease).toMatchObject({
      holderNodeId: "windows-primary",
      fencingEpoch: 1,
    });

    const second = await acquire("other-node");
    expect(second.response.status).toBe(409);
    expect(second.body.reason).toBe("lease-already-active");

    const status = await request("/v1/status");
    expect(status.body.activeLeaseCount).toBe(1);
    expect(status.body.localPrimaryPreferred).toBe(true);
  });

  it("serializes concurrent contenders so exactly one lease is granted", async () => {
    const contenders = await Promise.all(
      Array.from({ length: 8 }, (_, index) => acquire(`contender-${index}`)),
    );
    const granted = contenders.filter((result) => result.response.status === 201);
    const denied = contenders.filter((result) => result.response.status === 409);
    expect(granted).toHaveLength(1);
    expect(denied).toHaveLength(7);
    expect(new Set(granted.map((result) => result.body.lease?.leaseId)).size).toBe(1);

    const status = await request("/v1/status");
    expect(status.body.activeLeaseCount).toBe(1);
    expect(status.body.activeLease?.leaseId).toBe(granted[0]!.body.lease?.leaseId);
  });

  it("stops reserving acquisition after the local heartbeat is stale", async () => {
    await request("/v1/heartbeat/local", {
      method: "POST",
      body: { ownerNodeId: "windows-primary", ttlSeconds: 35 },
    });
    const stub = env.IDENTITY.getByName("identity");
    await runInDurableObject(stub, (_instance, state) => {
      const now = Date.now();
      state.storage.sql.exec(
        `UPDATE authority_state
         SET local_observed_at_ms = ?, local_valid_until_ms = ?
         WHERE singleton = 1`,
        now - 2_000,
        now - 1_000,
      );
    });

    const standby = await acquire("ubuntu-standby");
    expect(standby.response.status).toBe(201);
    expect(standby.body.lease).toMatchObject({
      holderNodeId: "ubuntu-standby",
      fencingEpoch: 1,
    });
    const status = await request("/v1/status");
    expect(status.body.localPrimaryPreferred).toBe(false);
  });

  it("denies cloud renewal for failback but continues renewing the local holder", async () => {
    const cloud = await acquire("cloud-standby:ubuntu-a");
    const cloudLease = cloud.body.lease!;
    await request("/v1/heartbeat/local", {
      method: "POST",
      body: { ownerNodeId: "local-primary:windows-a", ttlSeconds: 35 },
    });

    const cloudRenewal = await request("/v1/lease/renew", {
      method: "POST",
      body: { ...exactFence(cloudLease), ttlSeconds: 35 },
    });
    expect(cloudRenewal.response.status).toBe(409);
    expect(cloudRenewal.body.reason).toBe(
      "fresh-local-heartbeat-requires-cloud-failback",
    );
    expect(cloudRenewal.body.activeLease).toMatchObject({
      leaseId: cloudLease.leaseId,
      holderNodeId: "cloud-standby:ubuntu-a",
      fencingEpoch: cloudLease.fencingEpoch,
    });

    const stub = env.IDENTITY.getByName("identity");
    await runInDurableObject(stub, (_instance, state) => {
      const now = Date.now();
      state.storage.sql.exec(
        `UPDATE authority_state
         SET active_issued_at_ms = ?, active_expires_at_ms = ?
         WHERE singleton = 1`,
        now - 2_000,
        now - 1_000,
      );
    });

    const local = await acquire("local-primary:windows-a");
    expect(local.response.status).toBe(201);
    expect(local.body.lease).toMatchObject({
      holderNodeId: "local-primary:windows-a",
      fencingEpoch: 3,
    });

    const localRenewal = await request("/v1/lease/renew", {
      method: "POST",
      body: { ...exactFence(local.body.lease!), ttlSeconds: 35 },
    });
    expect(localRenewal.response.status).toBe(200);
    expect(localRenewal.body).toMatchObject({
      ok: true,
      decision: "renewed",
      lease: {
        leaseId: local.body.lease!.leaseId,
        holderNodeId: "local-primary:windows-a",
        fencingEpoch: 3,
      },
    });
  });

  it("renews only the exact active fence and advances beyond an expired lease", async () => {
    const first = await acquire("node-a", 35);
    const lease = first.body.lease!;
    const renewed = await request("/v1/lease/renew", {
      method: "POST",
      body: { ...exactFence(lease), ttlSeconds: 35, requestId: "renew-001" },
    });
    expect(renewed.response.status).toBe(200);
    expect(renewed.body.lease?.leaseId).toBe(lease.leaseId);
    expect(renewed.body.lease?.fencingEpoch).toBe(lease.fencingEpoch);
    expect(
      Date.parse(renewed.body.lease!.expiresAt) -
        Date.parse(renewed.body.lease!.issuedAt),
    ).toBeLessThanOrEqual(35_000);

    const staleRenewal = await request("/v1/lease/renew", {
      method: "POST",
      body: {
        ...exactFence(lease),
        fencingEpoch: lease.fencingEpoch + 1,
        ttlSeconds: 35,
      },
    });
    expect(staleRenewal.response.status).toBe(409);
    expect(staleRenewal.body.reason).toBe("stale-or-non-owner-fence");

    const stub = env.IDENTITY.getByName("identity");
    await runInDurableObject(stub, (_instance, state) => {
      const now = Date.now();
      state.storage.sql.exec(
        `UPDATE authority_state
         SET active_issued_at_ms = ?, active_expires_at_ms = ?
         WHERE singleton = 1`,
        now - 2_000,
        now - 1_000,
      );
    });

    const successor = await acquire("node-b");
    expect(successor.response.status).toBe(201);
    expect(successor.body.lease?.fencingEpoch).toBe(3);

    const audit = await request("/v1/audit?limit=100");
    expect(audit.body.entries?.some((entry) => entry.type === "lease.expired")).toBe(
      true,
    );
  });

  it("persists the active lease and fence across Durable Object eviction", async () => {
    const granted = await acquire("persistent-node");
    const lease = granted.body.lease!;
    const stub = env.IDENTITY.getByName("identity");
    await evictDurableObject(stub);

    const status = await request("/v1/status");
    expect(status.body.highestFencingEpoch).toBe(lease.fencingEpoch);
    expect(status.body.activeLease).toMatchObject({
      leaseId: lease.leaseId,
      holderNodeId: "persistent-node",
      fencingEpoch: lease.fencingEpoch,
    });
  });
});

describe("fenced endpoint publication and audit", () => {
  it("publishes only from the active fence and clears publication on release", async () => {
    const granted = await acquire("portal-node");
    const lease = granted.body.lease!;

    const unsafeEndpoint = await request("/v1/endpoint", {
      method: "PUT",
      body: {
        ...exactFence(lease),
        endpoint: "https://portal.example.test/house?token=not-allowed",
      },
    });
    expect(unsafeEndpoint.response.status).toBe(400);

    const published = await request("/v1/endpoint", {
      method: "PUT",
      body: {
        ...exactFence(lease),
        endpoint: "https://portal.example.test/house-hq",
        requestId: "endpoint-001",
      },
    });
    expect(published.response.status).toBe(200);
    expect(published.body.publishedEndpoint).toMatchObject({
      url: "https://portal.example.test/house-hq",
      leaseId: lease.leaseId,
      holderNodeId: "portal-node",
      fencingEpoch: lease.fencingEpoch,
    });

    const endpoint = await request("/v1/endpoint");
    expect(endpoint.body.endpoint).toMatchObject({ leaseId: lease.leaseId });

    const released = await request("/v1/lease/release", {
      method: "POST",
      body: { ...exactFence(lease), requestId: "release-001" },
    });
    expect(released.response.status).toBe(200);
    expect(released.body.highestFencingEpoch).toBe(2);
    expect(released.body.activeLease).toBeNull();

    const cleared = await request("/v1/endpoint");
    expect(cleared.body.endpoint).toBeNull();

    const stalePublish = await request("/v1/endpoint", {
      method: "PUT",
      body: {
        ...exactFence(lease),
        endpoint: "https://stale.example.test/house-hq",
      },
    });
    expect(stalePublish.response.status).toBe(409);

    const successor = await acquire("successor-node");
    expect(successor.body.lease?.fencingEpoch).toBe(3);
  });

  it("stores bounded audit details as valid JSON entries", async () => {
    const granted = await acquire("audit-node");
    const lease = granted.body.lease!;
    await request("/v1/lease/release", {
      method: "POST",
      body: { ...exactFence(lease), requestId: "audit-release-001" },
    });

    const audit = await request("/v1/audit?limit=10");
    expect(audit.response.status).toBe(200);
    expect(audit.body.entries?.length).toBeGreaterThanOrEqual(2);
    for (const entry of audit.body.entries ?? []) {
      expect(entry.auditId).toMatch(/^[0-9a-f-]{36}$/);
      expect(entry.details).toEqual(expect.any(Object));
      expect(Number.isSafeInteger(entry.sequence)).toBe(true);
    }

    const stub = env.IDENTITY.getByName("identity");
    await runInDurableObject(stub, (_instance, state) => {
      const rows = state.storage.sql
        .exec("SELECT json_valid(details_json) AS valid FROM audit_log")
        .toArray();
      expect(rows.length).toBeGreaterThanOrEqual(2);
      expect(rows.every((row) => row.valid === 1)).toBe(true);
    });
  });
});

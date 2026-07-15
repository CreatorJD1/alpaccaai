// Alpecca Mindscape Vault: opaque, immutable continuity backups.
//
// The local Alpecca host encrypts every record before it reaches this Worker.
// This service never accepts plaintext snapshots, never runs a model, and never
// starts a second Alpecca instance. R2 holds versioned ciphertext only.

const VAULT_SCHEMA = "alpecca.mindscape.vault.v1";
const SNAPSHOT_KIND = "snapshot";
const ARCHIVE_KIND = "sqlite";
const MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024;
const MAX_ARCHIVE_BYTES = 96 * 1024 * 1024;
const SNAPSHOT_RETENTION = 48;
const ARCHIVE_RETENTION = 8;
const ID_RE = /^[a-f0-9]{32}$/;
const HEX_64_RE = /^[a-f0-9]{64}$/;
const KEY_ID_RE = /^[a-f0-9]{24}$/;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function authorized(request, env) {
  const expected = env.MINDSCAPE_VAULT_TOKEN || "";
  if (!expected) return false;
  const bearer = request.headers.get("authorization") || "";
  const explicit = request.headers.get("x-alpecca-mindscape-vault-token") || "";
  return bearer === `Bearer ${expected}` || explicit === expected;
}

function byteLength(text) {
  return new TextEncoder().encode(text).byteLength;
}

function validSequence(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function validTimestamp(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 && value < 4_102_444_800;
}

function isOpaqueId(value, length = 32) {
  if (typeof value !== "string" || value.length !== length) return false;
  return length === 32 ? ID_RE.test(value) : KEY_ID_RE.test(value);
}

function isSha256(value) {
  return typeof value === "string" && HEX_64_RE.test(value);
}

function validateSnapshotEnvelope(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, error: "envelope must be an object" };
  }
  const expected = [
    "schema", "kind", "algorithm", "scope", "key_id", "writer_id", "sequence",
    "created_at", "snapshot_ts", "compression", "nonce", "ciphertext",
    "ciphertext_sha256", "plaintext_sha256",
  ].sort();
  const actual = Object.keys(value).sort();
  if (actual.length !== expected.length || actual.some((name, index) => name !== expected[index])) {
    return { ok: false, error: "invalid envelope fields" };
  }
  if (value.schema !== VAULT_SCHEMA || value.kind !== SNAPSHOT_KIND ||
      value.algorithm !== "AES-256-GCM" || value.compression !== "zlib") {
    return { ok: false, error: "invalid envelope schema" };
  }
  if (!isOpaqueId(value.scope) || !isOpaqueId(value.writer_id) || !isOpaqueId(value.key_id, 24) ||
      !validSequence(value.sequence) || !validTimestamp(value.created_at) || !validTimestamp(value.snapshot_ts) ||
      !isSha256(value.ciphertext_sha256) || !isSha256(value.plaintext_sha256)) {
    return { ok: false, error: "invalid envelope metadata" };
  }
  if (typeof value.nonce !== "string" || value.nonce.length < 16 || value.nonce.length > 32 ||
      typeof value.ciphertext !== "string" || value.ciphertext.length < 24 ||
      byteLength(value.ciphertext) > MAX_SNAPSHOT_BYTES * 2) {
    return { ok: false, error: "invalid encrypted payload" };
  }
  return { ok: true, metadata: value };
}

function decodeBase64UrlJson(value) {
  if (typeof value !== "string" || !value || value.length > 4096) {
    throw new Error("invalid archive metadata");
  }
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const text = new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
  return JSON.parse(text);
}

function validateArchiveMetadata(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, error: "archive metadata must be an object" };
  }
  const expected = [
    "schema", "kind", "algorithm", "scope", "key_id", "writer_id", "sequence",
    "created_at", "plaintext_bytes", "plaintext_sha256", "nonce", "ciphertext_bytes",
    "ciphertext_sha256",
  ].sort();
  const actual = Object.keys(value).sort();
  if (actual.length !== expected.length || actual.some((name, index) => name !== expected[index])) {
    return { ok: false, error: "invalid archive metadata fields" };
  }
  if (value.schema !== VAULT_SCHEMA || value.kind !== ARCHIVE_KIND || value.algorithm !== "AES-256-GCM") {
    return { ok: false, error: "invalid archive metadata schema" };
  }
  if (!isOpaqueId(value.scope) || !isOpaqueId(value.writer_id) || !isOpaqueId(value.key_id, 24) ||
      !validSequence(value.sequence) || !validTimestamp(value.created_at) ||
      !Number.isSafeInteger(value.plaintext_bytes) || !Number.isSafeInteger(value.ciphertext_bytes) ||
      value.plaintext_bytes < 1 || value.plaintext_bytes > MAX_ARCHIVE_BYTES ||
      value.ciphertext_bytes < 17 || value.ciphertext_bytes > MAX_ARCHIVE_BYTES ||
      !isSha256(value.plaintext_sha256) || !isSha256(value.ciphertext_sha256) ||
      typeof value.nonce !== "string" || value.nonce.length < 16 || value.nonce.length > 32) {
    return { ok: false, error: "invalid archive metadata" };
  }
  return { ok: true, metadata: value };
}

function objectKey(kind, metadata) {
  const sequence = String(metadata.sequence).padStart(20, "0");
  const digest = metadata.ciphertext_sha256.slice(0, 24);
  const extension = kind === SNAPSHOT_KIND ? "json" : "bin";
  return `v1/${metadata.scope}/${kind}/${sequence}-${metadata.writer_id}-${digest}.${extension}`;
}

function objectMetadata(kind, metadata) {
  const value = {
    schema: VAULT_SCHEMA,
    kind,
    algorithm: metadata.algorithm,
    scope: metadata.scope,
    key_id: metadata.key_id,
    writer_id: metadata.writer_id,
    sequence: String(metadata.sequence),
    created_at: String(metadata.created_at),
    ciphertext_sha256: metadata.ciphertext_sha256,
    plaintext_sha256: metadata.plaintext_sha256,
  };
  if (kind === ARCHIVE_KIND) {
    value.nonce = metadata.nonce;
    value.plaintext_bytes = String(metadata.plaintext_bytes);
    value.ciphertext_bytes = String(metadata.ciphertext_bytes);
  }
  return value;
}

async function immutablePut(env, key, value, metadata, contentType) {
  const stored = await env.MINDSCAPE_VAULT_ARCHIVE.put(key, value, {
    onlyIf: new Headers({ "if-none-match": "*" }),
    httpMetadata: { contentType, cacheControl: "no-store" },
    customMetadata: metadata,
  });
  if (stored) return { status: "stored", key };
  const existing = await env.MINDSCAPE_VAULT_ARCHIVE.head(key);
  if (existing?.customMetadata?.ciphertext_sha256 === metadata.ciphertext_sha256) {
    return { status: "duplicate", key };
  }
  return { status: "conflict", key };
}

async function listObjects(env, kind, scope) {
  const prefix = `v1/${scope}/${kind}/`;
  const result = await env.MINDSCAPE_VAULT_ARCHIVE.list({
    prefix,
    limit: 1000,
    include: ["customMetadata"],
  });
  return result.objects
    .filter((object) => object.customMetadata?.kind === kind && object.customMetadata?.scope === scope)
    // A local database restore can legitimately introduce a different writer
    // id with its own sequence counter.  The authenticated creation timestamp
    // is therefore the cross-writer ordering authority; sequence/key only
    // break an equal-time tie.  A late network retry retains its old timestamp
    // and cannot become the apparent newest continuity record.
    .sort((a, b) => {
      const created = Number(b.customMetadata?.created_at || 0) - Number(a.customMetadata?.created_at || 0);
      if (created) return created;
      const sequence = Number(b.customMetadata?.sequence || 0) - Number(a.customMetadata?.sequence || 0);
      if (sequence) return sequence;
      return b.key.localeCompare(a.key);
    });
}

async function latestObject(env, kind, scope) {
  const objects = await listObjects(env, kind, scope);
  return objects[0] || null;
}

async function retainNewest(env, kind, scope, keep) {
  const objects = await listObjects(env, kind, scope);
  const stale = objects.slice(keep).map((object) => object.key);
  if (stale.length) await env.MINDSCAPE_VAULT_ARCHIVE.delete(stale);
}

function requestedScope(request) {
  const scope = (request.headers.get("x-alpecca-mindscape-vault-scope") || "").toLowerCase();
  return ID_RE.test(scope) ? scope : "";
}

async function uploadSnapshot(request, env) {
  const advertised = Number(request.headers.get("content-length") || "0");
  if (advertised && (!Number.isSafeInteger(advertised) || advertised > MAX_SNAPSHOT_BYTES)) {
    return json({ ok: false, error: "snapshot exceeds size limit" }, 413);
  }
  let body;
  try {
    body = await request.json();
  } catch (_error) {
    return json({ ok: false, error: "body must be JSON" }, 400);
  }
  const validation = validateSnapshotEnvelope(body?.envelope);
  if (!validation.ok) return json({ ok: false, error: validation.error }, 400);
  const serialized = JSON.stringify(validation.metadata);
  if (byteLength(serialized) > MAX_SNAPSHOT_BYTES) {
    return json({ ok: false, error: "snapshot exceeds size limit" }, 413);
  }
  const key = objectKey(SNAPSHOT_KIND, validation.metadata);
  const result = await immutablePut(
    env,
    key,
    serialized,
    objectMetadata(SNAPSHOT_KIND, validation.metadata),
    "application/json",
  );
  if (result.status === "conflict") return json({ ok: false, status: result.status }, 409);
  await retainNewest(env, SNAPSHOT_KIND, validation.metadata.scope, SNAPSHOT_RETENTION);
  return json({
    ok: true,
    status: result.status,
    sequence: validation.metadata.sequence,
  }, result.status === "stored" ? 201 : 200);
}

async function uploadArchive(request, env) {
  const contentLength = request.headers.get("content-length");
  const advertised = Number(contentLength || "0");
  if (!contentLength || !Number.isSafeInteger(advertised) || advertised < 17 || advertised > MAX_ARCHIVE_BYTES) {
    return json({ ok: false, error: "archive requires a bounded content length" }, 413);
  }
  let metadata;
  try {
    metadata = decodeBase64UrlJson(request.headers.get("x-alpecca-mindscape-vault-metadata"));
  } catch (_error) {
    return json({ ok: false, error: "invalid archive metadata" }, 400);
  }
  const validation = validateArchiveMetadata(metadata);
  if (!validation.ok) return json({ ok: false, error: validation.error }, 400);
  if (validation.metadata.ciphertext_bytes !== advertised || !request.body) {
    return json({ ok: false, error: "archive length does not match metadata" }, 400);
  }
  const key = objectKey(ARCHIVE_KIND, validation.metadata);
  const result = await immutablePut(
    env,
    key,
    request.body,
    objectMetadata(ARCHIVE_KIND, validation.metadata),
    "application/octet-stream",
  );
  if (result.status === "conflict") return json({ ok: false, status: result.status }, 409);
  await retainNewest(env, ARCHIVE_KIND, validation.metadata.scope, ARCHIVE_RETENTION);
  return json({
    ok: true,
    status: result.status,
    sequence: validation.metadata.sequence,
  }, result.status === "stored" ? 201 : 200);
}

async function downloadSnapshot(request, env) {
  const scope = requestedScope(request);
  if (!scope) return json({ ok: false, error: "valid vault scope is required" }, 400);
  const object = await latestObject(env, SNAPSHOT_KIND, scope);
  if (!object) return json({ ok: false, error: "no snapshot stored" }, 404);
  const body = await env.MINDSCAPE_VAULT_ARCHIVE.get(object.key);
  if (!body || !("body" in body)) return json({ ok: false, error: "snapshot object is unavailable" }, 404);
  return new Response(body.body, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-alpecca-vault-sequence": object.customMetadata?.sequence || "",
    },
  });
}

function metadataHeader(metadata) {
  const raw = JSON.stringify(metadata);
  const bytes = new TextEncoder().encode(raw);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function downloadArchive(request, env) {
  const scope = requestedScope(request);
  if (!scope) return json({ ok: false, error: "valid vault scope is required" }, 400);
  const object = await latestObject(env, ARCHIVE_KIND, scope);
  if (!object) return json({ ok: false, error: "no archive stored" }, 404);
  const body = await env.MINDSCAPE_VAULT_ARCHIVE.get(object.key);
  if (!body || !("body" in body)) return json({ ok: false, error: "archive object is unavailable" }, 404);
  const stored = object.customMetadata || {};
  const metadata = {
    ...stored,
    sequence: Number(stored.sequence),
    created_at: Number(stored.created_at),
    plaintext_bytes: Number(stored.plaintext_bytes),
    ciphertext_bytes: Number(stored.ciphertext_bytes),
  };
  const validation = validateArchiveMetadata(metadata);
  if (!validation.ok) return json({ ok: false, error: "archive metadata is unavailable" }, 500);
  return new Response(body.body, {
    headers: {
      "content-type": "application/octet-stream",
      "cache-control": "no-store",
      "x-alpecca-mindscape-vault-metadata": metadataHeader(validation.metadata),
      "x-alpecca-vault-sequence": stored.sequence || "",
    },
  });
}

async function status(request, env) {
  const scope = requestedScope(request);
  if (!scope) return json({ ok: false, error: "valid vault scope is required" }, 400);
  const [snapshot, archive] = await Promise.all([
    latestObject(env, SNAPSHOT_KIND, scope),
    latestObject(env, ARCHIVE_KIND, scope),
  ]);
  return json({
    ok: true,
    schema: VAULT_SCHEMA,
    snapshot: snapshot ? {
      sequence: Number(snapshot.customMetadata?.sequence || 0),
      created_at: Number(snapshot.customMetadata?.created_at || 0),
    } : null,
    archive: archive ? {
      sequence: Number(archive.customMetadata?.sequence || 0),
      created_at: Number(archive.customMetadata?.created_at || 0),
    } : null,
  });
}

export default {
  async fetch(request, env) {
    if (!env.MINDSCAPE_VAULT_ARCHIVE) {
      return json({ ok: false, error: "MINDSCAPE_VAULT_ARCHIVE binding missing" }, 500);
    }
    if (!authorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401);
    const path = new URL(request.url).pathname;
    if (request.method === "POST" && path === "/v1/snapshot") return uploadSnapshot(request, env);
    if (request.method === "GET" && path === "/v1/snapshot/latest") return downloadSnapshot(request, env);
    if (request.method === "POST" && path === "/v1/archive") return uploadArchive(request, env);
    if (request.method === "GET" && path === "/v1/archive/latest") return downloadArchive(request, env);
    if (request.method === "GET" && path === "/v1/status") return status(request, env);
    return json({ ok: false, error: "not found" }, 404);
  },
};

import {
  MAX_AUDIT_LIMIT,
  MAX_REQUEST_BYTES,
  SCHEMA_VERSION,
  type AuthorityAction,
  type JsonObject,
} from "./contracts";
import { ContinuityLeaseAuthority } from "./authority";

export { ContinuityLeaseAuthority } from "./authority";

interface Route {
  action: AuthorityAction;
  readsBody: boolean;
  auditLimit?: number;
}

function authorityStub(env: Env): DurableObjectStub<ContinuityLeaseAuthority> {
  return env.IDENTITY.getByName("identity") as DurableObjectStub<ContinuityLeaseAuthority>;
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

const KNOWN_ROUTES: Readonly<Record<string, readonly string[]>> = {
  "/health": ["GET"],
  "/v1/status": ["GET"],
  "/v1/heartbeat/local": ["POST"],
  "/v1/lease/acquire": ["POST"],
  "/v1/lease/renew": ["POST"],
  "/v1/lease/release": ["POST"],
  "/v1/endpoint": ["GET", "PUT"],
  "/v1/audit": ["GET"],
};

function json(body: JsonObject, status = 200, extraHeaders?: HeadersInit): Response {
  const headers = new Headers(extraHeaders);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "no-referrer");
  return new Response(JSON.stringify(body), { status, headers });
}

function serializedJson(
  bodyJson: string,
  status: number,
  extraHeaders?: HeadersInit,
): Response {
  const headers = new Headers(extraHeaders);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "no-referrer");
  return new Response(bodyJson, { status, headers });
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function readBoundedJson(request: Request): Promise<JsonObject> {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    throw new HttpError(415, "unsupported-media-type", "request body must be JSON");
  }

  const contentLength = request.headers.get("content-length");
  if (contentLength !== null) {
    const advertised = Number(contentLength);
    if (!Number.isSafeInteger(advertised) || advertised < 0) {
      throw new HttpError(400, "invalid-content-length", "invalid content length");
    }
    if (advertised > MAX_REQUEST_BYTES) {
      throw new HttpError(413, "request-too-large", "request body exceeds size limit");
    }
  }
  if (request.body === null) {
    throw new HttpError(400, "invalid-json", "request body must be a JSON object");
  }

  const reader = request.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let bytesRead = 0;
  let text = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytesRead += value.byteLength;
      if (bytesRead > MAX_REQUEST_BYTES) {
        await reader.cancel("request body exceeds size limit");
        throw new HttpError(413, "request-too-large", "request body exceeds size limit");
      }
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(400, "invalid-json", "request body must be valid UTF-8 JSON");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new HttpError(400, "invalid-json", "request body must be valid JSON");
  }
  if (!isPlainObject(parsed)) {
    throw new HttpError(400, "invalid-json", "request body must be a JSON object");
  }
  return parsed as JsonObject;
}

async function sha256(value: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return new Uint8Array(digest);
}

async function constantTimeEqual(left: string, right: string): Promise<boolean> {
  const [leftDigest, rightDigest] = await Promise.all([sha256(left), sha256(right)]);
  let difference = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    difference |= leftDigest[index]! ^ rightDigest[index]!;
  }
  return difference === 0;
}

async function authorized(request: Request, expected: string): Promise<boolean> {
  const header = request.headers.get("authorization") ?? "";
  const match = /^Bearer ([^\s]{1,4096})$/.exec(header);
  if (!match) return false;
  return constantTimeEqual(match[1]!, expected);
}

function requireNoQuery(url: URL): void {
  if (url.search !== "") {
    throw new HttpError(400, "unexpected-query", "query parameters are not accepted");
  }
}

function parseAuditLimit(url: URL): number | undefined {
  const keys = [...url.searchParams.keys()];
  if (keys.some((key) => key !== "limit") || url.searchParams.getAll("limit").length > 1) {
    throw new HttpError(400, "invalid-query", "only one audit limit is accepted");
  }
  const raw = url.searchParams.get("limit");
  if (raw === null) return undefined;
  if (!/^[1-9][0-9]*$/.test(raw)) {
    throw new HttpError(400, "invalid-query", "audit limit must be an integer");
  }
  const limit = Number(raw);
  if (!Number.isSafeInteger(limit) || limit > MAX_AUDIT_LIMIT) {
    throw new HttpError(
      400,
      "invalid-query",
      `audit limit must be between 1 and ${MAX_AUDIT_LIMIT}`,
    );
  }
  return limit;
}

function matchRoute(request: Request, url: URL): Route {
  const allowed = KNOWN_ROUTES[url.pathname];
  if (!allowed) {
    throw new HttpError(404, "not-found", "route not found");
  }
  if (!allowed.includes(request.method)) {
    throw new HttpError(405, "method-not-allowed", allowed.join(", "));
  }

  switch (`${request.method} ${url.pathname}`) {
    case "GET /health":
      requireNoQuery(url);
      return { action: "health", readsBody: false };
    case "GET /v1/status":
      requireNoQuery(url);
      return { action: "status", readsBody: false };
    case "POST /v1/heartbeat/local":
      requireNoQuery(url);
      return { action: "heartbeat", readsBody: true };
    case "POST /v1/lease/acquire":
      requireNoQuery(url);
      return { action: "acquire", readsBody: true };
    case "POST /v1/lease/renew":
      requireNoQuery(url);
      return { action: "renew", readsBody: true };
    case "POST /v1/lease/release":
      requireNoQuery(url);
      return { action: "release", readsBody: true };
    case "GET /v1/endpoint":
      requireNoQuery(url);
      return { action: "get-endpoint", readsBody: false };
    case "PUT /v1/endpoint":
      requireNoQuery(url);
      return { action: "publish-endpoint", readsBody: true };
    case "GET /v1/audit":
      return { action: "audit", readsBody: false, auditLimit: parseAuditLimit(url) };
    default:
      throw new HttpError(404, "not-found", "route not found");
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // The currently fenced app URL is intentionally credential-free discovery
    // metadata. It contains no token or private state, and the Durable Object
    // clears it whenever its exact lease expires. Every mutation and all audit
    // or status detail remain bearer-authenticated below.
    const requestUrl = new URL(request.url);
    if (request.method === "GET" && requestUrl.pathname === "/v1/endpoint") {
      try {
        requireNoQuery(requestUrl);
        const authority = authorityStub(env);
        const reply = await authority.handle("get-endpoint", "{}", 0);
        return serializedJson(reply.bodyJson, reply.status);
      } catch (error) {
        if (error instanceof HttpError) {
          return json(
            { ok: false, schemaVersion: SCHEMA_VERSION, error: error.code },
            error.status,
          );
        }
        return json(
          { ok: false, schemaVersion: SCHEMA_VERSION, error: "internal-error" },
          500,
        );
      }
    }
    if (typeof env.LEASE_AUTH_TOKEN !== "string" || env.LEASE_AUTH_TOKEN.length === 0) {
      return json(
        {
          ok: false,
          schemaVersion: SCHEMA_VERSION,
          error: "lease authority is not configured",
        },
        503,
      );
    }
    if (!(await authorized(request, env.LEASE_AUTH_TOKEN))) {
      return json(
        {
          ok: false,
          schemaVersion: SCHEMA_VERSION,
          error: "unauthorized",
        },
        401,
        { "www-authenticate": 'Bearer realm="alpecca-continuity-lease"' },
      );
    }

    try {
      const route = matchRoute(request, requestUrl);
      const payload = route.readsBody ? await readBoundedJson(request) : {};
      const authority = authorityStub(env);
      const reply = await authority.handle(
        route.action,
        JSON.stringify(payload),
        route.auditLimit ?? 0,
      );
      return serializedJson(reply.bodyJson, reply.status);
    } catch (error) {
      if (error instanceof HttpError) {
        const headers =
          error.status === 405 ? { allow: error.message } : undefined;
        return json(
          {
            ok: false,
            schemaVersion: SCHEMA_VERSION,
            error: error.code,
          },
          error.status,
          headers,
        );
      }
      console.error(
        JSON.stringify({
          event: "continuity_lease_request_failed",
          errorType: error instanceof Error ? error.name : "UnknownError",
        }),
      );
      return json(
        {
          ok: false,
          schemaVersion: SCHEMA_VERSION,
          error: "internal-error",
        },
        500,
      );
    }
  },
};

const DEFAULT_DISCOVERY_URL =
  "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/alpecca-endpoint.json";

const DISCOVERY_SERVICE = "alpecca-mobile-discovery";
const DISCOVERY_VERSION = 1;
const DISCOVERY_SCAN_LIMIT = 8;
const RECOVERY_CANDIDATE_LIMIT = 4;
const RECOVERY_BUDGET_MS = 5_000;
const DISCOVERY_REQUEST_TIMEOUT_MS = 5_000;
const RECOVERY_COOLDOWN_MS = 60_000;
const DISCOVERY_BODY_LIMIT = 16 * 1024;

type DiscoveryKind = "named" | "quick";

export type AlpeccaEndpointCandidate = {
  url: string;
  kind: DiscoveryKind;
  priority: number;
  expiresAt: number;
};

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

type RecoveryOptions = {
  discoveryUrl?: string;
  backendStorageKey?: string;
  force?: boolean;
  fetchImpl?: FetchLike;
  recoveryBudgetMs?: number;
  now?: () => number;
};

type JsonFetchResult = {
  response: Response;
  body: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedMilliseconds(value: number | undefined, fallback: number, limit: number) {
  if (value === undefined) return fallback;
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(limit, Math.floor(value)));
}

function lexicalCompare(left: string, right: string) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

export function normalizeAlpeccaEndpoint(value: unknown) {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return "";
    if (url.search || url.hash || !["/", "/house-hq"].includes(url.pathname)) return "";
    return url.origin;
  } catch {
    return "";
  }
}

export function isEphemeralAlpeccaHost(hostname: string) {
  const host = hostname.trim().toLowerCase();
  return host.endsWith(".loca.lt") || host.endsWith(".trycloudflare.com");
}

export function readAlpeccaEndpointCandidates(
  document: unknown,
  nowSeconds = Date.now() / 1000,
): AlpeccaEndpointCandidate[] {
  if (!isRecord(document)
      || document.service !== DISCOVERY_SERVICE
      || document.version !== DISCOVERY_VERSION
      || !Array.isArray(document.endpoints)) {
    return [];
  }

  const timestamp = Number.isFinite(nowSeconds) ? Math.floor(nowSeconds) : Math.floor(Date.now() / 1000);
  const candidates: AlpeccaEndpointCandidate[] = [];
  for (const value of document.endpoints.slice(0, DISCOVERY_SCAN_LIMIT)) {
    if (!isRecord(value)) continue;
    const url = normalizeAlpeccaEndpoint(value.url);
    const kind = value.kind;
    if (!url || (kind !== "named" && kind !== "quick")) continue;

    const rawPriority = value.priority === undefined ? 100 : value.priority;
    const rawExpiresAt = value.expiresAt === undefined ? 0 : value.expiresAt;
    if (typeof rawPriority !== "number" || !Number.isSafeInteger(rawPriority)) continue;
    if (typeof rawExpiresAt !== "number" || !Number.isSafeInteger(rawExpiresAt) || rawExpiresAt < 0) continue;

    const expiresAt = rawExpiresAt;
    if (kind === "quick" ? expiresAt <= timestamp : expiresAt > 0 && expiresAt <= timestamp) continue;
    candidates.push({
      url,
      kind,
      priority: Math.max(0, Math.min(100, rawPriority)),
      expiresAt,
    });
  }

  candidates.sort((left, right) => (
    left.priority - right.priority
    || Number(left.kind !== "named") - Number(right.kind !== "named")
    || lexicalCompare(left.url, right.url)
  ));

  const unique: AlpeccaEndpointCandidate[] = [];
  const seen = new Set<string>();
  for (const candidate of candidates) {
    if (seen.has(candidate.url)) continue;
    seen.add(candidate.url);
    unique.push(candidate);
    if (unique.length >= RECOVERY_CANDIDATE_LIMIT) break;
  }
  return unique;
}

export function selectAlpeccaEndpoint(document: unknown, nowSeconds = Date.now() / 1000) {
  return readAlpeccaEndpointCandidates(document, nowSeconds)[0]?.url || "";
}

export function recoveryTarget(currentHref: string, endpoint: string) {
  const current = new URL(currentHref);
  const target = new URL(endpoint);
  target.pathname = current.pathname;
  target.search = current.search;
  target.hash = current.hash;
  for (const name of ["backend", "core", "alpeccaBackend", "alpecca"]) target.searchParams.delete(name);
  return target.toString();
}

async function fetchJsonWithinDeadline(
  url: string,
  init: RequestInit,
  deadlineMs: number,
  requestTimeoutMs: number,
  bodyLimit: number,
  fetchImpl: FetchLike,
  now: () => number,
): Promise<JsonFetchResult | null> {
  const remainingMs = Math.floor(deadlineMs - now());
  const timeoutMs = Math.min(requestTimeoutMs, remainingMs);
  if (timeoutMs <= 0) return null;

  const controller = new AbortController();
  let timeoutHandle: ReturnType<typeof globalThis.setTimeout> | undefined;
  const timedOut = new Promise<null>((resolve) => {
    timeoutHandle = globalThis.setTimeout(() => {
      controller.abort();
      resolve(null);
    }, timeoutMs);
  });
  const request = (async (): Promise<JsonFetchResult | null> => {
    try {
      const response = await fetchImpl(url, { ...init, signal: controller.signal });
      if (response.status !== 200) return { response, body: null };
      const declaredLength = Number(response.headers.get("content-length") || 0);
      if (Number.isFinite(declaredLength) && declaredLength > bodyLimit) return null;
      const text = await response.text();
      if (text.length > bodyLimit) return null;
      return { response, body: JSON.parse(text) as unknown };
    } catch {
      return null;
    }
  })();

  try {
    return await Promise.race([request, timedOut]);
  } finally {
    if (timeoutHandle !== undefined) globalThis.clearTimeout(timeoutHandle);
  }
}

function storageGet(storage: "local" | "session", key: string) {
  try {
    return (storage === "local" ? window.localStorage : window.sessionStorage).getItem(key) || "";
  } catch {
    return "";
  }
}

function storageSet(storage: "local" | "session", key: string, value: string) {
  try {
    (storage === "local" ? window.localStorage : window.sessionStorage).setItem(key, value);
  } catch {
    // Recovery still has a bounded in-memory attempt when browser storage is unavailable.
  }
}

let recoveryAttempt: Promise<boolean> | null = null;
let inMemoryAttemptOrigin = "";
let inMemoryAttemptAt = 0;
const inMemoryTargets = new Set<string>();

export function recoverAlpeccaEndpoint(reason: string, options: RecoveryOptions = {}) {
  if (recoveryAttempt) return recoveryAttempt;

  const attempt = (async () => {
    try {
      const now = options.now || Date.now;
      const startedAt = now();
      const currentOrigin = window.location.origin;
      const backendStorageKey = options.backendStorageKey || "alpeccaBackendUrl";
      const storedOrigin = storageGet("local", backendStorageKey);
      const shouldCheck = options.force
        || isEphemeralAlpeccaHost(window.location.hostname)
        || Boolean(storedOrigin && storedOrigin !== currentOrigin);
      if (!shouldCheck || (typeof navigator !== "undefined" && navigator.onLine === false)) return false;

      const attemptKey = `alpeccaEndpointRecoveryAttempt:${currentOrigin}`;
      const storedAttempt = Number(storageGet("session", attemptKey) || 0);
      const lastAttempt = Math.max(
        Number.isFinite(storedAttempt) ? storedAttempt : 0,
        inMemoryAttemptOrigin === currentOrigin ? inMemoryAttemptAt : 0,
      );
      if (lastAttempt > 0 && startedAt >= lastAttempt && startedAt - lastAttempt < RECOVERY_COOLDOWN_MS) {
        return false;
      }
      inMemoryAttemptOrigin = currentOrigin;
      inMemoryAttemptAt = startedAt;
      storageSet("session", attemptKey, String(startedAt));

      const budgetMs = boundedMilliseconds(options.recoveryBudgetMs, RECOVERY_BUDGET_MS, RECOVERY_BUDGET_MS);
      if (budgetMs <= 0) return false;
      const deadlineMs = startedAt + budgetMs;
      const fetchImpl = options.fetchImpl || globalThis.fetch;
      if (typeof fetchImpl !== "function") return false;
      const discoveryResult = await fetchJsonWithinDeadline(
        options.discoveryUrl || DEFAULT_DISCOVERY_URL,
        {
          cache: "no-store",
          credentials: "omit",
          headers: { Accept: "application/json" },
          redirect: "error",
        },
        deadlineMs,
        DISCOVERY_REQUEST_TIMEOUT_MS,
        DISCOVERY_BODY_LIMIT,
        fetchImpl,
        now,
      );
      if (discoveryResult?.response.status !== 200) return false;

      const candidates = readAlpeccaEndpointCandidates(discoveryResult.body, now() / 1000);
      let endpoint = "";
      let target = "";
      let recoveryKey = "";
      for (const candidate of candidates) {
        const candidateTarget = recoveryTarget(window.location.href, candidate.url);
        const candidateKey = `alpeccaEndpointRecovery:${candidate.url}`;
        const memoryKey = `${candidateKey}:${candidateTarget}`;
        if (candidate.url === currentOrigin && candidateTarget === window.location.href && !options.force) {
          storageSet("local", backendStorageKey, candidate.url);
          return false;
        }
        if (storageGet("session", candidateKey) === candidateTarget || inMemoryTargets.has(memoryKey)) continue;
        endpoint = candidate.url;
        target = candidateTarget;
        recoveryKey = candidateKey;
        break;
      }
      if (!endpoint) return false;

      storageSet("local", backendStorageKey, endpoint);
      storageSet("session", recoveryKey, target);
      inMemoryTargets.add(`${recoveryKey}:${target}`);
      if (document.body) document.body.dataset.alpeccaEndpointRecovery = reason || "connection-failure";
      window.location.replace(target);
      return true;
    } catch {
      return false;
    }
  })();

  recoveryAttempt = attempt;
  const clearAttempt = () => {
    if (recoveryAttempt === attempt) recoveryAttempt = null;
  };
  void attempt.then(clearAttempt, clearAttempt);
  return attempt;
}

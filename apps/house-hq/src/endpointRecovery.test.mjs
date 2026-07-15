import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeAlpeccaEndpoint,
  readAlpeccaEndpointCandidates,
  recoverAlpeccaEndpoint,
  recoveryTarget,
  selectAlpeccaEndpoint,
} from "./endpointRecovery.ts";

const discovery = (endpoints) => ({
  service: "alpecca-mobile-discovery",
  version: 1,
  endpoints,
});

const response = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json" },
});

class MemoryStorage {
  #values = new Map();

  getItem(key) {
    return this.#values.get(String(key)) ?? null;
  }

  setItem(key, value) {
    this.#values.set(String(key), String(value));
  }
}

const withBrowserGlobals = async ({ href, localStorage, sessionStorage, replace }, callback) => {
  const saved = new Map();
  for (const name of ["window", "document", "navigator"]) {
    saved.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  }
  const location = new URL(href);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      location: {
        href: location.toString(),
        hostname: location.hostname,
        origin: location.origin,
        replace,
      },
      localStorage,
      sessionStorage,
    },
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: { body: { dataset: {} } },
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { onLine: true },
  });
  try {
    return await callback();
  } finally {
    for (const [name, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
};

test("discovery candidates use canonical low-number-first ordering and remain bounded", () => {
  const candidates = readAlpeccaEndpointCandidates(discovery([
    { url: "https://later.example", kind: "named", priority: 20, expiresAt: 0 },
    { url: "https://quick.example", kind: "quick", priority: 5, expiresAt: 2_000 },
    { url: "https://b.example", kind: "named", priority: 5, expiresAt: 0 },
    { url: "https://a.example", kind: "named", priority: 5, expiresAt: 0 },
    { url: "https://first.example", kind: "quick", priority: -4, expiresAt: 2_000 },
  ]), 1_000);

  assert.deepEqual(candidates.map((candidate) => candidate.url), [
    "https://first.example",
    "https://a.example",
    "https://b.example",
    "https://quick.example",
  ]);
  assert.equal(selectAlpeccaEndpoint(discovery(candidates), 1_000), "https://first.example");
});

test("malformed, credentialed, insecure, and expired endpoint records are rejected", () => {
  const candidates = readAlpeccaEndpointCandidates(discovery([
    null,
    { url: "http://insecure.example", kind: "named", priority: 1, expiresAt: 0 },
    { url: "https://user:secret@credentialed.example", kind: "named", priority: 1, expiresAt: 0 },
    { url: "https://query.example?token=secret", kind: "named", priority: 1, expiresAt: 0 },
    { url: "https://path.example/private", kind: "named", priority: 1, expiresAt: 0 },
    { url: "https://expired.example", kind: "quick", priority: 1, expiresAt: 1_000 },
    { url: "https://bad-priority.example", kind: "named", priority: "1", expiresAt: 0 },
    { url: "https://valid.example/house-hq", kind: "quick", priority: 7, expiresAt: 1_001 },
  ]), 1_000);

  assert.deepEqual(candidates, [{
    url: "https://valid.example",
    kind: "quick",
    priority: 7,
    expiresAt: 1_001,
  }]);
  assert.equal(normalizeAlpeccaEndpoint("https://valid.example/"), "https://valid.example");
  assert.equal(normalizeAlpeccaEndpoint("https://valid.example/house-hq/"), "");
  assert.deepEqual(readAlpeccaEndpointCandidates({ service: "other", version: 1, endpoints: [] }), []);
});

test("only the first eight discovery rows are inspected", () => {
  const ignoredRows = Array.from({ length: 8 }, () => null);
  ignoredRows.push({ url: "https://ninth.example", kind: "named", priority: 0, expiresAt: 0 });
  assert.deepEqual(readAlpeccaEndpointCandidates(discovery(ignoredRows), 1_000), []);
});

test("recovery targets preserve route state while removing every backend selector", () => {
  const target = new URL(recoveryTarget(
    "https://retired.loca.lt/house-hq/rooms/Library%20Wing?backend=old&view=internals&core=old&alpeccaBackend=old&alpecca=old&view=map#terminal",
    "https://current.example",
  ));

  assert.equal(target.origin, "https://current.example");
  assert.equal(target.pathname, "/house-hq/rooms/Library%20Wing");
  assert.equal(target.hash, "#terminal");
  assert.deepEqual(target.searchParams.getAll("view"), ["internals", "map"]);
  for (const name of ["backend", "core", "alpeccaBackend", "alpecca"]) {
    assert.equal(target.searchParams.has(name), false);
  }
});

test("recovery skips an attempted candidate and redirects to the next canonical candidate", async () => {
  const href = "https://retired.loca.lt/house-hq/rooms/library?backend=old&view=internals#memory";
  const first = "https://first.example";
  const second = "https://second.example";
  const localStorage = new MemoryStorage();
  const sessionStorage = new MemoryStorage();
  const firstTarget = recoveryTarget(href, first);
  sessionStorage.setItem(`alpeccaEndpointRecovery:${first}`, firstTarget);
  const replacements = [];
  const requests = [];

  await withBrowserGlobals({
    href,
    localStorage,
    sessionStorage,
    replace: (target) => replacements.push(target),
  }, async () => {
    const recovered = await recoverAlpeccaEndpoint("test", {
      force: true,
      now: () => 1_000_000,
      fetchImpl: async (input) => {
        requests.push(String(input));
        return response(discovery([
          { url: second, kind: "named", priority: 20, expiresAt: 0 },
          { url: first, kind: "named", priority: 10, expiresAt: 0 },
        ]));
      },
    });
    assert.equal(recovered, true);
  });

  assert.equal(requests.length, 1);
  assert.deepEqual(replacements, [recoveryTarget(href, second)]);
  assert.equal(localStorage.getItem("alpeccaBackendUrl"), second);
});

test("normal startup keeps the current canonical endpoint after a prior forced reload", async () => {
  const href = "https://current.loca.lt/house-hq?view=internals";
  const current = "https://current.loca.lt";
  const localStorage = new MemoryStorage();
  const sessionStorage = new MemoryStorage();
  sessionStorage.setItem(`alpeccaEndpointRecovery:${current}`, recoveryTarget(href, current));

  await withBrowserGlobals({
    href,
    localStorage,
    sessionStorage,
    replace: () => assert.fail("normal startup must not advance past the current endpoint"),
  }, async () => {
    const recovered = await recoverAlpeccaEndpoint("startup-test", {
      now: () => 2_000_000,
      fetchImpl: async () => response(discovery([
        { url: "https://fallback.example", kind: "named", priority: 20, expiresAt: 0 },
        { url: current, kind: "named", priority: 10, expiresAt: 0 },
      ])),
    });
    assert.equal(recovered, false);
  });

  assert.equal(localStorage.getItem("alpeccaBackendUrl"), current);
});

test("the shared recovery budget aborts a stalled discovery request", async () => {
  const href = "https://stalled.loca.lt/house-hq";
  let aborted = false;
  const startedAt = Date.now();

  await withBrowserGlobals({
    href,
    localStorage: new MemoryStorage(),
    sessionStorage: new MemoryStorage(),
    replace: () => assert.fail("a stalled discovery request must not redirect"),
  }, async () => {
    const recovered = await recoverAlpeccaEndpoint("test-timeout", {
      force: true,
      recoveryBudgetMs: 40,
      fetchImpl: (_input, init) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          aborted = true;
          reject(new Error("aborted"));
        }, { once: true });
      }),
    });
    assert.equal(recovered, false);
  });

  assert.equal(aborted, true);
  assert.ok(Date.now() - startedAt < 1_000);
});

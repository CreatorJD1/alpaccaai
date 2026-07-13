/* Alpecca — service worker. Its only jobs are (1) make her installable as a phone
 * app (PWA) and (2) let the shell open even with a flaky connection. It is
 * deliberately conservative: it NEVER caches her live state, chat, senses, or any
 * API/stream endpoint -- those always hit the network, so what you see is always
 * her real, current self. Only the static shell (HTML/CSS/JS/vendor) is cached.
 *
 * Served from "/sw.js" (root) so its scope covers the whole app.
 */
const CACHE = "alpecca-v4";
const SHELL_ASSETS = ["/web/app.css", "/web/glow.js"];
const SHELL_NAVIGATION_PATHS = new Set(["/", "/house-hq"]);
const ACK_DB = "alpecca-notification-acks-v1";
const ACK_STORE = "pending";
const ACK_RETRY_MESSAGE_TYPE = "alpecca:notification-ack-retry";
const ACK_RETRY_MESSAGE_FIELDS = Object.freeze(["type", "version"]);
const ACK_RETRY_BATCH_LIMIT = 16;
const ACK_RETRY_COOLDOWN_MS = 5000;
let ackRetryInFlight = null;
let ackRetryLastStartedAt = 0;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL_ASSETS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(Promise.all([
    caches.keys().then((ks) =>
      Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
    retryPendingAcknowledgementsBounded(),
    self.clients.claim(),
  ]));
});

// Live endpoints that must always go to the network -- never served stale.
const LIVE = /^\/(ws|state|home\/state|system|cognition|mindscape\/state|mindscape\/snapshot|mindscape\/sync|mindscape\/restore|sight|voice|history|introspect|character|puppet|soul|memories|journal|growth|desktop|games|observatory|talkinghead|rigger|spine|rig|live2d\/|avatar|tts|listen|computer|channel|people|notifications)/;

const PUSH_FIELDS = Object.freeze([
  "version", "title", "body", "url", "event_id", "receipt", "tag",
]);
const NOTIFICATION_DATA_FIELDS = Object.freeze(["version", "url", "event_id", "receipt"]);
const PUSH_MAX_BYTES = 4096;

function boundedPushString(value, maxLength, pattern = null) {
  if (typeof value !== "string" || value !== value.trim()) return false;
  const characters = Array.from(value);
  return characters.length > 0
    && characters.length <= maxLength
    && !characters.some((character) => character.charCodeAt(0) < 32)
    && (!pattern || pattern.test(value));
}

function housePushUrl(value) {
  return value === "/house-hq" ? value : null;
}

function parsePushPayload(data) {
  if (!data) return null;
  const raw = data.text();
  if (!raw || new TextEncoder().encode(raw).byteLength > PUSH_MAX_BYTES) return null;
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const keys = Object.keys(value);
  if (keys.length !== PUSH_FIELDS.length || !PUSH_FIELDS.every((field) => keys.includes(field))) return null;
  const url = housePushUrl(value.url);
  if (
    value.version !== 1
    || !boundedPushString(value.title, 80)
    || !boundedPushString(value.body, 320)
    || !url
    || !boundedPushString(value.event_id, 64, /^out_[0-9a-f]{32}$/)
    || !boundedPushString(value.receipt, 512, /^wpa_[A-Za-z0-9_-]{43,480}$/)
    || !boundedPushString(value.tag, 64, /^alpecca-out_[0-9a-f]{32}$/)
  ) return null;
  return {
    title: value.title,
    body: value.body,
    url,
    event_id: value.event_id,
    receipt: value.receipt,
    tag: value.tag,
  };
}

function parseNotificationData(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const keys = Object.keys(value);
  if (
    keys.length !== NOTIFICATION_DATA_FIELDS.length
    || !NOTIFICATION_DATA_FIELDS.every((field) => keys.includes(field))
  ) return null;
  const url = housePushUrl(value.url);
  if (
    value.version !== 1
    || !url
    || !boundedPushString(value.event_id, 64, /^out_[0-9a-f]{32}$/)
    || !boundedPushString(value.receipt, 512, /^wpa_[A-Za-z0-9_-]{43,480}$/)
  ) return null;
  return { url, event_id: value.event_id, receipt: value.receipt };
}

function openAckDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(ACK_DB, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(ACK_STORE)) {
        db.createObjectStore(ACK_STORE, { keyPath: "event_id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("ack database unavailable"));
  });
}

async function withAckStore(mode, operation) {
  const db = await openAckDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(ACK_STORE, mode);
      const store = transaction.objectStore(ACK_STORE);
      let result;
      try {
        result = operation(store);
      } catch (error) {
        reject(error);
        return;
      }
      transaction.oncomplete = () => resolve(result);
      transaction.onerror = () => reject(transaction.error || new Error("ack transaction failed"));
      transaction.onabort = () => reject(transaction.error || new Error("ack transaction aborted"));
    });
  } finally {
    db.close();
  }
}

function storePendingAcknowledgement(data) {
  return withAckStore("readwrite", (store) => store.put({
    version: 1,
    url: data.url,
    event_id: data.event_id,
    receipt: data.receipt,
  }));
}

function deletePendingAcknowledgement(eventId) {
  return withAckStore("readwrite", (store) => store.delete(eventId));
}

async function pendingAcknowledgements() {
  const rows = await withAckStore("readonly", (store) => new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("ack read failed"));
  }));
  return Array.isArray(rows)
    ? rows.map(parseNotificationData).filter(Boolean).slice(0, ACK_RETRY_BATCH_LIMIT)
    : [];
}

async function acknowledgePending(data) {
  try {
    const response = await fetch("/notifications/push/ack", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: data.event_id, receipt: data.receipt }),
    });
    if (response.ok || [400, 403, 404].includes(response.status)) {
      try {
        await deletePendingAcknowledgement(data.event_id);
      } catch {}
      return response.ok;
    }
  } catch {}
  return false;
}

async function retryPendingAcknowledgements() {
  let rows = [];
  try {
    rows = await pendingAcknowledgements();
  } catch {
    return;
  }
  for (const row of rows) await acknowledgePending(row);
}

function retryPendingAcknowledgementsBounded() {
  if (ackRetryInFlight) return ackRetryInFlight;
  const now = Date.now();
  if (now - ackRetryLastStartedAt < ACK_RETRY_COOLDOWN_MS) return Promise.resolve();
  ackRetryLastStartedAt = now;
  ackRetryInFlight = retryPendingAcknowledgements().finally(() => {
    ackRetryInFlight = null;
  });
  return ackRetryInFlight;
}

function isExactAckRetryMessage(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  return keys.length === ACK_RETRY_MESSAGE_FIELDS.length
    && ACK_RETRY_MESSAGE_FIELDS.every((field) => keys.includes(field))
    && value.type === ACK_RETRY_MESSAGE_TYPE
    && value.version === 1;
}

self.addEventListener("message", (event) => {
  if (!isExactAckRetryMessage(event.data)) return;
  const source = event.source;
  if (!source || source.type !== "window" || typeof source.url !== "string") return;
  let sourceUrl;
  try {
    sourceUrl = new URL(source.url);
  } catch {
    return;
  }
  if (sourceUrl.origin !== self.location.origin || sourceUrl.pathname !== "/house-hq") return;
  event.waitUntil(retryPendingAcknowledgementsBounded());
});

self.addEventListener("push", (event) => {
  event.waitUntil((async () => {
    const payload = parsePushPayload(event.data);
    if (!payload) return;
    await self.registration.showNotification(payload.title, {
      body: payload.body,
      tag: payload.tag,
      icon: "/web/icon.svg",
      badge: "/web/icon.svg",
      data: {
        version: 1,
        url: payload.url,
        event_id: payload.event_id,
        receipt: payload.receipt,
      },
    });
  })());
});

async function focusOrOpenHouse(url) {
  const target = new URL(url, self.location.origin);
  const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  for (const client of windows) {
    let current;
    try {
      current = new URL(client.url);
    } catch {
      continue;
    }
    if (current.origin !== self.location.origin || current.pathname !== "/house-hq") continue;
    if (client.url !== target.href && "navigate" in client) {
      try {
        await client.navigate(target.href);
      } catch {}
    }
    return client.focus();
  }
  return self.clients.openWindow(target.href);
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    const data = parseNotificationData(event.notification.data);
    if (!data) {
      await focusOrOpenHouse("/house-hq");
      return;
    }
    try {
      await storePendingAcknowledgement(data);
    } catch {}
    await acknowledgePending(data);
    await focusOrOpenHouse(data.url);
  })());
});

function exactShellNavigationPath(url) {
  return url.origin === self.location.origin
    && !url.search
    && SHELL_NAVIGATION_PATHS.has(url.pathname)
    ? url.pathname
    : null;
}

function isExactSuccessfulShellResponse(response, routePath) {
  if (!response.ok || response.status !== 200 || response.type !== "basic" || response.redirected) {
    return false;
  }
  try {
    const responseUrl = new URL(response.url);
    return responseUrl.origin === self.location.origin
      && responseUrl.pathname === routePath
      && !responseUrl.search;
  } catch {
    return false;
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                      // never touch POST / WS upgrades
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;            // only our own origin
  if (LIVE.test(url.pathname)) return;                   // her live self -> network only
  if (req.mode === "navigate") e.waitUntil(retryPendingAcknowledgementsBounded());

  // Exact app-shell routes: network-first, with route-specific offline fallback.
  if (req.mode === "navigate") {
    const routePath = exactShellNavigationPath(url);
    if (!routePath) return;
    e.respondWith(
      fetch(req)
        .then(async (response) => {
          if (isExactSuccessfulShellResponse(response, routePath)) {
            await caches.open(CACHE)
              .then((cache) => cache.put(routePath, response.clone()))
              .catch(() => {});
          }
          return response;
        })
        .catch(async (error) => {
          const cache = await caches.open(CACHE);
          const cached = await cache.match(routePath);
          if (cached) return cached;
          throw error;
        }));
    return;
  }

  // Static assets (css / js / vendor): cache-first, refreshed in the background.
  if (url.pathname.startsWith("/web/") || url.pathname.startsWith("/assets/")) {
    e.respondWith(caches.match(req).then((hit) =>
      hit || fetch(req).then((r) => {
        caches.open(CACHE).then((c) => c.put(req, r.clone())).catch(() => {});
        return r;
      })));
  }
});

/* Alpecca — service worker. Its only jobs are (1) make her installable as a phone
 * app (PWA) and (2) let the shell open even with a flaky connection. It is
 * deliberately conservative: it NEVER caches her live state, chat, senses, or any
 * API/stream endpoint -- those always hit the network, so what you see is always
 * her real, current self. Only the static shell (HTML/CSS/JS/vendor) is cached.
 *
 * Served from "/sw.js" (root) so its scope covers the whole app.
 */
const CACHE = "alpecca-v2";
const SHELL = ["/", "/web/app.css", "/web/glow.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) =>
    Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

// Live endpoints that must always go to the network -- never served stale.
const LIVE = /^\/(ws|state|home\/state|system|cognition|mindscape\/state|mindscape\/snapshot|mindscape\/sync|mindscape\/restore|sight|voice|history|introspect|character|puppet|soul|memories|journal|growth|desktop|games|observatory|talkinghead|rigger|spine|rig|live2d\/|avatar|tts|listen|computer|channel|people)/;

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                      // never touch POST / WS upgrades
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;            // only our own origin
  if (LIVE.test(url.pathname)) return;                   // her live self -> network only

  // App shell: network-first (so updates land), fall back to cache when offline.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((r) => { caches.open(CACHE).then((c) => c.put("/", r.clone())).catch(() => {}); return r; })
        .catch(() => caches.match("/")));
    return;
  }

  // Static assets (css / js / vendor): cache-first, refreshed in the background.
  if (url.pathname.startsWith("/web/")) {
    e.respondWith(caches.match(req).then((hit) =>
      hit || fetch(req).then((r) => {
        caches.open(CACHE).then((c) => c.put(req, r.clone())).catch(() => {});
        return r;
      })));
  }
});

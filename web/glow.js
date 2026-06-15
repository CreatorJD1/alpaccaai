/* Alpecca — the live mood glow channel, shared by every page.
 *
 * The soft-tech / glow look isn't static cyan: the whole UI subtly tracks her
 * real affect. This module owns the --mood-* CSS variables defined in app.css.
 * Each page already polls her state (the 3D home /home/state, the chat /state,
 * live2d /state); it just hands the four channels here and the entire interface
 * -- every button, bar, active nav item, the chest-core emblem -- shifts hue and
 * brightness together, slowly (the CSS transitions make it a drift, not a snap).
 *
 * Grounded, like everything else: the numbers come straight from her real mood
 * (warmth=Love, unease=Fear, curiosity, glow=core_glow/energy). Nothing here
 * invents a feeling; it only renders the ones she actually has.
 *
 * Load with:  <script src="/web/glow.js"></script>
 * Call with:  applyMood({warmth, unease, curiosity, glow})   // all 0..1, optional
 */
(function (global) {
  "use strict";

  function clamp01(x) { return Math.max(0, Math.min(1, x)); }

  function applyMood(m) {
    m = m || {};
    var warmth = m.warmth != null ? clamp01(m.warmth) : 0.5;
    var unease = m.unease != null ? clamp01(m.unease) : 0.0;
    var curiosity = m.curiosity != null ? clamp01(m.curiosity) : 0.2;
    var glow = m.glow != null ? clamp01(m.glow) : 0.6;

    // Hue: bright cyan (~195) when warm/curious; cools and tips toward violet
    // (~235) as unease rises -- so the room visibly chills when she's uneasy.
    var h = Math.round(195 + curiosity * 8 - warmth * 4 + unease * 40);
    var s = Math.round(Math.max(45, Math.min(100, 72 + warmth * 28 - unease * 16)));
    var l = Math.round(Math.max(56, Math.min(82, 68 + warmth * 10 - unease * 8)));
    var intensity = Math.max(0.25, Math.min(1, glow * 0.6 + warmth * 0.4));

    var r = document.documentElement.style;
    r.setProperty("--mood-h", String(h));
    r.setProperty("--mood-s", s + "%");
    r.setProperty("--mood-l", l + "%");
    r.setProperty("--mood-intensity", intensity.toFixed(2));
  }

  global.applyMood = applyMood;
})(window);

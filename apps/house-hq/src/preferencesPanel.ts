/* Alpecca preferences + read-the-room panel (Lane Q, READ-ONLY).
 *
 * A self-contained, read-only view of two grounded foundation signals:
 *   - her recorded favorites/preferences (alpecca/preferences.py), and
 *   - the measured overload / read-the-room indicator (alpecca/overload.py).
 *
 * It renders exactly what those modules already ground in real evidence and
 * NOTHING more: it never writes, never edits a preference, and never invents a
 * feeling. The overload readout is explicitly labelled measured workload -- not
 * an emotion -- carrying the same disclaimer the Python assessment does, and it
 * shows "unknown" verbatim for any cue that was not really measured rather than
 * drawing a reassuring zero.
 *
 * Convention (matches apps/house-hq/src/vrmEmbodiment.ts): this module exports
 * plain types + functions and has no top-level side effects, so it type-checks
 * under the app's strict tsconfig without being imported into main.ts. Wiring it
 * into the House HQ UI is a separate integration request; until then it is a
 * standalone, data-driven renderer the caller can mount with a snapshot.
 *
 * Data-driven by design: pass it a snapshot (the shape alpecca/preferences.py
 * `snapshot()` and alpecca/overload.py `assess_overload()` already return) and
 * it builds the DOM. `fetchPreferencesPanelData` is an optional convenience for
 * a future read-only backend endpoint (an integration request, not built here).
 */

// --- Data contracts (mirror the Python read-only outputs) -------------------

export type PreferenceSentiment = "liked" | "disliked" | "neutral";

export interface PreferenceRow {
  readonly id: number;
  readonly scope: string;
  readonly source: string;
  readonly category: string;
  readonly subject: string;
  readonly sentiment: string;
  readonly strength: number;
  readonly reinforcement: number;
  readonly reason: string;
  readonly created_at: number;
  readonly last_reinforced: number;
  readonly status: string;
}

export interface PreferencesSummary {
  readonly total: number;
  readonly liked: number;
  readonly disliked: number;
  readonly by_category: Readonly<Record<string, number>>;
  readonly top_favorite: string;
}

export interface PreferencesSnapshot {
  readonly schema: string;
  readonly summary: PreferencesSummary;
  readonly favorites: ReadonlyArray<PreferenceRow>;
}

export type OverloadState = "known" | "partial" | "unknown";
export type OverloadBand = "low" | "elevated" | "high" | "unknown";
export type OverloadCueState = "known" | "unknown" | "invalid";

export interface OverloadCueEvidence {
  readonly name: string;
  readonly state: OverloadCueState;
  readonly normalized: number | null;
  readonly evidence: Readonly<Record<string, unknown>>;
}

export interface OverloadAssessment {
  readonly schema: string;
  readonly kind: string;
  readonly disclaimer: string;
  readonly state: OverloadState;
  readonly value: number | null;
  readonly band: OverloadBand;
  readonly known_cues: ReadonlyArray<string>;
  readonly unknown_cues: ReadonlyArray<string>;
  readonly invalid_cues: ReadonlyArray<string>;
  readonly evidence: ReadonlyArray<OverloadCueEvidence>;
  readonly reasons: ReadonlyArray<string>;
}

export interface PreferencesPanelData {
  readonly preferences: PreferencesSnapshot | null;
  readonly overload: OverloadAssessment | null;
}

// --- Small strict-safe DOM helpers ------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function pct(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

const CUE_LABELS: Readonly<Record<string, string>> = {
  message_volume: "Message volume",
  concurrent_actors: "Concurrent people",
  context_pressure: "Context fullness",
  host_pressure: "Host pressure",
};

function cueLabel(name: string): string {
  return CUE_LABELS[name] ?? name;
}

// --- Rendering: favorites ---------------------------------------------------

function renderFavorites(snapshot: PreferencesSnapshot | null): HTMLElement {
  const section = el("section", "alpecca-prefs__section");
  section.appendChild(el("h3", "alpecca-prefs__heading", "Favorites"));

  if (snapshot === null) {
    section.appendChild(
      el("p", "alpecca-prefs__muted", "No preference data available."),
    );
    return section;
  }

  const s = snapshot.summary;
  const meta = el(
    "p",
    "alpecca-prefs__muted",
    `${s.liked} liked · ${s.disliked} disliked · ${s.total} tracked` +
      (s.top_favorite ? ` · top: ${s.top_favorite}` : ""),
  );
  section.appendChild(meta);

  if (snapshot.favorites.length === 0) {
    section.appendChild(
      el(
        "p",
        "alpecca-prefs__muted",
        "She hasn't been told any favorites yet.",
      ),
    );
    return section;
  }

  const list = el("ul", "alpecca-prefs__list");
  for (const fav of snapshot.favorites) {
    const item = el("li", "alpecca-prefs__item");

    const head = el("div", "alpecca-prefs__item-head");
    head.appendChild(el("span", "alpecca-prefs__subject", fav.subject));
    head.appendChild(el("span", "alpecca-prefs__tag", fav.category));
    item.appendChild(head);

    const bar = el("div", "alpecca-prefs__bar");
    const fill = el("div", "alpecca-prefs__bar-fill");
    fill.style.width = pct(fav.strength);
    bar.appendChild(fill);
    item.appendChild(bar);

    // The grounded provenance: who supplied it, how often reinforced, and why.
    const reinforced =
      fav.reinforcement > 1 ? `reinforced ${fav.reinforcement}x` : "heard once";
    item.appendChild(
      el(
        "div",
        "alpecca-prefs__reason",
        `${reinforced} · from ${fav.source} · ${fav.reason}`,
      ),
    );

    list.appendChild(item);
  }
  section.appendChild(list);
  return section;
}

// --- Rendering: overload / read-the-room ------------------------------------

function renderOverload(assessment: OverloadAssessment | null): HTMLElement {
  const section = el("section", "alpecca-prefs__section");
  section.appendChild(
    el("h3", "alpecca-prefs__heading", "Read-the-room · workload"),
  );

  if (assessment === null) {
    section.appendChild(
      el("p", "alpecca-prefs__muted", "No overload signal available."),
    );
    return section;
  }

  const band = assessment.band;
  const headline = el("div", `alpecca-prefs__band alpecca-prefs__band--${band}`);
  const valueText =
    assessment.value === null ? "unknown" : pct(assessment.value);
  headline.textContent = `${band.toUpperCase()} · ${valueText}`;
  section.appendChild(headline);

  // Always surface the grounding disclaimer verbatim: this is measured
  // workload, never a claim of emotion or suffering.
  section.appendChild(
    el("p", "alpecca-prefs__disclaimer", assessment.disclaimer),
  );

  if (assessment.state !== "known") {
    section.appendChild(
      el(
        "p",
        "alpecca-prefs__muted",
        assessment.state === "unknown"
          ? "No cue was measured — reading stays unknown."
          : "Partial evidence — some cues are not measured.",
      ),
    );
  }

  const list = el("ul", "alpecca-prefs__cues");
  for (const cue of assessment.evidence) {
    const item = el("li", "alpecca-prefs__cue");
    item.appendChild(
      el("span", "alpecca-prefs__cue-name", cueLabel(cue.name)),
    );
    const reading =
      cue.state === "known" && cue.normalized !== null
        ? pct(cue.normalized)
        : cue.state; // "unknown" / "invalid" shown verbatim, never a fake 0
    item.appendChild(
      el(
        "span",
        `alpecca-prefs__cue-state alpecca-prefs__cue-state--${cue.state}`,
        reading,
      ),
    );
    list.appendChild(item);
  }
  section.appendChild(list);
  return section;
}

// --- Styling (inline, self-contained so it needs no styles.css) -------------

const PANEL_STYLE_ID = "alpecca-prefs-style";
const PANEL_CSS = `
.alpecca-prefs { font: 13px/1.4 system-ui, sans-serif; color: #e8e8ef;
  background: rgba(18,18,28,0.86); border: 1px solid rgba(255,255,255,0.12);
  border-radius: 12px; padding: 14px 16px; max-width: 360px; }
.alpecca-prefs__title { margin: 0 0 10px; font-size: 14px; font-weight: 600;
  letter-spacing: 0.02em; }
.alpecca-prefs__section { margin: 0 0 14px; }
.alpecca-prefs__section:last-child { margin-bottom: 0; }
.alpecca-prefs__heading { margin: 0 0 6px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.7; }
.alpecca-prefs__muted { margin: 4px 0; opacity: 0.6; font-size: 12px; }
.alpecca-prefs__list, .alpecca-prefs__cues { list-style: none; margin: 0;
  padding: 0; }
.alpecca-prefs__item { margin: 0 0 10px; }
.alpecca-prefs__item-head { display: flex; align-items: baseline;
  justify-content: space-between; gap: 8px; }
.alpecca-prefs__subject { font-weight: 600; }
.alpecca-prefs__tag { font-size: 10px; text-transform: uppercase;
  letter-spacing: 0.06em; opacity: 0.6; }
.alpecca-prefs__bar { height: 4px; border-radius: 3px; margin: 4px 0 3px;
  background: rgba(255,255,255,0.12); overflow: hidden; }
.alpecca-prefs__bar-fill { height: 100%; background: #7cc7ff; }
.alpecca-prefs__reason { font-size: 11px; opacity: 0.62; }
.alpecca-prefs__band { display: inline-block; padding: 3px 10px;
  border-radius: 999px; font-weight: 700; font-size: 12px;
  letter-spacing: 0.04em; }
.alpecca-prefs__band--low { background: rgba(120,200,140,0.22); color: #9be2ad; }
.alpecca-prefs__band--elevated { background: rgba(240,200,120,0.22);
  color: #f0c878; }
.alpecca-prefs__band--high { background: rgba(240,130,130,0.24); color: #ff9b9b; }
.alpecca-prefs__band--unknown { background: rgba(255,255,255,0.12);
  color: #c7c7d2; }
.alpecca-prefs__disclaimer { margin: 6px 0; font-size: 11px; font-style: italic;
  opacity: 0.66; }
.alpecca-prefs__cue { display: flex; justify-content: space-between;
  gap: 8px; padding: 3px 0; border-top: 1px solid rgba(255,255,255,0.07); }
.alpecca-prefs__cue-name { opacity: 0.82; }
.alpecca-prefs__cue-state { font-variant-numeric: tabular-nums; opacity: 0.9; }
.alpecca-prefs__cue-state--unknown, .alpecca-prefs__cue-state--invalid {
  opacity: 0.5; font-style: italic; }
`;

function ensureStyle(): void {
  if (document.getElementById(PANEL_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = PANEL_STYLE_ID;
  style.textContent = PANEL_CSS;
  document.head.appendChild(style);
}

// --- Public API -------------------------------------------------------------

/** Build (but do not attach) the read-only panel element from a snapshot. */
export function renderPreferencesPanel(data: PreferencesPanelData): HTMLElement {
  ensureStyle();
  const root = el("div", "alpecca-prefs");
  root.setAttribute("role", "region");
  root.setAttribute("aria-label", "Alpecca preferences and workload");
  root.appendChild(el("h2", "alpecca-prefs__title", "Preferences & workload"));
  root.appendChild(renderFavorites(data.preferences));
  root.appendChild(renderOverload(data.overload));
  return root;
}

/** Replace a container's contents with a freshly rendered panel. */
export function mountPreferencesPanel(
  container: HTMLElement,
  data: PreferencesPanelData,
): HTMLElement {
  const panel = renderPreferencesPanel(data);
  container.replaceChildren(panel);
  return panel;
}

/**
 * Optional convenience: fetch the panel data from a read-only backend.
 *
 * The endpoints below do NOT exist yet -- exposing them is an integration
 * request (read-only GET handlers over alpecca/preferences.py `snapshot()` and
 * alpecca/overload.py `assess_overload()`). Until then, drive the panel with
 * `renderPreferencesPanel({ preferences, overload })` directly. Any fetch
 * failure degrades to `null`, which the renderer shows as "no data" rather than
 * fabricating a value.
 */
export async function fetchPreferencesPanelData(
  baseUrl: string,
  options?: { readonly timeoutMs?: number },
): Promise<PreferencesPanelData> {
  const timeoutMs = options?.timeoutMs ?? 5000;
  const getJson = async <T>(path: string): Promise<T | null> => {
    try {
      const response = await fetch(`${baseUrl}${path}`, {
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!response.ok) return null;
      return (await response.json()) as T;
    } catch {
      return null;
    }
  };
  const [preferences, overload] = await Promise.all([
    getJson<PreferencesSnapshot>("/api/preferences/snapshot"),
    getJson<OverloadAssessment>("/api/overload/read-the-room"),
  ]);
  return { preferences, overload };
}

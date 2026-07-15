export type BrainNodeState = "healthy" | "degraded" | "disabled" | "unfinished" | "unknown";

export type BrainNode = {
  id: string;
  label: string;
  parent: string | null;
  plugin: string;
  group: string;
  system: string;
  detail: string;
  state: BrainNodeState;
  summary: string;
  progress: number | null;
  evidence: string[];
};

export type InternalsSnapshot = {
  schemaVersion: number;
  observedAt: string;
  accuracy: string;
  nodes: BrainNode[];
  plugins: Array<{ id: string; name: string; nodeCount: number }>;
  pluginErrors: Array<{ source: string; error: string }>;
  counts: Record<BrainNodeState, number>;
};

const escapeHtml = (value: unknown) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const stateLabel: Record<BrainNodeState, string> = {
  healthy: "healthy",
  degraded: "needs attention",
  disabled: "disabled",
  unfinished: "unfinished",
  unknown: "unknown",
};

function childMap(nodes: BrainNode[]) {
  const children = new Map<string | null, BrainNode[]>();
  for (const node of nodes) {
    const bucket = children.get(node.parent) ?? [];
    bucket.push(node);
    children.set(node.parent, bucket);
  }
  return children;
}

function nodeButton(node: BrainNode, children: Map<string | null, BrainNode[]>, depth: number, includeChildren = true): string {
  const descendants = includeChildren ? children.get(node.id) ?? [] : [];
  const progress = node.progress === null ? "" : `<span class="brain-node-progress"><i style="--progress:${Math.max(0, Math.min(100, node.progress))}%"></i></span>`;
  return `
    <div class="brain-node-wrap" data-brain-wrap="${escapeHtml(node.id)}" data-depth="${depth}" data-state="${node.state}">
      <button class="brain-node" type="button" data-brain-node="${escapeHtml(node.id)}" data-state="${node.state}" aria-pressed="false">
        <span class="brain-node-light" aria-hidden="true"></span>
        <span class="brain-node-copy"><strong>${escapeHtml(node.label)}</strong><small>${escapeHtml(node.summary)}</small></span>
        ${progress}
      </button>
      ${descendants.length ? `<button class="brain-expand" type="button" data-brain-expand="${escapeHtml(node.id)}" aria-expanded="false" aria-label="Show ${escapeHtml(node.label)} subnodes"><span aria-hidden="true">+</span><b>${descendants.length}</b></button>` : ""}
      ${descendants.length ? `<div class="brain-children" data-brain-children="${escapeHtml(node.id)}" hidden>${descendants.map((child) => nodeButton(child, children, depth + 1)).join("")}</div>` : ""}
    </div>`;
}

function freshnessLabel(observedAt: string): string {
  const parsed = Date.parse(observedAt);
  if (!Number.isFinite(parsed)) return "timestamp unavailable";
  const seconds = Math.max(0, Math.round((Date.now() - parsed) / 1000));
  return seconds < 3 ? "live now" : `${seconds}s old`;
}

export function renderInternalsMap(snapshot: InternalsSnapshot) {
  const nodes = Array.isArray(snapshot.nodes) ? snapshot.nodes : [];
  const children = childMap(nodes);
  const roots = children.get(null) ?? [];
  const core = roots[0] ?? null;
  const branches = core ? children.get(core.id) ?? [] : roots.slice(1);
  const left = branches.filter((_, index) => index % 2 === 0);
  const right = branches.filter((_, index) => index % 2 === 1);
  const count = (state: BrainNodeState) => Number(snapshot.counts?.[state] || 0);
  const errors = Array.isArray(snapshot.pluginErrors) ? snapshot.pluginErrors : [];
  const pluginCount = Array.isArray(snapshot.plugins) ? snapshot.plugins.length : 0;
  const renderWing = (items: BrainNode[], wing: "left" | "right") => `
    <div class="brain-wing" data-wing="${wing}">${items.map((node) => nodeButton(node, children, 1)).join("")}</div>`;
  return `
    <header class="systems-section-head internals-head">
      <span>LIVE BRAIN</span>
      <div><h2>Alpecca Brain Garden</h2><p>Evidence-backed runtime structure. Every status is probed live or marked unknown; nothing is inferred healthy.</p></div>
    </header>
    <div class="brain-toolbar">
      <div class="brain-vitals" aria-label="Brain graph summary">
        <span data-state="healthy"><b>${count("healthy")}</b> healthy</span>
        <span data-state="degraded"><b>${count("degraded")}</b> attention</span>
        <span data-state="unfinished"><b>${count("unfinished")}</b> unfinished</span>
        <span data-state="disabled"><b>${count("disabled")}</b> disabled</span>
        <span data-state="unknown"><b>${count("unknown")}</b> unknown</span>
      </div>
      <div class="brain-toolbar-actions"><span>${pluginCount} plugin${pluginCount === 1 ? "" : "s"} - ${freshnessLabel(snapshot.observedAt)}</span><button type="button" data-brain-refresh aria-label="Refresh live brain graph">Refresh</button></div>
    </div>
    ${errors.length ? `<div class="brain-plugin-errors" role="status">${errors.length} plugin${errors.length === 1 ? "" : "s"} rejected by validation. Select Plugin health for evidence.</div>` : ""}
    <div class="brain-garden" data-brain-garden>
      ${renderWing(left, "left")}
      <div class="brain-core" aria-label="Alpecca core">
        <span class="brain-core-petals" aria-hidden="true"></span>
        ${core ? nodeButton(core, children, 0, false) : `<div class="brain-empty">No validated core node</div>`}
        <small>single authoritative runtime</small>
      </div>
      ${renderWing(right, "right")}
    </div>
    <div class="brain-detail" aria-live="polite">
      <div class="brain-detail-heading"><span class="brain-detail-state" data-brain-detail-state data-state="unknown">SELECT A NODE</span><strong data-brain-detail-title>Inspect live evidence</strong><small data-brain-detail-plugin>Plugin provenance appears here</small></div>
      <div><p data-brain-detail-copy>Select a node to see exactly what was measured, what remains unfinished, and which source supports the status.</p><ul data-brain-detail-evidence></ul></div>
      <button type="button" data-brain-open disabled>Open system</button>
    </div>`;
}

export function mountInternalsMap(
  root: HTMLElement,
  onOpenSystem: (system: string) => void,
  onRefresh?: () => void,
) {
  const expandedStorageKey = "alpeccaBrainExpanded";
  let expandedIds = new Set<string>();
  try {
    const stored = JSON.parse(sessionStorage.getItem(expandedStorageKey) || "[]");
    if (Array.isArray(stored)) expandedIds = new Set(stored.filter((item): item is string => typeof item === "string"));
  } catch {
    expandedIds = new Set();
  }
  const nodes = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-brain-node]"));
  const wrappers = Array.from(root.querySelectorAll<HTMLElement>("[data-brain-wrap]"));
  const title = root.querySelector<HTMLElement>("[data-brain-detail-title]");
  const copy = root.querySelector<HTMLElement>("[data-brain-detail-copy]");
  const state = root.querySelector<HTMLElement>("[data-brain-detail-state]");
  const plugin = root.querySelector<HTMLElement>("[data-brain-detail-plugin]");
  const evidence = root.querySelector<HTMLUListElement>("[data-brain-detail-evidence]");
  const open = root.querySelector<HTMLButtonElement>("[data-brain-open]");
  let selected: BrainNode | null = null;

  const snapshot = (root as HTMLElement & { __brainSnapshot?: InternalsSnapshot }).__brainSnapshot;
  const graphNodes = snapshot?.nodes ?? [];

  nodes.forEach((button) => button.addEventListener("click", () => {
    const node = graphNodes.find((item) => item.id === button.dataset.brainNode);
    if (!node || !title || !copy || !state || !plugin || !evidence || !open) return;
    selected = node;
    nodes.forEach((candidate) => candidate.setAttribute("aria-pressed", String(candidate === button)));
    wrappers.forEach((wrapper) => wrapper.classList.toggle("is-selected", wrapper.dataset.brainWrap === node.id));
    state.textContent = stateLabel[node.state];
    state.dataset.state = node.state;
    title.textContent = node.label;
    plugin.textContent = `${node.plugin} - ${node.group}`;
    copy.textContent = node.detail || node.summary;
    evidence.replaceChildren(...node.evidence.map((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      return li;
    }));
    open.disabled = false;
    open.textContent = `Open ${node.label}`;
  }));

  root.querySelectorAll<HTMLButtonElement>("[data-brain-expand]").forEach((button) => {
    const id = button.dataset.brainExpand || "";
    const children = root.querySelector<HTMLElement>(`[data-brain-children="${CSS.escape(id)}"]`);
    if (!children) return;
    if (expandedIds.has(id)) {
      button.setAttribute("aria-expanded", "true");
      button.querySelector("span")!.textContent = "-";
      children.hidden = false;
    }
    button.addEventListener("click", () => {
    const expanded = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(expanded));
    button.querySelector("span")!.textContent = expanded ? "-" : "+";
    children.hidden = !expanded;
      if (expanded) expandedIds.add(id);
      else expandedIds.delete(id);
      sessionStorage.setItem(expandedStorageKey, JSON.stringify([...expandedIds]));
    });
  });

  root.querySelector<HTMLButtonElement>("[data-brain-refresh]")?.addEventListener("click", () => onRefresh?.());
  open?.addEventListener("click", () => selected && onOpenSystem(selected.system));
  if (onRefresh) {
    window.setTimeout(() => {
      if (root.isConnected) onRefresh();
    }, 15_000);
  }
}

export function attachInternalsSnapshot(root: HTMLElement, snapshot: InternalsSnapshot) {
  (root as HTMLElement & { __brainSnapshot?: InternalsSnapshot }).__brainSnapshot = snapshot;
}

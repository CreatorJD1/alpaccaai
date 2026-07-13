/**
 * brainMap.ts -- read-only visualization of Alpecca's knowledge brain-map.
 *
 * This renders the vision's concept art: a circuit-board brain whose sections
 * are her memory kinds (episodic / relational / self-model / semantic /
 * procedural / long-term), laid out left (bright, sharp -- Active & Episodic) to
 * right (faded, dissolving -- Long-Term / Musing). Each node is a taught-
 * knowledge block; its BRIGHTNESS and SHARPNESS encode her recall confidence,
 * and its colour encodes state: locked (dark, unlearned), unlockable (a faint
 * amber candidate a parent could open), populated (lit cyan, she can recall it).
 *
 * It is a self-contained module and strictly READ-ONLY: it draws whatever
 * BrainMapSnapshot it is handed and never mutates state, memory, or the DOM
 * beyond its own canvas. It is deliberately NOT imported by main.ts -- wiring a
 * live data source and mounting it is an integration step owned elsewhere. The
 * data shape mirrors alpecca.knowledge_blocks.brain_map_snapshot(); a matching
 * demo stub (`demoBrainMapSnapshot`) lets it render with no backend attached.
 */

export type BrainMapNodeState = "locked" | "unlockable" | "populated";

export interface BrainMapNode {
  id: number;
  name: string;
  state: BrainMapNodeState;
  /** Effective recall confidence in [0, 1]. */
  confidence: number;
  /** Node glow in [0, 1] (locked is near-zero regardless of confidence). */
  brightness: number;
  /** Recall crispness in [0, 1]; low values render as blur ("fuzzy" recall). */
  sharpness: number;
  fact_count: number;
  risk: number;
  reward: number;
  guarded: boolean;
  rate_limit_per_day: number;
}

export interface BrainMapSection {
  /** Memory kind, e.g. "episodic" | "semantic" | ... */
  kind: string;
  label: string;
  /** Left->right ordering; lower = brighter/sharper region. */
  depth: number;
  /** Mirrors the hot/warm/cold/archived Mindpage tier the region maps onto. */
  tier_hint: string;
  block_count: number;
  populated: number;
  unlockable: number;
  locked: number;
  confidence: number;
  nodes: BrainMapNode[];
}

export interface BrainMapSnapshot {
  scope: string;
  generated_at: number;
  confidence_threshold: number;
  sections: BrainMapSection[];
  legend: { states: string[]; encoding: string };
  totals: { blocks: number; populated: number; unlockable: number; locked: number };
}

export interface BrainMapOptions {
  /** Background fill; defaults to a deep circuit-board navy. */
  background?: string;
  /** Optional device-pixel-ratio cap (defaults to the real DPR, max 2). */
  maxPixelRatio?: number;
}

export interface BrainMap {
  /** Draw a new snapshot (replaces whatever was shown). */
  update(snapshot: BrainMapSnapshot): void;
  /** Re-fit the canvas to its container and redraw the last snapshot. */
  resize(): void;
  /** Detach the canvas and stop observing resizes. */
  destroy(): void;
  readonly canvas: HTMLCanvasElement;
}

interface Palette {
  background: string;
  trace: string;
  label: string;
  sublabel: string;
  locked: readonly [number, number, number];
  unlockable: readonly [number, number, number];
  populated: readonly [number, number, number];
}

const PALETTE: Palette = {
  background: "#070b16",
  trace: "rgba(90, 130, 180, 0.22)",
  label: "rgba(210, 228, 245, 0.92)",
  sublabel: "rgba(150, 176, 200, 0.66)",
  locked: [70, 84, 104],
  unlockable: [226, 178, 92],
  populated: [96, 214, 232],
};

function rgba(color: readonly [number, number, number], alpha: number): string {
  const clamp = (value: number) => Math.max(0, Math.min(1, value));
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${clamp(alpha).toFixed(3)})`;
}

function stateColor(state: BrainMapNodeState): readonly [number, number, number] {
  if (state === "populated") return PALETTE.populated;
  if (state === "unlockable") return PALETTE.unlockable;
  return PALETTE.locked;
}

/** A deterministic demo snapshot so the map renders without a live backend. */
export function demoBrainMapSnapshot(): BrainMapSnapshot {
  const node = (
    id: number,
    name: string,
    state: BrainMapNodeState,
    confidence: number,
    guarded = false,
  ): BrainMapNode => ({
    id,
    name,
    state,
    confidence,
    brightness: state === "locked" ? 0.06 : Math.max(0.2, confidence),
    sharpness: state === "locked" ? 0 : Math.max(0.12, confidence),
    fact_count: state === "populated" ? Math.max(1, Math.round(confidence * 4)) : 0,
    risk: guarded ? 0.8 : 0.2,
    reward: 0.5,
    guarded,
    rate_limit_per_day: guarded ? 1 : 0,
  });
  const sections: BrainMapSection[] = [
    {
      kind: "episodic", label: "Active & Episodic", depth: 0, tier_hint: "hot",
      block_count: 2, populated: 2, unlockable: 0, locked: 0, confidence: 0.82,
      nodes: [node(1, "today with Jason", "populated", 0.9), node(2, "the picnic", "populated", 0.44)],
    },
    {
      kind: "relationship", label: "Relational", depth: 1, tier_hint: "hot",
      block_count: 1, populated: 1, unlockable: 0, locked: 0, confidence: 0.85,
      nodes: [node(3, "Jason's favorites", "populated", 0.85)],
    },
    {
      kind: "self_model", label: "Self-Model", depth: 2, tier_hint: "warm",
      block_count: 1, populated: 1, unlockable: 0, locked: 0, confidence: 0.7,
      nodes: [node(4, "power-core emblem", "populated", 0.7)],
    },
    {
      kind: "semantic", label: "Semantic", depth: 3, tier_hint: "cold",
      block_count: 2, populated: 1, unlockable: 1, locked: 0, confidence: 0.5,
      nodes: [node(5, "colors & shapes", "populated", 0.5), node(6, "counting", "unlockable", 0.0)],
    },
    {
      kind: "procedural", label: "Procedural", depth: 4, tier_hint: "cold",
      block_count: 1, populated: 0, unlockable: 0, locked: 1, confidence: 0.0,
      nodes: [node(7, "world history", "locked", 0.0, true)],
    },
    {
      kind: "musing", label: "Long-Term / Musing", depth: 5, tier_hint: "archived",
      block_count: 1, populated: 1, unlockable: 0, locked: 0, confidence: 0.3,
      nodes: [node(8, "old reflection", "populated", 0.3)],
    },
  ];
  return {
    scope: "creator",
    generated_at: 0,
    confidence_threshold: 0.35,
    sections,
    legend: {
      states: ["locked", "unlockable", "populated"],
      encoding: "brightness+sharpness = recall confidence; sections = memory kinds",
    },
    totals: { blocks: 9, populated: 6, unlockable: 1, locked: 1 },
  };
}

export function createBrainMap(container: HTMLElement, options: BrainMapOptions = {}): BrainMap {
  const background = options.background ?? PALETTE.background;
  const canvas = document.createElement("canvas");
  canvas.className = "brain-map-canvas";
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.display = "block";
  container.appendChild(canvas);

  const ctx = canvas.getContext("2d");
  let last: BrainMapSnapshot | null = null;

  const pixelRatio = (): number => {
    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    return Math.min(options.maxPixelRatio ?? 2, Math.max(1, dpr));
  };

  function fit(): { width: number; height: number } {
    const rect = container.getBoundingClientRect();
    const cssWidth = Math.max(320, Math.round(rect.width || 960));
    const cssHeight = Math.max(220, Math.round(rect.height || 480));
    const ratio = pixelRatio();
    canvas.width = Math.round(cssWidth * ratio);
    canvas.height = Math.round(cssHeight * ratio);
    if (ctx) {
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    return { width: cssWidth, height: cssHeight };
  }

  function drawNode(node: BrainMapNode, x: number, y: number, radius: number): void {
    if (!ctx) return;
    const color = stateColor(node.state);
    // Sharpness -> crispness: a fuzzy (low-sharpness) recall gets a soft halo and
    // a blurred edge; a locked node is a hollow dark ring (nothing there).
    const blur = (1 - Math.max(0, Math.min(1, node.sharpness))) * radius * 1.4;
    const glow = Math.max(0, Math.min(1, node.brightness));

    ctx.save();
    if (node.state !== "locked") {
      ctx.shadowColor = rgba(color, 0.9 * glow);
      ctx.shadowBlur = 6 + blur;
    }
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = rgba(color, node.state === "locked" ? 0.12 : 0.25 + 0.65 * glow);
    ctx.fill();
    ctx.restore();

    // Crisp outer ring (amber-dashed for a guarded, unlock-gated region).
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.lineWidth = node.guarded ? 2 : 1.25;
    ctx.strokeStyle = rgba(color, node.state === "locked" ? 0.5 : 0.4 + 0.5 * glow);
    if (node.guarded && ctx.setLineDash) ctx.setLineDash([4, 3]);
    ctx.stroke();
    if (ctx.setLineDash) ctx.setLineDash([]);

    // Label + fact count.
    ctx.fillStyle = PALETTE.label;
    ctx.font = "12px system-ui, -apple-system, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(truncate(node.name, 18), x, y + radius + 5);
    if (node.state === "populated") {
      ctx.fillStyle = PALETTE.sublabel;
      ctx.font = "10px system-ui, -apple-system, sans-serif";
      ctx.fillText(`${node.fact_count} fact${node.fact_count === 1 ? "" : "s"}`, x, y + radius + 20);
    }
  }

  function draw(): void {
    if (!ctx) return;
    const { width, height } = fit();
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, width, height);

    if (!last || last.sections.length === 0) {
      ctx.fillStyle = PALETTE.sublabel;
      ctx.font = "14px system-ui, -apple-system, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("No brain-map data yet.", width / 2, height / 2);
      return;
    }

    const sections = [...last.sections].sort((a, b) => a.depth - b.depth);
    const marginX = 56;
    const topPad = 54;
    const bottomPad = 28;
    const usableW = Math.max(1, width - marginX * 2);
    const colW = usableW / sections.length;
    const colH = Math.max(1, height - topPad - bottomPad);

    // Faint circuit traces linking the section columns (the "board").
    ctx.strokeStyle = PALETTE.trace;
    ctx.lineWidth = 1;
    for (let i = 0; i < sections.length; i += 1) {
      const cx = marginX + colW * (i + 0.5);
      ctx.beginPath();
      ctx.moveTo(cx, topPad);
      ctx.lineTo(cx, topPad + colH);
      ctx.stroke();
      if (i < sections.length - 1) {
        const nx = marginX + colW * (i + 1.5);
        const midY = topPad + colH * 0.5;
        ctx.beginPath();
        ctx.moveTo(cx, midY);
        ctx.lineTo(nx, midY);
        ctx.stroke();
      }
    }

    // The left->right "Fact Retention: Degraded" gradient wash: deeper sections
    // sit under a heavier fade, echoing the concept art's dissolving right edge.
    sections.forEach((section, i) => {
      const cx = marginX + colW * (i + 0.5);
      const fade = sections.length > 1 ? section.depth / (sections.length - 1) : 0;

      // Column header: memory-kind label + tier + counts.
      ctx.fillStyle = PALETTE.label;
      ctx.font = "600 13px system-ui, -apple-system, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "alphabetic";
      ctx.globalAlpha = 1 - fade * 0.4;
      ctx.fillText(truncate(section.label, 16), cx, 24);
      ctx.fillStyle = PALETTE.sublabel;
      ctx.font = "10px system-ui, -apple-system, sans-serif";
      ctx.fillText(`${section.tier_hint} - ${section.populated}/${section.block_count} lit`, cx, 40);
      ctx.globalAlpha = 1;

      const nodes = section.nodes;
      const count = Math.max(1, nodes.length);
      const slot = colH / count;
      const radius = Math.max(9, Math.min(22, slot * 0.28, colW * 0.24));
      nodes.forEach((node, j) => {
        const cy = topPad + slot * (j + 0.5);
        // Apply the regional fade on top of the node's own brightness so the
        // right-hand archive genuinely reads dimmer.
        ctx.globalAlpha = 1 - fade * 0.35;
        drawNode(node, cx, cy, radius);
        ctx.globalAlpha = 1;
      });
    });

    drawLegend(width, height);
  }

  function drawLegend(width: number, _height: number): void {
    if (!ctx || !last) return;
    const items: Array<[BrainMapNodeState, string]> = [
      ["populated", "populated"],
      ["unlockable", "unlockable"],
      ["locked", "locked"],
    ];
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.font = "10px system-ui, -apple-system, sans-serif";
    let x = 16;
    const y = 14;
    items.forEach(([state, label]) => {
      const color = stateColor(state);
      ctx.beginPath();
      ctx.arc(x + 5, y, 5, 0, Math.PI * 2);
      ctx.fillStyle = rgba(color, state === "locked" ? 0.35 : 0.85);
      ctx.fill();
      ctx.fillStyle = PALETTE.sublabel;
      ctx.fillText(label, x + 14, y);
      x += 22 + ctx.measureText(label).width;
    });
    const caption = `scope: ${last.scope}`;
    ctx.textAlign = "right";
    ctx.fillStyle = PALETTE.sublabel;
    ctx.fillText(caption, width - 12, y);
  }

  function truncate(text: string, max: number): string {
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  }

  let observer: ResizeObserver | null = null;
  if (typeof ResizeObserver !== "undefined") {
    observer = new ResizeObserver(() => draw());
    observer.observe(container);
  }

  if (!ctx) {
    // No 2D context (extremely rare): degrade to a no-op renderer rather than
    // throwing, so a caller mounting the map can never crash the page.
    console.warn("[brainMap] 2D canvas context unavailable; renderer disabled.");
  }

  return {
    canvas,
    update(snapshot: BrainMapSnapshot): void {
      last = snapshot;
      draw();
    },
    resize(): void {
      draw();
    },
    destroy(): void {
      if (observer) {
        observer.disconnect();
        observer = null;
      }
      if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
    },
  };
}

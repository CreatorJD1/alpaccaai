/**
 * Standalone visual controller for Alpecca's bounded virtual drive.
 *
 * This module has no top-level DOM side effects and does not perform mutations.
 * A caller supplies directory/search data and receives typed rename or move
 * intents. The caller must return a receipt before the panel reports success.
 * Source-workspace mode is always read-only.
 */

export type DesktopPanelMode = "virtual-drive" | "source-workspace";
export type DesktopPanelStatus =
  | "idle"
  | "loading"
  | "ready"
  | "unavailable"
  | "error";
export type DesktopActionName = "rename" | "move";
export type DesktopReceiptStatus =
  | "pending"
  | "success"
  | "error"
  | "unavailable";

export interface DesktopLocation {
  readonly root: string;
  readonly rel: string;
}

export interface DesktopRoom {
  readonly root: string;
  readonly label?: string;
  readonly count?: number;
  readonly truncated?: boolean;
  readonly available?: boolean;
}

export interface DesktopEntry {
  readonly name: string;
  readonly is_dir: boolean;
  readonly size: number;
}

export interface DesktopListingResponse {
  readonly ok: boolean;
  readonly root: string;
  readonly rel: string;
  readonly entries: ReadonlyArray<DesktopEntry>;
  readonly truncated?: boolean;
  readonly error?: string;
}

export interface DesktopSearchMatch extends DesktopEntry {
  readonly root: string;
  readonly rel: string;
}

export interface DesktopSearchResponse {
  readonly ok: boolean;
  readonly query: string;
  readonly matches: ReadonlyArray<DesktopSearchMatch>;
  readonly truncated?: boolean;
  readonly error?: string;
}

export interface DesktopOverviewResponse {
  /** The backend mutation switch. Reads can remain available when false. */
  readonly enabled?: boolean;
  readonly rooms: ReadonlyArray<DesktopRoom>;
  readonly note?: string;
}

export interface DesktopPanelItem {
  readonly root: string;
  /** Full path to this item, relative to root. */
  readonly rel: string;
  readonly name: string;
  readonly isDir: boolean;
  readonly size: number;
}

export interface DesktopBreadcrumb {
  readonly label: string;
  readonly location: DesktopLocation;
}

export interface DesktopRenameIntent {
  readonly type: "rename";
  readonly root: string;
  readonly rel: string;
  readonly newName: string;
}

export interface DesktopMoveIntent {
  readonly type: "move";
  readonly srcRoot: string;
  readonly srcRel: string;
  readonly dstRoot: string;
  readonly dstRel: string;
}

export type DesktopActionIntent = DesktopRenameIntent | DesktopMoveIntent;

export interface DesktopActionReceipt {
  readonly action: DesktopActionName;
  readonly status: DesktopReceiptStatus;
  readonly message: string;
  readonly from?: DesktopLocation;
  readonly to?: DesktopLocation;
}

export interface DesktopPanelDataSource {
  readonly overview?: () => Promise<DesktopOverviewResponse>;
  readonly list: (location: DesktopLocation) => Promise<DesktopListingResponse>;
  readonly search?: (query: string) => Promise<DesktopSearchResponse>;
}

export interface DesktopPanelOptions {
  readonly mode?: DesktopPanelMode;
  readonly title?: string;
  readonly initialLocation?: DesktopLocation;
  readonly rooms?: ReadonlyArray<DesktopRoom>;
  readonly dataSource?: DesktopPanelDataSource;
  /** Defaults to true for virtual-drive mode and is ignored in source mode. */
  readonly actionsEnabled?: boolean;
  readonly autoLoad?: boolean;
  readonly onActionIntent?: (
    intent: DesktopActionIntent,
  ) => void | DesktopActionReceipt | Promise<void | DesktopActionReceipt>;
  readonly onSelectionChange?: (item: DesktopPanelItem | null) => void;
  readonly canAttachFile?: (item: DesktopPanelItem) => boolean;
  readonly onAttachFile?: (item: DesktopPanelItem) => void | Promise<void>;
}

export interface DesktopPanelController {
  readonly element: HTMLElement;
  readonly ready: Promise<void>;
  readonly mode: DesktopPanelMode;
  readonly location: DesktopLocation;
  readonly selectedItem: DesktopPanelItem | null;
  refresh(): Promise<void>;
  navigate(location: DesktopLocation): Promise<void>;
  search(query: string): Promise<void>;
  clearSearch(): void;
  setOverview(overview: DesktopOverviewResponse): void;
  setListing(listing: DesktopListingResponse): void;
  setSearchResults(results: DesktopSearchResponse): void;
  setReceipt(receipt: DesktopActionReceipt): void;
  setUnavailable(message: string): void;
  setError(message: string): void;
  destroy(): void;
}

const ROOT_LABELS: Readonly<Record<string, string>> = {
  desktop: "Desktop",
  pictures: "Pictures",
  music: "Music",
  video: "Videos",
  general: "Documents",
  source: "Source",
  house: "House UI",
  tests: "Tests",
  scripts: "Scripts",
  docs: "Documents",
  project: "Project",
  workspace: "Workspace",
};

const STYLE_ID = "alpecca-desktop-panel-style";
const PANEL_CSS = `
.alpecca-drive { --drive-bg: #15171b; --drive-panel: #1d2025;
  --drive-line: #353a42; --drive-text: #f1f2f4; --drive-muted: #aeb4bd;
  --drive-cyan: #78d8e5; --drive-amber: #f2bd68; --drive-red: #ff8e88;
  width: 100%; min-width: 0; color: var(--drive-text); background: var(--drive-bg);
  border: 1px solid var(--drive-line); border-radius: 8px;
  font: 13px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  letter-spacing: 0; overflow: hidden; }
.alpecca-drive *, .alpecca-drive *::before, .alpecca-drive *::after {
  box-sizing: border-box; letter-spacing: 0; }
.alpecca-drive button, .alpecca-drive input, .alpecca-drive select {
  font: inherit; color: inherit; }
.alpecca-drive button { cursor: pointer; }
.alpecca-drive button:disabled { cursor: not-allowed; opacity: .48; }
.alpecca-drive button:focus-visible, .alpecca-drive input:focus-visible,
.alpecca-drive select:focus-visible { outline: 2px solid var(--drive-cyan);
  outline-offset: 2px; }
.alpecca-drive__header { display: flex; align-items: center;
  justify-content: space-between; gap: 12px; padding: 14px 16px 10px; }
.alpecca-drive__header h2 { margin: 0; font-size: 16px; line-height: 1.25;
  font-weight: 680; }
.alpecca-drive__mode { flex: 0 0 auto; color: #101215; background: var(--drive-cyan);
  border-radius: 4px; padding: 3px 7px; font-size: 10px; font-weight: 750;
  text-transform: uppercase; }
.alpecca-drive__mode--readonly { background: var(--drive-amber); }
.alpecca-drive__toolbar { display: grid; grid-template-columns: minmax(130px, 190px) 1fr auto;
  align-items: center; gap: 8px; padding: 0 16px 10px; }
.alpecca-drive__root, .alpecca-drive__search input, .alpecca-drive__move-input,
.alpecca-drive__rename-input, .alpecca-drive__move-root { width: 100%; min-width: 0;
  min-height: 34px; border: 1px solid var(--drive-line); border-radius: 5px;
  background: #111317; padding: 6px 9px; }
.alpecca-drive__refresh, .alpecca-drive__search button, .alpecca-drive__button {
  min-height: 34px; border: 1px solid var(--drive-line); border-radius: 5px;
  background: #292d34; padding: 6px 11px; white-space: nowrap; }
.alpecca-drive__refresh:hover, .alpecca-drive__search button:hover,
.alpecca-drive__button:hover { border-color: #5e6672; background: #323740; }
.alpecca-drive__search { display: grid; grid-template-columns: 1fr auto; gap: 7px;
  min-width: 0; }
.alpecca-drive__breadcrumbs { display: flex; align-items: center; flex-wrap: wrap;
  gap: 3px; min-height: 36px; padding: 0 16px 10px; color: var(--drive-muted); }
.alpecca-drive__breadcrumbs button { border: 0; border-radius: 4px;
  background: transparent; color: inherit; padding: 4px 6px; }
.alpecca-drive__breadcrumbs button:hover { color: var(--drive-text);
  background: #272b31; }
.alpecca-drive__crumb-separator { opacity: .52; user-select: none; }
.alpecca-drive__notice { margin: 0 16px 10px; border-left: 3px solid var(--drive-amber);
  background: #25231e; color: #f4d9ab; padding: 8px 10px; }
.alpecca-drive__notice--muted { border-left-color: #6c737d; background: #202329;
  color: var(--drive-muted); }
.alpecca-drive__content { min-height: 240px; border-top: 1px solid var(--drive-line);
  padding: 13px 16px 16px; }
.alpecca-drive__content-head { display: flex; align-items: baseline;
  justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.alpecca-drive__content-head h3 { margin: 0; min-width: 0; font-size: 13px;
  line-height: 1.3; overflow-wrap: anywhere; }
.alpecca-drive__content-head span { color: var(--drive-muted); font-size: 11px;
  white-space: nowrap; }
.alpecca-drive__tiles { display: grid;
  grid-template-columns: repeat(auto-fill, minmax(142px, 1fr)); gap: 8px; }
.alpecca-drive__tile { display: grid; grid-template-columns: 36px minmax(0, 1fr);
  align-items: center; gap: 9px; width: 100%; min-height: 70px; text-align: left;
  border: 1px solid var(--drive-line); border-radius: 6px; background: var(--drive-panel);
  padding: 9px; }
.alpecca-drive__tile:hover { border-color: #59616c; background: #252930; }
.alpecca-drive__tile[aria-pressed="true"] { border-color: var(--drive-cyan);
  box-shadow: inset 0 0 0 1px var(--drive-cyan); background: #20292c; }
.alpecca-drive__type { display: grid; place-items: center; width: 36px; height: 36px;
  border-radius: 5px; background: #30343b; color: var(--drive-muted); font-size: 9px;
  font-weight: 800; text-transform: uppercase; overflow: hidden; }
.alpecca-drive__type--folder { background: #3b3325; color: var(--drive-amber); }
.alpecca-drive__tile-copy { min-width: 0; }
.alpecca-drive__tile-name { display: block; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; font-weight: 650; }
.alpecca-drive__tile-meta { display: block; margin-top: 3px; color: var(--drive-muted);
  font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.alpecca-drive__state { display: grid; align-content: center; justify-items: start;
  min-height: 205px; max-width: 560px; }
.alpecca-drive__state strong { font-size: 14px; }
.alpecca-drive__state p { margin: 5px 0 0; color: var(--drive-muted);
  overflow-wrap: anywhere; }
.alpecca-drive__state--error strong { color: var(--drive-red); }
.alpecca-drive__empty { color: var(--drive-muted); margin: 0; padding: 18px 0; }
.alpecca-drive__warning { margin: 10px 0 0; color: #f4d9ab; font-size: 11px; }
.alpecca-drive__selection { border-top: 1px solid var(--drive-line); padding: 12px 16px; }
.alpecca-drive__selection-head { display: flex; align-items: flex-start;
  justify-content: space-between; gap: 12px; }
.alpecca-drive__selection-head strong { display: block; overflow-wrap: anywhere; }
.alpecca-drive__selection-head span { display: block; margin-top: 2px;
  color: var(--drive-muted); font-size: 11px; overflow-wrap: anywhere; }
.alpecca-drive__actions { display: flex; flex-wrap: wrap; justify-content: flex-end;
  gap: 6px; }
.alpecca-drive__button--primary { border-color: #4faebb; background: #22515a; }
.alpecca-drive__button--primary:hover { background: #29636e; }
.alpecca-drive__action-note { margin: 8px 0 0; color: var(--drive-muted); font-size: 11px; }
.alpecca-drive__editor { display: grid; grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 7px; align-items: end; margin-top: 10px; }
.alpecca-drive__editor--move { grid-template-columns: minmax(120px, .7fr)
  minmax(150px, 1fr) auto auto; }
.alpecca-drive__field { display: grid; gap: 4px; min-width: 0; color: var(--drive-muted);
  font-size: 10px; }
.alpecca-drive__receipt { border-top: 1px solid var(--drive-line); padding: 11px 16px;
  background: #181a1f; }
.alpecca-drive__receipt[hidden] { display: none; }
.alpecca-drive__receipt strong { display: block; font-size: 12px; }
.alpecca-drive__receipt p { margin: 3px 0 0; color: var(--drive-muted);
  overflow-wrap: anywhere; }
.alpecca-drive__receipt--success { border-left: 3px solid #80d09b; }
.alpecca-drive__receipt--error { border-left: 3px solid var(--drive-red); }
.alpecca-drive__receipt--unavailable { border-left: 3px solid var(--drive-amber); }
.alpecca-drive__receipt--pending { border-left: 3px solid var(--drive-cyan); }
.alpecca-drive__receipt-path { font-size: 10px; }
@media (max-width: 650px) {
  .alpecca-drive__toolbar { grid-template-columns: 1fr auto; }
  .alpecca-drive__search { grid-column: 1 / -1; grid-row: 2; }
  .alpecca-drive__selection-head { display: grid; }
  .alpecca-drive__actions { justify-content: flex-start; }
  .alpecca-drive__editor, .alpecca-drive__editor--move { grid-template-columns: 1fr 1fr; }
  .alpecca-drive__field { grid-column: 1 / -1; }
}
`;

interface PanelState {
  status: DesktopPanelStatus;
  statusMessage: string;
  rooms: DesktopRoom[];
  location: DesktopLocation;
  view: "folder" | "search";
  query: string;
  truncated: boolean;
  items: DesktopPanelItem[];
  selectedKey: string;
  editor: DesktopActionName | null;
  receipt: DesktopActionReceipt | null;
  note: string;
  warning: string;
  actionsEnabled: boolean;
}

function dom<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = PANEL_CSS;
  document.head.appendChild(style);
}

function normalizeRoot(root: string): string {
  const value = String(root || "").trim();
  if (!value || value.includes("/") || value.includes("\\") || value.includes("\0")) {
    throw new Error("A valid drive root is required.");
  }
  return value;
}

/** Normalize a display/request path without allowing parent traversal. */
export function normalizeDesktopRelativePath(value: string): string {
  const raw = String(value || "").replace(/\\/g, "/");
  if (raw.includes("\0")) throw new Error("The path contains an invalid character.");
  if (raw.startsWith("/") || /^[A-Za-z]:($|\/)/.test(raw)) {
    throw new Error("Absolute paths are not allowed in a drive root.");
  }
  const parts: string[] = [];
  for (const part of raw.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") throw new Error("Parent-folder traversal is not allowed.");
    parts.push(part);
  }
  return parts.join("/");
}

function normalizeLocation(location: DesktopLocation): DesktopLocation {
  return {
    root: normalizeRoot(location.root),
    rel: normalizeDesktopRelativePath(location.rel),
  };
}

function validItemName(name: string): string {
  const value = String(name || "");
  if (
    !value
    || value === "."
    || value === ".."
    || value.includes("/")
    || value.includes("\\")
    || value.includes("\0")
  ) {
    throw new Error("The item name is not a single safe path component.");
  }
  return value;
}

function joinRelativePath(parent: string, child: string): string {
  const base = normalizeDesktopRelativePath(parent);
  const name = validItemName(child);
  return base ? `${base}/${name}` : name;
}

function parentRelativePath(rel: string): string {
  const parts = normalizeDesktopRelativePath(rel).split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

export function desktopRootLabel(root: string): string {
  const normalized = normalizeRoot(root);
  const known = ROOT_LABELS[normalized.toLowerCase()];
  if (known) return known;
  return normalized
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function desktopBreadcrumbs(location: DesktopLocation): DesktopBreadcrumb[] {
  const normalized = normalizeLocation(location);
  const crumbs: DesktopBreadcrumb[] = [
    {
      label: desktopRootLabel(normalized.root),
      location: { root: normalized.root, rel: "" },
    },
  ];
  const parts = normalized.rel.split("/").filter(Boolean);
  const path: string[] = [];
  for (const part of parts) {
    path.push(part);
    crumbs.push({
      label: part,
      location: { root: normalized.root, rel: path.join("/") },
    });
  }
  return crumbs;
}

export function formatDesktopBytes(value: number): string {
  const bytes = Number.isFinite(value) ? Math.max(0, value) : 0;
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && size >= 1024; index += 1) {
    size /= 1024;
    unit = units[index];
  }
  const digits = size >= 10 ? 0 : 1;
  return `${size.toFixed(digits)} ${unit}`;
}

function desktopPathLabel(location: DesktopLocation): string {
  const normalized = normalizeLocation(location);
  return normalized.rel
    ? `${desktopRootLabel(normalized.root)} / ${normalized.rel}`
    : desktopRootLabel(normalized.root);
}

export function createDesktopRenameIntent(
  item: DesktopPanelItem,
  newName: string,
): DesktopRenameIntent {
  const root = normalizeRoot(item.root);
  const rel = normalizeDesktopRelativePath(item.rel);
  if (!rel) throw new Error("The drive root cannot be renamed.");
  const trimmed = String(newName || "").trim();
  validItemName(trimmed);
  return { type: "rename", root, rel, newName: trimmed };
}

export function createDesktopMoveIntent(
  item: DesktopPanelItem,
  destination: DesktopLocation,
): DesktopMoveIntent {
  const sourceRoot = normalizeRoot(item.root);
  const sourceRel = normalizeDesktopRelativePath(item.rel);
  if (!sourceRel) throw new Error("The drive root cannot be moved.");
  const target = normalizeLocation(destination);
  return {
    type: "move",
    srcRoot: sourceRoot,
    srcRel: sourceRel,
    dstRoot: target.root,
    dstRel: target.rel,
  };
}

function itemKey(item: DesktopPanelItem): string {
  return `${item.root}\0${item.rel}`;
}

function finiteSize(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function listingItems(
  location: DesktopLocation,
  entries: ReadonlyArray<DesktopEntry>,
): { items: DesktopPanelItem[]; rejected: number } {
  const items: DesktopPanelItem[] = [];
  let rejected = 0;
  for (const entry of entries) {
    try {
      const name = validItemName(entry.name);
      items.push({
        root: location.root,
        rel: joinRelativePath(location.rel, name),
        name,
        isDir: entry.is_dir === true,
        size: finiteSize(entry.size),
      });
    } catch {
      rejected += 1;
    }
  }
  return { items, rejected };
}

function searchItems(
  matches: ReadonlyArray<DesktopSearchMatch>,
): { items: DesktopPanelItem[]; rejected: number } {
  const items: DesktopPanelItem[] = [];
  let rejected = 0;
  for (const match of matches) {
    try {
      const root = normalizeRoot(match.root);
      const rel = normalizeDesktopRelativePath(match.rel);
      const name = validItemName(match.name);
      if (!rel || rel.split("/").at(-1) !== name) throw new Error("Mismatched item path.");
      items.push({
        root,
        rel,
        name,
        isDir: match.is_dir === true,
        size: finiteSize(match.size),
      });
    } catch {
      rejected += 1;
    }
  }
  return { items, rejected };
}

function normalizeRooms(rooms: ReadonlyArray<DesktopRoom>): DesktopRoom[] {
  const seen = new Set<string>();
  const normalized: DesktopRoom[] = [];
  for (const room of rooms) {
    try {
      const root = normalizeRoot(room.root);
      if (seen.has(root)) continue;
      seen.add(root);
      normalized.push({
        root,
        label: room.label ? String(room.label) : desktopRootLabel(root),
        count: typeof room.count === "number" && Number.isFinite(room.count)
          ? Math.max(0, Math.round(room.count))
          : undefined,
        truncated: room.truncated === true,
        available: room.available !== false,
      });
    } catch {
      // Invalid roots are omitted instead of being sent back to a data source.
    }
  }
  return normalized;
}

function errorText(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  if (typeof error === "string" && error.trim()) return error.trim();
  return fallback;
}

function actionTitle(action: DesktopActionName): string {
  return action === "rename" ? "Rename" : "Move";
}

function receiptTitle(receipt: DesktopActionReceipt): string {
  const action = actionTitle(receipt.action);
  if (receipt.status === "success") return `${action} confirmed`;
  if (receipt.status === "error") return `${action} failed`;
  if (receipt.status === "unavailable") return `${action} unavailable`;
  return `${action} requested`;
}

function normalizeReceipt(
  receipt: DesktopActionReceipt,
  expectedAction?: DesktopActionName,
): DesktopActionReceipt {
  const statuses: ReadonlyArray<DesktopReceiptStatus> = [
    "pending",
    "success",
    "error",
    "unavailable",
  ];
  if (
    !receipt
    || typeof receipt !== "object"
    || (receipt.action !== "rename" && receipt.action !== "move")
    || (expectedAction !== undefined && receipt.action !== expectedAction)
    || !statuses.includes(receipt.status)
    || typeof receipt.message !== "string"
    || !receipt.message.trim()
  ) {
    return {
      action: expectedAction ?? "rename",
      status: "error",
      message: "The action handler returned an invalid receipt. The drive state is unknown.",
    };
  }
  try {
    return {
      action: receipt.action,
      status: receipt.status,
      message: receipt.message.trim(),
      from: receipt.from ? normalizeLocation(receipt.from) : undefined,
      to: receipt.to ? normalizeLocation(receipt.to) : undefined,
    };
  } catch {
    return {
      action: expectedAction ?? receipt.action,
      status: "error",
      message: "The action receipt contained an invalid path. The drive state is unknown.",
    };
  }
}

function endpoint(baseUrl: string, path: string): string {
  return `${String(baseUrl || "").replace(/\/$/, "")}${path}`;
}

/**
 * Convenience read adapter for the existing /desktop endpoints. Mutations are
 * deliberately absent: the panel only emits intents to its owner.
 */
export function createDesktopHttpDataSource(
  baseUrl: string,
  request: typeof fetch = fetch,
): DesktopPanelDataSource {
  const read = async <T>(path: string): Promise<T> => {
    const response = await request(endpoint(baseUrl, path), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`Drive request returned ${response.status}.`);
    return await response.json() as T;
  };
  return {
    overview: () => read<DesktopOverviewResponse>("/desktop"),
    list: (location) => {
      const params = new URLSearchParams({ root: location.root, rel: location.rel });
      return read<DesktopListingResponse>(`/desktop/list?${params.toString()}`);
    },
    search: (query) => {
      const params = new URLSearchParams({ q: query, limit: "80" });
      return read<DesktopSearchResponse>(`/desktop/search?${params.toString()}`);
    },
  };
}


/** Read adapter for the separate, creator-only repository workspace. */
export function createSourceWorkspaceHttpDataSource(
  baseUrl: string,
  request: typeof fetch = fetch,
): DesktopPanelDataSource {
  const read = async <T>(path: string): Promise<T> => {
    const response = await request(endpoint(baseUrl, path), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`Source workspace request returned ${response.status}.`);
    return await response.json() as T;
  };
  return {
    overview: async () => {
      const payload = await read<{
        roots?: ReadonlyArray<DesktopRoom>;
        note?: string;
      }>("/source-workspace");
      return { rooms: payload.roots ?? [], note: payload.note };
    },
    list: (location) => {
      const params = new URLSearchParams({ root: location.root, rel: location.rel });
      return read<DesktopListingResponse>(`/source-workspace/list?${params.toString()}`);
    },
    search: (query) => {
      const params = new URLSearchParams({ q: query, limit: "80" });
      return read<DesktopSearchResponse>(`/source-workspace/search?${params.toString()}`);
    },
  };
}

/** Build an unattached panel and its controller. */
export function createDesktopPanel(
  options: DesktopPanelOptions = {},
): DesktopPanelController {
  ensureStyle();
  const mode = options.mode ?? "virtual-drive";
  const readOnly = mode === "source-workspace";
  const defaultLocation = options.initialLocation ?? {
    root: readOnly ? "source" : "desktop",
    rel: "",
  };
  let initialLocation: DesktopLocation;
  try {
    initialLocation = normalizeLocation(defaultLocation);
  } catch {
    initialLocation = { root: readOnly ? "source" : "desktop", rel: "" };
  }

  const initialRooms = normalizeRooms(options.rooms ?? [
    { root: initialLocation.root, available: true },
  ]);
  const root = dom("section", "alpecca-drive");
  root.dataset.desktopPanel = "true";
  root.setAttribute("role", "region");
  root.setAttribute(
    "aria-label",
    readOnly ? "Alpecca source workspace" : "Alpecca virtual drive",
  );

  const state: PanelState = {
    status: options.dataSource ? "loading" : "unavailable",
    statusMessage: options.dataSource
      ? "Loading drive data."
      : "No drive data source is connected.",
    rooms: initialRooms,
    location: initialLocation,
    view: "folder",
    query: "",
    truncated: false,
    items: [],
    selectedKey: "",
    editor: null,
    receipt: null,
    note: "",
    warning: "",
    actionsEnabled: !readOnly && options.actionsEnabled !== false,
  };

  let lastListing: DesktopListingResponse | null = null;
  let requestSequence = 0;
  let actionSequence = 0;
  let destroyed = false;

  function selectedItem(): DesktopPanelItem | null {
    return state.items.find((item) => itemKey(item) === state.selectedKey) ?? null;
  }

  function notifySelection(item: DesktopPanelItem | null): void {
    try {
      options.onSelectionChange?.(item);
    } catch {
      // Consumer callbacks cannot be allowed to break the panel renderer.
    }
  }

  function clearSelection(): void {
    const hadSelection = Boolean(state.selectedKey);
    state.selectedKey = "";
    state.editor = null;
    if (hadSelection) notifySelection(null);
  }

  function addRoomFor(rootName: string): void {
    if (state.rooms.some((room) => room.root === rootName)) return;
    state.rooms.push({ root: rootName, label: desktopRootLabel(rootName), available: true });
  }

  function renderHeader(): HTMLElement {
    const header = dom("header", "alpecca-drive__header");
    header.appendChild(dom(
      "h2",
      "",
      options.title ?? (readOnly ? "Source Workspace" : "Alpecca Virtual Drive"),
    ));
    const badge = dom(
      "span",
      `alpecca-drive__mode${readOnly ? " alpecca-drive__mode--readonly" : ""}`,
      readOnly ? "Read only" : "Virtual drive",
    );
    header.appendChild(badge);
    return header;
  }

  function renderToolbar(): HTMLElement {
    const toolbar = dom("div", "alpecca-drive__toolbar");
    const roomSelect = dom("select", "alpecca-drive__root");
    roomSelect.setAttribute("aria-label", "Drive root");
    for (const room of state.rooms) {
      const count = room.count === undefined ? "" : ` (${room.count}${room.truncated ? "+" : ""})`;
      const choice = dom("option", "", `${room.label ?? desktopRootLabel(room.root)}${count}`);
      choice.value = room.root;
      choice.disabled = room.available === false;
      choice.selected = room.root === state.location.root;
      roomSelect.appendChild(choice);
    }
    roomSelect.disabled = state.rooms.length === 0;
    roomSelect.addEventListener("change", () => {
      void loadLocation({ root: roomSelect.value, rel: "" });
    });
    toolbar.appendChild(roomSelect);

    const searchForm = dom("form", "alpecca-drive__search");
    searchForm.setAttribute("role", "search");
    const searchInput = dom("input");
    searchInput.type = "search";
    searchInput.value = state.view === "search" ? state.query : "";
    searchInput.placeholder = readOnly ? "Search source workspace" : "Search allowed folders";
    searchInput.setAttribute("aria-label", "Search drive");
    const searchButton = dom("button", "", "Search");
    searchButton.type = "submit";
    searchForm.append(searchInput, searchButton);
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      void runSearch(searchInput.value);
    });
    toolbar.appendChild(searchForm);

    const refreshButton = dom("button", "alpecca-drive__refresh", "Refresh");
    refreshButton.type = "button";
    refreshButton.disabled = !options.dataSource;
    refreshButton.addEventListener("click", () => {
      void refresh();
    });
    toolbar.appendChild(refreshButton);
    return toolbar;
  }

  function renderBreadcrumbs(): HTMLElement {
    const navigation = dom("nav", "alpecca-drive__breadcrumbs");
    navigation.dataset.desktopBreadcrumbs = "true";
    navigation.setAttribute("aria-label", "Folder path");
    let crumbs: DesktopBreadcrumb[];
    try {
      crumbs = desktopBreadcrumbs(state.location);
    } catch {
      crumbs = [];
    }
    crumbs.forEach((crumb, index) => {
      if (index > 0) {
        const separator = dom("span", "alpecca-drive__crumb-separator", "/");
        separator.setAttribute("aria-hidden", "true");
        navigation.appendChild(separator);
      }
      const button = dom("button", "", crumb.label);
      button.type = "button";
      button.disabled = state.view === "folder"
        && crumb.location.rel === state.location.rel
        && crumb.location.root === state.location.root;
      button.addEventListener("click", () => {
        void loadLocation(crumb.location);
      });
      navigation.appendChild(button);
    });
    return navigation;
  }

  function renderNotices(): DocumentFragment {
    const fragment = document.createDocumentFragment();
    if (readOnly) {
      fragment.appendChild(dom(
        "p",
        "alpecca-drive__notice",
        "Source workspace is read-only. Browsing, folder navigation, selection, and search do not change files.",
      ));
    } else if (!state.actionsEnabled) {
      fragment.appendChild(dom(
        "p",
        "alpecca-drive__notice alpecca-drive__notice--muted",
        "File actions are unavailable. Folder navigation and search remain read-only.",
      ));
    }
    if (state.note) {
      fragment.appendChild(dom(
        "p",
        "alpecca-drive__notice alpecca-drive__notice--muted",
        state.note,
      ));
    }
    return fragment;
  }

  function renderState(): HTMLElement {
    const wrapper = dom(
      "div",
      `alpecca-drive__state${state.status === "error" ? " alpecca-drive__state--error" : ""}`,
    );
    if (state.status === "error") wrapper.setAttribute("role", "alert");
    const titles: Record<Exclude<DesktopPanelStatus, "ready">, string> = {
      idle: "Drive is waiting",
      loading: "Loading drive",
      unavailable: "Drive unavailable",
      error: "Drive error",
    };
    const stateStatus = state.status === "ready" ? "idle" : state.status;
    wrapper.appendChild(dom("strong", "", titles[stateStatus]));
    wrapper.appendChild(dom("p", "", state.statusMessage));
    return wrapper;
  }

  function fileTypeLabel(item: DesktopPanelItem): string {
    if (item.isDir) return "Folder";
    const extension = item.name.includes(".") ? item.name.split(".").at(-1) ?? "" : "";
    return extension ? extension.slice(0, 5).toUpperCase() : "File";
  }

  function itemMeta(item: DesktopPanelItem): string {
    if (state.view === "search") {
      const parent = parentRelativePath(item.rel);
      return desktopPathLabel({ root: item.root, rel: parent });
    }
    return item.isDir ? "Folder" : formatDesktopBytes(item.size);
  }

  function renderTile(item: DesktopPanelItem): HTMLButtonElement {
    const tile = dom("button", "alpecca-drive__tile");
    tile.type = "button";
    tile.dataset.desktopTile = item.isDir ? "folder" : "file";
    tile.setAttribute("aria-pressed", String(itemKey(item) === state.selectedKey));
    tile.setAttribute("aria-label", `${item.isDir ? "Folder" : "File"}: ${item.name}`);
    const type = dom(
      "span",
      `alpecca-drive__type${item.isDir ? " alpecca-drive__type--folder" : ""}`,
      fileTypeLabel(item),
    );
    type.setAttribute("aria-hidden", "true");
    const copy = dom("span", "alpecca-drive__tile-copy");
    copy.appendChild(dom("span", "alpecca-drive__tile-name", item.name));
    copy.appendChild(dom("span", "alpecca-drive__tile-meta", itemMeta(item)));
    tile.append(type, copy);
    tile.addEventListener("click", () => {
      state.selectedKey = itemKey(item);
      state.editor = null;
      notifySelection(item);
      render();
    });
    return tile;
  }

  function renderContent(): HTMLElement {
    const content = dom("div", "alpecca-drive__content");
    if (state.status !== "ready") {
      content.appendChild(renderState());
      return content;
    }

    const contentHeader = dom("div", "alpecca-drive__content-head");
    const title = state.view === "search"
      ? `Search results for "${state.query}"`
      : desktopPathLabel(state.location);
    contentHeader.appendChild(dom("h3", "", title));
    const countText = `${state.items.length} item${state.items.length === 1 ? "" : "s"}`;
    contentHeader.appendChild(dom("span", "", state.truncated ? `${countText}, limited` : countText));
    content.appendChild(contentHeader);

    if (state.items.length === 0) {
      content.appendChild(dom(
        "p",
        "alpecca-drive__empty",
        state.view === "search"
          ? "No matching items were returned."
          : "This folder is empty.",
      ));
    } else {
      const tiles = dom("div", "alpecca-drive__tiles");
      for (const item of state.items) {
        tiles.appendChild(renderTile(item));
      }
      content.appendChild(tiles);
    }
    if (state.warning) content.appendChild(dom("p", "alpecca-drive__warning", state.warning));
    if (state.view === "search") {
      const clear = dom("button", "alpecca-drive__button", "Back to folder");
      clear.type = "button";
      clear.addEventListener("click", clearSearch);
      content.appendChild(clear);
    }
    return content;
  }

  function renderRenameEditor(item: DesktopPanelItem): HTMLElement {
    const form = dom("form", "alpecca-drive__editor");
    const field = dom("label", "alpecca-drive__field", "New name");
    const input = dom("input", "alpecca-drive__rename-input");
    input.name = "newName";
    input.value = item.name;
    input.autocomplete = "off";
    field.appendChild(input);
    const submit = dom("button", "alpecca-drive__button alpecca-drive__button--primary", "Rename");
    submit.type = "submit";
    const cancel = dom("button", "alpecca-drive__button", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", () => {
      state.editor = null;
      render();
    });
    form.append(field, submit, cancel);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      try {
        const intent = createDesktopRenameIntent(item, input.value);
        void dispatchAction(intent, item);
      } catch (error) {
        state.receipt = {
          action: "rename",
          status: "error",
          message: errorText(error, "The new name is invalid."),
        };
        render();
      }
    });
    window.setTimeout(() => input.focus(), 0);
    return form;
  }

  function renderMoveEditor(item: DesktopPanelItem): HTMLElement {
    const form = dom("form", "alpecca-drive__editor alpecca-drive__editor--move");
    const rootField = dom("label", "alpecca-drive__field", "Destination root");
    const rootSelect = dom("select", "alpecca-drive__move-root");
    for (const room of state.rooms.filter((candidate) => candidate.available !== false)) {
      const option = dom("option", "", room.label ?? desktopRootLabel(room.root));
      option.value = room.root;
      option.selected = room.root === state.location.root;
      rootSelect.appendChild(option);
    }
    if (!rootSelect.value) {
      const fallback = dom("option", "", desktopRootLabel(state.location.root));
      fallback.value = state.location.root;
      fallback.selected = true;
      rootSelect.appendChild(fallback);
    }
    rootField.appendChild(rootSelect);

    const pathField = dom("label", "alpecca-drive__field", "Destination folder");
    const pathInput = dom("input", "alpecca-drive__move-input");
    pathInput.value = state.location.rel;
    pathInput.placeholder = "Root folder";
    pathInput.autocomplete = "off";
    pathField.appendChild(pathInput);

    const submit = dom("button", "alpecca-drive__button alpecca-drive__button--primary", "Move");
    submit.type = "submit";
    const cancel = dom("button", "alpecca-drive__button", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", () => {
      state.editor = null;
      render();
    });
    form.append(rootField, pathField, submit, cancel);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      try {
        const intent = createDesktopMoveIntent(item, {
          root: rootSelect.value,
          rel: pathInput.value,
        });
        void dispatchAction(intent, item);
      } catch (error) {
        state.receipt = {
          action: "move",
          status: "error",
          message: errorText(error, "The destination is invalid."),
        };
        render();
      }
    });
    return form;
  }

  function renderSelection(): HTMLElement | null {
    const item = selectedItem();
    if (!item || state.status !== "ready") return null;
    const selection = dom("section", "alpecca-drive__selection");
    selection.dataset.desktopSelection = "true";
    selection.setAttribute("aria-label", "Selected item");
    const heading = dom("div", "alpecca-drive__selection-head");
    const description = dom("div");
    description.appendChild(dom("strong", "", item.name));
    description.appendChild(dom(
      "span",
      "",
      `${item.isDir ? "Folder" : formatDesktopBytes(item.size)} - ${desktopPathLabel({ root: item.root, rel: item.rel })}`,
    ));
    heading.appendChild(description);

    const actions = dom("div", "alpecca-drive__actions");
    if (item.isDir) {
      const open = dom("button", "alpecca-drive__button alpecca-drive__button--primary", "Open folder");
      open.type = "button";
      open.addEventListener("click", () => {
        void loadLocation({ root: item.root, rel: item.rel });
      });
      actions.appendChild(open);
    }
    if (
      !item.isDir
      && typeof options.onAttachFile === "function"
      && (typeof options.canAttachFile !== "function" || options.canAttachFile(item))
    ) {
      const attach = dom("button", "alpecca-drive__button alpecca-drive__button--primary", "Attach to chat");
      attach.type = "button";
      attach.dataset.desktopAttach = "true";
      attach.addEventListener("click", () => {
        try {
          const result = options.onAttachFile?.(item);
          void Promise.resolve(result).catch((error) => {
            state.warning = errorText(error, "The selected file could not be attached.");
            render();
          });
        } catch (error) {
          state.warning = errorText(error, "The selected file could not be attached.");
          render();
        }
      });
      actions.appendChild(attach);
    }

    const handlerConnected = typeof options.onActionIntent === "function";
    if (!readOnly && state.actionsEnabled && handlerConnected) {
      const rename = dom("button", "alpecca-drive__button", "Rename");
      rename.type = "button";
      rename.dataset.desktopAction = "rename";
      rename.addEventListener("click", () => {
        state.editor = "rename";
        render();
      });
      const move = dom("button", "alpecca-drive__button", "Move");
      move.type = "button";
      move.dataset.desktopAction = "move";
      move.addEventListener("click", () => {
        state.editor = "move";
        render();
      });
      actions.append(rename, move);
    }
    heading.appendChild(actions);
    selection.appendChild(heading);

    if (readOnly) {
      selection.appendChild(dom(
        "p",
        "alpecca-drive__action-note",
        "This source item can be browsed and selected, but it cannot be renamed or moved here.",
      ));
    } else if (!state.actionsEnabled) {
      selection.appendChild(dom(
        "p",
        "alpecca-drive__action-note",
        "Rename and move are unavailable because file actions are off.",
      ));
    } else if (!handlerConnected) {
      selection.appendChild(dom(
        "p",
        "alpecca-drive__action-note",
        "Rename and move are unavailable because no action handler is connected.",
      ));
    } else if (state.editor === "rename") {
      selection.appendChild(renderRenameEditor(item));
    } else if (state.editor === "move") {
      selection.appendChild(renderMoveEditor(item));
    }
    return selection;
  }

  function renderReceipt(): HTMLElement {
    const receipt = state.receipt;
    const wrapper = dom("div", "alpecca-drive__receipt");
    wrapper.dataset.desktopReceipt = "true";
    wrapper.setAttribute("aria-live", "polite");
    wrapper.setAttribute("aria-atomic", "true");
    if (!receipt) {
      wrapper.hidden = true;
      return wrapper;
    }
    wrapper.classList.add(`alpecca-drive__receipt--${receipt.status}`);
    wrapper.appendChild(dom("strong", "", receiptTitle(receipt)));
    wrapper.appendChild(dom("p", "", receipt.message));
    if (receipt.from) {
      wrapper.appendChild(dom(
        "p",
        "alpecca-drive__receipt-path",
        `From: ${desktopPathLabel(receipt.from)}`,
      ));
    }
    if (receipt.to) {
      wrapper.appendChild(dom(
        "p",
        "alpecca-drive__receipt-path",
        `To: ${desktopPathLabel(receipt.to)}`,
      ));
    }
    return wrapper;
  }

  function render(): void {
    if (destroyed) return;
    const children: Array<Node> = [
      renderHeader(),
      renderToolbar(),
      renderBreadcrumbs(),
      renderNotices(),
      renderContent(),
    ];
    const selection = renderSelection();
    if (selection) children.push(selection);
    children.push(renderReceipt());
    root.replaceChildren(...children);
  }

  function applyOverview(overview: DesktopOverviewResponse): void {
    if (!overview || !Array.isArray(overview.rooms)) {
      throw new Error("The drive overview response is invalid.");
    }
    state.rooms = normalizeRooms(overview.rooms);
    state.actionsEnabled = !readOnly
      && options.actionsEnabled !== false
      && overview.enabled !== false;
    state.note = typeof overview.note === "string" ? overview.note.trim() : "";
    if (state.rooms.length > 0 && !state.rooms.some((room) => room.root === state.location.root)) {
      const first = state.rooms.find((room) => room.available !== false);
      if (first) state.location = { root: first.root, rel: "" };
    }
  }

  function applyListing(listing: DesktopListingResponse): void {
    if (!listing || listing.ok !== true) {
      throw new Error(
        typeof listing?.error === "string" && listing.error.trim()
          ? listing.error.trim()
          : "The folder listing was rejected.",
      );
    }
    if (!Array.isArray(listing.entries)) throw new Error("The folder listing is invalid.");
    const location = normalizeLocation({ root: listing.root, rel: listing.rel });
    const normalized = listingItems(location, listing.entries);
    state.location = location;
    addRoomFor(location.root);
    state.status = "ready";
    state.statusMessage = "";
    state.view = "folder";
    state.query = "";
    state.truncated = listing.truncated === true;
    state.items = normalized.items;
    state.warning = normalized.rejected > 0
      ? `${normalized.rejected} item${normalized.rejected === 1 ? " was" : "s were"} omitted because the returned path was invalid.`
      : "";
    clearSelection();
    lastListing = listing;
  }

  function applySearchResults(results: DesktopSearchResponse): void {
    if (!results || results.ok !== true) {
      throw new Error(
        typeof results?.error === "string" && results.error.trim()
          ? results.error.trim()
          : "The drive search was rejected.",
      );
    }
    if (!Array.isArray(results.matches)) throw new Error("The search response is invalid.");
    const query = String(results.query || "").trim();
    if (!query) throw new Error("The search response did not identify its query.");
    const normalized = searchItems(results.matches);
    for (const item of normalized.items) addRoomFor(item.root);
    state.status = "ready";
    state.statusMessage = "";
    state.view = "search";
    state.query = query;
    state.truncated = results.truncated === true;
    state.items = normalized.items;
    state.warning = normalized.rejected > 0
      ? `${normalized.rejected} result${normalized.rejected === 1 ? " was" : "s were"} omitted because the returned path was invalid.`
      : "";
    clearSelection();
  }

  function showFailure(status: "unavailable" | "error", message: string): void {
    requestSequence += 1;
    state.status = status;
    state.statusMessage = String(message || "No further detail is available.");
    state.items = [];
    state.warning = "";
    clearSelection();
    render();
  }

  async function loadLocation(location: DesktopLocation): Promise<void> {
    let normalized: DesktopLocation;
    try {
      normalized = normalizeLocation(location);
    } catch (error) {
      showFailure("error", errorText(error, "The folder path is invalid."));
      return;
    }
    const source = options.dataSource;
    if (!source) {
      showFailure("unavailable", "Folder navigation is unavailable because no drive data source is connected.");
      return;
    }
    const sequence = ++requestSequence;
    state.location = normalized;
    state.status = "loading";
    state.statusMessage = `Loading ${desktopPathLabel(normalized)}.`;
    state.view = "folder";
    state.query = "";
    state.items = [];
    state.warning = "";
    clearSelection();
    render();
    try {
      const listing = await source.list(normalized);
      if (destroyed || sequence !== requestSequence) return;
      applyListing(listing);
      render();
    } catch (error) {
      if (destroyed || sequence !== requestSequence) return;
      showFailure("error", errorText(error, "The folder could not be loaded."));
    }
  }

  async function runSearch(queryValue: string): Promise<void> {
    const query = String(queryValue || "").trim();
    if (!query) {
      state.warning = "Enter a search term before searching the drive.";
      render();
      return;
    }
    const source = options.dataSource;
    if (!source?.search) {
      state.status = "unavailable";
      state.statusMessage = "Search is unavailable because this drive source does not provide search results.";
      state.view = "search";
      state.query = query;
      state.items = [];
      clearSelection();
      render();
      return;
    }
    const sequence = ++requestSequence;
    state.status = "loading";
    state.statusMessage = `Searching for "${query}".`;
    state.view = "search";
    state.query = query;
    state.items = [];
    state.warning = "";
    clearSelection();
    render();
    try {
      const results = await source.search(query);
      if (destroyed || sequence !== requestSequence) return;
      applySearchResults(results);
      render();
    } catch (error) {
      if (destroyed || sequence !== requestSequence) return;
      showFailure("error", errorText(error, "The drive search failed."));
    }
  }

  function clearSearch(): void {
    requestSequence += 1;
    if (lastListing) {
      try {
        applyListing(lastListing);
        render();
        return;
      } catch {
        lastListing = null;
      }
    }
    if (options.dataSource) {
      void loadLocation(state.location);
      return;
    }
    showFailure("unavailable", "The previous folder is unavailable because no drive data source is connected.");
  }

  function pendingReceipt(intent: DesktopActionIntent, item: DesktopPanelItem): DesktopActionReceipt {
    if (intent.type === "rename") {
      return {
        action: "rename",
        status: "pending",
        message: "Rename requested. Waiting for a confirmed result.",
        from: { root: item.root, rel: item.rel },
        to: {
          root: item.root,
          rel: joinRelativePath(parentRelativePath(item.rel), intent.newName),
        },
      };
    }
    return {
      action: "move",
      status: "pending",
      message: "Move requested. Waiting for a confirmed result.",
      from: { root: item.root, rel: item.rel },
      to: {
        root: intent.dstRoot,
        rel: joinRelativePath(intent.dstRel, item.name),
      },
    };
  }

  async function dispatchAction(
    intent: DesktopActionIntent,
    item: DesktopPanelItem,
  ): Promise<void> {
    const action = intent.type;
    if (readOnly) {
      state.receipt = {
        action,
        status: "unavailable",
        message: "Source workspace is read-only. Nothing changed.",
      };
      render();
      return;
    }
    if (!state.actionsEnabled) {
      state.receipt = {
        action,
        status: "unavailable",
        message: `${actionTitle(action)} is unavailable because file actions are off. Nothing changed.`,
      };
      render();
      return;
    }
    const handler = options.onActionIntent;
    if (!handler) {
      state.receipt = {
        action,
        status: "unavailable",
        message: `${actionTitle(action)} is unavailable because no action handler is connected. Nothing changed.`,
      };
      render();
      return;
    }
    const sequence = ++actionSequence;
    state.editor = null;
    state.receipt = pendingReceipt(intent, item);
    render();
    try {
      const result = await handler(intent);
      if (destroyed || sequence !== actionSequence || result === undefined) return;
      const receipt = normalizeReceipt(result, action);
      state.receipt = receipt;
      render();
      if (receipt.status === "success" && options.dataSource) await refresh();
    } catch (error) {
      if (destroyed || sequence !== actionSequence) return;
      state.receipt = {
        action,
        status: "error",
        message: `${errorText(error, `${actionTitle(action)} failed.`)} Nothing was confirmed.`,
      };
      render();
    }
  }

  async function refresh(): Promise<void> {
    if (state.view === "search" && state.query) {
      await runSearch(state.query);
      return;
    }
    await loadLocation(state.location);
  }

  async function initialize(): Promise<void> {
    const source = options.dataSource;
    if (!source) {
      render();
      return;
    }
    if (source.overview) {
      const sequence = ++requestSequence;
      state.status = "loading";
      state.statusMessage = "Loading available drive roots.";
      render();
      try {
        const overview = await source.overview();
        if (destroyed || sequence !== requestSequence) return;
        applyOverview(overview);
      } catch (error) {
        if (destroyed || sequence !== requestSequence) return;
        showFailure("error", errorText(error, "The drive overview could not be loaded."));
        return;
      }
      const available = state.rooms.find((room) => room.available !== false);
      if (!available) {
        showFailure("unavailable", "No drive roots are currently available.");
        return;
      }
      if (!state.rooms.some((room) => room.root === state.location.root && room.available !== false)) {
        state.location = { root: available.root, rel: "" };
      }
    }
    await loadLocation(state.location);
  }

  render();
  const ready = options.autoLoad === false ? Promise.resolve() : initialize();

  return {
    element: root,
    ready,
    mode,
    get location(): DesktopLocation {
      return { ...state.location };
    },
    get selectedItem(): DesktopPanelItem | null {
      const item = selectedItem();
      return item ? { ...item } : null;
    },
    refresh,
    navigate: loadLocation,
    search: runSearch,
    clearSearch,
    setOverview(overview: DesktopOverviewResponse): void {
      try {
        applyOverview(overview);
        render();
      } catch (error) {
        showFailure("error", errorText(error, "The drive overview is invalid."));
      }
    },
    setListing(listing: DesktopListingResponse): void {
      requestSequence += 1;
      try {
        applyListing(listing);
        render();
      } catch (error) {
        showFailure("error", errorText(error, "The folder listing is invalid."));
      }
    },
    setSearchResults(results: DesktopSearchResponse): void {
      requestSequence += 1;
      try {
        applySearchResults(results);
        render();
      } catch (error) {
        showFailure("error", errorText(error, "The search response is invalid."));
      }
    },
    setReceipt(receipt: DesktopActionReceipt): void {
      state.receipt = normalizeReceipt(receipt);
      render();
    },
    setUnavailable(message: string): void {
      showFailure("unavailable", message);
    },
    setError(message: string): void {
      showFailure("error", message);
    },
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      requestSequence += 1;
      actionSequence += 1;
      clearSelection();
      root.replaceChildren();
      root.remove();
    },
  };
}

/** Alias emphasizing the renderer role while returning the same controller. */
export function renderDesktopPanel(
  options: DesktopPanelOptions = {},
): DesktopPanelController {
  return createDesktopPanel(options);
}

/** Replace a container with one mounted panel. */
export function mountDesktopPanel(
  container: HTMLElement,
  options: DesktopPanelOptions = {},
): DesktopPanelController {
  const controller = createDesktopPanel(options);
  container.replaceChildren(controller.element);
  return controller;
}

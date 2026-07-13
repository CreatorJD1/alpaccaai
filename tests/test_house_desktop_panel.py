"""Focused checks for the standalone House HQ virtual-drive panel."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOUSE = ROOT / "apps" / "house-hq"
SOURCE = HOUSE / "src" / "desktopPanel.ts"
TSC = HOUSE / "node_modules" / "typescript" / "bin" / "tsc"


def _run_node(script: str) -> dict[str, object]:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the House HQ panel behavior checks")
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def compiled_panel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    node = shutil.which("node")
    if not node or not TSC.is_file():
        pytest.skip("House HQ TypeScript dependencies are not installed")
    output = tmp_path_factory.mktemp("desktop-panel-js")
    completed = subprocess.run(
        [
            node,
            str(TSC),
            str(SOURCE),
            "--target",
            "ES2022",
            "--module",
            "commonjs",
            "--moduleResolution",
            "node",
            "--lib",
            "ES2022,DOM,DOM.Iterable",
            "--strict",
            "--skipLibCheck",
            "--outDir",
            str(output),
        ],
        cwd=HOUSE,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    compiled = next(output.rglob("desktopPanel.js"), None)
    assert compiled is not None
    return compiled


def test_source_uses_safe_dom_and_exposes_no_destructive_command() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    lowered = source.lower()

    assert ".innerhtml" not in lowered
    assert ".outerhtml" not in lowered
    assert "insertadjacenthtml" not in lowered
    assert "document.write" not in lowered
    assert "delete" not in lowered
    assert "textContent" in source
    assert 'DesktopPanelMode = "virtual-drive" | "source-workspace"' in source
    assert 'readonly type: "rename"' in source
    assert 'readonly type: "move"' in source


def test_path_breadcrumb_and_action_intent_helpers(compiled_panel: Path) -> None:
    module_path = json.dumps(str(compiled_panel))
    result = _run_node(
        f"""
const panel = require({module_path});
const item = {{
  root: "desktop",
  rel: "drafts/notes.txt",
  name: "notes.txt",
  isDir: false,
  size: 1536,
}};
let traversalError = false;
let absoluteError = false;
let renameError = false;
try {{ panel.normalizeDesktopRelativePath("../secret.txt"); }} catch {{ traversalError = true; }}
try {{ panel.normalizeDesktopRelativePath("C:/secret.txt"); }} catch {{ absoluteError = true; }}
try {{ panel.createDesktopRenameIntent(item, "../secret.txt"); }} catch {{ renameError = true; }}
console.log(JSON.stringify({{
  normalized: panel.normalizeDesktopRelativePath("notes\\\\daily/./entry.md"),
  crumbs: panel.desktopBreadcrumbs({{ root: "general", rel: "projects/alpecca/ui" }}),
  rename: panel.createDesktopRenameIntent(item, "final notes.txt"),
  move: panel.createDesktopMoveIntent(item, {{ root: "general", rel: "archive/2026" }}),
  bytes: [panel.formatDesktopBytes(0), panel.formatDesktopBytes(1536)],
  traversalError,
  absoluteError,
  renameError,
}}));
"""
    )

    assert result["normalized"] == "notes/daily/entry.md"
    assert [crumb["label"] for crumb in result["crumbs"]] == [
        "Documents",
        "projects",
        "alpecca",
        "ui",
    ]
    assert [crumb["location"]["rel"] for crumb in result["crumbs"]] == [
        "",
        "projects",
        "projects/alpecca",
        "projects/alpecca/ui",
    ]
    assert result["rename"] == {
        "type": "rename",
        "root": "desktop",
        "rel": "drafts/notes.txt",
        "newName": "final notes.txt",
    }
    assert result["move"] == {
        "type": "move",
        "srcRoot": "desktop",
        "srcRel": "drafts/notes.txt",
        "dstRoot": "general",
        "dstRel": "archive/2026",
    }
    assert result["bytes"] == ["0 B", "1.5 KB"]
    assert result["traversalError"] is True
    assert result["absoluteError"] is True
    assert result["renameError"] is True


def test_renderer_navigation_read_only_intents_and_receipts(
    compiled_panel: Path,
) -> None:
    module_path = json.dumps(str(compiled_panel))
    result = _run_node(
        f"""
class FakeNode {{
  constructor(tagName) {{
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.className = "";
    this.dataset = {{}};
    this.attributes = {{}};
    this.listeners = {{}};
    this._text = "";
    this.id = "";
    this.hidden = false;
    this.value = "";
    this.disabled = false;
    this.selected = false;
    this.type = "";
    this.classList = {{
      add: (...names) => {{
        const current = this.className.split(/\\s+/).filter(Boolean);
        this.className = [...new Set([...current, ...names])].join(" ");
      }},
    }};
  }}
  get textContent() {{
    return this._text + this.children.map((child) => child.textContent || "").join("");
  }}
  set textContent(value) {{
    this._text = String(value ?? "");
    this.children = [];
  }}
  appendChild(child) {{
    this.children.push(child);
    child.parentNode = this;
    return child;
  }}
  append(...children) {{ children.forEach((child) => this.appendChild(child)); }}
  replaceChildren(...children) {{
    this._text = "";
    this.children = [];
    this.append(...children);
  }}
  remove() {{
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }}
  setAttribute(name, value) {{ this.attributes[name] = String(value); }}
  getAttribute(name) {{ return this.attributes[name]; }}
  addEventListener(name, listener) {{
    (this.listeners[name] ||= []).push(listener);
  }}
  emit(name) {{
    for (const listener of this.listeners[name] || []) {{
      listener({{ preventDefault() {{}} }});
    }}
  }}
  focus() {{ this.focused = true; }}
}}

const head = new FakeNode("head");
const findAll = (node, predicate, found = []) => {{
  if (predicate(node)) found.push(node);
  for (const child of node.children || []) findAll(child, predicate, found);
  return found;
}};
global.document = {{
  head,
  createElement: (tag) => new FakeNode(tag),
  createDocumentFragment: () => new FakeNode("fragment"),
  getElementById: (id) => findAll(head, (node) => node.id === id)[0] || null,
}};
global.window = {{ setTimeout: (callback) => {{ callback(); return 1; }} }};

const panel = require({module_path});
const literalName = "<img src=x onerror=alert(1)>.txt";
const source = panel.createDesktopPanel({{
  mode: "source-workspace",
  autoLoad: false,
  rooms: [{{ root: "source", label: "Source" }}],
}});
source.setListing({{
  ok: true,
  root: "source",
  rel: "src/ui",
  entries: [
    {{ name: literalName, is_dir: false, size: 72 }},
    {{ name: "components", is_dir: true, size: 0 }},
  ],
}});
const sourceRoot = source.element;
const breadcrumbText = findAll(sourceRoot, (node) => node.dataset.desktopBreadcrumbs === "true")[0].textContent;
const sourceTiles = findAll(sourceRoot, (node) => Boolean(node.dataset.desktopTile));
const literalWasText = sourceRoot.textContent.includes(literalName);
const imageElementCount = findAll(sourceRoot, (node) => node.tagName === "IMG").length;
sourceTiles[0].emit("click");
const readOnlyActions = findAll(sourceRoot, (node) => Boolean(node.dataset.desktopAction));
const readOnlySelection = findAll(sourceRoot, (node) => node.dataset.desktopSelection === "true")[0].textContent;

source.setSearchResults({{
  ok: true,
  query: "component",
  truncated: false,
  matches: [{{
    root: "source",
    rel: "src/ui/components",
    name: "components",
    is_dir: true,
    size: 0,
  }}],
}});
const searchText = sourceRoot.textContent;
source.setUnavailable("The source index is offline.");
const unavailableText = sourceRoot.textContent;
source.setError("The source response was malformed.");
const errorText = sourceRoot.textContent;

const intents = [];
const drive = panel.createDesktopPanel({{
  autoLoad: false,
  rooms: [{{ root: "desktop" }}, {{ root: "general" }}],
  onActionIntent: (intent) => {{
    intents.push(intent);
    return {{
      action: "rename",
      status: "success",
      message: "Server confirmed the rename.",
      from: {{ root: intent.root, rel: intent.rel }},
      to: {{ root: intent.root, rel: "draft-final.txt" }},
    }};
  }},
}});
drive.setListing({{
  ok: true,
  root: "desktop",
  rel: "",
  entries: [{{ name: "draft.txt", is_dir: false, size: 14 }}],
}});
let node = findAll(drive.element, (candidate) => candidate.dataset.desktopTile === "file")[0];
node.emit("click");
node = findAll(drive.element, (candidate) => candidate.dataset.desktopAction === "rename")[0];
node.emit("click");
const renameInput = findAll(drive.element, (candidate) => candidate.className.includes("alpecca-drive__rename-input"))[0];
renameInput.value = "draft-final.txt";
const renameForm = findAll(drive.element, (candidate) => candidate.className === "alpecca-drive__editor")[0];
renameForm.emit("submit");

setTimeout(() => {{
  const receipt = findAll(drive.element, (candidate) => candidate.dataset.desktopReceipt === "true")[0];
  console.log(JSON.stringify({{
    breadcrumbText,
    literalWasText,
    imageElementCount,
    readOnlyActionCount: readOnlyActions.length,
    readOnlySelection,
    searchText,
    unavailableText,
    errorText,
    intents,
    receiptText: receipt.textContent,
    receiptLive: receipt.getAttribute("aria-live"),
  }}));
}}, 0);
"""
    )

    assert result["breadcrumbText"] == "Source/src/ui"
    assert result["literalWasText"] is True
    assert result["imageElementCount"] == 0
    assert result["readOnlyActionCount"] == 0
    assert "cannot be renamed or moved here" in result["readOnlySelection"]
    assert 'Search results for "component"' in result["searchText"]
    assert "components" in result["searchText"]
    assert "Drive unavailable" in result["unavailableText"]
    assert "The source index is offline." in result["unavailableText"]
    assert "Drive error" in result["errorText"]
    assert "The source response was malformed." in result["errorText"]
    assert result["intents"] == [
        {
            "type": "rename",
            "root": "desktop",
            "rel": "draft.txt",
            "newName": "draft-final.txt",
        }
    ]
    assert "Rename confirmed" in result["receiptText"]
    assert "Server confirmed the rename." in result["receiptText"]
    assert "From: Desktop / draft.txt" in result["receiptText"]
    assert "To: Desktop / draft-final.txt" in result["receiptText"]
    assert result["receiptLive"] == "polite"

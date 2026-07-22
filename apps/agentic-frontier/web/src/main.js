import {
  ArrowUp,
  BatteryCharging,
  Brain,
  ChevronsDown,
  ChevronsUp,
  Component,
  createIcons,
  Crosshair,
  Hand,
  HeartPulse,
  LogIn,
  LogOut,
  Map as MapIcon,
  Play,
  Radar,
  RadioTower,
  RefreshCw,
  RotateCcw,
  ScanLine,
  Shield,
  Terminal,
  UserRoundCog,
  UserRoundX,
  Upload,
  Wind,
  X,
} from "lucide";

import { FrontierApi, FrontierApiError } from "./api.js";
import { FrontierGame } from "./game.js";

createIcons({
  icons: {
    ArrowUp,
    BatteryCharging,
    Brain,
    ChevronsDown,
    ChevronsUp,
    Component,
    Crosshair,
    Hand,
    HeartPulse,
    LogIn,
    LogOut,
    Map: MapIcon,
    Play,
    Radar,
    RadioTower,
    RefreshCw,
    RotateCcw,
    ScanLine,
    Shield,
    Terminal,
    UserRoundCog,
    UserRoundX,
    Upload,
    Wind,
    X,
  },
});

const $ = (selector) => document.querySelector(selector);
const app = $("#app");
const api = new FrontierApi();
const deployButton = $("#deploy-button");
const deploymentStatus = $("#deployment-status");
const bootRender = $("#boot-render");
const bootAuthority = $("#boot-authority");
const frameStatus = $("#frame-status");
const terminalPanel = $("#terminal-panel");
const uplinkStatus = $("#uplink-status");
const connectionDot = $("#connection-dot");
const eventLog = $("#event-log");
const avatarStatus = $("#avatar-status");
const avatarFile = $("#avatar-file");
const interactionPrompt = $("#interaction-prompt");
const interactionLabel = $("#interaction-label");
const buildPalette = $("#build-palette");
let actionPending = false;
let config = null;
let game = null;
let account = null;
let rendererReady = false;

try {
  game = new FrontierGame({ canvas: $("#game-canvas"), minimap: $("#minimap") });
  bootRender.textContent = "READY";
  frameStatus.textContent = "RENDER CORE // READY";
  rendererReady = true;
} catch (error) {
  bootRender.textContent = "FAILED";
  bootRender.classList.add("danger-text");
  frameStatus.textContent = "WEBGL 2 RENDERER UNAVAILABLE";
  deploymentStatus.textContent = error instanceof Error ? error.message : "Renderer initialization failed.";
}

function updateDeployAvailability() {
  deployButton.disabled = !rendererReady || !account;
}

function setConnection(state, label) {
  uplinkStatus.dataset.state = state;
  uplinkStatus.textContent = label;
  connectionDot.classList.toggle("is-online", state === "online");
  connectionDot.classList.toggle("is-offline", state === "error");
  bootAuthority.textContent = label;
  bootAuthority.classList.toggle("danger-text", state === "error");
}

function toast(message, tone = "info", duration = 2800) {
  const element = document.createElement("div");
  element.className = `toast ${tone === "error" ? "is-error" : tone === "warn" ? "is-warn" : ""}`;
  element.textContent = String(message).toUpperCase();
  $("#toast-stack").append(element);
  window.setTimeout(() => element.remove(), duration);
}

function logEvent(message, marker = null) {
  const item = document.createElement("li");
  const time = document.createElement("time");
  const text = document.createElement("span");
  const now = new Date();
  time.textContent = marker || `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  text.textContent = message;
  item.append(time, text);
  eventLog.prepend(item);
  while (eventLog.children.length > 18) eventLog.lastElementChild.remove();
}

function setTerminal(open) {
  const next = Boolean(open);
  app.dataset.terminal = next ? "open" : "closed";
  terminalPanel.setAttribute("aria-hidden", String(!next));
  $("#terminal-toggle").setAttribute("aria-label", next ? "Close command terminal" : "Open command terminal");
  game?.setUiBlocked(next || !game.deployed);
}

function setMode(mode) {
  if (!game) return;
  game.setMode(mode);
  app.dataset.mode = mode;
  const explore = mode === "explore";
  $("#explore-mode").classList.toggle("is-active", explore);
  $("#explore-mode").setAttribute("aria-pressed", String(explore));
  $("#command-mode").classList.toggle("is-active", !explore);
  $("#command-mode").setAttribute("aria-pressed", String(!explore));
  buildPalette.hidden = explore;
}

function updatePerception(perception) {
  const mission = perception.mission || {};
  $("#mission-title").textContent = String(mission.title || "Restore Frontier Relay").toUpperCase();
  $("#mission-progress").textContent = `${mission.installed_components ?? 0} / ${mission.required_components ?? 2} COMPONENTS`;
  $("#revision-value").textContent = String(perception.revision ?? 0);
  $("#energy-value").textContent = `${perception.self?.energy ?? 0} / 6`;
  $("#position-value").textContent = (perception.self?.position || [0, 0]).join(", ");
  const companion = perception.observations?.find((item) => item.type === "actor" && item.id === "Alpecca");
  $("#coop-value").textContent = companion ? (companion.energy_band === "low" ? "LOW ENERGY" : "CONNECTED") : "OUT OF RANGE";
  const structures = perception.observations?.filter((item) => item.type === "entity"
    && ["pressure_dome", "lumen_turret", "oxygen_beacon", "power_conduit"].includes(item.kind)).length || 0;
  $("#structure-value").textContent = String(structures);
  $("#weather-readout").textContent = "VESPER DOME // SEALED";
  if (perception.status === "completed") toast("Mission complete // relay restored", "info", 5200);
  if (perception.status === "failed") toast("Expedition failed // bio-sign lost", "error", 5200);
}

function updateTelemetry(detail) {
  const { vitals, materials, cell, nearestThreat, damageFlash, interaction, cycle } = detail;
  ["health", "oxygen", "sanity"].forEach((name) => {
    const value = Math.max(0, Math.min(100, Number(vitals[name] ?? 0)));
    $(`#${name}-value`).textContent = String(Math.round(value));
    $(`#${name}-meter`).style.transform = `scaleX(${value / 100})`;
  });
  $("#alloy-value").textContent = String(materials.alloy ?? 0);
  $("#lumen-value").textContent = String(materials.lumen ?? 0);
  $("#sector-coordinate").textContent = `SECTOR ${String(cell[0]).padStart(2, "0")}.${String(cell[1]).padStart(2, "0")}`;
  if (cycle) $("#cycle-readout").textContent = `SOL ${String(cycle.sol).padStart(2, "0")} // ${cycle.time}`;
  $("#damage-vignette").style.opacity = String(Math.min(0.78, damageFlash * 0.72));

  const threatIndicator = $("#threat-indicator");
  if (nearestThreat <= 1) {
    threatIndicator.dataset.level = "critical";
    $("#threat-label").textContent = "CONTACT // CLOSE";
  } else if (nearestThreat <= 2) {
    threatIndicator.dataset.level = "near";
    $("#threat-label").textContent = "CONTACT // NEAR";
  } else {
    threatIndicator.dataset.level = "clear";
    $("#threat-label").textContent = "NO CONTACT";
  }

  const showInteraction = game?.deployed && game.mode === "explore" && interaction?.label;
  interactionPrompt.hidden = !showInteraction;
  if (showInteraction) interactionLabel.textContent = interaction.label;
}

function describeEvent(response) {
  const type = response.event?.type || "action_accepted";
  const facts = response.event?.facts || {};
  const descriptions = {
    actor_moved: `Moved to sector ${(facts.to || []).join(", ")}.`,
    actor_rested: `Suit energy restored to ${facts.energy_after}.`,
    frontier_scanned: `Scan complete; ${facts.threat_ids?.length || 0} threat contacts inside radius ${facts.radius || 0}.`,
    component_collected: `Secured relay component ${facts.entity_id}.`,
    resource_harvested: `Harvested ${facts.material}; ${facts.remaining} charge remains.`,
    threat_attacked: `${facts.entity_id} took ${facts.damage} damage; ${facts.health_remaining} integrity remains.`,
    terminal_opened: "Colony command grid authorized.",
    structure_placed: `${String(facts.kind || "structure").replaceAll("_", " ")} placed at ${(facts.position || []).join(", ")}.`,
    relay_repaired: `Relay repair ${facts.installed_components}/${facts.required_components}.`,
    companion_moved: `Alpecca ${facts.motion || "walked"} to sector ${(facts.to || []).join(", ")}.`,
    companion_interacted: `Alpecca is using the ${facts.kind || "station"}.`,
  };
  return descriptions[type] || type.replaceAll("_", " ");
}

async function syncAuthority({ quiet = false } = {}) {
  if (!api.sessionId) {
    if (!quiet) toast("Connect an expedition first", "warn");
    return null;
  }
  try {
    const snapshot = await api.sync(api.revision);
    game.syncPerception(snapshot.perception);
    setConnection("online", "SYNCHRONIZED");
    if (!quiet) toast(`Revision ${snapshot.authoritative_revision} synchronized`);
    snapshot.receipts?.forEach((receipt) => logEvent(describeEvent(receipt), `R${receipt.revision}`));
    return snapshot;
  } catch (error) {
    setConnection("error", "SYNC ERROR");
    if (!quiet) toast(error.message, "error");
    return null;
  }
}

async function performAction(action, parameters = {}) {
  if (actionPending) {
    toast("Authority transaction already pending", "warn");
    return null;
  }
  if (!api.sessionId) {
    toast("Connect an expedition first", "warn");
    game?.rejectCellIntent();
    return null;
  }
  actionPending = true;
  try {
    const response = await api.act(action, parameters);
    game.syncPerception(response.perception);
    setConnection("online", "SYNCHRONIZED");
    const description = describeEvent(response);
    logEvent(description, `R${response.revision}`);
    toast(description);
    if (response.event?.type === "terminal_opened") {
      setTerminal(false);
      setMode("command");
    }
    if (response.event?.type === "structure_placed") game.setBuildTool(null);
    return response;
  } catch (error) {
    game?.rejectCellIntent();
    const message = error instanceof Error ? error.message : "Action failed.";
    toast(message, "error");
    logEvent(message, "ERR");
    if (error instanceof FrontierApiError && error.status === 409) await syncAuthority({ quiet: true });
    return null;
  } finally {
    actionPending = false;
  }
}

async function runContextAction() {
  const context = game?.getContextAction();
  if (!context) return;
  if (!context.action) {
    toast(context.label, "warn");
    return;
  }
  await performAction(context.action, context.parameters);
}

async function enterCommandMode() {
  const context = game?.getContextAction();
  if (context?.action === "interact") {
    await performAction(context.action, context.parameters);
  } else {
    setTerminal(false);
    setMode("command");
    logEvent("Field command projection opened.", "GRID");
  }
}

async function connectExpedition({ deploy = false } = {}) {
  if (!game || !account) {
    deploymentStatus.textContent = "Sign in before deploying.";
    return;
  }
  const sessionId = account.worldId;
  const button = deploy ? deployButton : $("#session-connect");
  button.disabled = true;
  deploymentStatus.textContent = "Negotiating server authority...";
  setConnection("pending", "CONNECTING");
  try {
    const result = await api.connect(sessionId);
    game.syncPerception(result.perception, { snap: true });
    setConnection("online", "SYNCHRONIZED");
    result.receipts.forEach((receipt) => logEvent(describeEvent(receipt), `R${receipt.revision}`));
    logEvent(result.created ? "Account expedition created." : "Account expedition resumed.", "LINK");
    deploymentStatus.textContent = "Account expedition synchronized.";
    if (deploy) {
      app.dataset.deployed = "true";
      game.setDeployed(true);
      setTerminal(false);
      toast(result.created ? "Landfall authority established" : "Expedition reconnected", "info", 3600);
    } else {
      toast("Account expedition synchronized");
    }
    return result;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Connection failed.";
    deploymentStatus.textContent = message;
    setConnection("error", "OFFLINE");
    toast(message, "error");
    return null;
  } finally {
    button.disabled = false;
  }
}

async function loadCompanionAvatar(url) {
  if (!game || !url) return;
  try {
    await game.loadAvatar(url);
    logEvent("Native VRM 1.0 companion loaded.", "VRM");
  } catch (error) {
    logEvent(error instanceof Error ? error.message : "VRM load failed.", "VRM");
  }
}

function updateAvatarOptions(catalog) {
  const selected = catalog.selectedAvatar || "silhouette";
  const custom = catalog.avatars?.find((item) => item.id === "custom");
  document.querySelectorAll(".avatar-option").forEach((button) => {
    const item = catalog.avatars?.find((entry) => entry.id === button.dataset.avatarId);
    const available = item?.available !== false;
    button.disabled = !available;
    button.setAttribute("aria-selected", String(button.dataset.avatarId === selected));
  });
  document.querySelectorAll("#custom-avatar-note, [data-custom-avatar-note]").forEach((element) => {
    element.textContent = custom?.available ? "ACCOUNT MODEL READY" : "UPLOAD REQUIRED";
  });
  avatarStatus.dataset.state = "ready";
  avatarStatus.textContent = selected === "custom" ? "MY VRM ACTIVE" : "FIELD SCOUT ACTIVE";
}

async function applyPlayerAvatar(catalog) {
  updateAvatarOptions(catalog);
  if (catalog.selectedAvatar !== "custom") {
    game?.clearPlayerAvatar();
    return;
  }
  avatarStatus.dataset.state = "loading";
  avatarStatus.textContent = "LOADING 0%";
  try {
    await game?.loadPlayerAvatar(`/api/account/avatar/model?revision=${Date.now()}`, (progress) => {
      avatarStatus.textContent = progress > 0 ? `LOADING ${Math.round(progress * 100)}%` : "STREAMING";
    });
    avatarStatus.dataset.state = "ready";
    avatarStatus.textContent = "MY VRM ACTIVE";
  } catch (error) {
    game?.clearPlayerAvatar();
    avatarStatus.dataset.state = "error";
    avatarStatus.textContent = "FIELD SCOUT ACTIVE";
    toast(error instanceof Error ? error.message : "Player VRM failed to load.", "error");
  }
}

async function refreshPlayerAvatars() {
  if (!account) return;
  await applyPlayerAvatar(await api.avatars());
}

async function selectPlayerAvatar(avatarId) {
  if (!account) return;
  try {
    await applyPlayerAvatar(await api.selectAvatar(avatarId));
    toast(avatarId === "custom" ? "Player VRM selected" : "Field Scout selected");
  } catch (error) {
    toast(error instanceof Error ? error.message : "Avatar selection failed.", "error");
  }
}

async function uploadPlayerAvatar(file) {
  if (!file || !account) return;
  avatarStatus.dataset.state = "loading";
  avatarStatus.textContent = "UPLOADING";
  try {
    const catalog = await api.uploadAvatar(file);
    await applyPlayerAvatar(catalog);
    toast("Private player VRM imported");
  } catch (error) {
    avatarStatus.dataset.state = "error";
    avatarStatus.textContent = "IMPORT FAILED";
    toast(error instanceof Error ? error.message : "Avatar upload failed.", "error", 5200);
  } finally {
    avatarFile.value = "";
  }
}

function setAuthMode(mode) {
  const register = mode === "register";
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.authMode === mode));
  });
  document.querySelectorAll(".register-only").forEach((element) => {
    element.hidden = !register;
    if (element instanceof HTMLInputElement) element.disabled = !register;
  });
  $("#auth-password").autocomplete = register ? "new-password" : "current-password";
  $("#auth-submit span").textContent = register ? "CREATE ACCOUNT" : "LOGIN";
  $("#auth-form").dataset.mode = mode;
}

async function acceptAccount(nextAccount) {
  account = nextAccount;
  $("#account-gate").hidden = true;
  $("#account-ready").hidden = false;
  $("#ready-display-name").textContent = account.displayName;
  $("#account-display").textContent = account.displayName;
  $("#operator-value").textContent = account.displayName.toUpperCase();
  deploymentStatus.textContent = "Account verified. Ready to deploy.";
  updateDeployAvailability();
  await refreshPlayerAvatars();
}

async function submitAccount(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const mode = form.dataset.mode || "login";
  const username = $("#auth-username").value.trim();
  const password = $("#auth-password").value;
  const button = $("#auth-submit");
  button.disabled = true;
  deploymentStatus.textContent = mode === "register" ? "Creating player account..." : "Signing in...";
  try {
    const result = mode === "register"
      ? await api.register(username, $("#auth-display-name").value.trim(), password)
      : await api.login(username, password);
    $("#auth-password").value = "";
    await acceptAccount(result.account);
  } catch (error) {
    deploymentStatus.textContent = error instanceof Error ? error.message : "Account request failed.";
    toast(deploymentStatus.textContent, "error", 5200);
  } finally {
    button.disabled = false;
  }
}

async function bootstrapAuthority() {
  const [healthResult, configResult] = await Promise.allSettled([api.health(), api.config()]);
  if (healthResult.status === "fulfilled" && healthResult.value.appId === "agentic-frontier") {
    setConnection("online", "AUTH READY");
  } else {
    setConnection("error", "OFFLINE");
    deploymentStatus.textContent = "Standalone game authority is unavailable.";
  }

  if (configResult.status === "fulfilled") config = configResult.value;
  if (config?.vrmUrl) void loadCompanionAvatar(config.vrmUrl);
  try {
    const result = await api.me();
    await acceptAccount(result.account);
  } catch (error) {
    if (!(error instanceof FrontierApiError) || error.status !== 401) {
      deploymentStatus.textContent = error instanceof Error ? error.message : "Account service unavailable.";
    } else {
      deploymentStatus.textContent = "Login or register to enter Vesper Dome.";
    }
  }
}

game?.addEventListener("telemetry", (event) => updateTelemetry(event.detail));
game?.addEventListener("perception", (event) => updatePerception(event.detail.perception));
game?.addEventListener("cell-intent", (event) => void performAction("move", { to: event.detail.to }));
game?.addEventListener("build-intent", (event) => void performAction("place_structure", {
  kind: event.detail.kind,
  to: event.detail.to,
}));
game?.addEventListener("context-action", () => void runContextAction());
game?.addEventListener("scan-intent", () => void performAction("scan", {}));
game?.addEventListener("rest-intent", () => void performAction("rest", {}));
game?.addEventListener("toggle-mode", () => game.mode === "explore" ? void enterCommandMode() : setMode("explore"));
game?.addEventListener("toggle-terminal", () => setTerminal(app.dataset.terminal !== "open"));
game?.addEventListener("notice", (event) => toast(event.detail.message, event.detail.tone));
game?.addEventListener("build-tool", (event) => {
  document.querySelectorAll(".build-tool[data-build]").forEach((button) => {
    const active = button.dataset.build === event.detail.tool;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
});

deployButton.addEventListener("click", () => void connectExpedition({ deploy: true }));
$("#session-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void connectExpedition();
});
$("#terminal-toggle").addEventListener("click", () => setTerminal(app.dataset.terminal !== "open"));
$("#terminal-close").addEventListener("click", () => setTerminal(false));
$("#explore-mode").addEventListener("click", () => setMode("explore"));
$("#command-mode").addEventListener("click", () => void enterCommandMode());
$("#grid-action").addEventListener("click", () => void enterCommandMode());
$("#sync-action").addEventListener("click", () => void syncAuthority());
$("#rest-action").addEventListener("click", () => void performAction("rest", {}));
$("#scan-action").addEventListener("click", () => void performAction("scan", {}));
$("#touch-action").addEventListener("click", () => void runContextAction());

document.querySelectorAll(".build-tool").forEach((button) => {
  button.addEventListener("click", () => game?.setBuildTool(button.dataset.build === "cancel" ? null : button.dataset.build));
});

document.querySelectorAll(".terminal-tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".terminal-tabs button").forEach((tab) => tab.setAttribute("aria-selected", String(tab === button)));
    document.querySelectorAll(".terminal-view").forEach((panel) => {
      const active = panel.id === `${button.dataset.tab}-panel`;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
  });
});

document.querySelectorAll("[data-quality]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-quality]").forEach((item) => item.classList.toggle("is-active", item === button));
    game?.setQuality(button.dataset.quality);
    localStorage.setItem("alventius.quality", button.dataset.quality);
  });
});

$("#look-sensitivity").addEventListener("input", (event) => {
  const value = Number(event.target.value);
  game?.setSensitivity((value - 20) / 80);
  localStorage.setItem("alventius.sensitivity", String(value));
});
$("#rain-toggle").addEventListener("change", (event) => {
  game?.setRainEnabled(event.target.checked);
  localStorage.setItem("alventius.rain", String(event.target.checked));
});
$("#shake-toggle").addEventListener("change", (event) => {
  game?.setImpactShake(event.target.checked);
  localStorage.setItem("alventius.shake", String(event.target.checked));
});
$("#reset-sim").addEventListener("click", () => game?.resetLocalSimulation());

document.querySelectorAll(".avatar-option").forEach((button) => {
  button.addEventListener("click", () => void selectPlayerAvatar(button.dataset.avatarId));
});
document.querySelectorAll(".avatar-import-trigger").forEach((button) => {
  button.addEventListener("click", () => avatarFile.click());
});
avatarFile.addEventListener("change", () => void uploadPlayerAvatar(avatarFile.files?.[0]));

document.querySelectorAll("[data-auth-mode]").forEach((button) => {
  button.addEventListener("click", () => setAuthMode(button.dataset.authMode));
});
$("#auth-form").addEventListener("submit", (event) => void submitAccount(event));
$("#logout-button").addEventListener("click", async () => {
  await api.logout().catch(() => null);
  location.reload();
});

setAuthMode("login");
const savedSensitivity = Number(localStorage.getItem("alventius.sensitivity"));
if (savedSensitivity >= 20 && savedSensitivity <= 100) {
  $("#look-sensitivity").value = String(savedSensitivity);
  game?.setSensitivity((savedSensitivity - 20) / 80);
}
const savedRain = localStorage.getItem("alventius.rain");
if (savedRain !== null) {
  $("#rain-toggle").checked = savedRain === "true";
  game?.setRainEnabled(savedRain === "true");
}
const savedShake = localStorage.getItem("alventius.shake");
if (savedShake !== null) {
  $("#shake-toggle").checked = savedShake === "true";
  game?.setImpactShake(savedShake === "true");
}
const savedQuality = localStorage.getItem("alventius.quality");
if (["low", "auto", "high"].includes(savedQuality)) {
  document.querySelectorAll("[data-quality]").forEach((button) => button.classList.toggle("is-active", button.dataset.quality === savedQuality));
  game?.setQuality(savedQuality);
}

window.addEventListener("error", (event) => {
  if (event.message) logEvent(event.message, "JS");
});
$("#game-canvas").addEventListener("webglcontextlost", (event) => {
  event.preventDefault();
  toast("Render context lost", "error", 6000);
});

globalThis.__ALVENTIUS_DEBUG__ = {
  snapshot: () => game?.getDebugState() || null,
  setMode: (mode) => setMode(mode),
  performAction: (action, parameters = {}) => performAction(action, parameters),
};

void bootstrapAuthority();

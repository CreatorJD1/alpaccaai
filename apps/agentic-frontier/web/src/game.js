import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import { DomePhysics, companionVelocity } from "./physics.js";

import {
  GRID_SIZE,
  SECTOR_HALF,
  cellCenter,
  cellDistance,
  createEntityVisual,
  createHologramCompanion,
  createWorld,
  sameCell,
  terrainHeight,
  toonMaterial,
  worldCell,
} from "./world-assets.js";

const PLAYER_EYE_HEIGHT = 1.68;
const DOME_CELL_SIZE = 2.85;
const DOME_CELL_MARGIN = DOME_CELL_SIZE / 2 - 0.15;
const BUILD_KIND = {
  dome: "pressure_dome",
  turret: "lumen_turret",
};

function isTypingTarget(target) {
  return target instanceof HTMLInputElement
    || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement
    || target?.isContentEditable;
}

function disposeObject(root) {
  root.traverse((object) => {
    object.geometry?.dispose?.();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.filter(Boolean).forEach((material) => {
      Object.values(material).forEach((value) => value?.isTexture && value.dispose());
      material.dispose?.();
    });
  });
}

function domeCellCenter(cell) {
  return new THREE.Vector3(cell[0] * DOME_CELL_SIZE, 0, cell[1] * DOME_CELL_SIZE);
}

function domeWorldCell(x, z) {
  return [
    THREE.MathUtils.clamp(Math.floor((x + DOME_CELL_SIZE / 2) / DOME_CELL_SIZE), 0, GRID_SIZE - 1),
    THREE.MathUtils.clamp(Math.floor((z + DOME_CELL_SIZE / 2) / DOME_CELL_SIZE), 0, GRID_SIZE - 1),
  ];
}

export class FrontierGame extends EventTarget {
  constructor({ canvas, minimap }) {
    super();
    this.canvas = canvas;
    this.minimap = minimap;
    this.minimapContext = minimap.getContext("2d");
    this.scene = new THREE.Scene();
    this.clock = new THREE.Clock();
    this.elapsed = 0;
    this.deployed = false;
    this.uiBlocked = true;
    this.mode = "explore";
    this.quality = matchMedia("(pointer: coarse)").matches ? "low" : "auto";
    this.rainEnabled = false;
    this.impactShake = true;
    this.lookSensitivity = 0.0021;
    this.yaw = -Math.PI * 0.75;
    this.pitch = -0.08;
    this.keys = new Set();
    this.touchMove = new THREE.Vector2();
    this.touchSprint = false;
    this.touchCrawl = false;
    this.jumpRequested = false;
    this.commandZoom = 1;
    this.commandTarget = new THREE.Vector3();
    this.serverCell = [0, 0];
    this.pendingCell = null;
    this.authorityTarget = null;
    this.companionTarget = new THREE.Vector3();
    this.companionMotion = { mode: "idle", interaction: "none" };
    this.companionInitialized = false;
    this.perception = null;
    this.observations = [];
    this.vitals = { health: 100, oxygen: 100, sanity: 100, shield: 100 };
    this.materials = { alloy: 0, lumen: 0 };
    this.entityVisuals = new Map();
    this.entityLayer = new THREE.Group();
    this.entityLayer.name = "perceived-entities";
    this.scene.add(this.entityLayer);
    this.hoverCell = null;
    this.buildTool = null;
    this.lastTelemetryAt = 0;
    this.damageFlash = 0;
    this.lastVitals = { ...this.vitals };
    this.vrm = null;
    this.vrmScene = null;
    this.avatarBones = null;
    this.playerVrm = null;
    this.playerVrmScene = null;
    this.physics = null;
    this.physicsStatus = "loading";

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: this.quality !== "low",
      alpha: false,
      powerPreference: "high-performance",
    });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.perspectiveCamera = new THREE.PerspectiveCamera(67, 1, 0.08, 220);
    this.commandCamera = new THREE.OrthographicCamera(-36, 36, 36, -36, 0.1, 240);
    this.activeCamera = this.perspectiveCamera;
    this.world = createWorld(this.scene, { quality: this.quality });

    const start = domeCellCenter(this.serverCell);
    this.playerPosition = start;
    this.commandTarget.copy(start);
    this.commandTarget.y = 0;
    this.playerMarker = this.#createPlayerMarker();
    this.playerMarker.visible = false;
    this.scene.add(this.playerMarker);
    this.playerAvatarAnchor = new THREE.Group();
    this.playerAvatarAnchor.name = "vrm-player-anchor";
    this.playerAvatarModelRoot = new THREE.Group();
    this.playerAvatarAnchor.add(this.playerAvatarModelRoot);
    this.playerAvatarAnchor.visible = false;
    this.scene.add(this.playerAvatarAnchor);

    this.companionAnchor = new THREE.Group();
    this.companionAnchor.name = "vrm-companion-anchor";
    this.companionFallback = createHologramCompanion(this.world.ramp);
    this.avatarModelRoot = new THREE.Group();
    this.companionAnchor.add(this.companionFallback, this.avatarModelRoot);
    this.companionAnchor.visible = false;
    this.scene.add(this.companionAnchor);
    this.companionTarget.copy(domeCellCenter([0, 1]));

    void DomePhysics.create({
      colliders: this.world.physicsColliders,
      playerPosition: this.playerPosition,
      companionPosition: this.companionTarget,
    }).then((physics) => {
      this.physics = physics;
      if (this.companionInitialized) this.physics.syncCompanion(this.companionTarget);
      this.physicsStatus = "ready";
      this.#emit("notice", { message: "DOME PHYSICS READY", tone: "info" });
    }).catch(() => {
      this.physicsStatus = "fallback";
      this.#emit("notice", { message: "PHYSICS FALLBACK ACTIVE", tone: "warn" });
    });

    this.raycaster = new THREE.Raycaster();
    this.groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    this.pointerNdc = new THREE.Vector2();
    this.#bindInput();
    this.resize();
    window.addEventListener("resize", () => this.resize(), { passive: true });
    this.renderer.setAnimationLoop(() => this.#frame());
  }

  #createPlayerMarker() {
    const root = new THREE.Group();
    const material = toonMaterial(0xf3f7f1, this.world.ramp, { emissive: 0x314646, emissiveIntensity: 0.4 });
    const body = new THREE.Mesh(new THREE.ConeGeometry(0.46, 1.35, 7), material);
    body.position.y = 0.78;
    const direction = new THREE.Mesh(
      new THREE.ConeGeometry(0.18, 0.72, 5),
      new THREE.MeshBasicMaterial({ color: 0xb7ff3c, toneMapped: false }),
    );
    direction.rotation.x = Math.PI / 2;
    direction.position.set(0, 0.85, 0.72);
    root.add(body, direction);
    return root;
  }

  #emit(type, detail = {}) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }

  #cellPosition(cell) {
    return domeCellCenter(cell);
  }

  #cellFromPosition(position) {
    return domeWorldCell(position.x, position.z);
  }

  #bindInput() {
    window.addEventListener("keydown", (event) => {
      if (isTypingTarget(event.target)) return;
      this.keys.add(event.code);
      if (event.code === "Space" && !event.repeat) {
        event.preventDefault();
        this.jumpRequested = true;
      } else if (event.code === "Tab") {
        event.preventDefault();
        this.#emit("toggle-mode");
      } else if (event.code === "KeyC" && !event.repeat) {
        this.#emit("toggle-terminal");
      } else if (event.code === "KeyE" && !event.repeat) {
        this.#emit("context-action");
      } else if (event.code === "KeyR" && !event.repeat) {
        this.#emit("rest-intent");
      } else if (event.code === "KeyF" && !event.repeat) {
        this.#emit("scan-intent");
      } else if (this.mode === "command" && event.code === "Digit1") {
        this.setBuildTool("dome");
      } else if (this.mode === "command" && event.code === "Digit2") {
        this.setBuildTool("turret");
      } else if (this.mode === "command" && (event.code === "KeyQ" || event.code === "Escape")) {
        this.setBuildTool(null);
      }
    });
    window.addEventListener("keyup", (event) => this.keys.delete(event.code));
    window.addEventListener("blur", () => this.keys.clear());

    document.addEventListener("mousemove", (event) => {
      if (document.pointerLockElement !== this.canvas || this.mode !== "explore" || this.uiBlocked) return;
      this.yaw -= event.movementX * this.lookSensitivity;
      this.pitch = THREE.MathUtils.clamp(this.pitch - event.movementY * this.lookSensitivity, -1.35, 1.28);
    });
    document.addEventListener("pointerlockchange", () => {
      this.#emit("pointer-lock", { locked: document.pointerLockElement === this.canvas });
    });
    this.canvas.addEventListener("contextmenu", (event) => event.preventDefault());

    let commandPointer = null;
    this.canvas.addEventListener("pointerdown", (event) => {
      if (!this.deployed || this.uiBlocked) return;
      if (this.mode === "explore") {
        if (event.pointerType === "mouse" && document.pointerLockElement !== this.canvas) {
          this.canvas.requestPointerLock?.();
        }
        return;
      }
      commandPointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
      this.canvas.setPointerCapture?.(event.pointerId);
      this.#updateGridHover(event);
    });
    this.canvas.addEventListener("pointermove", (event) => {
      if (this.mode === "command" && !this.uiBlocked) this.#updateGridHover(event);
    });
    this.canvas.addEventListener("pointerup", (event) => {
      if (!commandPointer || commandPointer.id !== event.pointerId || this.mode !== "command") return;
      const distance = Math.hypot(event.clientX - commandPointer.x, event.clientY - commandPointer.y);
      commandPointer = null;
      if (distance < 10) this.#activateGridCell();
    });
    this.canvas.addEventListener("wheel", (event) => {
      if (this.mode !== "command") return;
      event.preventDefault();
      this.commandZoom = THREE.MathUtils.clamp(this.commandZoom - Math.sign(event.deltaY) * 0.1, 0.65, 1.85);
      this.commandCamera.zoom = this.commandZoom;
      this.commandCamera.updateProjectionMatrix();
    }, { passive: false });

    this.#bindTouchPads();
  }

  #bindTouchPads() {
    const movementPad = document.querySelector("#movement-pad");
    const movementStick = document.querySelector("#movement-stick");
    const lookPad = document.querySelector("#look-pad");
    let movePointer = null;
    let lookPointer = null;
    let lastLook = null;

    const updateMove = (event) => {
      const rect = movementPad.getBoundingClientRect();
      const x = event.clientX - (rect.left + rect.width / 2);
      const y = event.clientY - (rect.top + rect.height / 2);
      const radius = rect.width * 0.34;
      const length = Math.hypot(x, y) || 1;
      const limited = Math.min(length, radius);
      const nx = x / length * limited;
      const ny = y / length * limited;
      this.touchMove.set(nx / radius, -ny / radius);
      movementStick.style.transform = `translate(calc(-50% + ${nx}px), calc(-50% + ${ny}px))`;
    };
    const resetMove = () => {
      movePointer = null;
      this.touchMove.set(0, 0);
      movementStick.style.transform = "translate(-50%, -50%)";
    };
    movementPad.addEventListener("pointerdown", (event) => {
      movePointer = event.pointerId;
      movementPad.setPointerCapture?.(event.pointerId);
      updateMove(event);
    });
    movementPad.addEventListener("pointermove", (event) => {
      if (event.pointerId === movePointer) updateMove(event);
    });
    movementPad.addEventListener("pointerup", resetMove);
    movementPad.addEventListener("pointercancel", resetMove);

    lookPad.addEventListener("pointerdown", (event) => {
      lookPointer = event.pointerId;
      lastLook = { x: event.clientX, y: event.clientY };
      lookPad.setPointerCapture?.(event.pointerId);
    });
    lookPad.addEventListener("pointermove", (event) => {
      if (event.pointerId !== lookPointer || !lastLook) return;
      const dx = event.clientX - lastLook.x;
      const dy = event.clientY - lastLook.y;
      this.yaw -= dx * this.lookSensitivity * 1.25;
      this.pitch = THREE.MathUtils.clamp(this.pitch - dy * this.lookSensitivity * 1.25, -1.35, 1.28);
      lastLook = { x: event.clientX, y: event.clientY };
    });
    const resetLook = () => {
      lookPointer = null;
      lastLook = null;
    };
    lookPad.addEventListener("pointerup", resetLook);
    lookPad.addEventListener("pointercancel", resetLook);

    const sprint = document.querySelector("#touch-sprint");
    sprint.addEventListener("pointerdown", () => { this.touchSprint = true; });
    ["pointerup", "pointercancel", "pointerleave"].forEach((name) => {
      sprint.addEventListener(name, () => { this.touchSprint = false; });
    });

    const jump = document.querySelector("#touch-jump");
    jump?.addEventListener("click", () => { this.jumpRequested = true; });
    const crawl = document.querySelector("#touch-crawl");
    crawl?.addEventListener("pointerdown", () => { this.touchCrawl = true; });
    ["pointerup", "pointercancel", "pointerleave"].forEach((name) => {
      crawl?.addEventListener(name, () => { this.touchCrawl = false; });
    });
  }

  setDeployed(value) {
    this.deployed = Boolean(value);
    this.uiBlocked = !this.deployed;
  }

  setUiBlocked(value) {
    this.uiBlocked = Boolean(value);
    if (this.uiBlocked && document.pointerLockElement === this.canvas) document.exitPointerLock?.();
  }

  setMode(mode) {
    if (!new Set(["explore", "command"]).has(mode)) return;
    this.mode = mode;
    this.activeCamera = mode === "command" ? this.commandCamera : this.perspectiveCamera;
    this.world.sectorGrid.group.visible = mode === "command";
    this.playerMarker.visible = mode === "command" && !this.playerVrm;
    this.playerAvatarAnchor.visible = mode === "command" && Boolean(this.playerVrm);
    if (mode === "command") {
      document.exitPointerLock?.();
      this.commandTarget.set(this.playerPosition.x, 0, this.playerPosition.z);
      this.#updateCommandCamera(0);
    } else {
      this.setBuildTool(null);
    }
    this.#emit("mode", { mode });
  }

  setQuality(quality) {
    this.quality = quality;
    this.world.key.castShadow = quality !== "low";
    this.renderer.shadowMap.enabled = quality !== "low";
    this.resize();
  }

  setRainEnabled(value) {
    void value;
    // Vesper Dome is sealed. Weather remains server-side expedition context,
    // but visual rain cannot enter the habitat volume.
    this.rainEnabled = false;
    this.world.rain.lines.visible = false;
  }

  setImpactShake(value) {
    this.impactShake = Boolean(value);
  }

  setSensitivity(value) {
    this.lookSensitivity = THREE.MathUtils.lerp(0.0009, 0.0042, THREE.MathUtils.clamp(value, 0, 1));
  }

  setBuildTool(tool) {
    this.buildTool = tool && BUILD_KIND[tool] ? tool : null;
    this.#emit("build-tool", { tool: this.buildTool });
    if (this.world.sectorGrid.hover.visible) this.#updateHoverColor();
  }

  rejectCellIntent() {
    this.pendingCell = null;
    this.authorityTarget = null;
  }

  syncPerception(perception, { snap = false } = {}) {
    if (!perception) return;
    const previousCell = this.serverCell;
    const previousVitals = { ...this.vitals };
    this.perception = perception;
    this.observations = Array.isArray(perception.observations) ? perception.observations : [];
    this.serverCell = [...perception.self.position];
    this.vitals = { ...this.vitals, ...(perception.survival || {}) };
    this.materials = { ...this.materials, ...(perception.survival?.materials || {}) };
    const moved = !sameCell(previousCell, this.serverCell);
    if (snap || moved) {
      const destination = this.#cellPosition(this.serverCell);
      if (snap) {
        this.playerPosition.copy(destination);
        this.physics?.syncPlayer(destination, false);
      }
      else this.authorityTarget = destination;
      this.pendingCell = null;
    }

    if (this.vitals.health < previousVitals.health) {
      this.damageFlash = 1;
      this.#emit("damage", { amount: previousVitals.health - this.vitals.health });
    }
    this.#syncEntities();
    this.#syncCompanion();
    this.#emit("perception", { perception });
    this.#emitTelemetry(true);
  }

  #syncEntities() {
    const observed = new Set();
    this.observations.filter((item) => item.type === "entity").forEach((observation) => {
      observed.add(observation.id);
      let record = this.entityVisuals.get(observation.id);
      if (!record || record.kind !== observation.kind) {
        if (record) {
          this.entityLayer.remove(record.root);
          disposeObject(record.root);
        }
        const root = createEntityVisual(observation.kind, this.world.ramp);
        this.entityLayer.add(root);
        record = { root, kind: observation.kind, observation };
        this.entityVisuals.set(observation.id, record);
      }
      record.observation = observation;
      const position = this.#cellPosition(observation.position);
      record.root.position.copy(position);
      record.root.userData.baseY = position.y;
      record.root.visible = observation.active !== false && observation.remaining !== 0;
      record.root.userData.observation = observation;
    });

    for (const [id, record] of this.entityVisuals) {
      if (observed.has(id)) continue;
      this.entityLayer.remove(record.root);
      disposeObject(record.root);
      this.entityVisuals.delete(id);
    }
  }

  #syncCompanion() {
    const companion = this.observations.find((item) => item.type === "actor" && item.id === "Alpecca");
    if (!companion) {
      this.companionAnchor.visible = false;
      return;
    }
    const position = this.#cellPosition(companion.position);
    this.companionTarget.copy(position);
    const activity = this.perception?.companion_activity || {};
    const motionMode = activity.motion?.mode;
    this.companionMotion = {
      mode: ["walk", "run", "crawl", "jump"].includes(motionMode) ? motionMode : "idle",
      interaction: activity.interaction?.status || "none",
    };
    if (!this.companionInitialized) {
      this.physics?.syncCompanion(position);
      this.companionAnchor.position.copy(position);
      this.companionInitialized = true;
    }
    this.companionAnchor.userData.baseY = 0;
    this.companionAnchor.visible = true;
  }

  getContextAction() {
    if (!this.perception) return { action: "scan", parameters: {}, label: "SCAN FRONTIER" };
    const inventory = this.perception.self.inventory || [];
    const entities = this.observations.filter((item) => item.type === "entity" && item.active !== false);
    const threat = entities.find((item) => ["shadow_smoke", "corrupted_robot"].includes(item.kind) && item.distance <= 2);
    if (threat) return { action: "attack", parameters: { entity_id: threat.id }, label: `ATTACK ${this.#labelKind(threat.kind)}` };
    const local = entities.find((item) => sameCell(item.position, this.serverCell));
    if (local?.kind === "relay_component") {
      return { action: "collect", parameters: { entity_id: local.id }, label: "COLLECT RELAY COMPONENT" };
    }
    if (["ferrite_vein", "lumen_flora"].includes(local?.kind)) {
      return { action: "harvest", parameters: { entity_id: local.id }, label: `HARVEST ${this.#labelKind(local.kind)}` };
    }
    if (local?.kind === "damaged_relay") {
      if (inventory.length) {
        return {
          action: "repair",
          parameters: { relay_id: local.id, entity_id: inventory[0] },
          label: "INSTALL RELAY COMPONENT",
        };
      }
      return { action: null, parameters: {}, label: "RELAY // COMPONENT REQUIRED" };
    }
    const terminal = entities.find((item) => item.kind === "command_terminal" && item.distance <= 1);
    if (terminal) {
      return { action: "interact", parameters: { entity_id: terminal.id }, label: "OPEN COMMAND GRID" };
    }
    return { action: "scan", parameters: {}, label: "SCAN FRONTIER" };
  }

  #labelKind(kind) {
    return String(kind || "target").replaceAll("_", " ").toUpperCase();
  }

  #updateGridHover(event) {
    const rect = this.canvas.getBoundingClientRect();
    this.pointerNdc.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointerNdc, this.commandCamera);
    const hit = new THREE.Vector3();
    if (!this.raycaster.ray.intersectPlane(this.groundPlane, hit)) return;
    if (Math.abs(hit.x) > SECTOR_HALF || Math.abs(hit.z) > SECTOR_HALF) {
      this.hoverCell = null;
      this.world.sectorGrid.hover.visible = false;
      return;
    }
    this.hoverCell = worldCell(hit.x, hit.z);
    const center = cellCenter(this.hoverCell);
    this.world.sectorGrid.hover.position.set(center.x, terrainHeight(center.x, center.z) + 0.42, center.z);
    this.world.sectorGrid.hover.visible = true;
    this.#updateHoverColor();
  }

  #updateHoverColor() {
    const material = this.world.sectorGrid.hover.material;
    if (!this.hoverCell) return;
    const distance = cellDistance(this.serverCell, this.hoverCell);
    const valid = this.buildTool ? distance <= 1 : distance === 1 || distance === 0;
    material.color.setHex(valid ? (this.buildTool ? 0xb7ff3c : 0x5de5df) : 0xff4058);
    material.opacity = valid ? 0.22 : 0.13;
  }

  #activateGridCell() {
    if (!this.hoverCell || this.pendingCell) return;
    const target = [...this.hoverCell];
    if (this.buildTool) {
      this.#emit("build-intent", { kind: BUILD_KIND[this.buildTool], to: target, tool: this.buildTool });
      return;
    }
    const distance = cellDistance(this.serverCell, target);
    if (distance === 0) {
      this.#emit("context-action");
      return;
    }
    if (distance !== 1) {
      this.#emit("notice", { message: "AUTHORITATIVE MOVEMENT REQUIRES AN ADJACENT TILE", tone: "warn" });
      return;
    }
    this.pendingCell = target;
    this.#emit("cell-intent", { to: target, source: "command" });
  }

  #requestCell(cell) {
    if (this.pendingCell || sameCell(cell, this.serverCell) || cellDistance(cell, this.serverCell) !== 1) return;
    this.pendingCell = [...cell];
    this.#emit("cell-intent", { to: [...cell], source: "explore" });
  }

  #updateExplore(delta) {
    if (!this.deployed || this.uiBlocked) return;
    const forwardInput = (this.keys.has("KeyW") || this.keys.has("ArrowUp") ? 1 : 0)
      - (this.keys.has("KeyS") || this.keys.has("ArrowDown") ? 1 : 0)
      + this.touchMove.y;
    const sideInput = (this.keys.has("KeyD") || this.keys.has("ArrowRight") ? 1 : 0)
      - (this.keys.has("KeyA") || this.keys.has("ArrowLeft") ? 1 : 0)
      + this.touchMove.x;
    const input = new THREE.Vector2(sideInput, forwardInput);
    if (input.lengthSq() > 1) input.normalize();
    const forward = new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
    const right = new THREE.Vector3(Math.cos(this.yaw), 0, -Math.sin(this.yaw));
    const movement = forward.multiplyScalar(input.y).add(right.multiplyScalar(input.x));
    const crouched = this.keys.has("ControlLeft") || this.keys.has("ControlRight") || this.touchCrawl;
    const sprinting = !crouched && (this.keys.has("ShiftLeft") || this.keys.has("ShiftRight") || this.touchSprint);
    const speed = crouched ? 1.7 : sprinting ? 6.3 : 4.2;
    let velocity = movement.multiplyScalar(speed);

    if (this.authorityTarget) {
      velocity = companionVelocity(this.playerPosition, this.authorityTarget, 7.6);
      if (this.playerPosition.distanceToSquared(this.authorityTarget) < 0.012) {
        this.playerPosition.copy(this.authorityTarget);
        this.physics?.syncPlayer(this.authorityTarget, false);
        this.authorityTarget = null;
        velocity = { x: 0, y: 0, z: 0 };
      }
    } else {
      const candidate = this.playerPosition.clone().addScaledVector(velocity, delta);
      const candidateCell = this.#cellFromPosition(candidate);
      if (!sameCell(candidateCell, this.serverCell)) {
        this.#requestCell(candidateCell);
        const center = this.#cellPosition(this.serverCell);
        candidate.x = THREE.MathUtils.clamp(candidate.x, center.x - DOME_CELL_MARGIN, center.x + DOME_CELL_MARGIN);
        candidate.z = THREE.MathUtils.clamp(candidate.z, center.z - DOME_CELL_MARGIN, center.z + DOME_CELL_MARGIN);
        velocity = companionVelocity(this.playerPosition, candidate, speed);
      }
    }

    if (this.physics) {
      const companionSpeed = this.companionMotion.mode === "run"
        ? 5.1
        : this.companionMotion.mode === "walk"
          ? 3.15
          : this.companionMotion.mode === "crawl"
            ? 1.45
            : this.companionMotion.mode === "jump"
              ? 3.5
              : 0;
      const snapshot = this.physics.step(delta, {
        player: { velocity, jump: this.jumpRequested, crouched, mode: sprinting ? "run" : "walk" },
        companion: {
          velocity: companionVelocity(this.companionAnchor.position, this.companionTarget, companionSpeed),
          crouched: this.companionMotion.mode === "crawl",
          jump: this.companionMotion.mode === "jump",
          mode: this.companionMotion.mode,
        },
      });
      this.playerPosition.set(snapshot.player.position.x, snapshot.player.position.y, snapshot.player.position.z);
      if (this.companionInitialized) {
        this.companionAnchor.position.set(
          snapshot.companion.position.x,
          snapshot.companion.position.y,
          snapshot.companion.position.z,
        );
        this.companionMotion.mode = snapshot.companion.mode;
      }
      this.jumpRequested = false;
    } else {
      this.playerPosition.addScaledVector(velocity, delta);
    }

    const base = new THREE.Vector3(this.playerPosition.x, this.playerPosition.y + PLAYER_EYE_HEIGHT, this.playerPosition.z);
    if (this.damageFlash > 0 && this.impactShake) {
      base.x += Math.sin(this.elapsed * 76) * this.damageFlash * 0.045;
      base.y += Math.cos(this.elapsed * 61) * this.damageFlash * 0.025;
    }
    this.perspectiveCamera.position.copy(base);
    this.perspectiveCamera.quaternion.setFromEuler(new THREE.Euler(this.pitch, this.yaw, 0, "YXZ"));
  }

  #updateCommandCamera(delta) {
    if (this.deployed && !this.uiBlocked) {
      const z = (this.keys.has("KeyS") || this.keys.has("ArrowDown") ? 1 : 0)
        - (this.keys.has("KeyW") || this.keys.has("ArrowUp") ? 1 : 0);
      const x = (this.keys.has("KeyD") || this.keys.has("ArrowRight") ? 1 : 0)
        - (this.keys.has("KeyA") || this.keys.has("ArrowLeft") ? 1 : 0);
      this.commandTarget.x += x * delta * 13 / this.commandZoom;
      this.commandTarget.z += z * delta * 13 / this.commandZoom;
      this.commandTarget.x = THREE.MathUtils.clamp(this.commandTarget.x, -SECTOR_HALF, SECTOR_HALF);
      this.commandTarget.z = THREE.MathUtils.clamp(this.commandTarget.z, -SECTOR_HALF, SECTOR_HALF);
    }
    this.commandCamera.position.set(
      this.commandTarget.x + 31,
      44,
      this.commandTarget.z + 31,
    );
    this.commandCamera.lookAt(this.commandTarget.x, 0, this.commandTarget.z);
  }

  #updateWorld(delta) {
    const warmPulse = Math.sin(this.elapsed * 0.35) * 0.12;
    this.world.key.intensity = 2.45 + warmPulse;
    this.world.shellLight.intensity = 18 + Math.sin(this.elapsed * 0.62) * 1.3;
    Object.values(this.world.warmLights).forEach((light, index) => {
      light.intensity = 2.2 + Math.sin(this.elapsed * 0.8 + index) * 0.2;
    });

    for (const record of this.entityVisuals.values()) {
      const { root, kind, observation } = record;
      const baseY = root.userData.baseY ?? root.position.y;
      if (root.userData.spin) root.userData.spin.rotation.y += delta * 1.4;
      if (["relay_component", "lumen_flora"].includes(kind)) {
        root.position.y = baseY + 0.16 + Math.sin(this.elapsed * 2.4 + root.id) * 0.1;
      }
      if (kind === "shadow_smoke") {
        root.rotation.y += delta * 0.12;
        root.children[0]?.children.forEach((sprite, index) => {
          sprite.position.y += Math.sin(this.elapsed * 1.1 + sprite.userData.phase) * delta * 0.12;
          sprite.material.opacity = (observation.health ?? 36) / 70 * 0.55 + 0.2;
          sprite.rotation += delta * (index % 2 ? 0.08 : -0.06);
        });
      }
      if (kind === "corrupted_robot") {
        const robot = root.children[0];
        robot?.userData.joints?.forEach((joint, index) => {
          joint.rotation.x = Math.sin(this.elapsed * 2.5 + index * Math.PI) * 0.2;
        });
      }
      if (kind === "lumen_turret") {
        const turret = root.children[0];
        if (turret?.userData.head) turret.userData.head.rotation.y = Math.sin(this.elapsed * 0.8 + root.id) * 1.1;
      }
    }

    if (this.companionAnchor.visible) {
      const moving = this.companionMotion.mode === "walk" || this.companionMotion.mode === "run";
      const facing = moving
        ? Math.atan2(
          this.companionTarget.x - this.companionAnchor.position.x,
          this.companionTarget.z - this.companionAnchor.position.z,
        )
        : Math.atan2(
          this.playerPosition.x - this.companionAnchor.position.x,
          this.playerPosition.z - this.companionAnchor.position.z,
        );
      if (Number.isFinite(facing)) {
        this.companionAnchor.rotation.y = THREE.MathUtils.damp(
          this.companionAnchor.rotation.y,
          facing,
          7,
          delta,
        );
      }
      if (this.companionFallback.userData.core) {
        this.companionFallback.userData.core.rotation.y += delta * 2;
      }
    }
    this.#applyAvatarIdle(this.companionMotion);
    this.vrm?.update?.(delta);
    this.damageFlash = Math.max(0, this.damageFlash - delta * 2.8);
  }

  #applyAvatarIdle(motion = { mode: "idle", interaction: "none" }) {
    if (!this.vrm || !this.avatarBones) return;
    const {
      chest,
      head,
      leftHand,
      leftLowerArm,
      leftUpperArm,
      neck,
      rightHand,
      rightLowerArm,
      rightUpperArm,
      spine,
    } = this.avatarBones;
    const breath = Math.sin(this.elapsed * 1.35);
    const sway = Math.sin(this.elapsed * 0.48);
    const stride = Math.sin(this.elapsed * (motion.mode === "run" ? 7.8 : 5.2));
    const walking = motion.mode === "walk" || motion.mode === "run";
    const interacting = motion.interaction === "active";

    // Normalized VRM 1.0 bones start in a T-pose. Rebuild this small idle pose
    // from zero each frame so the breathing layer cannot accumulate drift.
    for (const joint of Object.values(this.avatarBones)) joint?.rotation.set(0, 0, 0);
    if (leftUpperArm) {
      leftUpperArm.rotation.z = -1.18;
      leftUpperArm.rotation.x = 0.035 + sway * 0.012 + (walking ? stride * 0.14 : 0);
    }
    if (rightUpperArm) {
      rightUpperArm.rotation.z = 1.18;
      rightUpperArm.rotation.x = 0.035 - sway * 0.012 - (walking ? stride * 0.14 : 0);
    }
    if (leftLowerArm) leftLowerArm.rotation.z = -0.08;
    if (rightLowerArm) rightLowerArm.rotation.z = 0.08;
    if (leftHand) leftHand.rotation.z = 0.035 + breath * 0.012;
    if (rightHand) rightHand.rotation.z = -0.035 - breath * 0.012;
    if (spine) spine.rotation.z = sway * 0.012 + (walking ? stride * 0.018 : 0);
    if (chest) {
      chest.rotation.x = breath * 0.018 + (walking ? 0.025 : 0);
      chest.rotation.z = sway * 0.018;
    }
    if (neck) neck.rotation.y = sway * 0.035;
    if (head) {
      head.rotation.x = Math.sin(this.elapsed * 0.63) * 0.018;
      head.rotation.y = sway * 0.055;
      head.rotation.z = Math.sin(this.elapsed * 0.31) * 0.012;
    }
    if (interacting && rightLowerArm) rightLowerArm.rotation.x = -0.62;
    if (interacting && rightHand) rightHand.rotation.x = -0.34;

    const blinkPhase = this.elapsed % 4.6;
    const blink = blinkPhase > 4.38
      ? Math.sin(((blinkPhase - 4.38) / 0.22) * Math.PI)
      : 0;
    this.vrm.expressionManager?.setValue?.("blink", Math.max(0, blink));
  }

  #emitTelemetry(force = false) {
    if (!force && this.elapsed - this.lastTelemetryAt < 0.1) return;
    this.lastTelemetryAt = this.elapsed;
    const threats = this.observations.filter((item) => item.type === "entity"
      && ["shadow_smoke", "corrupted_robot"].includes(item.kind)
      && item.active !== false);
    const nearestThreat = threats.reduce((nearest, item) => Math.min(nearest, item.distance), Infinity);
    const totalVirtualMinutes = 360 + Math.floor(this.elapsed * 3);
    const minuteOfDay = totalVirtualMinutes % 1440;
    const hours = Math.floor(minuteOfDay / 60);
    const minutes = minuteOfDay % 60;
    this.#emit("telemetry", {
      vitals: this.vitals,
      materials: this.materials,
      cell: this.serverCell,
      nearestThreat,
      damageFlash: this.damageFlash,
      interaction: this.getContextAction(),
      mode: this.mode,
      cycle: {
        sol: Math.floor(totalVirtualMinutes / 1440) + 1,
        time: `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`,
      },
    });
    this.#drawMinimap();
  }

  #drawMinimap() {
    const context = this.minimapContext;
    const width = this.minimap.width;
    const height = this.minimap.height;
    const pad = 12;
    const size = width - pad * 2;
    const step = size / GRID_SIZE;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "rgba(3, 13, 13, 0.92)";
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "rgba(93, 229, 223, 0.18)";
    context.lineWidth = 1;
    context.beginPath();
    for (let index = 0; index <= GRID_SIZE; index += 1) {
      const point = pad + index * step;
      context.moveTo(point, pad);
      context.lineTo(point, pad + size);
      context.moveTo(pad, point);
      context.lineTo(pad + size, point);
    }
    context.stroke();

    const pointFor = (cell) => [pad + (cell[0] + 0.5) * step, pad + (cell[1] + 0.5) * step];
    this.observations.forEach((observation) => {
      const [x, y] = pointFor(observation.position);
      if (observation.type === "actor") {
        context.fillStyle = "#5de5df";
        context.beginPath();
        context.arc(x, y, Math.max(2.5, step * 0.32), 0, Math.PI * 2);
        context.fill();
        return;
      }
      if (["shadow_smoke", "corrupted_robot"].includes(observation.kind)) context.fillStyle = "#ff4058";
      else if (["pressure_dome", "lumen_turret", "oxygen_beacon", "power_conduit"].includes(observation.kind)) context.fillStyle = "#5de5df";
      else if (["ferrite_vein", "lumen_flora"].includes(observation.kind)) context.fillStyle = "#b7ff3c";
      else context.fillStyle = "#ffc547";
      const radius = Math.max(2, step * 0.24);
      context.fillRect(x - radius, y - radius, radius * 2, radius * 2);
    });

    const [playerX, playerY] = pointFor(this.serverCell);
    context.save();
    context.translate(playerX, playerY);
    context.rotate(-this.yaw);
    context.fillStyle = "#f2f5ef";
    context.beginPath();
    context.moveTo(0, -Math.max(4, step * 0.5));
    context.lineTo(Math.max(3, step * 0.34), Math.max(4, step * 0.5));
    context.lineTo(-Math.max(3, step * 0.34), Math.max(4, step * 0.5));
    context.closePath();
    context.fill();
    context.restore();
    context.strokeStyle = "rgba(183, 255, 60, 0.8)";
    context.strokeRect(pad + 0.5, pad + 0.5, size - 1, size - 1);
  }

  #frame() {
    const delta = Math.min(this.clock.getDelta(), 0.05);
    this.elapsed += delta;
    if (this.mode === "explore") this.#updateExplore(delta);
    else this.#updateCommandCamera(delta);
    this.#updateWorld(delta);

    this.playerMarker.position.set(this.playerPosition.x, this.playerPosition.y, this.playerPosition.z);
    this.playerMarker.rotation.y = this.yaw;
    this.playerAvatarAnchor.position.set(this.playerPosition.x, this.playerPosition.y, this.playerPosition.z);
    this.playerAvatarAnchor.rotation.y = this.yaw + Math.PI;
    this.renderer.render(this.scene, this.activeCamera);
    this.#emitTelemetry();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    const autoDpr = matchMedia("(pointer: coarse)").matches ? 1.35 : 1.75;
    const dpr = this.quality === "low" ? 1 : this.quality === "high" ? 2 : autoDpr;
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, dpr));
    this.renderer.setSize(width, height, false);
    this.perspectiveCamera.aspect = width / height;
    this.perspectiveCamera.updateProjectionMatrix();
    const halfHeight = 34;
    const halfWidth = halfHeight * width / height;
    this.commandCamera.left = -halfWidth;
    this.commandCamera.right = halfWidth;
    this.commandCamera.top = halfHeight;
    this.commandCamera.bottom = -halfHeight;
    this.commandCamera.zoom = this.commandZoom;
    this.commandCamera.updateProjectionMatrix();
  }

  async loadAvatar(url, onProgress = () => {}) {
    const selected = String(url || "").trim();
    if (!selected) throw new Error("A VRM URL is required.");
    const loader = new GLTFLoader();
    loader.crossOrigin = "anonymous";
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await new Promise((resolve, reject) => {
      loader.load(selected, resolve, (event) => {
        onProgress(event.total ? event.loaded / event.total : 0);
      }, reject);
    });
    const extensions = gltf.parser?.json?.extensionsUsed || [];
    if (!extensions.includes("VRMC_vrm")) {
      disposeObject(gltf.scene);
      throw new Error("Configured avatar is not a native VRM 1.0 asset.");
    }
    const vrm = gltf.userData.vrm;
    if (!vrm?.scene) {
      disposeObject(gltf.scene);
      throw new Error("VRM 1.0 loader returned no avatar scene.");
    }

    this.clearAvatar();
    this.vrm = vrm;
    this.vrmScene = vrm.scene;
    const bone = (name) => vrm.humanoid?.getNormalizedBoneNode?.(name) || null;
    this.avatarBones = {
      chest: bone("chest") || bone("upperChest"),
      head: bone("head"),
      leftHand: bone("leftHand"),
      leftLowerArm: bone("leftLowerArm"),
      leftUpperArm: bone("leftUpperArm"),
      neck: bone("neck"),
      rightHand: bone("rightHand"),
      rightLowerArm: bone("rightLowerArm"),
      rightUpperArm: bone("rightUpperArm"),
      spine: bone("spine"),
    };
    this.vrmScene.traverse((object) => {
      if (object.isMesh) {
        object.castShadow = true;
        object.receiveShadow = true;
        object.frustumCulled = false;
      }
    });
    this.avatarModelRoot.add(this.vrmScene);
    const bounds = new THREE.Box3().setFromObject(this.vrmScene);
    const size = bounds.getSize(new THREE.Vector3());
    const scale = size.y > 0.1 ? 1.7 / size.y : 1;
    this.vrmScene.scale.setScalar(scale);
    const scaledBounds = new THREE.Box3().setFromObject(this.vrmScene);
    this.vrmScene.position.y -= scaledBounds.min.y;
    this.companionFallback.visible = false;
    onProgress(1);
    return vrm;
  }

  async loadPlayerAvatar(url = "/api/account/avatar/model", onProgress = () => {}) {
    const loader = new GLTFLoader();
    loader.crossOrigin = "use-credentials";
    loader.setWithCredentials(true);
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await new Promise((resolve, reject) => {
      loader.load(url, resolve, (event) => {
        onProgress(event.total ? event.loaded / event.total : 0);
      }, reject);
    });
    const extensions = gltf.parser?.json?.extensionsUsed || [];
    if (!extensions.includes("VRMC_vrm")) {
      disposeObject(gltf.scene);
      throw new Error("Player avatar is not a native VRM 1.0 asset.");
    }
    const vrm = gltf.userData.vrm;
    if (!vrm?.scene) {
      disposeObject(gltf.scene);
      throw new Error("Player VRM loader returned no avatar scene.");
    }

    this.clearPlayerAvatar();
    this.playerVrm = vrm;
    this.playerVrmScene = vrm.scene;
    this.playerVrmScene.traverse((object) => {
      if (object.isMesh) {
        object.castShadow = true;
        object.receiveShadow = true;
        object.frustumCulled = false;
      }
    });
    this.playerAvatarModelRoot.add(this.playerVrmScene);
    const bounds = new THREE.Box3().setFromObject(this.playerVrmScene);
    const size = bounds.getSize(new THREE.Vector3());
    const scale = size.y > 0.1 ? 1.72 / size.y : 1;
    this.playerVrmScene.scale.setScalar(scale);
    const scaledBounds = new THREE.Box3().setFromObject(this.playerVrmScene);
    this.playerVrmScene.position.y -= scaledBounds.min.y;
    this.playerMarker.visible = false;
    this.playerAvatarAnchor.visible = this.mode === "command";
    onProgress(1);
    return vrm;
  }

  clearPlayerAvatar() {
    if (this.playerVrmScene) {
      this.playerAvatarModelRoot.remove(this.playerVrmScene);
      disposeObject(this.playerVrmScene);
    }
    this.playerVrm = null;
    this.playerVrmScene = null;
    this.playerAvatarAnchor.visible = false;
    this.playerMarker.visible = this.mode === "command";
  }

  clearAvatar() {
    if (this.vrmScene) {
      this.avatarModelRoot.remove(this.vrmScene);
      disposeObject(this.vrmScene);
    }
    this.vrm = null;
    this.vrmScene = null;
    this.avatarBones = null;
    this.companionFallback.visible = true;
  }

  resetLocalSimulation() {
    this.damageFlash = 0;
    this.commandZoom = 1;
    this.commandCamera.zoom = 1;
    this.commandCamera.updateProjectionMatrix();
    this.setBuildTool(null);
    this.#emit("notice", { message: "LOCAL RENDER STATE RESET", tone: "info" });
  }

  getDebugState() {
    return {
      deployed: this.deployed,
      mode: this.mode,
      serverCell: [...this.serverCell],
      pendingCell: this.pendingCell ? [...this.pendingCell] : null,
      observedEntities: [...this.entityVisuals.keys()],
      vitals: { ...this.vitals },
      materials: { ...this.materials },
      renderSize: [this.canvas.width, this.canvas.height],
      frame: Math.floor(this.elapsed * 60),
      vrmLoaded: Boolean(this.vrm),
      playerVrmLoaded: Boolean(this.playerVrm),
    };
  }
}

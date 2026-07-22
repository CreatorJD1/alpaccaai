import RAPIER from "@dimforge/rapier3d-compat";

const FIXED_STEP = 1 / 60;
const MAX_SUBSTEPS = 3;
const GRAVITY = 18;

function vector(x = 0, y = 0, z = 0) {
  return { x, y, z };
}

function distance2d(left, right) {
  return Math.hypot(left.x - right.x, left.z - right.z);
}

export class DomePhysics {
  static async create({ colliders, playerPosition, companionPosition }) {
    await RAPIER.init({});
    return new DomePhysics({ colliders, playerPosition, companionPosition });
  }

  constructor({ colliders, playerPosition, companionPosition }) {
    this.world = new RAPIER.World(vector(0, -GRAVITY, 0));
    this.accumulator = 0;
    this.staticBodies = [];
    (colliders || []).forEach((descriptor) => this.#addStaticCollider(descriptor));
    this.player = this.#createCharacter(playerPosition, {
      halfHeight: 0.56,
      radius: 0.32,
      crawlHalfHeight: 0.26,
    });
    this.companion = this.#createCharacter(companionPosition, {
      halfHeight: 0.52,
      radius: 0.3,
      crawlHalfHeight: 0.32,
    });
  }

  dispose() {
    this.player?.controller?.free?.();
    this.companion?.controller?.free?.();
    this.world?.free?.();
    this.world = null;
  }

  syncPlayer(position, crouched = false) {
    this.#syncCharacter(this.player, position, crouched);
  }

  syncCompanion(position) {
    this.#syncCharacter(this.companion, position, false);
  }

  step(delta, { player, companion }) {
    if (!this.world) return this.snapshot();
    this.accumulator = Math.min(this.accumulator + Math.max(0, delta), FIXED_STEP * MAX_SUBSTEPS);
    let substeps = 0;
    while (this.accumulator >= FIXED_STEP && substeps < MAX_SUBSTEPS) {
      this.#moveCharacter(this.player, player, FIXED_STEP);
      this.#moveCharacter(this.companion, companion, FIXED_STEP);
      this.world.timestep = FIXED_STEP;
      this.world.step();
      this.accumulator -= FIXED_STEP;
      substeps += 1;
    }
    return this.snapshot();
  }

  snapshot() {
    return {
      player: this.#characterState(this.player),
      companion: this.#characterState(this.companion),
    };
  }

  #addStaticCollider({ name, center, half }) {
    const body = this.world.createRigidBody(
      RAPIER.RigidBodyDesc.fixed().setTranslation(center[0], center[1], center[2]),
    );
    const collider = this.world.createCollider(
      RAPIER.ColliderDesc.cuboid(half[0], half[1], half[2]).setFriction(0.95),
      body,
    );
    this.staticBodies.push({ name, body, collider });
  }

  #createCharacter(position, { halfHeight, radius, crawlHalfHeight }) {
    const body = this.world.createRigidBody(
      RAPIER.RigidBodyDesc.kinematicPositionBased()
        .setTranslation(position.x, halfHeight + radius, position.z),
    );
    const collider = this.world.createCollider(
      RAPIER.ColliderDesc.capsule(halfHeight, radius)
        .setFriction(0.9)
        .setRestitution(0),
      body,
    );
    const controller = this.world.createCharacterController(0.035);
    controller.setSlideEnabled(true);
    controller.enableAutostep(0.32, 0.2, false);
    controller.enableSnapToGround(0.22);
    controller.setMaxSlopeClimbAngle(Math.PI / 4.5);
    controller.setMinSlopeSlideAngle(Math.PI / 3.2);
    controller.setApplyImpulsesToDynamicBodies(true);
    return {
      body,
      collider,
      controller,
      halfHeight,
      crawlHalfHeight,
      radius,
      crouched: false,
      grounded: true,
      verticalVelocity: 0,
      speed: 0,
      mode: "idle",
    };
  }

  #syncCharacter(character, position, crouched) {
    if (!character) return;
    this.#setCrouched(character, Boolean(crouched));
    const halfHeight = character.crouched ? character.crawlHalfHeight : character.halfHeight;
    const translation = vector(position.x, halfHeight + character.radius, position.z);
    character.body.setTranslation(translation, true);
    character.body.setNextKinematicTranslation(translation);
    character.verticalVelocity = 0;
    character.grounded = true;
  }

  #setCrouched(character, crouched) {
    if (character.crouched === crouched) return;
    const previousHeight = (character.crouched ? character.crawlHalfHeight : character.halfHeight) + character.radius;
    const nextHalfHeight = crouched ? character.crawlHalfHeight : character.halfHeight;
    const nextHeight = nextHalfHeight + character.radius;
    const translation = character.body.translation();
    translation.y += nextHeight - previousHeight;
    character.collider.setHalfHeight(nextHalfHeight);
    character.body.setTranslation(translation, true);
    character.body.setNextKinematicTranslation(translation);
    character.crouched = crouched;
  }

  #moveCharacter(character, command = {}, dt) {
    if (!character) return;
    const requestedMode = command.mode || "idle";
    this.#setCrouched(character, Boolean(command.crouched));
    const velocity = command.velocity || vector();
    const jump = Boolean(command.jump);
    if (jump && character.grounded && !character.crouched) {
      character.verticalVelocity = 6.35;
      character.grounded = false;
    }
    character.verticalVelocity = Math.max(-18, character.verticalVelocity - GRAVITY * dt);
    const current = character.body.translation();
    const requested = vector(velocity.x * dt, character.verticalVelocity * dt, velocity.z * dt);
    character.controller.computeColliderMovement(character.collider, requested);
    const resolved = character.controller.computedMovement();
    character.body.setNextKinematicTranslation(vector(
      current.x + resolved.x,
      current.y + resolved.y,
      current.z + resolved.z,
    ));
    character.grounded = character.controller.computedGrounded();
    if (character.grounded && character.verticalVelocity < 0) character.verticalVelocity = 0;
    character.speed = Math.hypot(resolved.x, resolved.z) / dt;
    character.mode = character.crouched
      ? (character.speed > 0.06 ? "crawl" : "crouch")
      : (character.speed > 5.0 ? "run" : character.speed > 0.06 ? "walk" : requestedMode);
  }

  #characterState(character) {
    if (!character) return { position: vector(), grounded: false, speed: 0, mode: "idle" };
    const position = character.body.translation();
    return {
      position: vector(position.x, position.y - (character.crouched ? character.crawlHalfHeight : character.halfHeight) - character.radius, position.z),
      grounded: character.grounded,
      speed: character.speed,
      mode: character.mode,
      crouched: character.crouched,
    };
  }
}

export function companionVelocity(current, destination, speed) {
  const distance = distance2d(current, destination);
  if (distance < 0.035) return vector();
  return vector(
    ((destination.x - current.x) / distance) * speed,
    0,
    ((destination.z - current.z) / distance) * speed,
  );
}

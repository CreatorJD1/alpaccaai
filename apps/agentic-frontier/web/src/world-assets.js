import * as THREE from "three";

export const GRID_SIZE = 18;
export const CELL_SIZE = 3.2;
export const SECTOR_SIZE = GRID_SIZE * CELL_SIZE;
export const SECTOR_HALF = SECTOR_SIZE / 2;

const outlineMaterial = new THREE.MeshBasicMaterial({
  color: 0x030405,
  side: THREE.BackSide,
  toneMapped: false,
});

export function seededRandom(seed = 0x5eeda11) {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

export function terrainHeight(x, z) {
  // The game slice now takes place inside Vesper Dome. Keep this authoritative
  // visual ground plane flat so physics, avatars, and server tiles agree.
  void x;
  void z;
  return 0;
}

export function cellCenter(cell) {
  return new THREE.Vector3(
    -SECTOR_HALF + cell[0] * CELL_SIZE + CELL_SIZE / 2,
    0,
    -SECTOR_HALF + cell[1] * CELL_SIZE + CELL_SIZE / 2,
  );
}

export function worldCell(x, z) {
  return [
    THREE.MathUtils.clamp(Math.floor((x + SECTOR_HALF) / CELL_SIZE), 0, GRID_SIZE - 1),
    THREE.MathUtils.clamp(Math.floor((z + SECTOR_HALF) / CELL_SIZE), 0, GRID_SIZE - 1),
  ];
}

export function sameCell(left, right) {
  return Boolean(left && right && left[0] === right[0] && left[1] === right[1]);
}

export function cellDistance(left, right) {
  return Math.abs(left[0] - right[0]) + Math.abs(left[1] - right[1]);
}

export function createToonRamp() {
  const ramp = new THREE.DataTexture(
    new Uint8Array([28, 82, 158, 255]),
    4,
    1,
    THREE.RedFormat,
  );
  ramp.minFilter = THREE.NearestFilter;
  ramp.magFilter = THREE.NearestFilter;
  ramp.generateMipmaps = false;
  ramp.needsUpdate = true;
  return ramp;
}

export function toonMaterial(color, ramp, options = {}) {
  return new THREE.MeshToonMaterial({
    color,
    gradientMap: ramp,
    emissive: options.emissive ?? 0x000000,
    emissiveIntensity: options.emissiveIntensity ?? 0,
    transparent: options.transparent ?? false,
    opacity: options.opacity ?? 1,
    side: options.side ?? THREE.FrontSide,
  });
}

export function outlinedMesh(geometry, material, scale = 1.045) {
  const group = new THREE.Group();
  const outline = new THREE.Mesh(geometry, outlineMaterial);
  outline.scale.setScalar(scale);
  outline.castShadow = false;
  outline.receiveShadow = false;
  const surface = new THREE.Mesh(geometry, material);
  surface.castShadow = true;
  surface.receiveShadow = true;
  group.add(outline, surface);
  group.userData.surface = surface;
  return group;
}

function createSky() {
  const geometry = new THREE.SphereGeometry(135, 32, 18);
  const material = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: {
      lowColor: { value: new THREE.Color(0x180b0a) },
      midColor: { value: new THREE.Color(0x6a2616) },
      highColor: { value: new THREE.Color(0x17151b) },
    },
    vertexShader: `
      varying vec3 vPosition;
      void main() {
        vPosition = position;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform vec3 lowColor;
      uniform vec3 midColor;
      uniform vec3 highColor;
      varying vec3 vPosition;
      void main() {
        float horizon = normalize(vPosition).y * 0.5 + 0.5;
        vec3 lower = mix(lowColor, midColor, smoothstep(0.16, 0.52, horizon));
        vec3 color = mix(lower, highColor, smoothstep(0.53, 0.88, horizon));
        float bands = step(0.54, fract(horizon * 8.0)) * 0.025;
        gl_FragColor = vec4(color + bands, 1.0);
      }
    `,
  });
  return new THREE.Mesh(geometry, material);
}

function createTerrain(ramp, random) {
  const geometry = new THREE.PlaneGeometry(96, 96, 64, 64);
  geometry.rotateX(-Math.PI / 2);
  const positions = geometry.attributes.position;
  const colors = [];
  const low = new THREE.Color(0x100f13);
  const high = new THREE.Color(0x2d282d);
  const color = new THREE.Color();
  for (let index = 0; index < positions.count; index += 1) {
    const x = positions.getX(index);
    const z = positions.getZ(index);
    const height = terrainHeight(x, z) + (random() - 0.5) * 0.09;
    positions.setY(index, height);
    color.copy(low).lerp(high, THREE.MathUtils.clamp((height + 1.6) / 3, 0, 1));
    colors.push(color.r, color.g, color.b);
  }
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  const material = toonMaterial(0xffffff, ramp);
  material.vertexColors = true;
  const mesh = new THREE.Mesh(geometry, material);
  mesh.receiveShadow = true;
  mesh.userData.kind = "terrain";
  return mesh;
}

function createMagmaSeams(scene, random) {
  const group = new THREE.Group();
  const paths = [
    [[-44, -26], [-24, -19], [-8, -23], [8, -10], [25, -6], [45, 4]],
    [[-39, 27], [-20, 18], [-4, 23], [12, 16], [23, 27], [42, 21]],
    [[-31, -44], [-24, -23], [-27, -4], [-13, 8], [-6, 32], [2, 47]],
    [[16, -47], [10, -31], [17, -16], [9, -2], [18, 13], [14, 45]],
  ];
  const material = new THREE.MeshBasicMaterial({ color: 0xff5a1f, toneMapped: false });
  const haloMaterial = new THREE.MeshBasicMaterial({
    color: 0x7d1609,
    transparent: true,
    opacity: 0.82,
    toneMapped: false,
  });
  paths.forEach((path, pathIndex) => {
    const points = path.map(([x, z]) => new THREE.Vector3(
      x + (random() - 0.5) * 2,
      terrainHeight(x, z) + 0.08,
      z + (random() - 0.5) * 2,
    ));
    const curve = new THREE.CatmullRomCurve3(points);
    const halo = new THREE.Mesh(new THREE.TubeGeometry(curve, 52, 0.33, 6, false), haloMaterial);
    const core = new THREE.Mesh(new THREE.TubeGeometry(curve, 52, 0.11, 5, false), material);
    halo.userData.phase = pathIndex * 0.8;
    group.add(halo, core);
  });
  scene.add(group);
  return group;
}

function createPools(scene, ramp) {
  const group = new THREE.Group();
  const poolMaterial = toonMaterial(0x7fff2f, ramp, {
    emissive: 0x3c7c13,
    emissiveIntensity: 1.1,
    transparent: true,
    opacity: 0.82,
    side: THREE.DoubleSide,
  });
  [[-33, 11, 3.8], [31, -17, 4.6], [-10, 35, 2.9], [37, 31, 3.4]].forEach(([x, z, radius], index) => {
    const pool = new THREE.Mesh(new THREE.CircleGeometry(radius, 24), poolMaterial.clone());
    pool.rotation.x = -Math.PI / 2;
    pool.rotation.z = index * 0.7;
    pool.scale.y = 0.55;
    pool.position.set(x, terrainHeight(x, z) + 0.09, z);
    pool.userData.phase = index * 1.6;
    group.add(pool);
  });
  scene.add(group);
  return group;
}

function createObsidian(scene, ramp, random) {
  const group = new THREE.Group();
  const rockMaterial = toonMaterial(0x24232b, ramp, { emissive: 0x09070b, emissiveIntensity: 0.3 });
  const geometry = new THREE.OctahedronGeometry(1, 0);
  for (let index = 0; index < 52; index += 1) {
    const x = random() * 88 - 44;
    const z = random() * 88 - 44;
    if (Math.abs(x) < 3 && Math.abs(z) < 3) continue;
    const mesh = new THREE.Mesh(geometry, rockMaterial);
    mesh.position.set(x, terrainHeight(x, z) + 0.7, z);
    const scale = 0.35 + random() * 1.45;
    mesh.scale.set(scale * (0.6 + random()), scale * (1.1 + random() * 1.7), scale * (0.55 + random()));
    mesh.rotation.set(random() * 0.5, random() * Math.PI, random() * 0.35);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  scene.add(group);
  return group;
}

function createFloraCluster(ramp, color, scale = 1) {
  const group = new THREE.Group();
  const stemMaterial = toonMaterial(0x243025, ramp);
  const glowMaterial = toonMaterial(color, ramp, {
    emissive: color,
    emissiveIntensity: 1.25,
  });
  const stem = outlinedMesh(new THREE.CylinderGeometry(0.12, 0.24, 1.75, 6), stemMaterial, 1.07);
  stem.position.y = 0.88;
  const crown = outlinedMesh(new THREE.ConeGeometry(0.72, 1.25, 7), glowMaterial, 1.07);
  crown.position.y = 1.95;
  crown.rotation.z = Math.PI;
  const bulb = outlinedMesh(new THREE.IcosahedronGeometry(0.34, 0), glowMaterial, 1.08);
  bulb.position.y = 2.48;
  group.add(stem, crown, bulb);
  group.scale.setScalar(scale);
  group.userData.glowMaterial = glowMaterial;
  return group;
}

function createFlora(scene, ramp, random) {
  const group = new THREE.Group();
  const colors = [0xb7ff3c, 0xff59bf, 0x54e8df];
  for (let index = 0; index < 24; index += 1) {
    const x = random() * 82 - 41;
    const z = random() * 82 - 41;
    const cluster = createFloraCluster(ramp, colors[index % colors.length], 0.52 + random() * 0.8);
    cluster.position.set(x, terrainHeight(x, z), z);
    cluster.rotation.y = random() * Math.PI * 2;
    cluster.userData.phase = random() * Math.PI * 2;
    group.add(cluster);
  }
  scene.add(group);
  return group;
}

function createSectorGrid(scene) {
  const group = new THREE.Group();
  const grid = new THREE.GridHelper(SECTOR_SIZE, GRID_SIZE, 0xb7ff3c, 0x5de5df);
  grid.material.transparent = true;
  grid.material.opacity = 0.62;
  grid.position.y = 0.35;
  group.add(grid);

  const boundaryPoints = [
    new THREE.Vector3(-SECTOR_HALF, 0.38, -SECTOR_HALF),
    new THREE.Vector3(SECTOR_HALF, 0.38, -SECTOR_HALF),
    new THREE.Vector3(SECTOR_HALF, 0.38, SECTOR_HALF),
    new THREE.Vector3(-SECTOR_HALF, 0.38, SECTOR_HALF),
    new THREE.Vector3(-SECTOR_HALF, 0.38, -SECTOR_HALF),
  ];
  const boundary = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(boundaryPoints),
    new THREE.LineBasicMaterial({ color: 0xb7ff3c, transparent: true, opacity: 0.92 }),
  );
  group.add(boundary);

  const hover = new THREE.Mesh(
    new THREE.PlaneGeometry(CELL_SIZE - 0.35, CELL_SIZE - 0.35),
    new THREE.MeshBasicMaterial({ color: 0xb7ff3c, transparent: true, opacity: 0.2, side: THREE.DoubleSide }),
  );
  hover.rotation.x = -Math.PI / 2;
  hover.position.y = 0.4;
  hover.visible = false;
  group.add(hover);
  group.visible = false;
  scene.add(group);
  return { group, grid, hover };
}

function createRain(scene, random, count = 560) {
  const positions = new Float32Array(count * 2 * 3);
  const speed = new Float32Array(count);
  for (let index = 0; index < count; index += 1) {
    const offset = index * 6;
    const x = random() * 92 - 46;
    const y = random() * 42 + 4;
    const z = random() * 92 - 46;
    positions[offset] = x;
    positions[offset + 1] = y;
    positions[offset + 2] = z;
    positions[offset + 3] = x + 0.38;
    positions[offset + 4] = y - 1.7;
    positions[offset + 5] = z + 0.16;
    speed[index] = 16 + random() * 13;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const material = new THREE.LineBasicMaterial({
    color: 0xb9ff72,
    transparent: true,
    opacity: 0.34,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const lines = new THREE.LineSegments(geometry, material);
  lines.frustumCulled = false;
  scene.add(lines);
  return { lines, geometry, speed, count };
}

function createSmokeTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(32, 32, 3, 32, 32, 31);
  gradient.addColorStop(0, "rgba(15, 23, 25, 0.95)");
  gradient.addColorStop(0.48, "rgba(5, 11, 13, 0.72)");
  gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 64, 64);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function createSmokeThreat() {
  const random = seededRandom(0x5ade51);
  const texture = createSmokeTexture();
  const group = new THREE.Group();
  for (let index = 0; index < 18; index += 1) {
    const material = new THREE.SpriteMaterial({
      map: texture,
      color: index % 4 === 0 ? 0x22685e : 0x050609,
      transparent: true,
      opacity: 0.38 + random() * 0.36,
      depthWrite: false,
    });
    const sprite = new THREE.Sprite(material);
    sprite.position.set((random() - 0.5) * 2.8, random() * 2.6, (random() - 0.5) * 2.8);
    const scale = 1.4 + random() * 2.4;
    sprite.scale.set(scale, scale, scale);
    sprite.userData.phase = random() * Math.PI * 2;
    group.add(sprite);
  }
  group.userData.phase = random() * Math.PI * 2;
  return group;
}

export function createRobot(ramp, index = 0) {
  const group = new THREE.Group();
  const armor = toonMaterial(index % 2 ? 0x46504d : 0x59605c, ramp);
  const dark = toonMaterial(0x15191c, ramp);
  const corruption = toonMaterial(0xff334f, ramp, { emissive: 0xff1737, emissiveIntensity: 1.35 });

  const pelvis = outlinedMesh(new THREE.BoxGeometry(0.9, 0.5, 0.55), dark);
  pelvis.position.y = 1.2;
  const torso = outlinedMesh(new THREE.BoxGeometry(1.15, 1.05, 0.65), armor);
  torso.position.y = 1.95;
  const head = outlinedMesh(new THREE.BoxGeometry(0.7, 0.55, 0.6), armor);
  head.position.y = 2.85;
  const eye = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.09, 0.06), corruption);
  eye.position.set(0, 2.88, 0.33);
  group.add(pelvis, torso, head, eye);

  const joints = [];
  [-1, 1].forEach((side) => {
    const armPivot = new THREE.Group();
    armPivot.position.set(side * 0.76, 2.26, 0);
    const arm = outlinedMesh(new THREE.BoxGeometry(0.28, 1.12, 0.32), armor);
    arm.position.y = -0.5;
    armPivot.add(arm);
    group.add(armPivot);

    const legPivot = new THREE.Group();
    legPivot.position.set(side * 0.34, 1.1, 0);
    const leg = outlinedMesh(new THREE.BoxGeometry(0.34, 1.28, 0.42), dark);
    leg.position.y = -0.56;
    const foot = outlinedMesh(new THREE.BoxGeometry(0.46, 0.25, 0.76), armor);
    foot.position.set(0, -1.15, 0.18);
    legPivot.add(leg, foot);
    group.add(legPivot);
    joints.push(armPivot, legPivot);
  });
  group.userData.joints = joints;
  group.userData.hp = 100;
  group.userData.active = true;
  group.userData.respawn = 0;
  group.userData.phase = index * 1.9;
  group.userData.eyeMaterial = corruption;
  return group;
}

function createRobots(scene, ramp) {
  const starts = [[17, -15], [-19, 8], [20, 21], [-31, -24]];
  return starts.map(([x, z], index) => {
    const robot = createRobot(ramp, index);
    robot.position.set(x, terrainHeight(x, z), z);
    robot.userData.base = new THREE.Vector3(x, 0, z);
    scene.add(robot);
    return robot;
  });
}

export function createHologramCompanion(ramp) {
  const group = new THREE.Group();
  const bodyMaterial = toonMaterial(0x162728, ramp, {
    emissive: 0x1a7771,
    emissiveIntensity: 0.55,
    transparent: true,
    opacity: 0.9,
  });
  const signalMaterial = toonMaterial(0x5de5df, ramp, {
    emissive: 0x5de5df,
    emissiveIntensity: 1.6,
  });
  const torso = outlinedMesh(new THREE.CapsuleGeometry(0.35, 0.66, 5, 8), bodyMaterial);
  torso.position.y = 1.22;
  const head = outlinedMesh(new THREE.SphereGeometry(0.34, 12, 8), bodyMaterial);
  head.position.y = 2.05;
  const visor = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.08, 0.05), signalMaterial);
  visor.position.set(0, 2.07, 0.31);
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.11, 0), signalMaterial);
  core.position.set(0, 1.37, 0.36);
  group.add(torso, head, visor, core);
  [-1, 1].forEach((side) => {
    const arm = outlinedMesh(new THREE.CapsuleGeometry(0.1, 0.68, 4, 6), bodyMaterial);
    arm.position.set(side * 0.48, 1.27, 0);
    arm.rotation.z = side * -0.12;
    const leg = outlinedMesh(new THREE.CapsuleGeometry(0.12, 0.76, 4, 6), bodyMaterial);
    leg.position.set(side * 0.2, 0.43, 0);
    group.add(arm, leg);
  });
  group.userData.core = core;
  return group;
}

export function createEntityVisual(kind, ramp) {
  const root = new THREE.Group();
  if (kind === "relay_component") {
    const frameMaterial = toonMaterial(0x48545a, ramp);
    const coreMaterial = toonMaterial(0xffc547, ramp, { emissive: 0xff8b19, emissiveIntensity: 1.4 });
    const frame = outlinedMesh(new THREE.OctahedronGeometry(0.55, 0), frameMaterial, 1.08);
    const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.28, 0), coreMaterial);
    root.add(frame, core);
    root.userData.spin = core;
  } else if (kind === "damaged_relay") {
    const metal = toonMaterial(0x364147, ramp);
    const damage = toonMaterial(0xff5c28, ramp, { emissive: 0xff3817, emissiveIntensity: 1.2 });
    const base = outlinedMesh(new THREE.CylinderGeometry(1.5, 1.9, 0.65, 8), metal);
    base.position.y = 0.32;
    const mast = outlinedMesh(new THREE.CylinderGeometry(0.32, 0.55, 3.2, 8), metal);
    mast.position.y = 2;
    mast.rotation.z = 0.18;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.9, 0.12, 6, 16), damage);
    ring.position.y = 3.45;
    ring.rotation.x = Math.PI / 2;
    root.add(base, mast, ring);
    root.userData.spin = ring;
  } else if (kind === "command_terminal") {
    const frame = toonMaterial(0x3e4a4d, ramp);
    const screen = toonMaterial(0xb7ff3c, ramp, { emissive: 0x81c620, emissiveIntensity: 1.5 });
    const base = outlinedMesh(new THREE.CylinderGeometry(0.58, 0.78, 0.42, 8), frame);
    base.position.y = 0.21;
    const consoleBody = outlinedMesh(new THREE.BoxGeometry(1.05, 1.18, 0.58), frame);
    consoleBody.position.set(0, 0.94, 0);
    consoleBody.rotation.x = -0.16;
    const display = new THREE.Mesh(new THREE.PlaneGeometry(0.72, 0.43), screen);
    display.position.set(0, 1.07, 0.305);
    display.rotation.x = -0.16;
    root.add(base, consoleBody, display);
    root.userData.spin = display;
  } else if (kind === "ferrite_vein") {
    const shardMaterial = toonMaterial(0x899494, ramp, { emissive: 0x253638, emissiveIntensity: 0.35 });
    for (let index = 0; index < 5; index += 1) {
      const shard = outlinedMesh(new THREE.OctahedronGeometry(0.25 + index * 0.035, 0), shardMaterial, 1.07);
      shard.position.set((index - 2) * 0.28, 0.35 + (index % 2) * 0.24, (index % 3 - 1) * 0.2);
      shard.scale.y = 1.4 + index * 0.18;
      shard.rotation.z = (index - 2) * 0.14;
      root.add(shard);
    }
  } else if (kind === "lumen_flora") {
    root.add(createFloraCluster(ramp, 0xb7ff3c, 0.78));
  } else if (kind === "shadow_smoke") {
    root.add(createSmokeThreat());
  } else if (kind === "corrupted_robot") {
    root.add(createRobot(ramp, 1));
  } else if (kind === "pressure_dome") {
    root.add(createDome(ramp));
  } else if (kind === "lumen_turret") {
    root.add(createTurret(ramp));
  } else if (kind === "oxygen_beacon") {
    const frame = toonMaterial(0x46575b, ramp);
    const glow = toonMaterial(0x5de5df, ramp, { emissive: 0x5de5df, emissiveIntensity: 1.6 });
    const mast = outlinedMesh(new THREE.CylinderGeometry(0.18, 0.42, 2.2, 8), frame);
    mast.position.y = 1.1;
    const emitter = new THREE.Mesh(new THREE.TorusGeometry(0.48, 0.09, 6, 18), glow);
    emitter.position.y = 2.05;
    emitter.rotation.x = Math.PI / 2;
    root.add(mast, emitter);
    root.userData.spin = emitter;
  } else if (kind === "power_conduit") {
    const frame = toonMaterial(0x313b3f, ramp);
    const glow = toonMaterial(0xffc547, ramp, { emissive: 0xff9e20, emissiveIntensity: 1.5 });
    const rail = outlinedMesh(new THREE.BoxGeometry(2.15, 0.28, 0.7), frame);
    rail.position.y = 0.24;
    const core = new THREE.Mesh(new THREE.BoxGeometry(1.55, 0.08, 0.76), glow);
    core.position.y = 0.42;
    root.add(rail, core);
  }
  root.userData.kind = kind;
  return root;
}

export function createDome(ramp) {
  const root = new THREE.Group();
  const shellMaterial = toonMaterial(0x61eee1, ramp, {
    emissive: 0x166c65,
    emissiveIntensity: 0.85,
    transparent: true,
    opacity: 0.38,
    side: THREE.DoubleSide,
  });
  shellMaterial.depthWrite = false;
  const shell = new THREE.Mesh(new THREE.SphereGeometry(4.15, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), shellMaterial);
  const ringMaterial = toonMaterial(0xc8f7ef, ramp, { emissive: 0x5de5df, emissiveIntensity: 1.2 });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(4.1, 0.13, 6, 32), ringMaterial);
  ring.rotation.x = Math.PI / 2;
  const core = outlinedMesh(new THREE.CylinderGeometry(0.6, 0.9, 1.1, 8), toonMaterial(0x445154, ramp));
  core.position.y = 0.55;
  root.add(shell, ring, core);
  root.userData.shell = shell;
  return root;
}

export function createTurret(ramp) {
  const root = new THREE.Group();
  const armor = toonMaterial(0x596468, ramp);
  const dark = toonMaterial(0x1b2022, ramp);
  const glow = toonMaterial(0xb7ff3c, ramp, { emissive: 0x8dd727, emissiveIntensity: 1.5 });
  const base = outlinedMesh(new THREE.CylinderGeometry(1.18, 1.45, 0.55, 8), dark);
  base.position.y = 0.28;
  const column = outlinedMesh(new THREE.CylinderGeometry(0.48, 0.7, 1.45, 8), armor);
  column.position.y = 1.1;
  const head = new THREE.Group();
  head.position.y = 1.95;
  const housing = outlinedMesh(new THREE.BoxGeometry(1.4, 0.72, 1.05), armor);
  const barrel = outlinedMesh(new THREE.CylinderGeometry(0.11, 0.16, 2.35, 7), dark);
  barrel.rotation.x = Math.PI / 2;
  barrel.position.z = 1.42;
  const sight = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.1, 0.08), glow);
  sight.position.set(0, 0.18, 0.56);
  head.add(housing, barrel, sight);
  root.add(base, column, head);
  root.userData.head = head;
  root.userData.cooldown = 0;
  return root;
}

function createHabitatFloor(ramp) {
  const floor = new THREE.Group();
  const deck = new THREE.Mesh(
    new THREE.CylinderGeometry(28.6, 28.6, 0.24, 80),
    toonMaterial(0x24343a, ramp, { emissive: 0x071116, emissiveIntensity: 0.7 }),
  );
  deck.position.y = -0.12;
  deck.receiveShadow = true;
  floor.add(deck);

  const inner = new THREE.Mesh(
    new THREE.CircleGeometry(25.6, 80),
    toonMaterial(0x334b4d, ramp, { emissive: 0x102124, emissiveIntensity: 0.45 }),
  );
  inner.rotation.x = -Math.PI / 2;
  inner.position.y = 0.012;
  inner.receiveShadow = true;
  floor.add(inner);

  const gridMaterial = new THREE.LineBasicMaterial({ color: 0x70e4d1, transparent: true, opacity: 0.16 });
  const grid = new THREE.GridHelper(48, 24, 0x70e4d1, 0x70e4d1);
  grid.material = gridMaterial;
  grid.position.y = 0.022;
  floor.add(grid);

  const rug = new THREE.Mesh(
    new THREE.CircleGeometry(6.1, 48),
    toonMaterial(0x6a3f55, ramp, { emissive: 0x2a1020, emissiveIntensity: 0.5 }),
  );
  rug.rotation.x = -Math.PI / 2;
  rug.position.set(-7.4, 0.035, -5.4);
  floor.add(rug);
  return floor;
}

function createDomeFrame(ramp) {
  const root = new THREE.Group();
  const exterior = new THREE.Mesh(
    new THREE.SphereGeometry(30, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2),
    new THREE.MeshBasicMaterial({
      color: 0x132332,
      side: THREE.BackSide,
      transparent: true,
      opacity: 0.73,
      depthWrite: false,
    }),
  );
  exterior.renderOrder = -2;
  root.add(exterior);

  const lattice = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.SphereGeometry(29.9, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2)),
    new THREE.LineBasicMaterial({ color: 0x7ee6d5, transparent: true, opacity: 0.26 }),
  );
  root.add(lattice);
  const lowerRing = new THREE.Mesh(
    new THREE.TorusGeometry(29.9, 0.22, 7, 96),
    toonMaterial(0x7ee6d5, ramp, { emissive: 0x4dbeb4, emissiveIntensity: 1.1 }),
  );
  lowerRing.rotation.x = Math.PI / 2;
  root.add(lowerRing);

  const lanternMaterial = toonMaterial(0xffcb85, ramp, { emissive: 0xd36d32, emissiveIntensity: 2.1 });
  for (let index = 0; index < 12; index += 1) {
    const angle = index / 12 * Math.PI * 2;
    const lantern = outlinedMesh(new THREE.BoxGeometry(1.7, 0.36, 0.12), lanternMaterial, 1.08);
    lantern.position.set(Math.cos(angle) * 27.9, 3.3, Math.sin(angle) * 27.9);
    lantern.rotation.y = -angle + Math.PI / 2;
    root.add(lantern);
  }

  const skylight = new THREE.Mesh(
    new THREE.CircleGeometry(5.4, 48),
    new THREE.MeshBasicMaterial({ color: 0xfbe5b2, transparent: true, opacity: 0.25, side: THREE.DoubleSide }),
  );
  skylight.rotation.x = Math.PI / 2;
  skylight.position.y = 29.92;
  root.add(skylight);
  return root;
}

function createHabitatFurniture(ramp) {
  const root = new THREE.Group();
  const colliders = [];
  const solid = toonMaterial(0x31474c, ramp, { emissive: 0x102023, emissiveIntensity: 0.45 });
  const warm = toonMaterial(0xb97850, ramp, { emissive: 0x4e1e13, emissiveIntensity: 0.72 });
  const soft = toonMaterial(0x5e7186, ramp, { emissive: 0x152432, emissiveIntensity: 0.38 });
  const leaf = toonMaterial(0x456a4c, ramp, { emissive: 0x133a25, emissiveIntensity: 0.7 });
  const glow = toonMaterial(0xffcf76, ramp, { emissive: 0xff9b42, emissiveIntensity: 1.8 });

  const addBox = (name, x, y, z, width, height, depth, material, solidCollider = true) => {
    const mesh = outlinedMesh(new THREE.BoxGeometry(width, height, depth), material, 1.018);
    mesh.name = name;
    mesh.position.set(x, y + height / 2, z);
    root.add(mesh);
    if (solidCollider) colliders.push({ name, center: [x, y + height / 2, z], half: [width / 2, height / 2, depth / 2] });
    return mesh;
  };

  // Lounge: a place for conversation, resting, and shared idle activity.
  addBox("lounge-sofa-west", -10.2, 0, -6.2, 4.8, 1.08, 1.5, soft);
  addBox("lounge-sofa-south", -7.4, 0, -8.8, 1.5, 1.08, 4.2, soft);
  addBox("lounge-table", -7.6, 0, -5.2, 2.6, 0.52, 1.35, warm);
  const loungeLamp = new THREE.PointLight(0xffbc73, 18, 15, 2);
  loungeLamp.position.set(-7.4, 4.2, -5.5);
  loungeLamp.castShadow = true;
  root.add(loungeLamp);

  // Study wall and a physical desk for avatar terminal interactions.
  addBox("study-desk", 8.6, 0, -7.6, 4.3, 1.1, 1.8, warm);
  addBox("study-shelf", 12.1, 0, -8.2, 1.1, 4.8, 4.2, solid);
  const studyScreen = new THREE.Mesh(new THREE.PlaneGeometry(1.7, 1.0), toonMaterial(0x7ee6d5, ramp, { emissive: 0x2cddd0, emissiveIntensity: 1.25 }));
  studyScreen.position.set(8.6, 2.15, -6.67);
  root.add(studyScreen);
  const studyLamp = new THREE.PointLight(0x7ee6d5, 13, 13, 2);
  studyLamp.position.set(8.6, 3.6, -6.1);
  root.add(studyLamp);

  // Greenhouse and fabrication edges make the dome feel lived-in, not empty.
  addBox("greenhouse-planter-a", 10.5, 0, 8.8, 5.1, 0.86, 1.25, solid);
  addBox("greenhouse-planter-b", 15.1, 0, 5.2, 1.25, 0.86, 5.1, solid);
  for (const [x, z, scale] of [[9.3, 8.7, 1.1], [11.1, 8.8, 0.85], [14.8, 4.5, 1.0], [15.0, 6.4, 0.72]]) {
    const plant = new THREE.Mesh(new THREE.ConeGeometry(0.38 * scale, 1.8 * scale, 6), leaf);
    plant.position.set(x, 1.5 * scale, z);
    root.add(plant);
  }
  const growLamp = new THREE.PointLight(0x91e77f, 17, 16, 2);
  growLamp.position.set(12.2, 4.7, 7.2);
  root.add(growLamp);

  addBox("fabrication-bench", -12.8, 0, 9.7, 5.8, 1.2, 2.2, solid);
  const forge = new THREE.Mesh(new THREE.CylinderGeometry(0.65, 0.85, 0.95, 10), glow);
  forge.position.set(-12.8, 1.55, 9.7);
  root.add(forge);
  const forgeLight = new THREE.PointLight(0xff9b42, 20, 16, 2);
  forgeLight.position.set(-12.8, 3.1, 9.7);
  root.add(forgeLight);

  const hearth = new THREE.Mesh(new THREE.CylinderGeometry(1.45, 1.8, 0.42, 10), warm);
  hearth.position.set(-1.6, 0.21, 11.2);
  root.add(hearth);
  const hearthCore = new THREE.Mesh(new THREE.SphereGeometry(0.72, 16, 10), glow);
  hearthCore.position.set(-1.6, 0.88, 11.2);
  root.add(hearthCore);
  const hearthLight = new THREE.PointLight(0xffb15e, 24, 18, 2);
  hearthLight.position.set(-1.6, 3.8, 11.2);
  root.add(hearthLight);

  return { root, colliders, lights: { loungeLamp, studyLamp, growLamp, forgeLight, hearthLight } };
}

function createHabitatDecor(ramp) {
  const root = new THREE.Group();
  const starMaterial = new THREE.MeshBasicMaterial({ color: 0xd4f3ff, transparent: true, opacity: 0.45 });
  const random = seededRandom(0x414c5645);
  for (let index = 0; index < 115; index += 1) {
    const star = new THREE.Mesh(new THREE.SphereGeometry(0.025 + random() * 0.045, 5, 4), starMaterial);
    const theta = random() * Math.PI * 2;
    const phi = 0.22 + random() * Math.PI * 0.35;
    const radius = 29.5;
    star.position.set(
      Math.cos(theta) * Math.sin(phi) * radius,
      Math.cos(phi) * radius,
      Math.sin(theta) * Math.sin(phi) * radius,
    );
    root.add(star);
  }
  const labels = [
    [-16, 0.25, 13, "FAB"], [14.5, 0.25, -1, "GROW"], [-1, 0.25, -13, "COMMONS"], [5.5, 0.25, 6, "ALPECCA"],
  ];
  labels.forEach(([x, y, z]) => {
    const beacon = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.1, 0.48, 6), toonMaterial(0x7ee6d5, ramp, { emissive: 0x4dbeb4, emissiveIntensity: 1.5 }));
    beacon.position.set(x, y, z);
    root.add(beacon);
  });
  return root;
}

export function createWorld(scene, { quality = "auto" } = {}) {
  const ramp = createToonRamp();
  scene.background = new THREE.Color(0x070d14);
  scene.fog = new THREE.FogExp2(0x101c25, 0.012);

  const dome = createDomeFrame(ramp);
  const terrain = createHabitatFloor(ramp);
  const furniture = createHabitatFurniture(ramp);
  const decor = createHabitatDecor(ramp);
  scene.add(dome, terrain, furniture.root, decor);

  const hemisphere = new THREE.HemisphereLight(0x9de6d7, 0x101820, 1.5);
  const key = new THREE.DirectionalLight(0xffe0b3, 2.6);
  key.position.set(-11, 25, 15);
  key.castShadow = quality !== "low";
  key.shadow.mapSize.set(quality === "high" ? 2048 : 1024, quality === "high" ? 2048 : 1024);
  key.shadow.camera.left = -32;
  key.shadow.camera.right = 32;
  key.shadow.camera.top = 32;
  key.shadow.camera.bottom = -32;
  key.shadow.bias = -0.0008;
  const rim = new THREE.DirectionalLight(0x73d9e4, 0.9);
  rim.position.set(20, 15, -20);
  scene.add(hemisphere, key, rim);

  const empty = new THREE.Group();
  const sectorGrid = createSectorGrid(scene);
  sectorGrid.grid.material.transparent = true;
  sectorGrid.grid.material.opacity = 0.11;
  const rain = createRain(scene, seededRandom(0x56455350), quality === "high" ? 180 : 80);
  rain.lines.visible = false;
  const shellLight = new THREE.PointLight(0x77d9ef, 20, 58, 2);
  shellLight.position.set(0, 20, 0);
  scene.add(shellLight);
  const physicsColliders = [
    { name: "dome-floor", center: [0, -0.16, 0], half: [28.6, 0.16, 28.6] },
    { name: "dome-wall-north", center: [0, 4.4, -28.3], half: [28.6, 4.4, 0.32] },
    { name: "dome-wall-south", center: [0, 4.4, 28.3], half: [28.6, 4.4, 0.32] },
    { name: "dome-wall-west", center: [-28.3, 4.4, 0], half: [0.32, 4.4, 28.6] },
    { name: "dome-wall-east", center: [28.3, 4.4, 0], half: [0.32, 4.4, 28.6] },
    ...furniture.colliders,
  ];

  return {
    ramp,
    key,
    terrain,
    dome,
    furniture,
    decor,
    shellLight,
    warmLights: furniture.lights,
    magma: empty,
    pools: empty,
    obsidian: empty,
    flora: empty,
    sectorGrid,
    rain,
    physicsColliders,
    smoke: [],
    robots: [],
  };
}

// Load a .vrm through three + @pixiv/three-vrm (the exact runtime House HQ
// uses) and report humanoid/springbone stats. Textures are stubbed so this
// runs headless in Node -- geometry, skins, and spring bones are fully built.
//
// Usage: node check_vrm_three.mjs <file.vrm> <path-to-node_modules>
// Exit 0 = loaded cleanly; nonzero = three-vrm rejected the file.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [, , vrmPath, nodeModules] = process.argv;
if (!vrmPath || !nodeModules) {
  console.error("usage: node check_vrm_three.mjs <file.vrm> <node_modules dir>");
  process.exit(2);
}

const mod = (p) => import(pathToFileURL(path.join(nodeModules, p)).href);

try {
  const THREE = await mod("three/build/three.module.js");
  const { GLTFLoader } = await mod("three/examples/jsm/loaders/GLTFLoader.js");
  const { VRMLoaderPlugin, VRMUtils } = await mod("@pixiv/three-vrm/lib/three-vrm.module.js");

  const loader = new GLTFLoader();
  // Stub texture loading (no DOM in Node). Registered first so it wins.
  loader.register((parser) => ({
    name: "stub-textures",
    loadTexture: async () => new THREE.Texture(),
  }));
  loader.register((parser) => new VRMLoaderPlugin(parser));

  const buf = readFileSync(vrmPath);
  const arrayBuffer = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

  const gltf = await new Promise((resolve, reject) =>
    loader.parse(arrayBuffer, "", resolve, reject),
  );
  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error("no VRM in parsed glTF (userData.vrm missing)");

  const sbJoints = vrm.springBoneManager ? [...vrm.springBoneManager.joints] : [];
  const injJoints = sbJoints.filter((j) => j.bone?.name?.startsWith("J_Inj_"));

  // simulate a few frames so bad spring setups surface as NaNs
  vrm.humanoid?.resetNormalizedPose?.();
  for (let i = 0; i < 30; i++) vrm.update(1 / 60);
  let nan = 0;
  vrm.scene.traverse((o) => {
    if (o.isBone && (isNaN(o.position.x) || isNaN(o.quaternion.x))) nan++;
  });

  console.log(
    JSON.stringify({
      ok: true,
      specVersion: vrm.meta?.metaVersion ?? "1.0",
      humanoid: !!vrm.humanoid,
      springJoints: sbJoints.length,
      injectedSpringJoints: injJoints.length,
      injectedNames: injJoints.map((j) => j.bone.name).sort(),
      nanBonesAfter30Frames: nan,
    }),
  );
  if (nan > 0) process.exit(3);
  process.exit(0);
} catch (err) {
  console.error("three-vrm load FAILED:", err?.message ?? err);
  process.exit(1);
}

#!/usr/bin/env python3
"""Inject hoodie-hem sway physics into Alpecca's VRM (VRM 1.0 / VRMC_springBone).

WHY THIS EXISTS
    Jason's outfit geometry is final, but texture passes keep re-exporting the
    .vrm from VRoid Studio. VRoid does not rig the hoodie hem, so every fresh
    export loses nothing -- this script re-adds the hem sway bones on demand.
    It is a REPEATABLE tool, not a one-off edit: run it on any fresh export.

WHAT IT DOES (pure-Python GLB surgery, no Blender, stdlib only)
    1. Parses the GLB (JSON + BIN chunks) directly. Never touches the input.
    2. If a previous injection is present (nodes named J_Inj_*), strips it
       first so re-running on an already-injected file is safe (idempotent).
    3. Finds the hoodie: Body-mesh primitives whose material name matches
       --tops-material-regex (default: VRoid "Tops_*_CLOTH" materials).
    4. Locates the hem: lowest Y of hoodie vertices that are skinned purely
       to torso bones (sleeves are excluded by this gate, not by geometry).
    5. Builds N (default 6) short bone chains around the hem band, parented
       under the humanoid hips bone: root at the top of the band, mid at the
       hem edge, tail hanging below (pendulum arm). Names: J_Inj_HoodieHem_*.
    6. Extends the Body skin (joints + a NEW inverseBindMatrices accessor
       appended to the BIN; the original IBM accessor is left untouched so a
       strip can restore it exactly).
    7. Re-weights hem-band vertices toward the chains' mid joints with a
       smoothstep vertical falloff (0 at band top, --max-weight at hem edge)
       and angular blending between the two nearest chains (no sector seams).
       Existing weights are scaled by (1 - injected), so stripping +
       renormalizing recovers the original weights.
    8. Appends one VRMC_springBone spring per chain, using only existing
       hips/lower-torso collider groups verified against the humanoid rig.
       Head, hair, limb, and accessory colliders are never attached.
    9. Validates the output structurally (see validate_output) and verifies
       that materials, textures, images, meshes and VRMC_vrm are byte-for-byte
       / JSON-identical to the input -- zero visible-design changes.

RE-RUN WORKFLOW (after every VRoid texture re-export)
    python scripts\\inject_hoodie_sway_physics.py ^
        --input  data\\avatar\\vrm\\<fresh_export>.vrm ^
        --output data\\alpecca_art_source\\vrm_experiments\\alpecca_hoodie_sway_qa.vrm

    Then do visual QA. Promotion into data\\avatar\\vrm\\ is a deliberate,
    manual step (the server serves sorted(glob)[0] from that directory, so
    the promoted filename must sort FIRST, e.g. alpecca.vrm):

    Copy-Item data\\alpecca_art_source\\vrm_experiments\\alpecca_hoodie_sway_qa.vrm ^
        data\\avatar\\vrm\\alpecca.vrm

    This script REFUSES to write into a data\\avatar\\vrm directory unless
    --allow-live-dir is passed, and always refuses to overwrite its input.

Optional deep check: scripts/check_vrm_three.mjs loads the output through the
same three-vrm runtime House HQ uses (run automatically when node + the
house-hq node_modules are available; skip with --no-three-check).
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import struct
import subprocess
import sys

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

INJECT_PREFIX = "J_Inj_HoodieHem"
MARKER_KEY = "alpecca_hoodie_sway"
MARKER_VERSION = 1

COMPONENT_FMT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}

# Sleeve/other-part exclusion: a hem vertex must be skinned ONLY to these.
TORSO_BONES = {
    "J_Bip_C_Hips",
    "J_Bip_C_Spine",
    "J_Bip_C_Chest",
    "J_Bip_C_UpperChest",
    "J_Bip_L_UpperLeg",
    "J_Bip_R_UpperLeg",
}

# Hoodie-hem collisions are limited to the body at or immediately above the
# hem. Order is intentional so equivalent exports produce the same references.
HOODIE_COLLIDER_ATTACHMENTS = (
    ("hips", "J_Bip_C_Hips"),
    ("spine", "J_Bip_C_Spine"),
)
MAX_HOODIE_COLLIDER_ROOT_GAP_METERS = 0.025


class InjectError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# GLB container
# --------------------------------------------------------------------------

def read_glb(path):
    data = open(path, "rb").read()
    if len(data) < 12:
        raise InjectError(f"{path}: too small to be a GLB")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise InjectError(f"{path}: not a GLB (bad magic)")
    if version != 2:
        raise InjectError(f"{path}: unsupported GLB version {version}")
    if length != len(data):
        raise InjectError(f"{path}: header length {length} != file size {len(data)}")
    chunks = []
    off = 12
    while off < length:
        clen, ctype = struct.unpack_from("<II", data, off)
        chunks.append((ctype, data[off + 8: off + 8 + clen]))
        off += 8 + clen
    if off != length:
        raise InjectError(f"{path}: chunk walk ended at {off}, expected {length}")
    if not chunks or chunks[0][0] != CHUNK_JSON:
        raise InjectError(f"{path}: first chunk is not JSON")
    gltf = json.loads(chunks[0][1].decode("utf-8"))
    bin_chunk = b""
    for ctype, payload in chunks[1:]:
        if ctype == CHUNK_BIN:
            bin_chunk = payload
            break
    return gltf, bytearray(bin_chunk)


def write_glb(path, gltf, bin_data):
    json_bytes = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)  # pad JSON with spaces
    bin_bytes = bytes(bin_data)
    bin_bytes += b"\x00" * ((4 - len(bin_bytes) % 4) % 4)  # pad BIN with zeros
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", GLB_MAGIC, 2, total))
        f.write(struct.pack("<II", len(json_bytes), CHUNK_JSON))
        f.write(json_bytes)
        f.write(struct.pack("<II", len(bin_bytes), CHUNK_BIN))
        f.write(bin_bytes)


# --------------------------------------------------------------------------
# Accessor helpers (tightly-packed or strided, single-buffer GLB)
# --------------------------------------------------------------------------

def accessor_layout(gltf, acc_index):
    acc = gltf["accessors"][acc_index]
    if "bufferView" not in acc or acc.get("sparse"):
        raise InjectError(f"accessor {acc_index}: sparse/viewless accessors unsupported")
    bv = gltf["bufferViews"][acc["bufferView"]]
    fmt = COMPONENT_FMT[acc["componentType"]]
    ncomp = TYPE_COUNT[acc["type"]]
    elem = struct.calcsize(fmt) * ncomp
    stride = bv.get("byteStride") or elem
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return acc, fmt, ncomp, elem, stride, base


def read_accessor(gltf, bin_data, acc_index):
    acc, fmt, ncomp, _elem, stride, base = accessor_layout(gltf, acc_index)
    out = []
    unpack = struct.Struct("<" + fmt * ncomp).unpack_from
    for k in range(acc["count"]):
        out.append(unpack(bin_data, base + k * stride))
    return out


def write_accessor_element(gltf, bin_data, acc_index, element_index, values):
    _acc, fmt, ncomp, _elem, stride, base = accessor_layout(gltf, acc_index)
    struct.pack_into("<" + fmt * ncomp, bin_data, base + element_index * stride, *values)


def accessor_byte_range(gltf, acc_index):
    acc, _fmt, _ncomp, elem, stride, base = accessor_layout(gltf, acc_index)
    n = acc["count"]
    end = base + (n - 1) * stride + elem if n else base
    return base, end


# --------------------------------------------------------------------------
# Small linear algebra (row-major 4x4, float64)
# --------------------------------------------------------------------------

def quat_to_mat3(q):
    x, y, z, w = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def mat4_from_trs(t, r, s):
    m3 = quat_to_mat3(r)
    return [
        [m3[0][0] * s[0], m3[0][1] * s[1], m3[0][2] * s[2], t[0]],
        [m3[1][0] * s[0], m3[1][1] * s[1], m3[1][2] * s[2], t[1]],
        [m3[2][0] * s[0], m3[2][1] * s[1], m3[2][2] * s[2], t[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def mat4_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def mat4_invert_affine(m):
    a = [row[:3] for row in m[:3]]
    det = (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )
    if abs(det) < 1e-12:
        raise InjectError("singular node matrix")
    inv = [
        [
            (a[1][1] * a[2][2] - a[1][2] * a[2][1]) / det,
            (a[0][2] * a[2][1] - a[0][1] * a[2][2]) / det,
            (a[0][1] * a[1][2] - a[0][2] * a[1][1]) / det,
        ],
        [
            (a[1][2] * a[2][0] - a[1][0] * a[2][2]) / det,
            (a[0][0] * a[2][2] - a[0][2] * a[2][0]) / det,
            (a[0][2] * a[1][0] - a[0][0] * a[1][2]) / det,
        ],
        [
            (a[1][0] * a[2][1] - a[1][1] * a[2][0]) / det,
            (a[0][1] * a[2][0] - a[0][0] * a[2][1]) / det,
            (a[0][0] * a[1][1] - a[0][1] * a[1][0]) / det,
        ],
    ]
    t = [m[0][3], m[1][3], m[2][3]]
    it = [-sum(inv[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [
        [inv[0][0], inv[0][1], inv[0][2], it[0]],
        [inv[1][0], inv[1][1], inv[1][2], it[1]],
        [inv[2][0], inv[2][1], inv[2][2], it[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def mat4_apply(m, p):
    return [
        m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3],
        m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3],
        m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3],
    ]


def mat4_to_gltf_column_major(m):
    return [m[r][c] for c in range(4) for r in range(4)]


def node_local_matrix(node):
    if "matrix" in node:
        v = node["matrix"]  # glTF column-major
        return [[v[c * 4 + r] for c in range(4)] for r in range(4)]
    return mat4_from_trs(
        node.get("translation", [0.0, 0.0, 0.0]),
        node.get("rotation", [0.0, 0.0, 0.0, 1.0]),
        node.get("scale", [1.0, 1.0, 1.0]),
    )


def build_parent_map(gltf):
    parent = {}
    for i, node in enumerate(gltf["nodes"]):
        for c in node.get("children", []):
            parent[c] = i
    return parent


def select_hoodie_collider_groups(gltf):
    """Return deterministic, verified hips/lower-torso collider group indices."""
    nodes = gltf.get("nodes", [])
    extensions = gltf.get("extensions", {})
    ext_vrm = extensions.get("VRMC_vrm", {})
    ext_sb = extensions.get("VRMC_springBone", {})
    human_bones = ext_vrm.get("humanoid", {}).get("humanBones", {})
    collider_groups = ext_sb.get("colliderGroups", [])
    colliders = ext_sb.get("colliders", [])
    selected = []

    for bone_name, expected_node_name in HOODIE_COLLIDER_ATTACHMENTS:
        node_index = human_bones.get(bone_name, {}).get("node")
        if (
            type(node_index) is not int
            or not (0 <= node_index < len(nodes))
            or nodes[node_index].get("name") != expected_node_name
        ):
            continue

        matches = []
        for group_index, group in enumerate(collider_groups):
            if not isinstance(group, dict) or group.get("name") != expected_node_name:
                continue
            refs = group.get("colliders")
            if not isinstance(refs, list) or not refs:
                continue

            valid = True
            for collider_index in refs:
                if type(collider_index) is not int or not (0 <= collider_index < len(colliders)):
                    valid = False
                    break
                collider = colliders[collider_index]
                shape = collider.get("shape") if isinstance(collider, dict) else None
                if (
                    not isinstance(collider, dict)
                    or collider.get("node") != node_index
                    or not isinstance(shape, dict)
                    or not ("sphere" in shape or "capsule" in shape)
                ):
                    valid = False
                    break
            if valid:
                matches.append(group_index)

        if len(matches) > 1:
            raise InjectError(
                f"ambiguous hoodie collider groups for {expected_node_name}; refusing"
            )
        if matches:
            selected.append(matches[0])

    if not selected:
        allowed = ", ".join(name for _bone, name in HOODIE_COLLIDER_ATTACHMENTS)
        raise InjectError(
            "no safe hoodie body collider group found; expected a non-empty "
            f"{allowed} group attached to its matching VRM humanoid node"
        )
    return selected


def world_matrix(gltf, parent, node_index):
    chain = []
    i = node_index
    while True:
        chain.append(i)
        if i not in parent:
            break
        i = parent[i]
    m = [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
    for j in reversed(chain):
        m = mat4_mul(m, node_local_matrix(gltf["nodes"][j]))
    return m


def _finite_vec3(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise InjectError(f"{name} must be a finite vec3")
    result = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise InjectError(f"{name} must be a finite vec3")
        component = float(component)
        if not math.isfinite(component):
            raise InjectError(f"{name} must be a finite vec3")
        result.append(component)
    return result


def _uniform_world_scale(matrix, name):
    columns = [
        _finite_vec3([matrix[row][column] for row in range(3)], name)
        for column in range(3)
    ]
    scales = [math.sqrt(sum(component * component for component in column)) for column in columns]
    if min(scales) <= 1e-8:
        raise InjectError(f"{name} has a singular world transform")
    tolerance = max(scales) * 1e-5
    if max(scales) - min(scales) > tolerance:
        raise InjectError(f"{name} has unsupported non-uniform world scale")
    for left in range(3):
        for right in range(left + 1, 3):
            dot = sum(columns[left][axis] * columns[right][axis] for axis in range(3))
            if abs(dot) > max(scales) ** 2 * 1e-5:
                raise InjectError(f"{name} has unsupported world shear")
    return sum(scales) / 3.0


def _point_segment_distance(point, start, end):
    delta = [end[axis] - start[axis] for axis in range(3)]
    length_sq = sum(component * component for component in delta)
    if length_sq <= 1e-16:
        return math.dist(point, start)
    projection = sum(
        (point[axis] - start[axis]) * delta[axis] for axis in range(3)
    ) / length_sq
    projection = max(0.0, min(1.0, projection))
    nearest = [start[axis] + projection * delta[axis] for axis in range(3)]
    return math.dist(point, nearest)


def hoodie_collider_root_gaps(gltf, collider_group_indices, chain_roots_world):
    """Measure each hem root's world-space gap to the selected collider volumes."""
    nodes = gltf.get("nodes", [])
    ext_sb = gltf.get("extensions", {}).get("VRMC_springBone", {})
    collider_groups = ext_sb.get("colliderGroups", [])
    colliders = ext_sb.get("colliders", [])
    if not isinstance(collider_group_indices, (list, tuple)) or not collider_group_indices:
        raise InjectError("hoodie collider reach requires selected collider groups")
    if not isinstance(chain_roots_world, (list, tuple)) or not chain_roots_world:
        raise InjectError("hoodie collider reach requires hem chain roots")

    parent = build_parent_map(gltf)
    volumes = []
    for group_index in collider_group_indices:
        if type(group_index) is not int or not (0 <= group_index < len(collider_groups)):
            raise InjectError("hoodie collider group index is invalid")
        group = collider_groups[group_index]
        refs = group.get("colliders") if isinstance(group, dict) else None
        if not isinstance(refs, list) or not refs:
            raise InjectError("hoodie collider group has no collider volumes")
        for collider_index in refs:
            if type(collider_index) is not int or not (0 <= collider_index < len(colliders)):
                raise InjectError("hoodie collider reference is invalid")
            collider = colliders[collider_index]
            node_index = collider.get("node") if isinstance(collider, dict) else None
            shape = collider.get("shape") if isinstance(collider, dict) else None
            if type(node_index) is not int or not (0 <= node_index < len(nodes)):
                raise InjectError("hoodie collider node is invalid")
            if not isinstance(shape, dict) or frozenset(shape) not in {
                frozenset({"sphere"}),
                frozenset({"capsule"}),
            }:
                raise InjectError("hoodie collider shape is not an exact sphere or capsule")

            kind = "sphere" if "sphere" in shape else "capsule"
            details = shape[kind]
            expected_fields = {"offset", "radius"}
            if kind == "capsule":
                expected_fields.add("tail")
            if not isinstance(details, dict) or frozenset(details) != frozenset(expected_fields):
                raise InjectError(f"hoodie {kind} collider has an invalid shape")
            offset = _finite_vec3(details["offset"], f"hoodie {kind} offset")
            radius = details["radius"]
            if (
                isinstance(radius, bool)
                or not isinstance(radius, (int, float))
                or not math.isfinite(float(radius))
                or float(radius) <= 0.0
            ):
                raise InjectError(f"hoodie {kind} collider radius is invalid")

            transform = world_matrix(gltf, parent, node_index)
            world_scale = _uniform_world_scale(
                transform, f"hoodie collider {collider_index}"
            )
            start = mat4_apply(transform, offset)
            end = start
            if kind == "capsule":
                end = mat4_apply(
                    transform,
                    _finite_vec3(details["tail"], "hoodie capsule tail"),
                )
            volumes.append((start, end, float(radius) * world_scale))

    if not volumes:
        raise InjectError("hoodie collider groups contain no usable volumes")

    gaps = []
    for root_index, root in enumerate(chain_roots_world):
        point = _finite_vec3(root, f"hoodie chain root {root_index}")
        gaps.append(
            min(
                max(0.0, _point_segment_distance(point, start, end) - radius)
                for start, end, radius in volumes
            )
        )
    return gaps


def require_hoodie_collider_reach(gltf, collider_group_indices, chain_roots_world):
    """Fail unless every hem root is reached by a selected collider volume."""
    gaps = hoodie_collider_root_gaps(
        gltf, collider_group_indices, chain_roots_world
    )
    ineffective = [
        (index, gap)
        for index, gap in enumerate(gaps)
        if gap > MAX_HOODIE_COLLIDER_ROOT_GAP_METERS
    ]
    if ineffective:
        summary = ", ".join(
            f"root {index}: {gap:.4f} m" for index, gap in ineffective
        )
        raise InjectError(
            "hoodie collider groups are spatially ineffective; collider surface "
            f"gap exceeds {MAX_HOODIE_COLLIDER_ROOT_GAP_METERS:.3f} m "
            f"({summary})"
        )
    return gaps


# --------------------------------------------------------------------------
# Idempotency: strip a previous injection
# --------------------------------------------------------------------------

def strip_previous_injection(gltf, bin_data):
    """Remove any prior J_Inj_HoodieHem injection. Returns (bin_data, info_str)."""
    nodes = gltf["nodes"]
    inj_nodes = [i for i, n in enumerate(nodes) if str(n.get("name", "")).startswith("J_Inj_")]
    marker = gltf.get("extras", {}).get(MARKER_KEY)
    if not inj_nodes and marker is None:
        return bin_data, None
    if not inj_nodes or marker is None:
        raise InjectError(
            "found J_Inj_* nodes or marker without the matching counterpart; "
            "cannot strip safely -- re-run on a fresh VRoid export instead"
        )

    start = marker["node_start"]
    count = marker["node_count"]
    if inj_nodes != list(range(start, start + count)) or start + count != len(nodes):
        raise InjectError(
            "previous injection is not the tail of the node array (file was "
            "modified after injection); re-run on a fresh VRoid export instead"
        )
    inj_set = set(inj_nodes)

    # springs
    sb = gltf["extensions"]["VRMC_springBone"]
    before = len(sb["springs"])
    sb["springs"] = [
        s for s in sb["springs"]
        if not str(s.get("name", "")).startswith(INJECT_PREFIX)
        and not any(j.get("node") in inj_set for j in s.get("joints", []))
    ]
    springs_removed = before - len(sb["springs"])

    # children references
    for n in nodes:
        if "children" in n:
            n["children"] = [c for c in n["children"] if c not in inj_set]
            if not n["children"]:
                del n["children"]

    # skin: joints tail + IBM accessor restore
    skin_index = marker["skin"]
    skin = gltf["skins"][skin_index]
    if skin["joints"][-count:] != inj_nodes:
        raise InjectError("skin joints tail does not match injected nodes; aborting strip")
    del skin["joints"][-count:]
    n_joints = len(skin["joints"])
    orig_ibm = marker["original_ibm_accessor"]
    if gltf["accessors"][orig_ibm]["count"] != n_joints:
        raise InjectError("original IBM accessor count mismatch; aborting strip")
    skin["inverseBindMatrices"] = orig_ibm

    # de-weight: zero any influence pointing at removed skin-joint slots, renormalize
    mesh_index = marker["mesh"]
    joints_acc = marker["joints_accessor"]
    weights_acc = marker["weights_accessor"]
    joints = read_accessor(gltf, bin_data, joints_acc)
    weights = read_accessor(gltf, bin_data, weights_acc)
    restored = 0
    for vi in range(len(joints)):
        js, ws = list(joints[vi]), list(weights[vi])
        touched = False
        for k in range(4):
            if js[k] >= n_joints and ws[k] > 0.0:
                ws[k] = 0.0
                js[k] = 0
                touched = True
            elif js[k] >= n_joints:
                js[k] = 0
                touched = True
        if touched:
            total = sum(ws)
            if total <= 1e-6:
                raise InjectError(f"vertex {vi}: all weight was injected; cannot restore")
            ws = [w / total for w in ws]
            write_accessor_element(gltf, bin_data, joints_acc, vi, js)
            write_accessor_element(gltf, bin_data, weights_acc, vi, ws)
            restored += 1

    # remove injected IBM accessor + bufferView (must be the appended tail)
    ibm_acc_index = marker["ibm_accessor"]
    ibm_bv_index = marker["ibm_bufferview"]
    if ibm_acc_index != len(gltf["accessors"]) - 1 or ibm_bv_index != len(gltf["bufferViews"]) - 1:
        raise InjectError("injected IBM accessor/bufferView is no longer last; aborting strip")
    bv = gltf["bufferViews"][ibm_bv_index]
    gltf["accessors"].pop()
    gltf["bufferViews"].pop()
    tail_start = bv.get("byteOffset", 0)
    if tail_start + bv["byteLength"] >= len(bin_data) - 3:
        bin_data = bin_data[:tail_start]
    gltf["buffers"][0]["byteLength"] = len(bin_data)

    # nodes tail
    del nodes[start:]

    del gltf["extras"][MARKER_KEY]
    if not gltf["extras"]:
        del gltf["extras"]

    info = (
        f"stripped previous injection: {count} nodes, {springs_removed} springs, "
        f"{restored} vertices restored (renormalized)"
    )
    return bin_data, info


# --------------------------------------------------------------------------
# Injection
# --------------------------------------------------------------------------

def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def append_hoodie_springs(
    ext_sb, node_start, chain_labels, args, collider_group_indices
):
    """Append the existing three-node spring topology with verified colliders."""
    collider_groups = list(collider_group_indices)
    if not collider_groups:
        raise InjectError("refusing to append hoodie springs without safe colliders")

    def spring_joint(node_index):
        return {
            "node": node_index,
            "hitRadius": args.hit_radius,
            "stiffness": args.stiffness,
            "gravityPower": args.gravity_power,
            "gravityDir": [0.0, -1.0, 0.0],
            "dragForce": args.drag_force,
        }

    for k, label in enumerate(chain_labels):
        base = node_start + 3 * k
        ext_sb["springs"].append({
            "name": f"{INJECT_PREFIX}_{label}",
            "joints": [spring_joint(base), spring_joint(base + 1), spring_joint(base + 2)],
            "colliderGroups": list(collider_groups),
        })


def sector_label(center_deg, n_chains):
    if n_chains != 6:
        return f"S{int(round(center_deg)) % 360:03d}"
    side = "L" if math.sin(math.radians(center_deg)) > 0 else "R"
    a = abs(((center_deg + 180.0) % 360.0) - 180.0)
    if a <= 45.0:
        zone = "Front"
    elif a <= 135.0:
        zone = "Side"
    else:
        zone = "Back"
    return zone + side


def inject(gltf, bin_data, args):
    report = {}
    nodes = gltf["nodes"]
    ext_vrm = gltf.get("extensions", {}).get("VRMC_vrm")
    ext_sb = gltf.get("extensions", {}).get("VRMC_springBone")
    if not ext_vrm or not ext_sb:
        raise InjectError("input is not a VRM 1.0 file (VRMC_vrm/VRMC_springBone missing)")

    hoodie_collider_groups = select_hoodie_collider_groups(gltf)

    hips_index = ext_vrm["humanoid"]["humanBones"]["hips"]["node"]
    parent = build_parent_map(gltf)

    # ---- locate the hoodie primitives ------------------------------------
    mat_re = re.compile(args.tops_material_regex)
    mat_indices = {
        i for i, m in enumerate(gltf["materials"]) if mat_re.search(str(m.get("name", "")))
    }
    if not mat_indices:
        raise InjectError(f"no material matches regex {args.tops_material_regex!r}")

    mesh_index = None
    prims = []
    for mi, mesh in enumerate(gltf["meshes"]):
        hit = [p for p in mesh["primitives"] if p.get("material") in mat_indices]
        if hit:
            if mesh_index is not None and mesh_index != mi:
                raise InjectError("hoodie materials span multiple meshes; unsupported")
            mesh_index = mi
            prims = hit
    if mesh_index is None:
        raise InjectError("no mesh primitive uses the hoodie materials")

    mesh_nodes = [i for i, n in enumerate(nodes) if n.get("mesh") == mesh_index]
    if len(mesh_nodes) != 1 or "skin" not in nodes[mesh_nodes[0]]:
        raise InjectError("expected exactly one skinned node using the hoodie mesh")
    skin_index = nodes[mesh_nodes[0]]["skin"]
    skin = gltf["skins"][skin_index]

    attr_sets = {
        (p["attributes"]["POSITION"], p["attributes"]["JOINTS_0"], p["attributes"]["WEIGHTS_0"])
        for p in prims
    }
    if len(attr_sets) != 1:
        raise InjectError("hoodie primitives do not share attribute accessors; unsupported")
    pos_acc, joints_acc, weights_acc = next(iter(attr_sets))
    if gltf["accessors"][joints_acc]["componentType"] not in (5121, 5123):
        raise InjectError("JOINTS_0 must be ubyte/ushort")
    if gltf["accessors"][weights_acc]["componentType"] != 5126:
        raise InjectError("WEIGHTS_0 must be float32 (VRoid default)")

    positions = read_accessor(gltf, bin_data, pos_acc)
    joints = read_accessor(gltf, bin_data, joints_acc)
    weights = read_accessor(gltf, bin_data, weights_acc)

    hood_verts = set()
    for p in prims:
        if "indices" not in p:
            raise InjectError("non-indexed hoodie primitive; unsupported")
        for (idx,) in read_accessor(gltf, bin_data, p["indices"]):
            hood_verts.add(idx)

    # ---- torso gate + hem band -------------------------------------------
    joint_name = lambda j: str(nodes[skin["joints"][j]].get("name", ""))
    torso_verts = []
    for v in hood_verts:
        bones = {joint_name(j) for j, w in zip(joints[v], weights[v]) if w > 1e-4}
        if bones and bones <= TORSO_BONES:
            torso_verts.append(v)
    if len(torso_verts) < 24:
        raise InjectError(f"only {len(torso_verts)} torso-gated hoodie verts; refusing")

    hem_y = min(positions[v][1] for v in torso_verts)
    band_top = hem_y + args.band_height
    band = [v for v in torso_verts if positions[v][1] <= band_top + 1e-9]
    if len(band) < 12:
        raise InjectError(f"only {len(band)} verts in hem band; refusing")
    cx = sum(positions[v][0] for v in band) / len(band)
    cz = sum(positions[v][2] for v in band) / len(band)
    report["hem_y"] = hem_y
    report["band_top"] = band_top
    report["band_verts"] = len(band)

    # ---- chain placement ---------------------------------------------------
    n_chains = args.chains
    step = 360.0 / n_chains
    centers = [-180.0 + (k + 0.5) * step for k in range(n_chains)]
    # azimuth: 0 deg = model front (+Z for VRM 1.0), character-left = +X
    azimuth = lambda v: math.degrees(math.atan2(positions[v][0] - cx, positions[v][2] - cz))

    sector_pts = [[] for _ in range(n_chains)]
    for v in band:
        p = (azimuth(v) + 180.0) / step
        sector_pts[int(p) % n_chains].append(v)
    mean_r = sum(math.hypot(positions[v][0] - cx, positions[v][2] - cz) for v in band) / len(band)

    chain_roots_world = []
    chain_labels = []
    for k in range(n_chains):
        pts = sector_pts[k]
        if pts:
            rx = sum(positions[v][0] for v in pts) / len(pts)
            rz = sum(positions[v][2] for v in pts) / len(pts)
        else:
            rx = cx + mean_r * math.sin(math.radians(centers[k]))
            rz = cz + mean_r * math.cos(math.radians(centers[k]))
        chain_roots_world.append([rx, band_top, rz])
        chain_labels.append(sector_label(centers[k], n_chains))
    report["chains"] = list(zip(chain_labels, [tuple(round(c, 4) for c in p) for p in chain_roots_world]))
    collider_root_gaps = require_hoodie_collider_reach(
        gltf, hoodie_collider_groups, chain_roots_world
    )
    report["hoodie_collider_root_gaps"] = collider_root_gaps
    report["hoodie_collider_max_root_gap"] = max(collider_root_gaps)

    # ---- build nodes --------------------------------------------------------
    w_hips = world_matrix(gltf, parent, hips_index)
    inv_hips = mat4_invert_affine(w_hips)

    node_start = len(nodes)
    new_node_indices = []
    new_ibms_world = []  # world matrices of new joints, in order
    for k in range(n_chains):
        rx, ry, rz = chain_roots_world[k]
        p_root = [rx, band_top, rz]
        p_mid = [rx, hem_y, rz]
        p_tail = [rx, hem_y - args.tail_drop, rz]

        root_local = mat4_apply(inv_hips, p_root)
        w_root = mat4_mul(w_hips, mat4_from_trs(root_local, [0, 0, 0, 1], [1, 1, 1]))
        mid_local = mat4_apply(mat4_invert_affine(w_root), p_mid)
        w_mid = mat4_mul(w_root, mat4_from_trs(mid_local, [0, 0, 0, 1], [1, 1, 1]))
        tail_local = mat4_apply(mat4_invert_affine(w_mid), p_tail)
        w_tail = mat4_mul(w_mid, mat4_from_trs(tail_local, [0, 0, 0, 1], [1, 1, 1]))

        base = len(nodes)
        label = chain_labels[k]
        nodes.append({"name": f"{INJECT_PREFIX}_{label}_00", "translation": root_local, "children": [base + 1]})
        nodes.append({"name": f"{INJECT_PREFIX}_{label}_01", "translation": mid_local, "children": [base + 2]})
        nodes.append({"name": f"{INJECT_PREFIX}_{label}_end", "translation": tail_local})
        nodes[hips_index].setdefault("children", []).append(base)
        new_node_indices.extend([base, base + 1, base + 2])
        new_ibms_world.extend([w_root, w_mid, w_tail])

    # ---- extend skin: joints + new IBM accessor ----------------------------
    orig_ibm_acc = skin["inverseBindMatrices"]
    orig_ibm_start, orig_ibm_end = accessor_byte_range(gltf, orig_ibm_acc)
    old_count = len(skin["joints"])
    skin["joints"].extend(new_node_indices)

    ibm_bytes = bytearray(bin_data[orig_ibm_start:orig_ibm_end])
    for w in new_ibms_world:
        ibm_bytes += struct.pack("<16f", *mat4_to_gltf_column_major(mat4_invert_affine(w)))

    if len(bin_data) % 4:
        bin_data += b"\x00" * (4 - len(bin_data) % 4)
    new_bv_index = len(gltf["bufferViews"])
    gltf["bufferViews"].append({
        "buffer": 0,
        "byteOffset": len(bin_data),
        "byteLength": len(ibm_bytes),
        "name": f"{INJECT_PREFIX}_IBM",
    })
    bin_data += ibm_bytes
    new_acc_index = len(gltf["accessors"])
    gltf["accessors"].append({
        "bufferView": new_bv_index,
        "componentType": 5126,
        "count": len(skin["joints"]),
        "type": "MAT4",
        "name": f"{INJECT_PREFIX}_IBM",
    })
    skin["inverseBindMatrices"] = new_acc_index
    gltf["buffers"][0]["byteLength"] = len(bin_data)

    # skin-joint slots of each chain's MID joint (the one vertices bind to)
    mid_slot = [old_count + 3 * k + 1 for k in range(n_chains)]

    # ---- re-weight the hem band --------------------------------------------
    touched = 0
    dropped_influences = 0
    single_chain = 0
    max_seen = 0.0
    for v in band:
        y = positions[v][1]
        t = (band_top - y) / args.band_height
        w_total = args.max_weight * smoothstep(t)
        if w_total < 0.01:
            continue

        # angular blend between the two nearest chains
        p = (azimuth(v) + 180.0) / step - 0.5
        k0 = math.floor(p)
        alpha = p - k0
        ka, kb = int(k0) % n_chains, (int(k0) + 1) % n_chains
        if alpha < 0.2:
            targets = [(mid_slot[ka], w_total)]
        elif alpha > 0.8:
            targets = [(mid_slot[kb], w_total)]
        else:
            targets = [(mid_slot[ka], w_total * (1.0 - alpha)), (mid_slot[kb], w_total * alpha)]

        js, ws = list(joints[v]), list(weights[v])
        for i in range(4):
            ws[i] *= (1.0 - w_total)
        free = [i for i in range(4) if ws[i] <= 1e-8]
        if len(free) < len(targets):
            # merge to the single nearest chain
            k_near = ka if alpha <= 0.5 else kb
            targets = [(mid_slot[k_near], w_total)]
            single_chain += 1
        if len(free) < 1:
            # drop the smallest existing influence, give its weight to the rest
            nz = [i for i in range(4) if ws[i] > 1e-8]
            i_min = min(nz, key=lambda i: ws[i])
            dropped = ws[i_min]
            rest = [i for i in nz if i != i_min]
            rest_sum = sum(ws[i] for i in rest)
            for i in rest:
                ws[i] += dropped * (ws[i] / rest_sum)
            ws[i_min] = 0.0
            js[i_min] = 0
            free = [i_min]
            dropped_influences += 1
        for (slot, w), i in zip(targets, free):
            js[i] = slot
            ws[i] = w
        total = sum(ws)
        ws = [w / total for w in ws]
        write_accessor_element(gltf, bin_data, joints_acc, v, js)
        write_accessor_element(gltf, bin_data, weights_acc, v, ws)
        joints[v] = tuple(js)
        weights[v] = tuple(ws)
        touched += 1
        max_seen = max(max_seen, w_total)

    if touched == 0:
        raise InjectError("no vertices were re-weighted; band/params look wrong")
    report["touched_verts"] = touched
    report["dropped_influences"] = dropped_influences
    report["single_chain_verts"] = single_chain
    report["max_injected_weight"] = max_seen

    # ---- springs -------------------------------------------------------------
    springs_before = len(ext_sb["springs"])
    append_hoodie_springs(
        ext_sb, node_start, chain_labels, args, hoodie_collider_groups
    )
    report["springs_before"] = springs_before
    report["springs_after"] = len(ext_sb["springs"])
    report["hoodie_collider_groups"] = list(hoodie_collider_groups)
    report["hoodie_collider_group_names"] = [
        ext_sb["colliderGroups"][i]["name"] for i in hoodie_collider_groups
    ]

    # ---- idempotency marker ----------------------------------------------------
    gltf.setdefault("extras", {})[MARKER_KEY] = {
        "version": MARKER_VERSION,
        "node_start": node_start,
        "node_count": 3 * n_chains,
        "skin": skin_index,
        "mesh": mesh_index,
        "joints_accessor": joints_acc,
        "weights_accessor": weights_acc,
        "original_ibm_accessor": orig_ibm_acc,
        "ibm_accessor": new_acc_index,
        "ibm_bufferview": new_bv_index,
        "hem_y": hem_y,
        "band_top": band_top,
    }

    report["mesh_index"] = mesh_index
    report["skin_index"] = skin_index
    report["joints_accessor"] = joints_acc
    report["weights_accessor"] = weights_acc
    report["new_nodes"] = 3 * n_chains
    return bin_data, report


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate_output(output_path, input_path, report):
    gltf, bin_data = read_glb(output_path)
    src_gltf, src_bin = read_glb(input_path)
    problems = []

    n_nodes = len(gltf["nodes"])

    def check_node(i, what):
        if not isinstance(i, int) or not (0 <= i < n_nodes):
            problems.append(f"{what}: node index {i} out of range")

    for si, scene in enumerate(gltf.get("scenes", [])):
        for i in scene.get("nodes", []):
            check_node(i, f"scene {si}")
    for ni, node in enumerate(gltf["nodes"]):
        for c in node.get("children", []):
            check_node(c, f"node {ni} children")

    # buffer views / accessors within bounds
    blen = gltf["buffers"][0]["byteLength"]
    if blen != len(bin_data):
        problems.append(f"buffer byteLength {blen} != BIN chunk {len(bin_data)}")
    for bi, bv in enumerate(gltf["bufferViews"]):
        if bv.get("byteOffset", 0) + bv["byteLength"] > len(bin_data):
            problems.append(f"bufferView {bi} exceeds buffer")
    for ai in range(len(gltf["accessors"])):
        acc = gltf["accessors"][ai]
        if "bufferView" not in acc:
            continue
        _, end = accessor_byte_range(gltf, ai)
        bv = gltf["bufferViews"][acc["bufferView"]]
        if end > bv.get("byteOffset", 0) + bv["byteLength"]:
            problems.append(f"accessor {ai} exceeds its bufferView")

    # skins
    for si, skin in enumerate(gltf["skins"]):
        for j in skin["joints"]:
            check_node(j, f"skin {si} joints")
        ibm = gltf["accessors"][skin["inverseBindMatrices"]]
        if ibm["count"] != len(skin["joints"]):
            problems.append(
                f"skin {si}: IBM count {ibm['count']} != joints {len(skin['joints'])}"
            )

    # springbone refs + chain integrity
    sb = gltf["extensions"]["VRMC_springBone"]
    n_collider_groups = len(sb.get("colliderGroups", []))
    for s in sb["springs"]:
        prev = None
        for j in s.get("joints", []):
            check_node(j.get("node"), f"spring {s.get('name')}")
            if prev is not None and j["node"] not in gltf["nodes"][prev].get("children", []):
                problems.append(f"spring {s.get('name')}: joint {j['node']} not a child of {prev}")
            prev = j["node"]
        for group_index in s.get("colliderGroups", []):
            if type(group_index) is not int or not (0 <= group_index < n_collider_groups):
                problems.append(
                    f"spring {s.get('name')}: collider group {group_index!r} out of range"
                )
    for c in sb.get("colliders", []):
        check_node(c.get("node"), "collider")
    if len(sb["springs"]) != report["springs_after"]:
        problems.append("spring count does not match report")

    injected_springs = [
        spring for spring in sb["springs"]
        if str(spring.get("name", "")).startswith(INJECT_PREFIX)
    ]
    if len(injected_springs) != len(report["chains"]):
        problems.append("injected hoodie spring count does not match chain report")
    expected_groups = report["hoodie_collider_groups"]
    for spring in injected_springs:
        if spring.get("colliderGroups") != expected_groups:
            problems.append(
                f"spring {spring.get('name')}: hoodie collider groups do not match report"
            )
    try:
        verified_groups = select_hoodie_collider_groups(gltf)
    except InjectError as exc:
        problems.append(f"hoodie collider verification failed: {exc}")
    else:
        if verified_groups != expected_groups:
            problems.append("hoodie collider groups are not the verified safe set")
        try:
            parent = build_parent_map(gltf)
            chain_roots_world = [
                mat4_apply(
                    world_matrix(gltf, parent, spring["joints"][0]["node"]),
                    [0.0, 0.0, 0.0],
                )
                for spring in injected_springs
            ]
            require_hoodie_collider_reach(
                gltf, expected_groups, chain_roots_world
            )
        except (InjectError, KeyError, IndexError, TypeError, ValueError) as exc:
            problems.append(f"hoodie collider spatial validation failed: {exc}")

    # weights of the body mesh: all joints in range, sums == 1
    skin = gltf["skins"][report["skin_index"]]
    joints = read_accessor(gltf, bin_data, report["joints_accessor"])
    weights = read_accessor(gltf, bin_data, report["weights_accessor"])
    n_joints = len(skin["joints"])
    bad_sum = bad_joint = 0
    for vi in range(len(joints)):
        s = sum(weights[vi])
        if abs(s - 1.0) > 2e-3:
            bad_sum += 1
        if any(w < -1e-6 for w in weights[vi]):
            bad_sum += 1
        for j, w in zip(joints[vi], weights[vi]):
            if w > 1e-8 and not (0 <= j < n_joints):
                bad_joint += 1
    if bad_sum:
        problems.append(f"{bad_sum} vertices with bad weight sums")
    if bad_joint:
        problems.append(f"{bad_joint} influences referencing out-of-range joints")

    # locked-design guarantees: visible asset JSON identical to input
    for key in ("materials", "textures", "images", "samplers", "meshes"):
        if gltf.get(key) != src_gltf.get(key):
            problems.append(f"{key} changed vs input (locked design violation)")
    if gltf["extensions"].get("VRMC_vrm") != src_gltf["extensions"].get("VRMC_vrm"):
        problems.append("VRMC_vrm changed vs input")

    # BIN identical to input except JOINTS_0/WEIGHTS_0 slices + appended tail
    allowed = []
    for acc in (report["joints_accessor"], report["weights_accessor"]):
        allowed.append(accessor_byte_range(src_gltf, acc))
    cursor = 0
    src_view, out_view = memoryview(src_bin), memoryview(bin_data)
    for a, b in sorted(allowed):
        if src_view[cursor:a] != out_view[cursor:a]:
            problems.append(f"unexpected BIN change in [{cursor},{a})")
        cursor = b
    if src_view[cursor:len(src_bin)] != out_view[cursor:len(src_bin)]:
        problems.append(f"unexpected BIN change in [{cursor},{len(src_bin)})")

    return problems


def run_three_check(output_path, script_dir):
    """Load the output through the same three-vrm runtime House HQ uses."""
    check_js = os.path.join(script_dir, "check_vrm_three.mjs")
    node_modules = os.path.join(
        os.path.dirname(script_dir), "apps", "house-hq", "node_modules"
    )
    if not os.path.isfile(check_js) or not os.path.isdir(node_modules):
        return None, "three-vrm check skipped (check_vrm_three.mjs or house-hq node_modules missing)"
    try:
        proc = subprocess.run(
            ["node", check_js, output_path, node_modules],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"three-vrm check skipped ({exc})"
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inject hoodie-hem sway spring bones into a VRoid VRM 1.0 export.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--input", required=True, help="fresh VRoid .vrm export (never modified)")
    ap.add_argument("--output", required=True, help="where to write the injected copy")
    ap.add_argument("--chains", type=int, default=6, help="number of hem chains")
    ap.add_argument("--band-height", type=float, default=0.12,
                    help="hem band height in meters (weights fade to 0 at the top)")
    ap.add_argument("--max-weight", type=float, default=0.6,
                    help="max injected skin weight at the hem edge (subtlety > drama)")
    ap.add_argument("--tail-drop", type=float, default=0.04,
                    help="how far the chain tail hangs below the hem edge (m)")
    ap.add_argument("--stiffness", type=float, default=0.6)
    ap.add_argument("--drag-force", type=float, default=0.15)
    ap.add_argument("--gravity-power", type=float, default=0.05)
    ap.add_argument("--hit-radius", type=float, default=0.02)
    ap.add_argument("--tops-material-regex", default=r"Tops_.*CLOTH",
                    help="regex matched against material names to find the hoodie")
    ap.add_argument("--allow-live-dir", action="store_true",
                    help="allow writing into a data/avatar/vrm directory (NOT recommended; "
                         "promotion should be a manual copy after visual QA)")
    ap.add_argument("--no-three-check", action="store_true",
                    help="skip the optional three-vrm load test")
    args = ap.parse_args(argv)

    in_path = os.path.abspath(args.input)
    out_path = os.path.abspath(args.output)
    if not os.path.isfile(in_path):
        ap.error(f"input not found: {in_path}")
    if os.path.normcase(in_path) == os.path.normcase(out_path):
        ap.error("refusing to overwrite the input file; pick a different --output")
    live_marker = os.path.normcase(os.path.join("data", "avatar", "vrm"))
    if live_marker in os.path.normcase(out_path) and not args.allow_live_dir:
        ap.error(
            "refusing to write into data/avatar/vrm (the live model dir; the server "
            "serves sorted(glob)[0] from there). Promote manually after visual QA, "
            "or pass --allow-live-dir if you really mean it."
        )
    if not (0.0 < args.max_weight <= 1.0):
        ap.error("--max-weight must be in (0, 1]")
    if args.chains < 3:
        ap.error("--chains must be >= 3")

    gltf, bin_data = read_glb(in_path)

    bin_data, strip_info = strip_previous_injection(gltf, bin_data)
    if strip_info:
        print(f"[strip] {strip_info}")

    bin_data, report = inject(gltf, bin_data, args)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    write_glb(out_path, gltf, bin_data)

    problems = validate_output(out_path, in_path, report)

    print("[inject] hoodie hem sway injection")
    print(f"  input : {in_path}")
    print(f"  output: {out_path} ({os.path.getsize(out_path):,} bytes)")
    print(f"  hem band: y {report['hem_y']:.4f} .. {report['band_top']:.4f} "
          f"({report['band_verts']} candidate verts)")
    print(f"  chains ({args.chains}, 3 joints each, parented under hips):")
    for label, pos in report["chains"]:
        print(f"    {INJECT_PREFIX}_{label} root at {pos}")
    print(f"  springs: {report['springs_before']} -> {report['springs_after']}")
    print(
        "  hoodie collider groups: "
        + ", ".join(
            f"{name} [{index}]"
            for name, index in zip(
                report["hoodie_collider_group_names"],
                report["hoodie_collider_groups"],
            )
        )
    )
    print(
        "  hoodie collider max root gap: "
        f"{report['hoodie_collider_max_root_gap']:.4f} m "
        f"(limit {MAX_HOODIE_COLLIDER_ROOT_GAP_METERS:.3f} m)"
    )
    print(f"  re-weighted verts: {report['touched_verts']} "
          f"(max injected weight {report['max_injected_weight']:.3f}, "
          f"{report['single_chain_verts']} snapped to a single chain, "
          f"{report['dropped_influences']} had their smallest original influence dropped)")

    if problems:
        print("[FAIL] validation problems:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("[ok] structural validation passed "
          "(glTF bounds, skins, springs, weight sums, locked-design JSON+BIN diff)")

    if not args.no_three_check:
        ok, msg = run_three_check(out_path, os.path.dirname(os.path.abspath(__file__)))
        if ok is None:
            print(f"[skip] {msg}")
        elif ok:
            print(f"[ok] three-vrm load test passed:\n{msg}")
        else:
            print(f"[FAIL] three-vrm load test:\n{msg}")
            return 1

    print("\nNext: visual QA. To promote (manual, only after QA -- filename must sort")
    print("FIRST in data/avatar/vrm because the server serves sorted(glob)[0]):")
    print(f"  Copy-Item \"{out_path}\" \"data\\avatar\\vrm\\alpecca.vrm\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())

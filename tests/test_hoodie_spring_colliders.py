from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import inject_hoodie_sway_physics as injector


CHAIN_LABELS = ("BackR", "SideR", "FrontR", "FrontL", "SideL", "BackL")
LOCKED_DESIGN_KEYS = ("materials", "textures", "images", "samplers", "meshes")


def _sphere(
    node: int,
    *,
    offset: list[float] | None = None,
    radius: float = 0.1,
) -> dict:
    return {
        "node": node,
        "shape": {
            "sphere": {
                "offset": offset or [0.0, 0.0, 0.0],
                "radius": radius,
            }
        },
    }


def _capsule(node: int) -> dict:
    return {
        "node": node,
        "shape": {
            "capsule": {
                "offset": [-0.1, 0.0, 0.0],
                "tail": [0.1, 0.0, 0.0],
                "radius": 0.02,
            }
        },
    }


def _synthetic_vrm_json() -> dict:
    return {
        "nodes": [
            {"name": "Root", "translation": [0.0, 0.0, 0.0], "children": [1]},
            {"name": "J_Bip_C_Hips", "translation": [0.0, 0.9, 0.0], "children": [2]},
            {"name": "J_Bip_C_Spine", "translation": [0.0, 0.1, 0.0]},
            {"name": "J_Bip_C_Head", "translation": [0.0, 1.4, 0.0]},
            {"name": "HairAccessory", "translation": [0.0, 1.5, 0.0]},
        ],
        "materials": [{"name": "Tops_01_CLOTH", "extras": {"locked": True}}],
        "textures": [{"source": 0}],
        "images": [{"name": "alpecca_locked.png"}],
        "samplers": [{"magFilter": 9729}],
        "meshes": [{"name": "Body", "primitives": [{"material": 0}]}],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "humanoid": {
                    "humanBones": {
                        "hips": {"node": 1},
                        "spine": {"node": 2},
                        "head": {"node": 3},
                    }
                },
            },
            "VRMC_springBone": {
                "colliders": [_sphere(3), _sphere(2), _sphere(4), _sphere(1)],
                "colliderGroups": [
                    {"name": "J_Bip_C_Head", "colliders": [0]},
                    {"name": "J_Bip_C_Spine", "colliders": [1]},
                    {"name": "HairAccessory", "colliders": [2]},
                    {"name": "J_Bip_C_Hips", "colliders": [3]},
                ],
                "springs": [],
            },
        },
    }


def _spring_args() -> SimpleNamespace:
    return SimpleNamespace(
        hit_radius=0.02,
        stiffness=0.6,
        gravity_power=0.05,
        drag_force=0.15,
    )


def _inject_args() -> SimpleNamespace:
    return SimpleNamespace(
        chains=6,
        band_height=0.12,
        max_weight=0.6,
        tail_drop=0.04,
        stiffness=0.6,
        drag_force=0.15,
        gravity_power=0.05,
        hit_radius=0.02,
        tops_material_regex=r"Tops_.*CLOTH",
    )


def test_selects_deterministic_safe_hem_body_groups():
    document = _synthetic_vrm_json()

    first = injector.select_hoodie_collider_groups(document)
    second = injector.select_hoodie_collider_groups(copy.deepcopy(document))

    assert first == second == [3, 1]
    groups = document["extensions"]["VRMC_springBone"]["colliderGroups"]
    assert [groups[index]["name"] for index in first] == [
        "J_Bip_C_Hips",
        "J_Bip_C_Spine",
    ]


def test_rejects_head_hair_and_spoofed_spine_groups():
    document = _synthetic_vrm_json()
    spring_bone = document["extensions"]["VRMC_springBone"]
    spring_bone["colliderGroups"] = [
        {"name": "J_Bip_C_Head", "colliders": [0]},
        {"name": "HairAccessory", "colliders": [2]},
        # An allowlisted name is insufficient when attached to the head node.
        {"name": "J_Bip_C_Spine", "colliders": [0]},
    ]

    with pytest.raises(injector.InjectError, match="no safe hoodie body collider"):
        injector.select_hoodie_collider_groups(document)


def test_identity_selection_does_not_substitute_for_spatial_reach():
    document = _synthetic_vrm_json()
    selected = injector.select_hoodie_collider_groups(document)
    spring_bone = document["extensions"]["VRMC_springBone"]
    spring_bone["colliders"][1] = _sphere(2, offset=[0.0, 2.0, 0.0])
    spring_bone["colliders"][3] = _sphere(1, offset=[0.0, 2.0, 0.0])

    assert injector.select_hoodie_collider_groups(document) == selected == [3, 1]
    with pytest.raises(injector.InjectError, match="spatially ineffective"):
        injector.require_hoodie_collider_reach(
            document,
            selected,
            [[-0.08, 0.92, 0.0], [0.08, 0.92, 0.0]],
        )


def test_spatial_reach_measures_sphere_and_capsule_volumes_in_world_space():
    document = _synthetic_vrm_json()
    selected = injector.select_hoodie_collider_groups(document)
    roots = [
        [-0.08, 0.92, 0.0],
        [0.08, 0.92, 0.0],
        [0.0, 0.92, 0.06],
    ]

    sphere_gaps = injector.require_hoodie_collider_reach(
        document, selected, roots
    )
    assert sphere_gaps == [0.0, 0.0, 0.0]
    assert injector.require_hoodie_collider_reach(
        document, [3], [[0.12, 0.9, 0.0]]
    ) == pytest.approx([0.02])
    with pytest.raises(injector.InjectError, match="spatially ineffective"):
        injector.require_hoodie_collider_reach(
            document, [3], [[0.126, 0.9, 0.0]]
        )

    spring_bone = document["extensions"]["VRMC_springBone"]
    spring_bone["colliders"][3] = _capsule(1)
    capsule_gaps = injector.require_hoodie_collider_reach(
        document, [3], [[-0.08, 0.92, 0.0], [0.08, 0.92, 0.0]]
    )
    assert capsule_gaps == pytest.approx([0.0, 0.0], abs=1e-12)


def test_real_v4_is_rejected_when_selected_collider_cannot_reach_hem_roots():
    real_v4 = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "avatar"
        / "vrm"
        / "alpecca_vroid_prototype_v4_20260709.vrm"
    )
    if not real_v4.is_file():
        pytest.skip("local real V4 fixture is unavailable")

    document, binary = injector.read_glb(real_v4)
    binary, _ = injector.strip_previous_injection(document, binary)
    selected = injector.select_hoodie_collider_groups(document)
    groups = document["extensions"]["VRMC_springBone"]["colliderGroups"]

    assert [groups[index]["name"] for index in selected] == ["J_Bip_C_Spine"]
    with pytest.raises(injector.InjectError, match="spatially ineffective"):
        injector.inject(document, binary, _inject_args())


def test_six_spring_assignment_preserves_design_and_bone_transforms():
    document = _synthetic_vrm_json()
    locked_before = {
        key: copy.deepcopy(document[key]) for key in LOCKED_DESIGN_KEYS
    }
    nodes_before = copy.deepcopy(document["nodes"])
    vrm_before = copy.deepcopy(document["extensions"]["VRMC_vrm"])
    selected = injector.select_hoodie_collider_groups(document)

    injector.append_hoodie_springs(
        document["extensions"]["VRMC_springBone"],
        node_start=20,
        chain_labels=CHAIN_LABELS,
        args=_spring_args(),
        collider_group_indices=selected,
    )

    springs = document["extensions"]["VRMC_springBone"]["springs"]
    assert len(springs) == 6
    for chain_index, spring in enumerate(springs):
        base = 20 + 3 * chain_index
        assert spring["colliderGroups"] == [3, 1]
        assert [joint["node"] for joint in spring["joints"]] == [
            base,
            base + 1,
            base + 2,
        ]

    assert document["nodes"] == nodes_before
    assert document["extensions"]["VRMC_vrm"] == vrm_before
    for key, value in locked_before.items():
        assert document[key] == value

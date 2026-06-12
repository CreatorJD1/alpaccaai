"""alpecca_rigger — modular Live2D auto-rigging + posing tool for the Alpecca AI.

Quick start:
    from alpecca_rigger import build_rig, Pose, render_pose, list_poses

    rig = build_rig("alpecca.psd")          # classify + analyze
    rig.save_rig_json("alpecca.rig.json")   # rig descriptor
    rig.export_parts("parts/")              # per-part PNGs in draw order

    pose = Pose().pose("Wave").expression("Happy")
    render_pose(rig, pose, scale=0.5).save("wave.png")
    pose.save("alpecca.rigpose.json")
"""
from .rig import Rig, build_rig
from .pose import Pose, list_poses, list_expressions, EXPRESSIONS, POSES, DEFAULTS
from .render import render_pose
from .classify import classify, analyze, detect_side
from ._schema import SCHEMA, PARAM_DEFS, FOLDER_ORDER, PROFILE

__version__ = "1.0.0"
__all__ = ["Rig", "build_rig", "Pose", "render_pose", "classify", "analyze",
           "detect_side", "list_poses", "list_expressions", "EXPRESSIONS", "POSES",
           "DEFAULTS", "SCHEMA", "PARAM_DEFS", "FOLDER_ORDER", "PROFILE", "__version__"]

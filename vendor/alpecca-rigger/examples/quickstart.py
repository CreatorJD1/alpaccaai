"""Minimal end-to-end example. Run:  python examples/quickstart.py path/to/alpecca.psd"""
import sys
from alpecca_rigger import build_rig, Pose, render_pose, list_poses, list_expressions

psd = sys.argv[1] if len(sys.argv) > 1 else "alpecca.psd"

rig = build_rig(psd)                              # classify + analyze the PSD
print("Rigged %d parts (%dx%d)" % (len(rig.parts), rig.width, rig.height))
rig.save_rig_json("alpecca.rig.json")            # rig descriptor for your AI
rig.save_manifest("alpecca.manifest.json")       # full Cubism rig plan
rig.export_parts("parts")                        # per-part PNGs in draw order

print("Poses:", ", ".join(list_poses()))
print("Expressions:", ", ".join(list_expressions()))

# build a pose the way the AI would, then render + persist it
pose = Pose().pose("Present Information").expression("Warm Smile")
render_pose(rig, pose, scale=0.5, background=(0, 0, 0, 0)).save("alpecca_present.png")
pose.save("alpecca.rigpose.json")
print("Wrote alpecca_present.png + alpecca.rigpose.json")

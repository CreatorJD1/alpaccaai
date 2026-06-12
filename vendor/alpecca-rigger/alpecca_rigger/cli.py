"""Command line interface:  python -m alpecca_rigger <command>"""
import argparse, os, sys
from . import build_rig, Pose, render_pose, list_poses, list_expressions


def main(argv=None):
    ap = argparse.ArgumentParser(prog="alpecca_rigger", description="Alpecca Live2D auto-rigger")
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("rig", help="classify a PSD and export rig data")
    r.add_argument("psd")
    r.add_argument("-o", "--out", default="rig_out")

    p = sub.add_parser("pose", help="render a posed PNG")
    p.add_argument("psd")
    p.add_argument("pose", help="a pose name (see 'list') or a .rigpose.json path")
    p.add_argument("-e", "--expression", default=None)
    p.add_argument("-o", "--out", default="pose.png")
    p.add_argument("-s", "--scale", type=float, default=1.0)

    sub.add_parser("list", help="list available poses and expressions")

    a = ap.parse_args(argv)
    if a.cmd == "rig":
        rig = build_rig(a.psd)
        os.makedirs(a.out, exist_ok=True)
        base = os.path.splitext(os.path.basename(a.psd))[0]
        rig.save_rig_json(os.path.join(a.out, base + ".rig.json"))
        rig.save_manifest(os.path.join(a.out, base + ".manifest.json"))
        rig.export_parts(os.path.join(a.out, "parts"))
        print("rig: %d parts -> %s" % (len(rig.parts), a.out))
    elif a.cmd == "pose":
        rig = build_rig(a.psd)
        if a.pose.endswith(".json") and os.path.exists(a.pose):
            pose = Pose.load(a.pose)
        else:
            pose = Pose().pose(a.pose)
        if a.expression:
            pose.expression(a.expression)
        render_pose(rig, pose, scale=a.scale).save(a.out)
        print("pose -> %s" % a.out)
    elif a.cmd == "list":
        print("Poses:", ", ".join(list_poses()))
        print("Expressions:", ", ".join(list_expressions()))
    else:
        ap.print_help()


if __name__ == "__main__":
    main(sys.argv[1:])

"""Runtime pose renderer (Pillow). Composites the classified parts in draw order
and rotates arm limbs about the shoulder and the head group about the neck, so
the Alpecca AI can render posed frames programmatically.

Note: this is an approximate runtime renderer (rigid limb rotation, no per-pixel
elbow mesh). The browser tool (web/) has the full mesh-skinned deformation; this
module covers companion gestures (arms up/down, wave, present, celebrate, etc.)."""
from PIL import Image

ARM_UP, ARM_BEND = 80.0, 100.0
HEAD_FOLDERS = {"Face", "Eyes", "Brows", "Mouth", "Hair Front", "Accessory", "Hair Back"}


def _shoulder(part, W):
    b = part["bbox"]; cx = W / 2.0
    center = (b["left"] + b["right"]) / 2.0
    inner_x = b["left"] if center > cx else b["right"]
    return (inner_x, (b["top"] + b["bottom"]) / 2.0)


def _arm_deg(part, P):
    side = part["cls"]["side"]
    up = -1 if side == "L" else 1
    a = max(-100.0, min(100.0, P.get("ParamArm" + side + "A", 0) * ARM_UP))
    b = max(-5.0, min(135.0, P.get("ParamArm" + side + "B", 0) * ARM_BEND))
    # shoulder rotation dominant; add a fraction of the elbow bend (rigid approx)
    return -(a + 0.45 * b) * up   # PIL rotate is CCW; negate to match canvas/screen


def render_pose(rig, pose, scale=1.0, background=None):
    P = pose.params if hasattr(pose, "params") else dict(pose)
    hand_front = pose.handFront if hasattr(pose, "handFront") else {"L": False, "R": False}
    W, H = rig.width, rig.height
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    neck = next((p for p in rig.parts if p["cls"]["key"] == "neck"), None)
    head_pivot = (neck["pivot"]["x"], neck["bbox"]["top"]) if neck else (W // 2, int(H * 0.5))
    head_z = P.get("ParamAngleZ", 0)

    def place(part):
        img = rig.part_image(part)
        b = part["bbox"]
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.paste(img, (b["left"], b["top"]), img)
        key, side = part["cls"]["key"], part["cls"]["side"]
        if key == "handwear" and side:
            deg = _arm_deg(part, P)
            if abs(deg) > 1e-6:
                layer = layer.rotate(deg, center=_shoulder(part, W), resample=Image.BICUBIC)
        elif part["cls"]["folder"] in HEAD_FOLDERS and key != "neck" and abs(head_z) > 1e-6:
            layer = layer.rotate(head_z, center=head_pivot, resample=Image.BICUBIC)
        canvas.alpha_composite(layer)

    deferred, flushed = [], [False]
    for p in rig.ordered:
        if not flushed[0] and p["cls"]["order"] >= 44:
            for d in deferred:
                place(d)
            deferred, flushed[0] = [], True
        if p["cls"]["key"] == "handwear" and p["cls"]["side"] and hand_front.get(p["cls"]["side"]):
            deferred.append(p); continue
        place(p)
    for d in deferred:
        place(d)

    if background:
        bg = Image.new("RGBA", (W, H), background)
        bg.alpha_composite(canvas); canvas = bg
    if scale != 1.0:
        canvas = canvas.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    return canvas

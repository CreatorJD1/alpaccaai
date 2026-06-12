"""Layer classification + rig analysis. Faithful port of the web engine
(rigcore.js): longest-keyword-wins matching, side detection, draw-order grouping."""
import re
from ._schema import SCHEMA, PARAM_DEFS, FOLDER_ORDER


def detect_side(raw):
    n = " " + re.sub(r"[_\-]", " ", raw.lower()) + " "
    if re.search(r"(^|[ (\[])left([ )\]]|$)", n) or "左" in raw:
        return "L"
    if re.search(r"(^|[ (\[])right([ )\]]|$)", n) or "右" in raw:
        return "R"
    m = re.search(r"[ _\-]([lr])(?:[ _\-.)]|$)", raw.lower())
    return m.group(1).upper() if m else None


def classify(name):
    lower = " " + re.sub(r"[_\-]+", " ", name.lower()) + " "
    best, best_len = None, 0
    for key, rule in SCHEMA.items():
        for kw in rule["kw"]:
            latin = bool(re.search(r"[a-z0-9]", kw))
            found = ((" " + kw + " ") in lower or kw in lower) if latin else (kw in name)
            if found and len(kw) > best_len:
                best, best_len = key, len(kw)
    side = detect_side(name)
    if not best:
        return dict(key=None, label="Unclassified", folder="Unsorted", order=200,
                    side=side, params=[], deformer=None, mesh="medium", confidence=0.0)
    s = SCHEMA[best]

    def sub(arr):
        if not side:
            return [p for p in arr if "{S}" not in p]
        return [p.replace("{S}", side) for p in arr]

    order = s["order"] + (0.2 if side == "R" else 0.1 if side == "L" else 0)
    deformer = s["deformer"].replace("{S}", side or "").rstrip("_") if s.get("deformer") else None
    return dict(key=best, label=s["label"], folder=s["folder"], order=order,
                side=(side if s.get("side") else None), params=sub(s["params"]),
                deformer=deformer, mesh=s["mesh"], confidence=min(1.0, best_len / 6.0))


def _part_name(cls, taken):
    base = cls["label"] + ((" " + cls["side"]) if cls["side"] else "")
    name, i = base, 2
    while name in taken:
        name, i = base + " " + str(i), i + 1
    taken.add(name)
    return name


def analyze(layers, canvas=None, reorder=True):
    """layers: list of dicts with name,left,top,right,bottom. Returns rig dict."""
    taken = set()
    parts = []
    for idx, l in enumerate(layers):
        cls = classify(l["name"])
        parts.append(dict(
            index=idx, original=l["name"],
            bbox=dict(left=l["left"], top=l["top"], right=l["right"], bottom=l["bottom"]),
            pivot=dict(x=round((l["left"] + l["right"]) / 2), y=round((l["top"] + l["bottom"]) / 2)),
            cls=cls, partName=_part_name(cls, taken), drawOrder=cls["order"], origStack=idx))
    ordered = sorted(parts, key=(lambda p: (p["drawOrder"], p["origStack"])) if reorder
                     else (lambda p: p["origStack"]))
    for i, p in enumerate(ordered):
        p["finalStack"] = i
    by_folder = {}
    for p in ordered:
        by_folder.setdefault(p["cls"]["folder"], []).append(p)
    fo = {f: i for i, f in enumerate(FOLDER_ORDER)}
    folders = [dict(name=f, parts=by_folder[f])
               for f in sorted(by_folder, key=lambda f: fo.get(f, 100))]
    return dict(parts=parts, ordered=ordered, folders=folders,
                manifest=build_manifest(ordered, canvas))


def build_manifest(ordered, canvas=None):
    used = {}
    for p in ordered:
        for pid in p["cls"]["params"]:
            used[pid] = True
    if any(p["cls"]["folder"] == "Face" or p["cls"]["key"] == "mouth" for p in ordered):
        for pid in ("ParamAngleX", "ParamAngleY", "ParamAngleZ"):
            used[pid] = True
    parameters = []
    for pid in used:
        d = PARAM_DEFS.get(pid, dict(name=pid, group="Misc", min=-1, max=1, **{"def": 0}))
        parameters.append(dict(id=pid, name=d["name"], group=d["group"],
                               min=d["min"], max=d["max"], default=d["def"]))
    defmap = {}
    for p in ordered:
        if p["cls"]["deformer"]:
            defmap.setdefault(p["cls"]["deformer"], []).append(p["partName"])
    deformers = [dict(id=k, affects=v) for k, v in defmap.items()]
    return dict(
        meta=dict(generator="alpecca_rigger", version="1.0", canvas=canvas, partCount=len(ordered),
                  note="The .moc3 binary is proprietary to Live2D Cubism Editor and cannot be "
                       "generated outside it. Use the cleaned parts + this manifest to finish rigging."),
        parameters=parameters, deformerTree=deformers,
        parts=[dict(id=p["partName"], folder=p["cls"]["folder"], category=p["cls"]["key"] or "unsorted",
                    side=p["cls"]["side"], original=p["original"], drawOrder=p["finalStack"],
                    bbox=p["bbox"], pivot=p["pivot"], deformer=p["cls"]["deformer"],
                    bind=p["cls"]["params"], meshDensity=p["cls"]["mesh"],
                    confidence=round(p["cls"]["confidence"], 2)) for p in ordered],
        drawOrder=[p["partName"] for p in ordered])

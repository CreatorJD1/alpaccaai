"""Read a character PSD, classify it, and build a Rig (parts + images + manifest)."""
import os, json
from psd_tools import PSDImage
from .classify import analyze


def _collect(node, out):
    for layer in node:
        if layer.is_group():
            _collect(layer, out)
        else:
            try:
                img = layer.composite()
            except Exception:
                img = None
            if img is None:
                continue
            l, t, r, b = layer.bbox
            if r <= l or b <= t:
                continue
            out.append(dict(name=layer.name, left=l, top=t, right=r, bottom=b,
                            image=img.convert("RGBA")))


class Rig:
    """Classified character rig. .parts[i] has partName/cls/bbox/image; .manifest holds the spec."""
    def __init__(self, psd_path, reorder=True):
        psd = PSDImage.open(psd_path)
        self.width, self.height = psd.width, psd.height
        self.source = psd_path
        layers = []
        _collect(psd, layers)
        self._images = [l.pop("image") for l in layers]
        self.result = analyze(layers, canvas=dict(width=self.width, height=self.height), reorder=reorder)
        self.parts = self.result["parts"]
        self.manifest = self.result["manifest"]
        for p in self.parts:
            p["image"] = self._images[p["index"]]

    # -- convenience views --
    @property
    def ordered(self):
        return self.result["ordered"]

    def part_image(self, part):
        return self._images[part["index"]]

    # -- exports --
    def save_manifest(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

    def save_rig_json(self, path):
        """A compact rig descriptor (parts, folders, draw order, parameters, bones-free)."""
        rj = dict(character=os.path.splitext(os.path.basename(self.source))[0],
                  canvas=dict(width=self.width, height=self.height),
                  folders=[dict(name=fo["name"], parts=[p["partName"] for p in fo["parts"]])
                           for fo in self.result["folders"]],
                  drawOrder=self.manifest["drawOrder"],
                  parameters=self.manifest["parameters"],
                  parts=self.manifest["parts"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rj, f, indent=2)

    def export_parts(self, out_dir):
        """Write each classified part as a trimmed PNG named by its part name + draw order."""
        os.makedirs(out_dir, exist_ok=True)
        index = []
        for p in self.ordered:
            safe = p["partName"].replace("/", "-").replace(" ", "_")
            fn = "%02d_%s.png" % (p["finalStack"], safe)
            self._images[p["index"]].save(os.path.join(out_dir, fn))
            index.append(dict(file=fn, part=p["partName"], folder=p["cls"]["folder"],
                              drawOrder=p["finalStack"],
                              offset=[p["bbox"]["left"], p["bbox"]["top"]]))
        with open(os.path.join(out_dir, "parts.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
        return index


def build_rig(psd_path, reorder=True):
    return Rig(psd_path, reorder=reorder)

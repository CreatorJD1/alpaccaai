"""Pose / expression model + .rigpose.json IO. Pulls the named libraries from the
Alpecca profile so the AI can drive the character by name."""
import json
from ._schema import PROFILE

DEFAULTS = dict(
    ParamAngleX=0, ParamAngleY=0, ParamAngleZ=0,
    ParamEyeLOpen=1, ParamEyeROpen=1, ParamEyeLSmile=0, ParamEyeRSmile=0,
    ParamEyeBallX=0, ParamEyeBallY=0,
    ParamBrowLY=0, ParamBrowRY=0, ParamBrowLForm=0, ParamBrowRForm=0,
    ParamMouthOpenY=0, ParamMouthForm=0,
    ParamBodyAngleX=0, ParamBodyAngleY=0, ParamBodyAngleZ=0, ParamBreath=0,
    ParamArmLA=0, ParamArmLB=0, ParamArmRA=0, ParamArmRB=0,
    ParamLegLA=0, ParamLegLB=0, ParamLegRA=0, ParamLegRB=0)

EXPRESSIONS = PROFILE.get("expressions", {})
POSES = PROFILE.get("poses", {})


class Pose:
    def __init__(self, **params):
        self.params = dict(DEFAULTS)
        self.handFront = dict(L=False, R=False)
        self.set(**params)

    def set(self, **params):
        for k, v in params.items():
            if k in self.params:
                self.params[k] = v
        return self

    def expression(self, name):
        for k, v in EXPRESSIONS.get(name, {}).items():
            if k in self.params:
                self.params[k] = v
        return self

    def pose(self, name):
        m = POSES.get(name, {})
        self.handFront["L"] = bool(m.get("handFrontL"))
        self.handFront["R"] = bool(m.get("handFrontR"))
        for k, v in m.items():
            if k in self.params:
                self.params[k] = v
        return self

    def to_dict(self):
        return dict(tool="alpecca_rigger", kind="rigpose", version=1,
                    params=dict(self.params), handFront=dict(self.handFront))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        p = cls()
        p.set(**d.get("params", {}))
        hf = d.get("handFront", {})
        p.handFront["L"], p.handFront["R"] = bool(hf.get("L")), bool(hf.get("R"))
        return p


def list_poses():
    return list(POSES.keys())


def list_expressions():
    return list(EXPRESSIONS.keys())

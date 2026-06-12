"""Canonical part schema (with the Alpecca profile already merged), loaded from
data/schema.json which is generated from the shared rig engine so the Python
classifier and the web tool stay perfectly in sync."""
import json, os
_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "schema.json"), "r", encoding="utf-8") as f:
    _d = json.load(f)
SCHEMA       = _d["schema"]          # ordered dict: part-key -> rule
PARAM_DEFS   = _d["paramDefs"]
FOLDER_ORDER = _d["folderOrder"]

with open(os.path.join(_DATA, "alpecca.profile.json"), "r", encoding="utf-8") as f:
    PROFILE = json.load(f)

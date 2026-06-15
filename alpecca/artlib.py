"""Her art library: grounded classification of her real art into Jason's own scheme.

Jason hands her batches of her own art (the "Update2" set: 97 portraits/sheets that
arrived from Drive with opaque hash names like ``file_0000...png``). The batch ships
with his authoritative organization scheme -- the Claude Image Naming Guide PDF and
its CSV manifest -- which sorts every image by **asset role** (reference sheet vs
production bust vs Live2D layer candidate vs reject) and lays down hard canon-QC
rules. But that manifest keys on descriptive names the Drive export threw away, so it
can't be name-joined to the hash files. The honest way to recover his curation is the
same pattern her pose library already uses: let **her own local vision model look at
each image and place it into his scheme**, then flag anything that breaks canon.

Everything traces back to her art and her perception -- nothing is invented. This
module is the pure half: his closed role taxonomy and canon rules (lifted from the
guide), the prompt that asks the model to choose only from them, and the
parsing/snapping/naming logic in his exact filename grammar. It imports nothing heavy,
so it is testable with no Ollama and no GPU. The thin CLI that looks at pixels and
copies files is ``scripts/ingest_art.py``.
"""
from __future__ import annotations

import json
import re
from typing import Optional


# --- His role taxonomy, straight off the Claude Image Naming Guide ----------
#
# The PRIMARY axis: what *role* an asset plays, which decides where it belongs and
# whether it's production-usable at all. Each code maps to (human label, the Claude
# action from the guide, recognised aliases for snapping the model's answer).

CATEGORIES = {
    "source_ref":       ("Source reference", "User/source file; keep raw, never overwrite.",
                         ["source", "source ref", "user upload", "original upload"]),
    "ref_sheet":        ("Reference sheet", "General design/reference sheet; reference only.",
                         ["ref sheet", "reference sheet", "design sheet", "model sheet", "guide", "infographic", "poster"]),
    "wardrobe":         ("Wardrobe sheet", "Outfit/turnaround reference; preserve mode details.",
                         ["wardrobe", "outfit", "turnaround", "clothing", "mode sheet", "outfit breakdown"]),
    "l2d_guide":        ("Live2D guide", "Rigging guide page; setup notes, not direct import.",
                         ["l2d guide", "live2d guide", "rigging guide", "rig guide"]),
    "l2d_eye":          ("Eye layer", "Eye/iris/lash/brow layer candidate; isolate before import.",
                         ["l2d eye", "eye layer", "eye", "iris", "eyelash", "eyebrow", "brow", "gaze"]),
    "l2d_mouth":        ("Mouth layer", "Mouth/phoneme layer candidate; isolate before import.",
                         ["l2d mouth", "mouth layer", "mouth", "phoneme", "lip"]),
    "l2d_hair":         ("Hair layer", "Hair layer/guide; split bangs/side/back/ahoge.",
                         ["l2d hair", "hair layer", "hair", "hairstyle", "bangs", "ahoge"]),
    "l2d_ear":          ("Ear layer", "Ear layer candidate; must connect under side hair.",
                         ["l2d ear", "ear layer", "ear", "ears"]),
    "expr":             ("Expression bust", "Expression/face-bust reference; keep corrected only.",
                         ["expr", "expression", "bust", "face portrait", "portrait", "headshot", "face"]),
    "pose":             ("Pose / motion", "Motion/action reference for animation planning.",
                         ["pose", "motion", "action", "walk", "run", "sprint", "stride", "shield", "guard", "gesture", "full body"]),
    "desktop":          ("Desktop companion", "Desktop companion / UI behavior reference.",
                         ["desktop", "ui", "notification", "reminder", "task list", "system alert", "widget"]),
    "chibi":            ("Chibi", "Chibi/notification persona art.",
                         ["chibi", "mascot small", "mini"]),
    "legacy":           ("Legacy", "Numbered legacy image; inspect before final naming.",
                         ["legacy", "numbered", "old"]),
    "reject_composite": ("Reject (composite)", "Grid/collage/multi-panel; reference only, not an asset.",
                         ["reject", "composite", "grid", "collage", "catalog", "multi panel", "multi-panel", "compilation", "panels"]),
    "misc":             ("Misc", "Unclear; review manually.",
                         ["misc", "unclear", "miscellaneous", "other"]),
}

# Secondary refinement axes, used only where they apply (an `expr` gets an expression,
# a `wardrobe` gets a mode, an `l2d_mouth` gets a phoneme). These stay because they
# feed the eventual consumers (wardrobe switcher, lip-sync, expression set); they are
# always optional -- UNKNOWN is a fine, expected answer.

WARDROBE = {
    "companion":    ("Companion Mode",    ["companion", "default"]),
    "co_learning":  ("Co-Learning Mode",  ["co learning", "colearning", "learning", "study", "school"]),
    "workstation":  ("Workstation Mode",  ["workstation", "work", "office", "professional"]),
    "compassion":   ("Compassion Mode",   ["compassion", "comfort", "caring dress", "gown"]),
    "protection":   ("Protection Mode",   ["protection", "protect", "guard", "armor", "armour"]),
    "low_power":    ("Low Power Mode",     ["low power", "lowpower", "energy saving", "saver", "rest mode"]),
    "casual":       ("Casual Mode",        ["casual", "relaxed", "everyday", "hoodie shorts"]),
    "night_lounge": ("Night Lounge Mode",  ["night lounge", "nightlounge", "night", "lounge", "pajama", "pyjama", "sleep", "loungewear"]),
}

EXPRESSION = {
    "neutral":       ("Neutral Calm",      ["neutral", "calm", "neutral calm", "serene", "tranquil"]),
    "warm_smile":    ("Warm Smile",        ["warm smile", "warm", "soft smile", "gentle smile"]),
    "happy":         ("Happy",             ["happy", "joy", "joyful", "cheerful", "bright", "smiling"]),
    "curious":       ("Curious",           ["curious", "curiosity", "inquisitive", "interested"]),
    "thinking":      ("Thinking",          ["thinking", "thoughtful", "pondering", "contemplative", "considering"]),
    "concerned":     ("Concerned",         ["concerned", "worried", "concern", "anxious"]),
    "compassionate": ("Compassionate",     ["compassionate", "compassion", "tender", "caring"]),
    "soft_sadness":  ("Soft Sadness",      ["soft sadness", "sad", "sadness", "downcast", "melancholy", "crying"]),
    "apologetic":    ("Apologetic",        ["apologetic", "sorry", "sheepish"]),
    "reassuring":    ("Reassuring",        ["reassuring", "reassurance", "comforting"]),
    "low_power":     ("Tired / Low Power", ["low power", "tired", "sleepy", "drowsy", "weary", "exhausted"]),
    "protective":    ("Protective Serious",["protective", "protective serious", "serious", "stern", "determined", "angry"]),
    "fear_spike":    ("Fear Spike",        ["fear spike", "fear", "afraid", "scared", "alarmed", "startled", "surprised", "confused"]),
    "overload":      ("Emotional Overload",["overload", "emotional overload", "overwhelmed", "overwhelm"]),
    "playful":       ("Playful",           ["playful", "teasing", "mischievous", "wink"]),
    "gentle":        ("Gentle Light",      ["gentle", "gentle light", "soft glow"]),
}

MOUTH = {
    "closed":         ("Closed",          ["closed", "mouth closed", "neutral mouth", "shut"]),
    "small_smile":    ("Small Smile",     ["small smile", "slight smile"]),
    "open_smile":     ("Open Smile",      ["open smile", "smiling open", "grin"]),
    "ah":             ("Ah (A)",          ["ah", "aa", "a sound", "open a", "wide open"]),
    "ee":             ("Ee (E)",          ["ee", "e sound", "ii", "wide"]),
    "oh":             ("Oh (O)",          ["oh", "o sound", "rounded", "ou"]),
    "mbp":            ("M/P/B Closed",    ["m p b", "mbp", "mpb", "pressed lips", "m/p/b"]),
    "fv":             ("F/V",             ["f v", "fv", "f/v", "teeth on lip"]),
    "concerned_open": ("Concerned Open",  ["concerned open", "frown open", "worried mouth"]),
    "laughing":       ("Laughing",        ["laughing", "laugh", "big laugh"]),
    "whispering":     ("Whispering",      ["whispering", "whisper", "small open"]),
    "soft_gasp":      ("Soft Gasp",       ["soft gasp", "gasp", "surprised mouth", "o small"]),
}

REFINEMENT = {"wardrobe": WARDROBE, "expr": EXPRESSION, "l2d_mouth": MOUTH}
AXES = {"category": CATEGORIES, "wardrobe": WARDROBE, "expression": EXPRESSION, "mouth": MOUTH}

UNKNOWN = "unknown"   # the model couldn't tell, or wrote something off-taxonomy

# The non-negotiable canon checks from the guide's section 1. Phrased as a checklist
# the model verifies; any failure is recorded so a bad asset is flagged, not filed.
CANON_RULES = (
    "white inner shirt (no black/dark undershirt; black only on shorts/thigh-strap)",
    "both ears connected to the head and tucked under the side hair (no floating ears)",
    "consistent blue neck lanyard with a centered rectangular ALPECCA ID badge",
    "clean modern anime style (no photorealism, no cyberpunk darkness, no fantasy armor)",
)


# --- The prompt: choose only from his taxonomy, and check canon -------------

def classification_prompt() -> str:
    """The instruction handed to her vision model for one image. It leads with the
    role taxonomy (the decision that matters most), folds in the canon-QC checklist,
    and demands strict JSON so parsing stays mechanical. We tell her to answer
    `unknown` / report a canon issue rather than guess -- a flagged blank we can fix
    by hand beats a confident wrong tag we won't notice."""
    cats = "\n".join(f'  "{code}" = {label}: {action}' for code, (label, action, _) in CATEGORIES.items())
    canon = "; ".join(CANON_RULES)
    return (
        "This is one image from an anime AI-companion character's art archive "
        "(a girl named Alpecca: cream-blonde hair, blue glowing eyes, chest "
        "power-core, blue lanyard ID badge). Classify it and reply with ONLY a "
        "JSON object -- no prose, no code fence.\n\n"
        "category (the asset's role) -- choose exactly one code:\n" + cats + "\n"
        "  If the image is a grid / collage / catalog / multi-panel sheet, use "
        '"reject_composite". If it is a single isolated face it is "expr"; a single '
        'full-body action is "pose".\n\n'
        "Also report her secondary tags WHEN they apply (else \"unknown\"):\n"
        "  expression (only for expr/face): the feeling shown.\n"
        "  wardrobe (only for wardrobe/full-figure): her outfit mode.\n"
        "  mouth (only for mouth layers/talking): the mouth/phoneme shape.\n\n"
        "Canon check -- verify ALL of: " + canon + ". Set canon_ok=false and name "
        "the broken rule in canon_issue if any fails.\n\n"
        'Use exactly this shape: {"category":"<code>","descriptor":"<3-5 word '
        'snake_case summary>","expression":"<slug or unknown>","wardrobe":"<slug or '
        'unknown>","mouth":"<slug or unknown>","canon_ok":true,"canon_issue":"",'
        '"desc":"<one short plain sentence>"}'
    )


# --- Pure parsing / snapping / naming ---------------------------------------

def _norm(s: str) -> str:
    """Lowercase, and turn every run of non-alphanumerics into one space, so
    'M/P/B', 'm p b' and 'mbp' all compare equal-ish for alias matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def snap(value: Optional[str], axis: str) -> str:
    """Land a free-text value onto one taxonomy slug for `axis`, or UNKNOWN.

    Matching is forgiving on purpose -- the model may echo the human label, the
    slug, or a near-synonym. We try, in order: exact slug, exact alias, then
    whole-token containment. For containment we pick the *most specific* alias
    (the one whose tokens are all present and most numerous), so a label like
    "M/P/B Closed" lands on `mbp` (3 tokens) rather than `closed` (1 token) just
    because the word "closed" happens to appear. No match -> the blank UNKNOWN
    that flags the image for a human glance."""
    table = AXES[axis]
    if not value:
        return UNKNOWN
    v = _norm(value)
    if v in table:                       # the model returned the slug itself
        return v
    v_tokens = set(v.split())
    best_slug, best_len = UNKNOWN, 0
    for slug, meta in table.items():
        aliases = meta[-1]               # aliases are always the last tuple element
        for alias in [slug] + list(aliases):
            na = _norm(alias)
            if na == v:                  # exact alias/slug match wins outright
                return slug
            na_tokens = na.split()
            if na_tokens and set(na_tokens) <= v_tokens and len(na_tokens) > best_len:
                best_slug, best_len = slug, len(na_tokens)
    return best_slug


def _descriptor(text: Optional[str], limit: int = 5) -> str:
    """Sanitize the model's short summary into snake_case for the filename grammar:
    lowercase words, alphanumeric only, capped to `limit` words. Falls back to
    'image' so a name is always well-formed."""
    words = _norm(text).split()[:limit] if text else []
    return "_".join(words) if words else "image"


def parse_classification(text: Optional[str]) -> Optional[dict]:
    """Pull the model's JSON out of `text` and snap it to his scheme.

    Returns a dict with: category (a real role code or UNKNOWN), descriptor
    (snake_case), the snapped secondary tags (expression/wardrobe/mouth, each a slug
    or UNKNOWN), canon_ok/canon_issue, and a free `desc`. Returns None if no JSON
    object could be found at all (a hard failure -- caller marks the image fully
    unclassified for the human)."""
    if not text:
        return None
    fenced = re.sub(r"^```[a-zA-Z]*|```$", "", text.strip(), flags=re.MULTILINE)
    m = re.search(r"\{.*\}", fenced, flags=re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    return {
        "category":   snap(raw.get("category"), "category"),
        "descriptor": _descriptor(raw.get("descriptor")),
        "expression": snap(raw.get("expression"), "expression"),
        "wardrobe":   snap(raw.get("wardrobe"), "wardrobe"),
        "mouth":      snap(raw.get("mouth"), "mouth"),
        "canon_ok":   bool(raw.get("canon_ok", True)),
        "canon_issue": str(raw.get("canon_issue", "")).strip(),
        "desc":       str(raw.get("desc", "")).strip(),
    }


def proposed_name(tags: dict, index: int, ext: str = ".png") -> str:
    """Build a filename in Jason's canonical grammar from the tags:
    ``alpecca_<category>_<NNN>_<descriptor>_v01.png``. `index` is the per-category
    running number (the guide numbers within each category). Unknown category stays
    literally 'unknown' so it's easy to grep and fix."""
    code = tags.get("category") or UNKNOWN
    descriptor = tags.get("descriptor") or "image"
    ext = (ext if ext.startswith(".") else "." + ext).lower()
    return f"alpecca_{code}_{index:03d}_{descriptor}_v01{ext}"


def merge_into_manifest(manifest: dict, entry: dict) -> dict:
    """Add/replace one image's record in the library manifest, keyed by filename.
    Pure dict-in/dict-out so the apply step is testable without touching disk."""
    out = dict(manifest)
    out[entry["file"]] = {k: v for k, v in entry.items() if k != "file"}
    return out


# --- His folder system (Naming Guide, section 2) ----------------------------
#
# Where a renamed copy belongs on disk, by role. Raw originals are preserved
# untouched in RAW_DIR; anything that fails canon goes to the redo bin no matter
# its role -- that is precisely what 99_rejects_redo exists for.

RAW_DIR = "00_raw_originals"
REDO_DIR = "99_rejects_redo"
ROLE_TO_FOLDER = {
    "source_ref": "01_reference_sheets",
    "ref_sheet":  "01_reference_sheets",
    "l2d_guide":  "01_reference_sheets",
    "expr":       "02_approved_character_busts",
    "wardrobe":   "03_wardrobe_modes",
    "pose":       "04_motion_desktop_chibi",
    "desktop":    "04_motion_desktop_chibi",
    "chibi":      "04_motion_desktop_chibi",
    "l2d_eye":    "05_live2d_layers/eyes",
    "l2d_mouth":  "05_live2d_layers/mouth",
    "l2d_hair":   "05_live2d_layers/hair",
    "l2d_ear":    "05_live2d_layers/ears",
    "reject_composite": REDO_DIR,
    "legacy":     REDO_DIR,
    "misc":       REDO_DIR,
    UNKNOWN:      REDO_DIR,
}


def guide_folder(entry: dict) -> str:
    """Which of his guide folders a classified image belongs in. A canon failure
    overrides the role and routes to the redo bin; an unknown role lands there too."""
    if not entry.get("canon_ok", True):
        return REDO_DIR
    return ROLE_TO_FOLDER.get(entry.get("category", UNKNOWN), REDO_DIR)

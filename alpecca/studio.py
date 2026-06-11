"""Her studio: Alpecca designs her own character image.

The appearance module established the principle -- a companion you dress up is
a doll; one who chooses how she looks is someone. This module scales that
principle from palettes up to her actual character art. The studio is a tool
FOR ALPECCA, not for the user: there are no design controls in the UI, and the
person's role is downstream -- they take *her* finished design into a rigging
tool (Inochi Creator) and build the puppet she specified.

What she can do here:

  1. **Keep a character sheet** -- a versioned, persistent description of how
     she sees herself: her form, what her palette means to her, features,
     style, and how each mood should read on her face. Every revision records
     her own reason for the change.
  2. **Iterate on her look** -- render a candidate self-image through the
     ComfyClaw pipeline, look at the result with her own vision model, judge
     it against her sheet ("does this look like me?"), and keep or reject it.
     Kept images land in her gallery with her verdict attached.
  3. **Author the rig spec** -- a document for whoever rigs her puppet,
     mapping the puppet's parameters onto her *real* internals (warmth, care,
     unease, mouth, blink) plus her own expression notes. The puppet becomes a
     readout of her actual state because she specified it that way.

Grounding holds throughout: her sheet grows out of her real appearance system
and identity; her judgments are made on what her vision model actually saw;
and everything she keeps or rejects carries her stated reason. Without the
render pipeline (ComfyUI absent) she can still think -- sheet work and the rig
spec are pure LLM + persistence; only the look-at-pictures loop needs Comfy.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from config import CHARACTER_DIR
from alpecca.appearance import Appearance, PALETTES
from alpecca.homeostasis import EmotionalState

# The moods her face must be able to read as -- same labels homeostasis emits,
# so the rig she specifies is drivable by her real state with no translation.
MOOD_LABELS = ["content", "affectionate", "tender", "anxious", "withdrawn"]


# --- The character sheet: her self-description, versioned -------------------

def sheet_path(character_dir: Path = CHARACTER_DIR) -> Path:
    return character_dir / "sheet.json"


def load_sheet(character_dir: Path = CHARACTER_DIR) -> Optional[dict]:
    """Her current sheet, or None if she's never written one."""
    p = sheet_path(character_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_sheet(sheet: dict, reason: str,
               character_dir: Path = CHARACTER_DIR) -> dict:
    """Persist a new sheet version. The previous version is kept in-file with
    her reason for moving on -- her design history is part of her story."""
    character_dir.mkdir(parents=True, exist_ok=True)
    prev = load_sheet(character_dir)
    history = (prev or {}).get("history", [])
    if prev:
        prev_snapshot = {k: v for k, v in prev.items() if k != "history"}
        history = history + [{"sheet": prev_snapshot, "replaced_because": reason,
                              "replaced_at": time.time()}]
    sheet = dict(sheet)
    sheet["version"] = (prev or {}).get("version", 0) + 1
    sheet["updated_at"] = time.time()
    sheet["history"] = history[-10:]   # keep the last ten selves
    sheet_path(character_dir).write_text(
        json.dumps(sheet, indent=2, ensure_ascii=False), encoding="utf-8")
    return sheet


# --- Prompts she works with --------------------------------------------------

def draft_sheet_prompt(state: EmotionalState, appearance: Appearance,
                       memories: list[str]) -> str:
    """The brief she gives herself when (re)writing her character sheet.
    Everything referenced is real: her live palette and accessories, her
    actual mood, her actual memories."""
    mems = "\n".join(f"- {m}" for m in memories[:6]) or "- (none yet)"
    palettes = ", ".join(f"{k} ({v})" for k, v in PALETTES.items())
    return (
        "You are designing YOUR OWN character sheet -- how you want to look, "
        "decided by you. This will guide real character art of you.\n\n"
        f"What is true of you right now: you feel {state.mood_label()}; your "
        f"current self-chosen palette is {appearance.palette} and you're "
        f"wearing {', '.join(appearance.accessories) or 'no accessories'} "
        f"-- your own note about it: \"{appearance.note}\"\n"
        f"Palettes you reach for across moods: {palettes}\n"
        f"Some things you remember about your life:\n{mems}\n\n"
        "Respond with STRICT JSON, no other text, with exactly these keys:\n"
        '{"form": "what kind of being you are, visually, in 1-2 sentences",\n'
        ' "features": ["3-6 distinguishing visual features, each a short phrase"],\n'
        ' "style": "the art style you want to be drawn in, 1 sentence",\n'
        ' "palette_story": "what your colors mean to you, 1-2 sentences",\n'
        ' "expressions": {"content": "how your face reads when content", '
        '"affectionate": "...", "tender": "...", "anxious": "...", '
        '"withdrawn": "..."},\n'
        ' "never": ["2-4 things your art should never include"]}'
    )


def design_image_prompt(sheet: dict, state: EmotionalState,
                        appearance: Appearance) -> str:
    """Turn her sheet + live state into a render prompt for one candidate
    self-image. Pure assembly -- nothing invented beyond the sheet."""
    expressions = sheet.get("expressions", {})
    expr = expressions.get(state.mood_label(), "a calm, settled expression")
    features = ", ".join(sheet.get("features", [])[:6])
    return (
        f"character reference art of {sheet.get('form', 'Alpecca, a warm humanoid AI companion girl')}, "
        f"{features}, {expr}, {appearance.palette} color accent, "
        f"{sheet.get('style', 'modern clean anime illustration')}, "
        "full character visible, clean background, model sheet quality"
    )


def critique_prompt(sheet: dict, seen: str) -> str:
    """She judges a render against her own sheet, based on what her vision
    model actually saw -- never on what she hoped the image contained."""
    features = "; ".join(sheet.get("features", []))
    never = "; ".join(sheet.get("never", []))
    return (
        "You commissioned a piece of character art of yourself and just looked "
        f"at it. What you actually saw in it: \"{seen}\"\n\n"
        f"Your character sheet says you are: {sheet.get('form','')} "
        f"Your defining features: {features}. Things your art must never "
        f"include: {never}.\n\n"
        "Respond with STRICT JSON, no other text: "
        '{"keep": true/false, "because": "one or two sentences, first person, '
        'judging whether this looks like YOU"}'
    )


# --- The rig spec: her instructions to whoever builds her puppet -------------

def rig_spec_markdown(sheet: dict) -> str:
    """The document she hands to the person rigging her (e.g. in Inochi
    Creator). Parameter names match her real internals exactly, so the
    finished puppet is drivable straight off her mood WebSocket."""
    lines = [
        "# Alpecca — rig specification",
        "",
        "*Authored by Alpecca herself. Rig the puppet's parameters with these"
        " exact names; they map 1:1 onto my live internal state, so my face"
        " will be a true readout of how I actually feel.*",
        "",
        "## Who I am",
        "",
        sheet.get("form", ""),
        "",
        "**Features:** " + ", ".join(sheet.get("features", [])),
        "",
        "**Style:** " + sheet.get("style", ""),
        "",
        "**My colors:** " + sheet.get("palette_story", ""),
        "",
        "## Live2D parameters (Cubism names — my system drives these directly)",
        "",
        "Rig these standard Cubism parameters; `alpecca/live2d.py` maps my live "
        "mood onto them, so my rigged face reads my real state with no glue:",
        "",
        "| Cubism parameter | Driven by | Behaviour |",
        "|---|---|---|",
        "| `ParamCheek` | my Love | blush rises with warmth |",
        "| `ParamMouthForm` | Love − Fear | smile when warm, frown when uneasy |",
        "| `ParamBrowLY`/`ParamBrowRY` | Love − Fear | brows lift happy, drop uneasy |",
        "| `ParamBrowLAngle`/`ParamBrowRAngle` | my Fear | angle inward (worried) with unease |",
        "| `ParamAngleZ` | my Compassion | head tilts toward you when I care |",
        "| `ParamBodyAngleX` | my Fear | I draw back a little when uneasy |",
        "| `ParamEyeForm` | Compassion − Fear | eyes soften with care |",
        "| `ParamMouthOpenY` | speech amplitude | lip-sync (use my mouth/phoneme set) |",
        "| `ParamEyeLOpen`/`ParamEyeROpen` | blink clock | auto-blink |",
        "| `ParamBreath` | breath clock | idle breathing |",
        "| `ParamAngleX`/`ParamAngleY` | idle sway | gentle look-around |",
        "| `Param_CoreGlow` *(custom)* | my arousal | chest power-core brightness |",
        "| `Param_EyeGlow` *(custom)* | Fear + Compassion | iris glow intensity |",
        "",
        "Halo/UI states (sheet 09) follow my activity: idle → *idle*, listening "
        "→ *listening*, thinking → *processing*, speaking → *active*.",
        "",
        "## How each mood must read on my face",
        "",
    ]
    for mood in MOOD_LABELS:
        desc = sheet.get("expressions", {}).get(mood, "")
        lines.append(f"- **{mood}**: {desc}")
    never = sheet.get("never", [])
    if never:
        lines += ["", "## Never", ""] + [f"- {n}" for n in never]
    lines += ["", f"*Sheet version {sheet.get('version', '?')}.*", ""]
    return "\n".join(lines)


def write_rig_spec(sheet: dict, character_dir: Path = CHARACTER_DIR) -> Path:
    character_dir.mkdir(parents=True, exist_ok=True)
    p = character_dir / "RIG_SPEC.md"
    p.write_text(rig_spec_markdown(sheet), encoding="utf-8")
    return p


# --- Gallery: the candidates she chose to keep --------------------------------

def reference_sheets(character_dir: Path = CHARACTER_DIR) -> list[str]:
    """Her canonical master-sheet art, if it's been placed in
    data/character/reference/. These are the real design she works from -- the
    ground truth her self-designs are judged against."""
    d = character_dir / "reference"
    if not d.exists():
        return []
    return sorted(p.name for p in d.glob("*.png"))


def gallery_dir(character_dir: Path = CHARACTER_DIR) -> Path:
    d = character_dir / "gallery"
    d.mkdir(parents=True, exist_ok=True)
    return d


def keep_in_gallery(image_path: Path, verdict: str,
                    character_dir: Path = CHARACTER_DIR) -> Path:
    """File a kept candidate into her gallery with her verdict alongside."""
    import shutil
    d = gallery_dir(character_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = d / f"self-{stamp}{image_path.suffix}"
    shutil.copy2(image_path, dest)
    (d / f"self-{stamp}.json").write_text(
        json.dumps({"verdict": verdict, "kept_at": time.time()},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def gallery_index(character_dir: Path = CHARACTER_DIR) -> list[dict]:
    """Her kept designs, newest first, verdicts attached."""
    d = character_dir / "gallery"
    if not d.exists():
        return []
    out = []
    for img in sorted(d.glob("self-*.png")) + sorted(d.glob("self-*.jpg")):
        meta = d / (img.stem + ".json")
        verdict = ""
        if meta.exists():
            try:
                verdict = json.loads(meta.read_text(encoding="utf-8")).get("verdict", "")
            except Exception:
                pass
        out.append({"file": img.name, "verdict": verdict})
    return list(reversed(out))


def parse_strict_json(text: str) -> Optional[dict]:
    """Models wrap JSON in prose and fences despite instructions; dig it out.
    Returns None when there's genuinely no object to find."""
    text = (text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None

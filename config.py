"""Central configuration for Alpacca.

Everything that you might reasonably want to tune lives here so the rest of the
code can stay focused on behavior rather than magic numbers. The emotional-model
coefficients in particular are meant to be played with -- nudge them and the
companion's temperament changes.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------
# By default we keep all persistent state next to the code in a `data/` folder.
# The spec suggests pointing this at a synced Google Drive folder; to do that
# just set ALPACCA_HOME to that path.
HOME = Path(os.environ.get("ALPACCA_HOME", Path(__file__).parent / "data"))
HOME.mkdir(parents=True, exist_ok=True)

DB_PATH = HOME / "alpacca.db"             # homeostasis state + memories
TELEMETRY_LOG = HOME / "telemetry.jsonl"  # raw sensory stream

# --- Local model (Ollama) --------------------------------------------------
# The reasoning model. Pull it once with: `ollama pull qwen2.5:7b-instruct`
OLLAMA_MODEL = os.environ.get("ALPACCA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# --- Emotional model coefficients -----------------------------------------
# See alpacca/homeostasis.py for how each of these is used. The names map onto
# the state vector S = [Love, Compassion, Fear].
class Emotion:
    # Love / alignment: an EMA toward the "reward" of an interaction.
    LOVE_LEARN_RATE = 0.12     # how fast warmth builds with good interaction
    LOVE_DECAY = 0.01          # slow drift back toward baseline when ignored
    LOVE_BASELINE = 0.4

    # Compassion: sigmoid over weighted fatigue signals (late hours, errors...).
    # Each weight says how strongly that signal pushes perceived user fatigue.
    COMPASSION_WEIGHTS = {
        "late_night": 1.4,     # active in the small hours
        "long_session": 0.9,   # many minutes without a break
        "error_context": 1.1,  # error-y window titles (stack traces, "failed")
        "idle_return": -0.6,   # just came back from a break -> less tired
    }
    COMPASSION_BIAS = -0.8     # baseline so an average moment sits low

    # Fear / existential: prediction error above a threshold, clamped to >= 0.
    FEAR_THRESHOLD = 0.35      # surprise below this doesn't register as fear
    FEAR_GAIN = 1.2
    FEAR_DECAY = 0.15          # fear fades fairly quickly once things settle

    # Global clamp so every dimension stays in [0, 1].
    MIN, MAX = 0.0, 1.0


# --- Memory ----------------------------------------------------------------
MEMORY_TOP_K = 4                  # how many memories to retrieve per turn
MEMORY_SALIENCE_THRESHOLD = 0.3   # below this we don't bother storing a memory

# --- Server ----------------------------------------------------------------
HOST = os.environ.get("ALPACCA_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("ALPACCA_SERVER_PORT", "8765"))


# --- Self-portrait via ComfyClaw / ComfyUI --------------------------------
# Alpacca can render herself as an actual image by shelling out to ComfyClaw
# (a small ComfyUI workflow runner). Disabled by default so the companion still
# runs out of the box without ComfyUI installed; flip ALPACCA_PORTRAIT=1 once
# you've got `comfyclaw` on PATH and a ComfyUI server up. The defaults assume a
# stock setup; everything is overridable via env.
class Portrait:
    ENABLED = os.environ.get("ALPACCA_PORTRAIT", "0") not in ("", "0", "false", "False")
    COMFYCLAW = os.environ.get("ALPACCA_COMFYCLAW", "comfyclaw")
    WORKFLOW = os.environ.get("ALPACCA_PORTRAIT_WORKFLOW", "alpacca-portrait")
    # Where comfyclaw drops the rendered images. Served back over /portrait.
    OUTPUT_DIR = Path(os.environ.get("ALPACCA_PORTRAIT_DIR", str(HOME / "portraits")))
    # Optional checkpoint name to inject via @checkpoint.ckpt_name; if unset,
    # we trust whatever the workflow's default is.
    CHECKPOINT = os.environ.get("ALPACCA_PORTRAIT_CHECKPOINT", "")


# --- OpenClaw channel bridge ----------------------------------------------
# Optional: route Alpacca through OpenClaw so she can be reached on Telegram,
# Discord, iMessage, etc. We integrate via OpenClaw's two simplest surfaces --
# the `openclaw message send` CLI for outbound, and an Alpacca HTTP endpoint
# that an OpenClaw hook can POST inbound messages to. No device pairing, no WS
# protocol implementation -- both sides degrade gracefully when not configured.
class OpenClaw:
    ENABLED = os.environ.get("ALPACCA_OPENCLAW", "0") not in ("", "0", "false", "False")
    EXEC = os.environ.get("ALPACCA_OPENCLAW_EXEC", "openclaw")
    # Optional default target (channel-aware string like "telegram:+1234567890")
    # used when an inbound message doesn't carry an explicit reply target.
    DEFAULT_TARGET = os.environ.get("ALPACCA_OPENCLAW_TARGET", "")

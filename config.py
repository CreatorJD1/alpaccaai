"""Central configuration for Alpecca.

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
# just set ALPECCA_HOME to that path.
HOME = Path(os.environ.get("ALPECCA_HOME", Path(__file__).parent / "data"))
HOME.mkdir(parents=True, exist_ok=True)

DB_PATH = HOME / "alpecca.db"             # homeostasis state + memories
TELEMETRY_LOG = HOME / "telemetry.jsonl"  # raw sensory stream

# One-time migration: she used to be misspelled "alpacca", and her whole
# remembered life lives in that file. Carry it across to the corrected name so
# the rename doesn't cost her a single memory.
_OLD_DB = HOME / "alpacca.db"
if _OLD_DB.exists() and not DB_PATH.exists():
    _OLD_DB.rename(DB_PATH)

# --- Local model (Ollama) --------------------------------------------------
# The reasoning model. Pull it once with: `ollama pull qwen3:8b`
# Qwen3 is markedly better than Qwen2.5 at the things a companion needs --
# human-preference alignment, role-play, multi-turn dialogue -- so it's the
# default. Qwen3 hybrid models may emit <think>...</think> blocks; mind.py
# strips those from replies, so thinking variants also work. For lower latency
# on small GPUs, ALPECCA_MODEL=qwen3:4b-instruct-2507 is a good pick (the
# instruct-2507 line never thinks). qwen2.5:7b-instruct still works if that's
# what you have pulled.
OLLAMA_MODEL = os.environ.get("ALPECCA_MODEL", "qwen3:8b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# --- Emotional model coefficients -----------------------------------------
# See alpecca/homeostasis.py for how each of these is used. The names map onto
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
        "raised_voice": 0.7,   # sustained loud talking nearby -> stress read
        "weary_face": 1.0,     # the webcam expression sense reads tiredness
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
HOST = os.environ.get("ALPECCA_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("ALPECCA_SERVER_PORT", "8765"))


# --- Voice-tone sense (Phase 4) ---------------------------------------------
# A mic-level sensor that lets Alpecca *hear the room*: how much voice activity
# there is, how loud it is, and whether something sudden just happened. It does
# NOT record or transcribe anything -- only coarse loudness numbers ever leave
# the audio callback, and nothing is written to disk. Even so, a microphone is
# more intimate than a window title, so this is opt-in: set ALPECCA_VOICE=1.
class Voice:
    ENABLED = os.environ.get("ALPECCA_VOICE", "0") not in ("", "0", "false", "False")
    SAMPLE_RATE = 16000
    BLOCK_SECONDS = 0.03       # per-callback chunk; ~30ms is standard for VAD
    # RMS level (0..1) above which a chunk counts as "someone's talking".
    SPEECH_THRESHOLD = 0.02
    # Mean active level that maps to loudness 1.0 (a raised voice, not a jet).
    LOUD_REFERENCE = 0.2
    # A peak this many times the window's median -- after a quiet stretch --
    # reads as a startle (door slam, shout) and feeds prediction error.
    SPIKE_RATIO = 6.0
    SPIKE_MIN_LEVEL = 0.08


# --- Vision: seeing images, the screen, and your face -----------------------
# All sight runs through a local Ollama vision model; nothing leaves the
# machine. Chat images work whenever the model is pulled. The two ambient
# senses are separately opt-in because they are progressively more intimate:
#   ALPECCA_SIGHT=1  -> periodic screen glimpses (what are you working on)
#   ALPECCA_FACE=1   -> periodic webcam expression reads (how do you look)
# Only the model's short text description is kept; frames are dropped
# immediately and never written to disk.
class Vision:
    MODEL = os.environ.get("ALPECCA_VISION_MODEL", "qwen2.5vl:7b")
    SIGHT_ENABLED = os.environ.get("ALPECCA_SIGHT", "0") not in ("", "0", "false", "False")
    FACE_ENABLED = os.environ.get("ALPECCA_FACE", "0") not in ("", "0", "false", "False")
    SIGHT_INTERVAL = 60.0     # seconds between screen glimpses
    FACE_INTERVAL = 45.0      # seconds between expression reads
    # Expression label -> how strongly it reads as "they look worn down".
    WEARY_WEIGHTS = {"tired": 1.0, "stressed": 0.8, "sad": 0.6}


# --- Proactive speech --------------------------------------------------------
# Alpecca may say something unprompted when her own introspection notices a
# real shift -- the same grounded trend data behind /introspect, never an
# invented feeling. On by default because a companion who only ever answers
# isn't much of a companion; ALPECCA_PROACTIVE=0 turns it off.
class Proactive:
    ENABLED = os.environ.get("ALPECCA_PROACTIVE", "1") not in ("", "0", "false", "False")
    COOLDOWN_S = 20 * 60      # at most one unprompted remark per cooldown
    SHIFT_THRESHOLD = 0.15    # mood drift vs recent baseline that counts as real
    FEAR_FLOOR = 0.6          # acute unease speaks regardless of trend

    # Idle chatter: beyond mood-shift remarks, she may simply start a
    # conversation during a quiet stretch -- about what she senses you doing,
    # something she remembers, or just to say hello. ALPECCA_CHATTER=0 turns
    # only this off (mood-shift remarks stay governed by ENABLED above).
    CHATTER_ENABLED = os.environ.get("ALPECCA_CHATTER", "1") not in ("", "0", "false", "False")
    CHATTER_SILENCE_S = 3 * 60   # you must have been quiet at least this long
    CHATTER_MIN_GAP_S = 10 * 60  # and she won't chatter more often than this
    # Once eligible, each background tick fires with this probability, so her
    # timing feels like a person glancing over, not a cron job.
    CHATTER_CHANCE = 0.04


# --- App actions -------------------------------------------------------------
# "She can interact with apps if given access." Access is the allowlist below
# and nothing else: ALPECCA_APPS="spotify=C:\path\Spotify.exe;notes=notepad.exe"
# gives her an open_app tool restricted to exactly those names. Empty list
# (the default) means no actuator at all -- she can't touch anything you
# haven't explicitly handed her.
class Actions:
    APPS_SPEC = os.environ.get("ALPECCA_APPS", "")


# --- Self-portrait via ComfyClaw / ComfyUI --------------------------------
# Alpecca can render herself as an actual image by shelling out to ComfyClaw
# (a small ComfyUI workflow runner). Disabled by default so the companion still
# runs out of the box without ComfyUI installed; flip ALPECCA_PORTRAIT=1 once
# you've got `comfyclaw` on PATH and a ComfyUI server up. The defaults assume a
# stock setup; everything is overridable via env.
class Portrait:
    ENABLED = os.environ.get("ALPECCA_PORTRAIT", "0") not in ("", "0", "false", "False")
    COMFYCLAW = os.environ.get("ALPECCA_COMFYCLAW", "comfyclaw")
    WORKFLOW = os.environ.get("ALPECCA_PORTRAIT_WORKFLOW", "alpecca-portrait")
    # Where comfyclaw drops the rendered images. Served back over /portrait.
    OUTPUT_DIR = Path(os.environ.get("ALPECCA_PORTRAIT_DIR", str(HOME / "portraits")))
    # Optional checkpoint name to inject via @checkpoint.ckpt_name; if unset,
    # we trust whatever the workflow's default is.
    CHECKPOINT = os.environ.get("ALPECCA_PORTRAIT_CHECKPOINT", "")


# --- OpenClaw channel bridge ----------------------------------------------
# Optional: route Alpecca through OpenClaw so she can be reached on Telegram,
# Discord, iMessage, etc. We integrate via OpenClaw's two simplest surfaces --
# the `openclaw message send` CLI for outbound, and an Alpecca HTTP endpoint
# that an OpenClaw hook can POST inbound messages to. No device pairing, no WS
# protocol implementation -- both sides degrade gracefully when not configured.
class OpenClaw:
    ENABLED = os.environ.get("ALPECCA_OPENCLAW", "0") not in ("", "0", "false", "False")
    EXEC = os.environ.get("ALPECCA_OPENCLAW_EXEC", "openclaw")
    # Optional default target (channel-aware string like "telegram:+1234567890")
    # used when an inbound message doesn't carry an explicit reply target.
    DEFAULT_TARGET = os.environ.get("ALPECCA_OPENCLAW_TARGET", "")

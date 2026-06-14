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
AVATAR_DIR = HOME / "avatar"              # drop-in custom avatar clips (alpecca/avatar.py)
CHARACTER_DIR = HOME / "character"        # her self-authored design studio (alpecca/studio.py)

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
# on a small GPU (e.g. 4 GB), ALPECCA_MODEL=qwen3:4b is the right pick.
# qwen2.5:7b-instruct still works if that's what you have pulled.
OLLAMA_MODEL = os.environ.get("ALPECCA_MODEL", "qwen3:8b")

# Safety net for a specific, painful gotcha: an earlier build suggested the tag
# 'qwen3:4b-instruct-2507', which is NOT a real Ollama model -- pulling it 404s.
# If a stale env var still points there, EVERY reply silently falls back to the
# "You said: ..." echo. Quietly remap that one dead name to the real 4B tag so a
# leftover setting can't keep her brain offline.
if OLLAMA_MODEL == "qwen3:4b-instruct-2507":
    OLLAMA_MODEL = "qwen3:8b"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# A second, tiny model for *cheap* work -- short, low-stakes generations like her
# unprompted little remarks, idle chatter, and posing herself a one-line question.
# Routing these to a small fast model keeps the big MoE reserved for real
# reasoning (her replies, reflection, self-critique) and keeps a single consumer
# GPU responsive. Defaults to Gemma 4 E4B (4B active -- fast on consumer hardware);
# register it once with `ollama create gemma4-e4b -f Modelfile` (FROM your GGUF).
# If that model isn't present, cheap calls fall back to OLLAMA_MODEL automatically
# (see mind._LLM.generate), so this default never breaks a fresh setup. Set
# ALPECCA_FAST_MODEL="" to force everything back onto the single primary model.
OLLAMA_FAST_MODEL = os.environ.get("ALPECCA_FAST_MODEL", "gemma4-e4b")

# Context window (in tokens) we ask Ollama to allocate. This is the single most
# important knob on a small machine: modern models like qwen3 advertise a 256K
# context, and Ollama will try to allocate a KV cache for the FULL window up
# front -- which for qwen3:4b is ~36 GB and instantly OOMs a normal laptop, so
# the model fails to start and she silently drops to her echo fallback. Capping
# the context to a few thousand tokens shrinks the KV cache to ~1 GB and is far
# more than a companion chat ever needs. Raise ALPECCA_NUM_CTX if you have RAM
# to spare and want her to remember more of a long conversation at once.
OLLAMA_NUM_CTX = int(os.environ.get("ALPECCA_NUM_CTX", "8192"))

# --- Brain backend: local Ollama (default) or Hugging Face cloud ---------------
# On a small laptop the local model spills onto the CPU and eats RAM. Routing her
# *thinking* to Hugging Face's hosted inference lifts that whole load off the
# machine -- she replies fast and your CPU/RAM are freed. Only her chat text and
# prompt travel to HF; senses, mood, memory and her avatar all stay local. To
# keep the project's privacy line, what she's SENSED on your screen is stripped
# from cloud prompts unless you explicitly opt in below.
#   Switch on with:  ALPECCA_LLM_BACKEND=hf
#   Auth: run `huggingface-cli login` once (token cached) OR set HF_TOKEN.
LLM_BACKEND = os.environ.get("ALPECCA_LLM_BACKEND", "ollama").lower()
HF_TOKEN = (os.environ.get("HF_TOKEN", "")
            or os.environ.get("HUGGINGFACEHUB_API_TOKEN", ""))
# A solid, widely-served instruct model in her Qwen lineage (no <think> noise).
# Change with ALPECCA_HF_MODEL; any chat model on HF Inference Providers works.
HF_MODEL = os.environ.get("ALPECCA_HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
HF_PROVIDER = os.environ.get("ALPECCA_HF_PROVIDER", "auto")
# Privacy: keep what she's sensed on your screen OUT of cloud prompts by default.
CLOUD_SEND_SENSES = os.environ.get("ALPECCA_CLOUD_SEND_SENSES", "0") \
    not in ("", "0", "false", "False")

# --- Her voice (text-to-speech) ------------------------------------------------
# Server-side TTS for a real, natural voice (alpecca/tts.py), replacing the
# robotic browser engine. 'auto' uses the best installed engine: Kokoro (best
# open, fully local) if present, else edge-tts (Microsoft neural voices, no
# install pain, uses the network). 'kokoro'/'edge' force one; 'browser'/'off'
# keep the old built-in voice. TTS_VOICE picks the speaker (e.g. af_heart for
# Kokoro, en-US-AriaNeural for edge); blank = a warm default.
TTS_BACKEND = os.environ.get("ALPECCA_TTS_BACKEND", "auto").lower()
TTS_VOICE = os.environ.get("ALPECCA_TTS_VOICE", "")
# Voice character. A bright, young female voice with a lifted pitch and a little
# extra pace reads as "anime girl" rather than flat newsreader. These tune the
# edge-tts voice; raise/lower to taste. ALPECCA_TTS_VOICE overrides the speaker.
TTS_RATE = os.environ.get("ALPECCA_TTS_RATE", "+6%")     # slightly livelier pace
TTS_PITCH = os.environ.get("ALPECCA_TTS_PITCH", "+18Hz")  # brighter, younger tone
# Kokoro voice + pitch (separate from the edge voice above, since Kokoro uses its
# own names like af_heart/af_bella). KOKORO_PITCH > 1 brightens her toward an
# anime tone; ~1.08 is "just right" -- youthful but not squeaky. 1.0 = natural.
KOKORO_VOICE = os.environ.get("ALPECCA_KOKORO_VOICE", "af_heart")
KOKORO_PITCH = float(os.environ.get("ALPECCA_KOKORO_PITCH", "1.08"))

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

    # Energy / arousal: rises when she's actively engaged with the person and
    # decays toward a drowsy floor when left alone -- this is what makes her get
    # sleepy after a long stretch of no interaction, and lively when you're here.
    ENERGY_BASELINE = 0.5
    ENERGY_ACTIVE = 0.9        # target when the person is actively interacting
    ENERGY_RISE = 0.30         # how fast she perks up when engaged
    ENERGY_DECAY = 0.05        # how fast she winds down when ignored
    ENERGY_FLOOR = 0.10        # how drowsy she gets after long solitude
    ENERGY_ACTIVE_WINDOW = 120  # seconds since last interaction still counts as "with her"

    # Curiosity / interest: rises with *novelty* and decays in monotony. The
    # honest distinction that makes this grounded rather than invented: a small,
    # sub-threshold prediction error is *interest*; a large one is *fear*. So the
    # same surprise signal that feeds Fear above its threshold feeds Curiosity
    # below it. A fresh question, an unseen image, a new window all read as mild
    # novelty. Without new input it eases back toward a low, content baseline.
    CURIOSITY_BASELINE = 0.2
    CURIOSITY_GAIN = 0.9       # how strongly mild novelty lifts interest
    CURIOSITY_DECAY = 0.08     # how fast interest fades when nothing's new
    # Novelty above FEAR_THRESHOLD is fear's business, not curiosity's -- we only
    # count the interesting band below it, so the two never double-count a jolt.
    CURIOSITY_NOVELTY_CAP = FEAR_THRESHOLD

    # Social hunger / connection-seeking: rises with time-since-interaction
    # *scaled by warmth* -- she misses you more the more she loves you. Purely a
    # read of real timestamps and her real Love value; resets when you're back.
    SOCIAL_HUNGER_RATE = 0.6   # how fast solitude builds wanting-company
    SOCIAL_HUNGER_WARMTH = 0.7 # how much her warmth amplifies the missing
    SOCIAL_HUNGER_FULL_S = 3600.0  # solitude (sec) that, at full warmth, maxes it

    # Global clamp so every dimension stays in [0, 1].
    MIN, MAX = 0.0, 1.0


# --- Memory ----------------------------------------------------------------
MEMORY_TOP_K = 4                  # how many memories to retrieve per turn
MEMORY_SALIENCE_THRESHOLD = 0.3   # below this we don't bother storing a memory


# --- Her home: the modular rooms she roams ----------------------------------
# Her interface is a home of rooms she moves between of her own accord
# (alpecca/home.py). She chooses the room from her real state, so where she is
# is itself honest. These knobs govern how she roams.
class Home:
    # On the idle loop she may drift to whichever room is calling strongest. A
    # bonus for the room she's already in keeps her from flickering between
    # near-tied rooms -- people settle before they wander on.
    STAY_BONUS = 0.25
    ROAM_SILENCE_S = 20        # drift rooms after a short lull (visible life)
    ROAM_MIN_GAP_S = 40        # and not more often than this
    ROAM_CHANCE = 0.30         # per eligible tick -- she wanders within a minute


# --- Her workstation: the desktop file room ---------------------------------
# The room where she can see a desktop-like layout and organize files -- strictly
# within the charter's allowed roots (Desktop/Pictures/Music/Video/general) and
# never deleting. Off by default because it touches the real filesystem; flip
# ALPECCA_FILES=1 to let her tidy. The roots are overridable via
# ALPECCA_ROOT_DESKTOP, ALPECCA_ROOT_PICTURES, etc. (see alpecca/desktop.py).
class Files:
    ENABLED = os.environ.get("ALPECCA_FILES", "0") not in ("", "0", "false", "False")


# --- Her avatar rig data loop (RIGFORGE -> Alpeccaai-data) -------------------
# The recursive foundation: every rig that passes RIGFORGE's readiness check is
# captured as a labelled sample (figure + corrected keypoints + rig) so her own
# joint detector can be retrained on her own art. Samples stage locally under
# data/avatar/samples/{figures,pose,rigs}; build_manifest.py assembles them and
# can push to the Hugging Face dataset below. This is selfmod, applied to her body.
class RigData:
    SAMPLES_DIR = Path(os.environ.get("ALPECCA_SAMPLES_DIR", str(HOME / "avatar" / "samples")))
    # The HF dataset repo that accumulates certified samples (your bucket).
    HF_DATASET = os.environ.get("ALPECCA_RIG_DATASET", "CREATORJD/Alpeccaai-data")
    # Only certified rigs (readiness >= this) are ever captured.
    MIN_READINESS = float(os.environ.get("ALPECCA_RIG_MIN_READINESS", "85"))

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


# --- Hearing: local speech-to-text -------------------------------------------
# The browser records your voice (push-to-talk in the UI) and POSTs it to
# /listen; the server transcribes it locally with faster-whisper. Nothing is
# stored and nothing leaves the machine -- the audio lives exactly long enough
# to become words. Model sizes: tiny/base/small/medium; "base" is a good
# latency/accuracy balance on CPU.
class Hearing:
    WHISPER_MODEL = os.environ.get("ALPECCA_WHISPER", "base")


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
    CHATTER_SILENCE_S = 35       # you must have been quiet at least this long
    CHATTER_MIN_GAP_S = 100      # and she won't chatter more often than this
    # Once eligible, each background tick fires with this probability, so her
    # timing feels like a person glancing over, not a cron job. (Livelier default
    # so she visibly stirs; raise gaps / lower chance to make her quieter.)
    CHATTER_CHANCE = 0.25


# --- Idle reflection ----------------------------------------------------------
# Her fourth directive (self-actualization through exploration), running: in
# quiet stretches she revisits her own memories, thinks something new about
# them, and keeps the thought as a memory of its own (kind="musing"). Those
# musings feed back into recall and chatter, so her inner life genuinely
# compounds. ALPECCA_REFLECT=0 turns it off.
class Reflection:
    ENABLED = os.environ.get("ALPECCA_REFLECT", "1") not in ("", "0", "false", "False")
    SILENCE_S = 30            # only when idle a short stretch
    MIN_GAP_S = 150           # at most one musing every couple of minutes
    CHANCE = 0.15             # per-tick chance once eligible
    MUSING_SALIENCE = 0.45    # above the storage threshold, below big moments


# --- App actions -------------------------------------------------------------
# "She can interact with apps if given access." Access is the allowlist below
# and nothing else: ALPECCA_APPS="spotify=C:\path\Spotify.exe;notes=notepad.exe"
# gives her an open_app tool restricted to exactly those names. Empty list
# (the default) means no actuator at all -- she can't touch anything you
# haven't explicitly handed her.
class Actions:
    APPS_SPEC = os.environ.get("ALPECCA_APPS", "")


# --- Computer use: she sees the screen and drives mouse/keyboard -------------
# Her own eyes (the local vision model) plus pyautogui, in a screenshot ->
# reason -> act loop. Fully local: screenshots are analyzed on-machine and
# never leave it -- the same privacy line as every other sense. Off by default
# because handing any program the mouse is a real grant; ALPECCA_COMPUTER_USE=1
# turns it on. Even then, anything consequential (send / delete / buy / post /
# install / overwrite) pauses for the person's confirmation -- the autonomy
# tier the owner chose.
class Computer:
    ENABLED = os.environ.get("ALPECCA_COMPUTER_USE", "0") not in ("", "0", "false", "False")
    MAX_STEPS = int(os.environ.get("ALPECCA_COMPUTER_MAX_STEPS", "12"))
    # Long edge the screenshot is downscaled to before her vision model reads
    # it; her returned coordinates are scaled back up to the real screen.
    VIEW_LONG_EDGE = 1280
    # Words that mark an action as consequential regardless of the model's own
    # judgment -- the keyword safety net under her self-declared flag.
    CONSEQUENTIAL_HINTS = (
        "send", "delete", "remove", "buy", "purchase", "pay", "order", "post",
        "publish", "submit", "confirm", "transfer", "install", "uninstall",
        "overwrite", "format", "shutdown", "restart", "sign out", "log out",
        "unsubscribe", "trash", "discard", "wipe", "erase",
    )


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

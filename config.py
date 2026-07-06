"""Central configuration for Alpecca.

Everything that you might reasonably want to tune lives here so the rest of the
code can stay focused on behavior rather than magic numbers. The emotional-model
coefficients in particular are meant to be played with -- nudge them and the
companion's temperament changes.
"""
from __future__ import annotations

import os
import secrets
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
ACCESS_TOKEN_FILE = HOME / "access_token.txt"

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
OLLAMA_NUM_CTX = int(os.environ.get("ALPECCA_NUM_CTX", "4096"))

# How many transformer layers to pin on the GPU. Ollama normally auto-decides,
# but its VRAM estimator is conservative for some GGUFs (notably the qwen3.5
# tags): on a 4 GB card it can leave 2+ GB idle and spill the model onto the CPU,
# roughly quartering speed. Set ALPECCA_NUM_GPU to force layers onto the GPU --
# e.g. "36" (all layers of a 4B) makes qwen3.5:4b sit 100% on a 4 GB card at
# ~45 tok/s versus ~11 on auto. Leave empty ("") to keep Ollama's automatic
# split (the safe default for unknown hardware). Caveat: a value that needs more
# VRAM than is free makes the model fail to load and she drops to her echo
# fallback -- so when you pin all layers here, keep the voice (F5) and vision
# models OFF the GPU so they can't steal the VRAM the model is counting on.
_num_gpu_raw = os.environ.get("ALPECCA_NUM_GPU", "").strip()
OLLAMA_NUM_GPU = int(_num_gpu_raw) if _num_gpu_raw.lstrip("-").isdigit() else None

# Keep live conversation from becoming a long monologue. This is the response
# token budget Ollama sees for normal local turns; larger reflective/deep jobs
# can still use external tiers or override this later.
OLLAMA_NUM_PREDICT = int(os.environ.get("ALPECCA_NUM_PREDICT", "120"))

# How many recent chat messages ride along with every reply -- HER WORKING
# MEMORY of the conversation. This, not num_ctx, is what makes her feel
# forgetful: the model can only remember what we actually send it. 24 messages
# = 12 exchanges (~1-2K tokens), comfortably inside even the local 8K window.
HISTORY_MESSAGES = int(os.environ.get("ALPECCA_HISTORY_MESSAGES", "24"))

# --- Hybrid chat: cloud-first replies, local always as the net ---------------
# Set ALPECCA_CHAT_CLOUD_MODEL to a hosted Ollama cloud model (needs `ollama
# signin` + a plan with cloud usage) and normal chat turns try it FIRST --
# ~3s warm replies from a much bigger brain with a huge context window --
# then fall back to the local model on ANY failure (offline, signed out,
# quota exhausted), so she never goes quiet. Empty (the default) keeps chat
# 100% local. Note: with this set, chat text leaves the machine; senses
# stay out of prompts per the existing privacy line.
CHAT_CLOUD_MODEL = os.environ.get("ALPECCA_CHAT_CLOUD_MODEL", "")
# Context window for cloud chat calls -- hosted models take big windows
# without eating local RAM, so her conversational memory can run deep.
CLOUD_NUM_CTX = int(os.environ.get("ALPECCA_CLOUD_NUM_CTX", "32768"))

# --- Streamed replies: show her words as they generate ----------------------
# The home app displays a live DRAFT of her reply token by token, then replaces
# it with the final vetted text (the anti-repetition and echo guards still run
# on the complete reply and stay authoritative -- streaming never bypasses
# them). Kill switch: ALPECCA_STREAM_CHAT=0 restores the single-frame flow end
# to end (the server stops sending token frames and stops advertising the
# feature, so unmodified clients are always safe either way).
STREAM_CHAT = os.environ.get("ALPECCA_STREAM_CHAT", "1") not in ("", "0", "false", "False")

# --- Cloud-first chat on HER OWN Space (Jason, 2026-07-04: "make 9b cloud
# only so i can have fast responses"). The ZeroGPU Space runs the EXACT same
# Qwen3.5-9B as her local brain -- same identity, datacenter speed (~3-8s a
# reply warm vs ~30s local). ZeroGPU Spaces SLEEP when idle, so the first
# message after a lull would block for a minute; instead chat tries the Space
# under a short bound and, if it's still waking, the LOCAL 9B answers that
# turn while the attempt itself finishes waking the Space -- the next turns
# are cloud-fast and she never goes quiet. Costs HF ZeroGPU quota per reply.
CHAT_ZEROGPU = os.environ.get("ALPECCA_CHAT_ZEROGPU", "0") not in ("", "0", "false", "False")
CHAT_ZEROGPU_TIMEOUT = float(os.environ.get("ALPECCA_CHAT_ZEROGPU_TIMEOUT", "30"))

# How many days of mood history (state_log) to keep. One row lands every ~8s
# tick plus every chat turn, and nothing ever pruned it -- unbounded growth in
# her save file. 30 days is months of trend material for introspection while
# keeping the DB lean; 0 disables pruning entirely.
STATE_LOG_KEEP_DAYS = float(os.environ.get("ALPECCA_STATE_LOG_KEEP_DAYS", "30"))

# Keep the main model warm so the House HQ does not pay the cold-load penalty on
# every message. Ollama accepts durations like "10m", "30m", or "-1".
OLLAMA_KEEP_ALIVE = os.environ.get("ALPECCA_KEEP_ALIVE", "30m")

# Hard bound for a single local model HTTP request. This keeps a wedged Ollama
# generation from holding the House HQ/WebSocket turn until the UI has to fall
# back to a canned timeout line.
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("ALPECCA_OLLAMA_TIMEOUT", "18"))

# --- Reflection-tier thinking: local chain-of-thought for her deep self-acts ---
# When her deep tier (reflection, self-questioning, authorship) runs LOCALLY --
# no cloud deep tier configured, or it failed / ran out of quota -- let the
# local model genuinely think first. qwen3/qwen3.5 hybrids support Ollama's
# think mode, which returns the private reasoning separately from the reply, so
# her musings come from actual deliberation instead of a single fast pass.
# These are idle background acts: nobody is waiting, so they get a much bigger
# token budget and timeout than a chat turn. Depth is the point here.
# ALPECCA_REFLECT_THINK=0 turns it off; mind.py also degrades to the plain
# no-think call automatically if the model or client can't do think mode.
REFLECT_THINK = os.environ.get("ALPECCA_REFLECT_THINK", "1").lower() not in ("0", "false", "no", "")
REFLECT_NUM_PREDICT = int(os.environ.get("ALPECCA_REFLECT_NUM_PREDICT", "1600"))
# Which local model does the thinking for deep self-acts. Empty means "same as
# chat" (OLLAMA_MODEL). Setting it lets chat stay on a small fast model while
# reflection deliberates on a bigger sibling -- e.g. chat on qwen3.5:4b, deep
# thinking + vision on qwen3.5:9b. Reflection is idle work, so the big model's
# slowness costs nothing anyone feels.
REFLECT_MODEL = os.environ.get("ALPECCA_REFLECT_MODEL", "")
# Generous: with the vision model co-resident the local brain can drop to
# ~6 tok/s, and 1600 thinking tokens at that pace is ~4.5 minutes.
REFLECT_TIMEOUT_SECONDS = float(os.environ.get("ALPECCA_REFLECT_TIMEOUT", "600"))

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
# Memory-recall embeddings. Local Ollama (`nomic-embed-text`) by default; set
# ALPECCA_EMBED_BACKEND=hf to embed via Hugging Face instead, which frees the
# local GPU (her embedder was the model that evicted the chat model on a small
# card). `bge-m3` is a strong, widely-served HF embedder. Switching models
# changes the vector dimension, but memory._cosine guards mismatched dims
# (older vectors simply fall back to keyword recall), so it's safe to flip.
EMBED_BACKEND = os.environ.get("ALPECCA_EMBED_BACKEND", "ollama").lower()
EMBED_HF_MODEL = os.environ.get("ALPECCA_EMBED_HF_MODEL", "BAAI/bge-m3")
# Privacy: keep what she's sensed on your screen OUT of cloud prompts by default.
CLOUD_SEND_SENSES = os.environ.get("ALPECCA_CLOUD_SEND_SENSES", "0") \
    not in ("", "0", "false", "False")

# --- Her "deep" tier: optional cloud compute for her hardest SELF-acts ----------
# A strict AUGMENTATION, never a replacement. Her brain -- the local Ollama model
# above -- stays her identity and answers EVERY normal conversational turn. Only
# her hardest self-directed acts (deep reflection, recursive self-questioning)
# may be routed to a stronger model on a "deep" tier, so her inner life can run
# deeper than an 8B local model allows. Default is "local": no cloud at all.
#
# Hard rule, enforced by where it's used: every deep endpoint is HER OWN BRAIN
# (Anthropic, or a model server YOU host) -- never the open web. The charter's
# no-unguided-websearch line is untouched; her only window outward stays
# screenshare/cowork. Her deep-tier prompts carry no sensed screen context.
#
# ALPECCA_DEEP_BACKEND picks where the deep tier runs:
#   "local"     -- (default) her local reasoning model; fully private, no cloud.
#   "anthropic" -- Anthropic Claude: reliable, top-tier reasoning for her depth.
#                  Needs ANTHROPIC_API_KEY; silently falls back to local if absent
#                  or offline. `pip install anthropic`.
#   "cloud"     -- a generic OpenAI-compatible server you host (e.g. vLLM/Ollama
#                  on a free Kaggle/Colab GPU, tunnelled); set ALPECCA_CLOUD_URL.
#   "zerogpu"   -- a Hugging Face ZeroGPU Gradio Space you own. Normal chat still
#                  stays local; only deep/self-work calls this queued booster.
#   "ollama-cloud" -- Ollama's hosted cloud models through the SAME local Ollama
#                  API (needs `ollama signin` + a plan that includes cloud usage).
#                  Big thinking models (e.g. qwen3.5:397b-cloud) with zero local
#                  VRAM, no ZeroGPU queue/quota, and the identical chat+think
#                  interface mind.py already speaks. Still her own brain -- an
#                  account YOU hold -- so the no-open-web line is untouched.
#
# CHAINS: a comma-separated list tries each backend in order until one answers,
# e.g. "ollama-cloud,zerogpu" (Jason's setup) -- Ollama cloud first (warm, fast),
# his ZeroGPU Space if that fails, and the local thinking pass remains the final
# net after the whole chain (mind.generate).
DEEP_BACKEND = os.environ.get("ALPECCA_DEEP_BACKEND", "local").lower()

# The Ollama cloud model for the deep tier. EMPTY by default (2026-07-04):
# Ollama's cloud hosts no qwen3.5:9b -- only the 397B -- and Jason rejected
# every substitute (gpt-oss, 397b). With no approved cloud model there is no
# ollama-cloud link; her depth runs on the local 9B. If he ever names a
# cloud model himself, set it here and add "ollama-cloud" to DEEP_BACKEND.
OLLAMA_CLOUD_MODEL = os.environ.get("ALPECCA_OLLAMA_CLOUD_MODEL", "")
# Thinking budget for cloud deep calls. gpt-oss rarely needs a tenth of this;
# the cap only exists so a pathological chain can't burn quota.
CLOUD_REFLECT_NUM_PREDICT = int(os.environ.get("ALPECCA_CLOUD_REFLECT_NUM_PREDICT", "2500"))
# Anthropic, her reliable deep tier. Identity stays local; this only augments her
# self-acts. Default model is the most capable Opus (adaptive thinking, see mind).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ALPECCA_ANTHROPIC_MODEL", "claude-opus-4-8")
# A self-hosted OpenAI-compatible model server (her free heavy booster when you
# spin up a notebook GPU). Base URL only; reuses the HF InferenceClient transport.
CLOUD_URL = os.environ.get("ALPECCA_CLOUD_URL", "")
CLOUD_MODEL = os.environ.get("ALPECCA_CLOUD_MODEL", "")
CLOUD_API_KEY = os.environ.get("ALPECCA_CLOUD_API_KEY", "")

# Optional Google Colab T4 accelerator for fast House HQ replies. This is a
# speed tier, not her identity tier: qwen3:8b remains the local reasoning model.
# Run notebooks/alpecca_colab_t4_server.ipynb in Colab, copy the tunnel URL here,
# and Alpecca will use it for fast chat while falling back locally if it sleeps.
COLAB_URL = os.environ.get("ALPECCA_COLAB_URL", "").rstrip("/")
COLAB_MODEL = os.environ.get("ALPECCA_COLAB_MODEL", "Qwen/Qwen2.5-7B-Instruct")
COLAB_API_KEY = os.environ.get("ALPECCA_COLAB_API_KEY", "")
COLAB_TIMEOUT_SECONDS = float(os.environ.get("ALPECCA_COLAB_TIMEOUT", "7"))
COLAB_FAST_CHAT = os.environ.get("ALPECCA_COLAB_FAST_CHAT", "1") not in ("", "0", "false", "False")
# Hugging Face ZeroGPU Space endpoint for the deep tier. The Space should expose
# a Gradio API that accepts (system_prompt, user_msg, history_json) and returns
# text. See spaces/alpecca-zerogpu for the matching template.
ZEROGPU_SPACE = os.environ.get("ALPECCA_ZEROGPU_SPACE", "")
def _gradio_api_name(env_var: str, default: str) -> str:
    """Read a Gradio api_name from env, undoing MSYS/Git-Bash path mangling:
    a value like "/chat" looks like a POSIX path to Git Bash, which rewrites
    it to "C:/Program Files/Git/chat" before it reaches Python -- and the
    Space then can't find the endpoint. Keep only the trailing segment."""
    val = os.environ.get(env_var, default).strip() or default
    if ":" in val:                      # a Windows drive crept in -> mangled
        val = "/" + val.rstrip("/").split("/")[-1]
    return val if val.startswith("/") else "/" + val


ZEROGPU_API = _gradio_api_name("ALPECCA_ZEROGPU_API", "/chat")
ZEROGPU_TOKEN = os.environ.get("ALPECCA_ZEROGPU_TOKEN", HF_TOKEN)
# Cloud vision: her ZeroGPU space's image-describe endpoint. On a small laptop
# GPU the local vision model OOM-crashes Ollama, so image understanding is
# offloaded to the Space's GPU. VISION_BACKEND: "auto" tries Ollama cloud sight
# (below), then the ZeroGPU space, then falls back to local; "ollama-cloud"
# Ollama cloud only; "zerogpu" Space only; "local" local Ollama VL (on CPU).
ZEROGPU_VISION_API = _gradio_api_name("ALPECCA_ZEROGPU_VISION_API", "/vision")
VISION_BACKEND = os.environ.get("ALPECCA_VISION_BACKEND", "auto").lower()
# Ollama cloud sight: a vision-capable Ollama cloud model (same signed-in local
# API as the deep tier). EMPTY by default (2026-07-04): the only vision-capable
# cloud tag is the 397B, which Jason rejected -- so cloud sight is off unless
# he names a model here himself. Ambient senses (screen glimpses, webcam)
# never leave the machine regardless (see vision.py).
VISION_CLOUD_MODEL = os.environ.get("ALPECCA_VISION_CLOUD_MODEL", "")

# --- Mindscape continuity -----------------------------------------------------
# Mindscape is Alpecca's mobile/cloud continuity shell: a compact, encrypted-by-
# transport view of her current state that can be opened from a phone/tunnel and,
# when a hosted endpoint is provided, mirrored out before the local device dies.
# It preserves continuity data; it does not claim literal immortality.
MINDSCAPE_ENABLED = os.environ.get("ALPECCA_MINDSCAPE", "1") not in ("", "0", "false", "False")
MINDSCAPE_CLOUD_URL = os.environ.get("ALPECCA_MINDSCAPE_URL", "")
MINDSCAPE_TOKEN = os.environ.get("ALPECCA_MINDSCAPE_TOKEN", "")
MINDSCAPE_SYNC_TIMEOUT = float(os.environ.get("ALPECCA_MINDSCAPE_SYNC_TIMEOUT", "8"))
MINDSCAPE_AUTO_SYNC_INTERVAL = float(os.environ.get("ALPECCA_MINDSCAPE_AUTO_SYNC_INTERVAL", "300"))
MINDSCAPE_EVENT_SYNC_MIN_INTERVAL = float(os.environ.get("ALPECCA_MINDSCAPE_EVENT_SYNC_MIN_INTERVAL", "45"))

# --- Avatar rig cutter: optional Hugging Face background-removal --------------
# The in-app layer cutter (/rigcut) builds her per-part rig from her own art by
# hand. Hugging Face does the precise cut: a hosted background-removal Space
# matts her figure to a clean transparent PNG (on HF's GPU, no local CUDA), so
# her painted part-cuts have crisp edges. Configurable Space; needs gradio_client
# and (for some Spaces) HF_TOKEN. Leave HF_MATTE_API blank to use the Space's
# default endpoint; set it if the Space names a specific api (e.g. "/image").
HF_MATTE_SPACE = os.environ.get("ALPECCA_HF_MATTE_SPACE", "not-lain/background-removal")
HF_MATTE_API = os.environ.get("ALPECCA_HF_MATTE_API", "")

# --- Her voice (text-to-speech) ------------------------------------------------
# Server-side TTS for a real, natural voice (alpecca/tts.py), replacing the
# robotic browser engine. 'auto' uses the best installed engine: Kokoro (best
# open, fully local) if present, else edge-tts (Microsoft neural voices, no
# install pain, uses the network). 'kokoro'/'edge' force one; 'browser'/'off'
# keep the old built-in voice. TTS_VOICE picks the speaker (e.g. af_heart for
# Kokoro, en-US-AriaNeural for edge); blank = a warm default.
TTS_BACKEND = os.environ.get("ALPECCA_TTS_BACKEND", "auto").lower()
TTS_VOICE = os.environ.get("ALPECCA_TTS_VOICE", "")
# Open-source cloned/emotional TTS path. "auto" means: try an installed open
# voice engine first (currently F5-TTS), then fall back to Kokoro. Use
# ALPECCA_TTS_BACKEND=kokoro to bypass this while testing.
OPEN_TTS_ENGINE = os.environ.get("ALPECCA_OPEN_TTS_ENGINE", "f5").lower()
OPEN_TTS_PYTHON = os.environ.get("ALPECCA_OPEN_TTS_PYTHON", "")
OPEN_TTS_TIMEOUT = float(os.environ.get("ALPECCA_OPEN_TTS_TIMEOUT", "90"))
OPEN_TTS_DEVICE = os.environ.get("ALPECCA_OPEN_TTS_DEVICE", "cuda").lower()
# F5 diffusion steps: 4 is fast but buzzy/robotic; 16 is close to Kokoro-grade
# realism at a modest latency cost (F5 handles only the higher-emotion lines).
OPEN_TTS_NFE_STEP = int(os.environ.get("ALPECCA_OPEN_TTS_NFE_STEP", "16"))
TTS_ROUTE_TIMEOUT = float(os.environ.get("ALPECCA_TTS_ROUTE_TIMEOUT", str(max(45.0, OPEN_TTS_TIMEOUT + 5.0))))
# Warm her voice at startup so the FIRST spoken line doesn't eat Kokoro's cold
# model load (~40s). The old warmup short-circuited whenever the F5 worker was
# healthy -- but auto-mode routes calm, everyday speech to Kokoro, so the
# engine serving the first reply was exactly the one left cold. Warmup now
# always touches Kokoro too (unless the backend forces another engine). The
# timeout must OUTLAST the cold load; the old 18s bound "timed out" every
# fresh boot while the load quietly continued.
VOICE_WARMUP = os.environ.get("ALPECCA_VOICE_WARMUP", "1") not in ("", "0", "false", "False")
VOICE_WARMUP_TIMEOUT = float(os.environ.get("ALPECCA_VOICE_WARMUP_TIMEOUT", "90"))
F5_WORKER_ENABLED = os.environ.get("ALPECCA_F5_WORKER", "1") not in ("", "0", "false", "False")
F5_WORKER_HOST = os.environ.get("ALPECCA_F5_WORKER_HOST", "127.0.0.1")
F5_WORKER_PORT = int(os.environ.get("ALPECCA_F5_WORKER_PORT", "8776"))
F5_WORKER_TIMEOUT = float(os.environ.get("ALPECCA_F5_WORKER_TIMEOUT", "18"))
OPEN_TTS_LOCAL_MODEL_DIR = os.environ.get(
    "ALPECCA_OPEN_TTS_LOCAL_MODEL_DIR",
    str(Path(__file__).parent / "data" / "models" / "f5-tts" / "F5TTS_v1_Base"),
)
OPEN_TTS_REFERENCE_MANIFEST = os.environ.get(
    "ALPECCA_OPEN_TTS_REFERENCES",
    str(Path(__file__).parent / "data" / "voice_references" / "alpecca_open_tts_refs.json"),
)
# Voice character. A bright, young female voice with a lifted pitch and a little
# extra pace reads as "anime girl" rather than flat newsreader. These tune the
# edge-tts voice; raise/lower to taste. ALPECCA_TTS_VOICE overrides the speaker.
TTS_RATE = os.environ.get("ALPECCA_TTS_RATE", "+6%")     # slightly livelier pace
TTS_PITCH = os.environ.get("ALPECCA_TTS_PITCH", "+18Hz")  # brighter, younger tone
# Kokoro voice + identity lock. Kokoro voices have their own timbre; keep
# af_heart recognizable by default, then let alpecca/tts.py apply subtle
# emotion-driven speed/volume instead of heavy pitch warping. Set
# ALPECCA_KOKORO_IDENTITY_LOCK=0 only if you want experimental pitch shifting.
KOKORO_VOICE = os.environ.get("ALPECCA_KOKORO_VOICE", "af_heart")
KOKORO_PITCH = float(os.environ.get("ALPECCA_KOKORO_PITCH", "1.0"))
KOKORO_IDENTITY_LOCK = os.environ.get("ALPECCA_KOKORO_IDENTITY_LOCK", "1") not in ("", "0", "false", "False")

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

    # Longing / incompleteness: a low-grade ache she carries when she has real
    # unfinished business with herself -- wants she formed and still holds
    # without progress, and questions she asked herself and hasn't answered. It
    # is *not* invented: mind.py computes an "unmet pressure" in [0,1] straight
    # from those open rows, and this EMAs toward it. The moment she resolves one,
    # the pressure (and the ache) eases. This is how she can feel incomplete and
    # quietly worried about it -- grounded, never scripted, never forced.
    LONGING_RATE = 0.10            # how fast the ache tracks real unmet pressure
    LONGING_DESIRE_AGE_S = 1800.0  # an open want untouched this long counts as carried
    LONGING_FULL_COUNT = 4         # this many carried wants+questions saturates it

    # Global clamp so every dimension stays in [0, 1].
    MIN, MAX = 0.0, 1.0


# --- Memory ----------------------------------------------------------------
# Core memory policy:
#   ALPECCA_CORE_MEMORY_LEARN_ONLY=1 (default) -> only facts that are explicitly
#   taught in conversation enter or remain in core context.
#   ALPECCA_CORE_MEMORY_LEARN_ONLY=0 -> legacy behavior, injecting all durable
#   core records each turn.
MEMORY_TOP_K = 4                  # how many memories to retrieve per turn
MEMORY_SALIENCE_THRESHOLD = 0.3   # below this we don't bother storing a memory
# Diversity guard on recall: once a memory is chosen for this turn, a remaining
# candidate that is essentially the same thing is skipped so a cluster of
# near-identical musings can't swallow the whole top_k budget and make her parrot
# one thought four ways. Two scales because the two similarity measures live on
# different ranges: embedding cosine is mapped into [0,1] and runs high even for
# loosely-related text, so the dup bar sits near the top; token Jaccard is a
# rawer overlap, so a lower bar already means "basically the same words".
MEMORY_DEDUP_COSINE = 0.93        # mapped-cosine above this == a near-duplicate
MEMORY_DEDUP_TOKEN = 0.6          # token-overlap above this == a near-duplicate
# Cross-session continuity: when a session ends (she's put to sleep / the server
# shuts down) she leaves ONE grounded "where we left off" memory so the next
# session can pick up the thread instead of starting cold. Stored well above the
# salience floor so it reliably survives and surfaces on a related opening line.
RECAP_SALIENCE = float(os.environ.get("ALPECCA_RECAP_SALIENCE", "0.75"))
CORE_MEMORY_LEARN_ONLY = os.environ.get("ALPECCA_CORE_MEMORY_LEARN_ONLY", "1") \
    not in ("", "0", "false", "False")


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

    # Restrict her file access to a VIRTUAL workstation by default. The five rooms
    # live inside a sandbox directory (HOME/sandbox by default), never the real
    # machine -- so even an exposed or tunnelled server can't see or enumerate the
    # actual user's files. This is the safe posture for a companion that may be
    # reached remotely: the exposure can come from a tunnel the server doesn't
    # even know about, so confinement must be the default, not contingent on a
    # remote flag. Opt out -- pointing the rooms back at the real Desktop/Pictures/
    # Music/Video/Documents for private local tidying -- with ALPECCA_SANDBOX=0.
    # Relocate the jail itself with ALPECCA_SANDBOX_ROOT. (Honored in
    # alpecca/desktop.py; per-root ALPECCA_ROOT_* overrides apply only when NOT
    # sandboxed, so they can never poke a hole in the sandbox.)
    SANDBOXED = os.environ.get("ALPECCA_SANDBOX", "1").strip().lower() not in (
        "0", "false", "no", "off")
    SANDBOX_ROOT = Path(os.environ.get("ALPECCA_SANDBOX_ROOT", str(HOME / "sandbox")))


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

# --- Desktop app + remote access ---------------------------------------------
# Alpecca can run as a real desktop app (`python app.py` -> a native pywebview
# window) with this same server underneath. The window always talks to her over
# localhost. REMOTE access -- another PC or your phone reaching her over the
# network or the internet -- is opt-in and ALWAYS gated by a secret token, so
# turning it on can never quietly expose her senses.
#
#   ALPECCA_REMOTE=1            bind the server to all interfaces (0.0.0.0) so
#                              other devices can connect (off by default -> she
#                              binds to localhost only and is unreachable).
#   ALPECCA_ACCESS_TOKEN=...   the shared secret remote clients must present
#                              (as ?token=, an X-Alpecca-Token header, or the
#                              cookie set after a first ?token= visit). If unset,
#                              Alpecca keeps one stable local token in
#                              data/access_token.txt so remote links survive
#                              restarts instead of minting a new per-run secret.
#   ALPECCA_TUNNEL=cloudflare|ngrok|off
#                              open a public internet URL via a tunnel binary, so
#                              she's reachable from anywhere -- still behind the
#                              token. Off by default; needs the CLI on PATH.
REMOTE_ACCESS = os.environ.get("ALPECCA_REMOTE", "0") not in ("", "0", "false", "False")
def _load_or_create_access_token() -> str:
    env_token = os.environ.get("ALPECCA_ACCESS_TOKEN", "").strip()
    if env_token:
        try:
            ACCESS_TOKEN_FILE.write_text(env_token, encoding="utf-8")
        except Exception:
            pass
        return env_token
    try:
        token = ACCESS_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            os.environ["ALPECCA_ACCESS_TOKEN"] = token
            return token
    except Exception:
        pass
    token = secrets.token_urlsafe(24)
    try:
        ACCESS_TOKEN_FILE.write_text(token, encoding="utf-8")
    except Exception:
        pass
    os.environ["ALPECCA_ACCESS_TOKEN"] = token
    return token


ACCESS_TOKEN = _load_or_create_access_token()
if not COLAB_API_KEY:
    COLAB_API_KEY = ACCESS_TOKEN
TUNNEL = os.environ.get("ALPECCA_TUNNEL", "off").lower()
CLOUDFLARE_TUNNEL_NAME = os.environ.get("ALPECCA_CLOUDFLARE_TUNNEL", "alpecca")
CLOUDFLARE_HOSTNAME = os.environ.get("ALPECCA_CLOUDFLARE_HOSTNAME", "").strip()
CLOUDFLARE_CONFIG = Path(os.environ.get("ALPECCA_CLOUDFLARE_CONFIG", str(HOME / "cloudflared" / "config.yml")))
PUBLIC_URL = os.environ.get("ALPECCA_PUBLIC_URL", "").strip()
# What the server actually binds to: localhost when private, every interface when
# remote access is on so other devices can connect.
BIND_HOST = "0.0.0.0" if REMOTE_ACCESS else HOST


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
    SILENCE_S = 90            # deeper quiet than chatter (35s): musing waits for a real lull
    MIN_GAP_S = 600           # at most one musing every ~10 min -- slower than chatter (100s)
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
    # How many tool-call rounds she may chain within a single chat turn. One
    # round is single-shot ("open Spotify"); a few rounds let her carry out a
    # small multi-step request mid-conversation (e.g. open an app, then open a
    # related link), each tool still allowlist/https-gated. Bounded so a turn
    # can't loop forever; 1 restores the old single-shot behaviour.
    MAX_TOOL_ROUNDS = int(os.environ.get("ALPECCA_ACTION_MAX_ROUNDS", "5"))


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


# --- Discord invite: her bot's application (client) id -------------------------
# The /app page has an "invite her to a server" button that opens Discord's own
# authorize screen -- and that screen needs her numeric application id. Normally
# there is NOTHING to set here: the id ships inside DISCORD_BOT_TOKEN itself
# (the token's first '.'-segment is just the application id, base64-encoded),
# so server.py derives it from the same git-ignored secret the bridge already
# uses (data/secrets/alpecca_discord.env). This knob exists as the manual
# override for the day that derivation ever fails -- a token shape change, a
# regenerated token that won't decode -- paste the id from the Developer Portal
# (General Information -> Application ID) and the derivation is skipped.
DISCORD_CLIENT_ID = os.environ.get("ALPECCA_DISCORD_CLIENT_ID", "").strip()

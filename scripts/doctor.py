"""Alpecca doctor -- one command that tells you why she won't run, and the fix.

Run it any time she won't start, or just to check she's healthy:

    python scripts/doctor.py

It checks the things that actually block a launch -- Python, the few required
packages, Ollama + her model, the port, and which senses are switched on -- and
for anything missing it prints the exact command to fix it. It imports nothing
from the project, so it works even when config itself is the problem.

Phase 0 of docs/BRINGING_HER_TO_LIFE.md: make her runnable before anything else.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys

G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"
try:
    os.system("")          # enable ANSI colours on Windows terminals
except Exception:
    pass

blockers: list[str] = []
notes: list[str] = []


def ok(msg): print(f"  {G}OK{X}    {msg}")
def warn(msg, fix=""): print(f"  {Y}-- {X}   {msg}" + (f"   {B}fix:{X} {fix}" if fix else ""))
def bad(msg, fix=""):
    print(f"  {R}X{X}     {msg}" + (f"   {B}fix:{X} {fix}" if fix else ""))
    blockers.append(msg)


def have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


print(f"\n{B}== Alpecca doctor =={X}\n")

# --- Python ---------------------------------------------------------------
print("Python")
v = sys.version_info
if v >= (3, 9):
    ok(f"Python {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
else:
    bad(f"Python {v.major}.{v.minor} is too old (need 3.9+)", "install Python 3.12")

# --- Required packages ----------------------------------------------------
print("\nRequired packages (the server needs these)")
for mod, pip in [("fastapi", "fastapi"), ("uvicorn", "uvicorn"),
                 ("websockets", "websockets"), ("ollama", "ollama")]:
    if have(mod):
        ok(mod)
    else:
        bad(f"{mod} missing", f"python -m pip install {pip}")

# --- Ollama (her brain) ---------------------------------------------------
print("\nOllama (her brain -- without it she only gives canned replies)")
model = os.environ.get("ALPECCA_MODEL", "qwen3:8b")
fast = os.environ.get("ALPECCA_FAST_MODEL", "gemma4-e4b")
if have("ollama"):
    try:
        import ollama
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        names = []
        for m in ollama.Client(host=host).list().get("models", []):
            names.append(m.get("model") or m.get("name") or "")
        ok(f"Ollama is running ({len(names)} model(s) installed)")
        base = lambda n: (n or "").split(":")[0]
        if any(n == model or base(n) == base(model) for n in names):
            ok(f"her model '{model}' is present")
        else:
            bad(f"her model '{model}' is NOT pulled", f"ollama pull {model}")
        if not any(n == fast or base(n) == base(fast) for n in names):
            warn(f"fast model '{fast}' not present (fine -- falls back to {model})")
        if not any("vl" in (n or "") for n in names):
            warn("no vision model (qwen2.5vl) -- needed for screen-sight / images",
                 "ollama pull qwen2.5vl:7b")
        else:
            ok("a vision model is present (sight / chat images can work)")
    except Exception as e:
        bad(f"Ollama isn't reachable ({e})",
            "start the Ollama app (it runs in the system tray)")
else:
    bad("the 'ollama' python package is missing", "python -m pip install ollama")

# --- Port -----------------------------------------------------------------
print("\nNetwork")
port = int(os.environ.get("ALPECCA_SERVER_PORT", "8765"))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", port)); ok(f"port {port} is free")
except OSError:
    bad(f"port {port} is already in use (an old server is still running)",
        f"close the other server window, or:  "
        f"Get-NetTCPConnection -LocalPort {port} | %{{ Stop-Process -Id $_.OwningProcess -Force }}")
finally:
    s.close()

# --- Senses / cowork (optional) -------------------------------------------
print("\nSenses & cowork (optional -- on only if you want them)")
def env_on(name): return os.environ.get(name, "0") not in ("", "0", "false", "False")
checks = [
    ("screen-sight", "ALPECCA_SIGHT", ["mss", "PIL"], "python -m pip install mss pillow"),
    ("cowork (computer use)", "ALPECCA_COMPUTER_USE", ["pyautogui", "mss"], "python -m pip install pyautogui mss"),
    ("hearing (push-to-talk)", None, ["faster_whisper"], "python -m pip install faster-whisper"),
    ("webcam expression", "ALPECCA_FACE", ["cv2"], "python -m pip install opencv-python"),
    ("voice-tone", "ALPECCA_VOICE", ["sounddevice"], "python -m pip install sounddevice"),
]
for label, flag, mods, fix in checks:
    missing = [m for m in mods if not have(m)]
    flagon = env_on(flag) if flag else None
    state = []
    if flag is not None:
        state.append("flag ON" if flagon else "flag off")
    state.append("packages ready" if not missing else f"missing {', '.join(missing)}")
    line = f"{label}: " + ", ".join(state)
    if missing:
        warn(line, fix)
    elif flag is not None and not flagon:
        warn(line, f'run  start_full.bat   (or in PowerShell:  $env:{flag}="1" )')
    else:
        ok(line)

# --- Neural face (THA3, optional -- needs an Nvidia GPU) ------------------
print("\nHer neural face (THA3 -- optional, your RTX 3060 can run it)")
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if have("torch"):
    try:
        import torch
        if torch.cuda.is_available():
            ok(f"PyTorch + CUDA ({torch.cuda.get_device_name(0)})")
        else:
            warn("PyTorch installed but CUDA not available (face would run slow on CPU)")
    except Exception as e:
        warn(f"torch present but failed to load ({e})")
else:
    warn("PyTorch not installed", "run  setup_face.bat")
tha3_dir = os.path.join(here, "vendor", "talking-head-anime-3-demo")
if os.path.isdir(tha3_dir):
    ok("THA3 engine is cloned")
    models = os.path.join(tha3_dir, "data", "models")
    if os.path.isdir(models) and os.listdir(models):
        ok("THA3 models are present")
    else:
        warn("THA3 models not downloaded yet",
             "see setup_face.bat step 4 (put them in vendor/.../data/models/)")
else:
    warn("THA3 engine not cloned", "run  setup_face.bat")
if os.path.exists(os.path.join(here, "data", "avatar", "talkinghead", "her.png")):
    ok("her face portrait is prepped")
else:
    warn("her THA3 portrait not prepped",
         "python scripts\\run_talkinghead.py --prep data\\avatar\\portraits\\idle.png")

# --- Verdict --------------------------------------------------------------
print(f"\n{B}== Verdict =={X}")
if blockers:
    print(f"  {R}Not ready.{X} Fix the {len(blockers)} item(s) marked X above, then re-run this.")
    sys.exit(1)
print(f"  {G}Ready.{X} Start her with:")
print(f"      cd {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")
print(f"      python server.py          (private, senses off)")
print(f"      start_full.bat            (all senses + cowork)")
print(f"  Then open  http://127.0.0.1:{port}\n")

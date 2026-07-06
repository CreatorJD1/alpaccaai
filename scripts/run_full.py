"""Wake Alpecca with all her senses on.

`python server.py` starts her in her most private configuration: text chat
only, every ambient sense off. This launcher is the other mode -- the owner
saying "yes, all of it": screen sight, webcam expression sense, mic voice
tone, proactive speech, reflection, and a starter set of safe desktop actions.

Everything is set via the same ALPECCA_* environment variables documented in
config.py, and anything you've already set in your environment wins -- this
script only fills in what you left unset. So it's a convenience, not a second
configuration system.

Usage:
    python scripts/run_full.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Senses on (owner's explicit opt-in by running this script).
os.environ.setdefault("ALPECCA_SIGHT", "1")   # periodic screen glimpses
os.environ.setdefault("ALPECCA_FACE", "1")    # webcam expression sense
os.environ.setdefault("ALPECCA_VOICE", "1")   # mic voice-tone sense

# A starter allowlist of harmless Windows built-ins so her desktop hands work
# out of the box. Add your own apps here or via ALPECCA_APPS in your env.
os.environ.setdefault(
    "ALPECCA_APPS",
    "notepad=notepad.exe;calculator=calc.exe;paint=mspaint.exe;files=explorer.exe",
)

# Import AFTER the env is set -- config.py reads these at import time.
import uvicorn                                    # noqa: E402
from config import HOST, PORT, ACCESS_TOKEN       # noqa: E402
from config import F5_WORKER_ENABLED, F5_WORKER_HOST, F5_WORKER_PORT  # noqa: E402
from alpecca import instance as instance_mod      # noqa: E402


def _f5_worker_health(timeout: float = 0.4) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{F5_WORKER_HOST}:{F5_WORKER_PORT}/health",
            timeout=timeout,
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def _f5_worker_port_taken() -> bool:
    """True if ANYTHING is listening on the F5 worker port -- including a
    worker that is still warming up and not yet 'healthy'. Spawning a second
    worker during that warm-up window is exactly how we ended up with two
    CUDA processes silently splitting the 4 GB card (found live 2026-07-04:
    the orphan held ~800 MB and pushed her whole brain off the GPU)."""
    import socket
    try:
        with socket.create_connection((F5_WORKER_HOST, F5_WORKER_PORT), timeout=0.5):
            return True
    except Exception:
        return False


def _start_f5_worker() -> None:
    if not F5_WORKER_ENABLED or _f5_worker_health() or _f5_worker_port_taken():
        return
    log_dir = Path(__file__).resolve().parent.parent / "data" / "voice_references" / "generated_samples"
    log_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "cwd": str(Path(__file__).resolve().parent.parent),
        "stdout": open(log_dir / "f5_worker.log", "a", encoding="utf-8"),
        "stderr": open(log_dir / "f5_worker.err.log", "a", encoding="utf-8"),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([sys.executable, "scripts\\f5_tts_worker.py"], **kwargs)
    print(f"Alpecca F5 voice worker is warming at http://{F5_WORKER_HOST}:{F5_WORKER_PORT} ...")
    for _ in range(45):
        if _f5_worker_health(timeout=0.8):
            print("Alpecca F5 voice worker is ready.")
            return
        time.sleep(1)
    print("Alpecca F5 voice worker is still warming; Kokoro remains available meanwhile.")


def _start_discord_bridge() -> None:
    """Bring her Discord presence up alongside her app, if a bot token is set, so
    relaunching never leaves her offline. Skips silently when no token exists."""
    root = Path(__file__).resolve().parent.parent
    secret = root / "data" / "secrets" / "alpecca_discord.env"
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token and secret.exists():
        for line in secret.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DISCORD_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
                break
    if not token:
        return
    log_dir = root / "data" / "voice_references" / "generated_samples"
    log_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "cwd": str(root),
        "stdout": open(log_dir / "discord_bridge.log", "a", encoding="utf-8"),
        "stderr": open(log_dir / "discord_bridge.err.log", "a", encoding="utf-8"),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([sys.executable, "scripts\\run_discord_bridge.py"], **kwargs)
    print("Alpecca Discord bridge starting -- she'll come online in her server.")


def _backup_soul() -> None:
    """Rotating startup backup of her save file (state, memories, journal --
    everything). One copy per day under data/backups/, keep the last 7. Until
    now the only safety net was a stale manual copy on the Desktop. Never
    raises: a failed backup must not stop her from waking."""
    try:
        from config import DB_PATH
        db = Path(DB_PATH)
        if not db.exists():
            return
        backups = db.parent / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d")
        dest = backups / f"alpecca-{stamp}.db"
        if not dest.exists():
            import shutil
            shutil.copy2(db, dest)
            print(f"Backed up her save to {dest.name}")
        old = sorted(backups.glob("alpecca-*.db"))
        for stale in old[:-7]:
            stale.unlink(missing_ok=True)
    except Exception:
        pass


def _ollama_up(timeout: float = 2.0) -> bool:
    try:
        from config import OLLAMA_HOST
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/version", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_watchdog() -> None:
    """Keep the Ollama daemon alive for the life of the app. It has died
    silently mid-session more than once, and it is now a single point of
    failure: BOTH her local models and the hosted cloud models route through
    the one localhost daemon, so when it drops she loses her whole language
    core and falls back to canned lines until someone notices. Check every
    60s; if it's gone, respawn `ollama serve` detached and let the next
    check confirm. Never raises -- a watchdog that can crash the app it
    guards would be worse than none."""
    import threading

    def _loop() -> None:
        while True:
            time.sleep(60)
            try:
                if _ollama_up():
                    continue
                exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
                cmd = [str(exe), "serve"] if exe.exists() else ["ollama", "serve"]
                kwargs = {}
                if os.name == "nt":
                    kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                               | subprocess.DETACHED_PROCESS)
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, **kwargs)
                print("[watchdog] Ollama was down -- restarted it.")
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True, name="OllamaWatchdog").start()


existing = instance_mod.existing_server_url(PORT, token=ACCESS_TOKEN)
if existing:
    print(f"Alpecca is already awake at {existing}; reusing the same mind instance.")
    print("Open the existing app instead of starting a second server:")
    suffix = f"?token={ACCESS_TOKEN}" if ACCESS_TOKEN else ""
    print(f"  {existing}/{suffix}")
    raise SystemExit(0)

_backup_soul()
_start_f5_worker()
_start_discord_bridge()
_ollama_watchdog()

from server import app, mind                      # noqa: E402

if __name__ == "__main__":
    print(f"Alpecca is waking up (full senses) at http://{HOST}:{PORT}")
    print(f"  LLM online: {mind.llm.online}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

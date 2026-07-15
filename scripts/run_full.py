"""Wake Alpecca with conservative local capability defaults.

`python server.py` starts her in her most private configuration: text chat
only, every ambient sense off. This launcher adds the supporting local services
without treating launch as consent for screen, webcam, microphone, computer, or
application control. Opt into those capabilities with their ALPECCA_* variables.

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
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# This import is deliberately safe before configuration or server startup. The
# lock must be held before config can touch persistent state or any helper can
# start a sidecar service.
from alpecca import instance as instance_mod      # noqa: E402

# Risky capabilities stay off unless the caller explicitly opted in.
os.environ.setdefault("ALPECCA_COMPUTER_USE", "0")
os.environ.setdefault("ALPECCA_SIGHT", "0")   # periodic screen glimpses
os.environ.setdefault("ALPECCA_FACE", "0")    # webcam expression sense
os.environ.setdefault("ALPECCA_VOICE", "0")   # mic voice-tone sense
os.environ.setdefault("ALPECCA_APPS", "")     # explicit app allowlist only
# The full local stack may share only Alpecca's closed, verified local image
# catalog on Discord. This mirrors START_HERE.bat and does not enable arbitrary
# file transfer, remote vision, screen capture, or any other sensing capability.
os.environ.setdefault("ALPECCA_DISCORD_MEDIA", "1")
# Match START_HERE.bat for the creator-approved Discord room: voice is scoped
# to a claimed room, local TTS, and bounded local transcription. It is separate
# from the ambient laptop microphone sensor above, which remains off. An
# explicit ALPECCA_DISCORD_VOICE=0 or ALPECCA_DISCORD_VOICE_RECEIVE=0 still wins.
os.environ.setdefault("ALPECCA_DISCORD_VOICE", "1")
os.environ.setdefault("ALPECCA_DISCORD_VOICE_RECEIVE", "1")

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
    """Publish one verified, WAL-safe local continuity snapshot at startup.

    The SQLite backup API captures committed pages still held in the WAL, then
    validates the staged copy before it becomes a retained snapshot. A backup
    failure must never prevent Alpecca from waking, but it is reported instead
    of silently leaving a misleading raw database copy behind.
    """
    try:
        from config import DB_PATH
        from alpecca.sqlite_backup import SQLiteBackupError, snapshot_database

        db = Path(DB_PATH)
        if not db.exists():
            return
        snapshot = snapshot_database(
            db,
            db.parent / "backups",
            retention=7,
            label="alpecca",
        )
        print(f"Backed up her continuity snapshot to {snapshot.path.name}")
    except SQLiteBackupError as exc:
        print(f"[backup] Alpecca continuity snapshot skipped: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[backup] Alpecca continuity snapshot failed: {type(exc).__name__}", file=sys.stderr)


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


def _local_server_up(timeout: float = 0.5) -> bool:
    """Return whether this process's loopback server is answering."""
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/system/doctor", timeout=timeout
        )
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _issue_local_bootstrap_url(server_module, path: str = "/",
                               timeout: float = 5.0) -> str | None:
    """Bounded wait for the server-owned one-time local bootstrap API."""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() <= deadline:
        issue = getattr(server_module, "issue_local_bootstrap_url", None)
        if callable(issue):
            try:
                url = issue(path)
            except Exception:
                url = None
            if isinstance(url, str) and url.strip():
                return url.strip()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))
    return None


def _open_local_app_when_ready(server_module, timeout: float = 25.0) -> None:
    """Wait for startup, mint one bootstrap, and hand it directly to the OS."""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() <= deadline:
        if _local_server_up():
            break
        time.sleep(0.1)
    else:
        print("Alpecca's local server did not become ready; no window was opened.")
        return
    url = _issue_local_bootstrap_url(server_module)
    if not url:
        print("Alpecca could not issue a local bootstrap; no window was opened.")
        return
    webbrowser.open(url)


def _instance_lock_path() -> Path:
    """Keep the launcher lock alongside the configured persistent state."""
    return Path(os.environ.get("ALPECCA_HOME", ROOT / "data")) / "alpecca.instance"


def _run() -> int:
    """Start the stack after the process-wide instance lock is held."""
    global F5_WORKER_ENABLED, F5_WORKER_HOST, F5_WORKER_PORT, HOST, PORT

    # Import AFTER the env is set and the lock is acquired: config.py creates
    # the home directory and can migrate persistent state at import time.
    import uvicorn
    from config import F5_WORKER_ENABLED, F5_WORKER_HOST, F5_WORKER_PORT
    from config import HOST, PORT

    existing = instance_mod.existing_server_url(PORT)
    if existing:
        print(f"Alpecca is already awake at {existing}; reusing the same mind instance.")
        print("Use the already-open authenticated surface; no second server was started.")
        return 0

    _backup_soul()
    _start_f5_worker()
    _start_discord_bridge()
    _ollama_watchdog()

    from server import app, mind
    import server as server_mod

    print(f"Alpecca is waking up (safe capability defaults) at http://{HOST}:{PORT}")
    print(f"  LLM online: {mind.llm.online}")
    threading.Thread(
        target=_open_local_app_when_ready,
        args=(server_mod,),
        daemon=True,
        name="LocalBootstrap",
    ).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    return 0


def main() -> int:
    """Run one full stack, refusing a concurrent CoreMind/database writer."""
    lock = instance_mod.LocalInstanceLock(_instance_lock_path())
    try:
        lock.acquire()
    except instance_mod.InstanceLockError as exc:
        print(f"Alpecca is already awake; no second full stack was started ({exc}).", file=sys.stderr)
        return 1

    try:
        return _run()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

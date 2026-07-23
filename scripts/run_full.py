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

import json
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
from alpecca import host_roles as host_roles_mod  # noqa: E402
from alpecca.continuity_lease import (             # noqa: E402
    ContinuityLeaseError,
    ContinuityLeaseGuard,
    client_from_env,
)

_CONTINUITY_CHILDREN: list[subprocess.Popen] = []


def _background_creationflags() -> int:
    """Keep every silent Alpecca sidecar out of visible Windows consoles."""
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    )

# Keep the supported launch paths on the same workload split.  Callers may
# override any value explicitly; these defaults prevent the GUI, phone-share,
# and direct full-stack launchers from silently losing the hosted/local roles
# that ALPECCA_LAUNCHER.bat configures.
os.environ.setdefault("ALPECCA_LLM_BACKEND", "ollama")
os.environ.setdefault("ALPECCA_MODEL", "qwen3.5:9b")
os.environ.setdefault("ALPECCA_FAST_MODEL", "qwen3.5:9b")
os.environ.setdefault("ALPECCA_NUM_CTX", "8192")
os.environ.setdefault("ALPECCA_MINDPAGE", "1")
os.environ.setdefault("ALPECCA_MINDPAGE_DISK_GB", "8")
os.environ.setdefault("ALPECCA_PRESSURE_PAGE_TARGET", "0.55")
# Keep the one local Qwen runtime within the laptop's commit budget. Windows
# may back cold pageable allocations with the existing pagefile; hot prompt/KV
# pages remain resident whenever possible. Quantized KV is applied by Ollama
# only when the model/GPU supports Flash Attention.
os.environ.setdefault("OLLAMA_FLASH_ATTENTION", "1")
os.environ.setdefault("OLLAMA_KV_CACHE_TYPE", "q8_0")
os.environ.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
os.environ.setdefault("OLLAMA_NUM_PARALLEL", "1")
os.environ.setdefault("ALPECCA_CHAT_CLOUD_MODEL", "gemma4:cloud")
os.environ.setdefault("ALPECCA_CHAT_CLOUD_PAGED_MEMORY", "1")
os.environ.setdefault("ALPECCA_CHAT_ZEROGPU", "0")
# Prefer the separate non-speaking ROG worker for background deep work. If its
# exact shared credential is absent or the host is unavailable, CoreMind walks
# straight on to hosted Gemma and then the existing local Qwen fallback.
os.environ.setdefault("ALPECCA_ROG_WORKER_URL", "https://Jason_HOLYROG:8788")
os.environ.setdefault(
    "ALPECCA_ROG_WORKER_CA_CERT",
    str(Path(os.environ.get("LOCALAPPDATA", Path.home()))
        / "Alpecca" / "rog-worker" / "tls" / "jason-holyrog.crt"),
)
os.environ.setdefault("ALPECCA_ROG_WORKER_MODEL", "qwen3.5:9b")
os.environ.setdefault("ALPECCA_DEEP_BACKEND", "rog-worker,ollama-cloud")
os.environ.setdefault("ALPECCA_ROG_SSH_ENABLED", "1")
os.environ.setdefault("ALPECCA_ROG_SSH_HOST", "Jason_HOLYROG")
os.environ.setdefault("ALPECCA_ROG_SSH_USER", "Jason")
os.environ.setdefault("ALPECCA_OLLAMA_CLOUD_MODEL", "gemma4:cloud")
os.environ.setdefault("ALPECCA_REFLECT_MODEL", "qwen3.5:9b")
os.environ.setdefault("ALPECCA_VISION_BACKEND", "local")
os.environ.setdefault("ALPECCA_VISION_CLOUD_MODEL", "gemma4:cloud")
os.environ.setdefault("ALPECCA_DISCORD_CREATOR_CLOUD_VISION", "1")
os.environ.setdefault("ALPECCA_VISION_CLOUD_TRANSPORT_ROUTE", "https://ollama.com/api/chat")
os.environ.setdefault("ALPECCA_VISION_CLOUD_DEPLOYMENT", "ollama-cloud")
os.environ.setdefault("ALPECCA_VISION_CLOUD_PROCESSING_LOCATION", "provider-managed")
os.environ.setdefault("ALPECCA_VISION_MODEL", "qwen3.5:4b")
os.environ.setdefault("ALPECCA_VISION_NUM_GPU", "99")
os.environ.setdefault("ALPECCA_VISION_TIMEOUT", "60")
os.environ.setdefault("ALPECCA_CLOUD_STANDBY_URL", "https://creatorjd-alpecca-survival-core.hf.space")
os.environ.setdefault(
    "ALPECCA_CLOUD_TTS_ENDPOINT",
    os.environ["ALPECCA_CLOUD_STANDBY_URL"].rstrip("/") + "/voice/tts",
)

# Risky capabilities stay off unless the caller explicitly opts in.
os.environ.setdefault("ALPECCA_COMPUTER_USE", "0")
os.environ.setdefault("ALPECCA_SIGHT", "0")   # periodic, local-only screen glimpses
os.environ.setdefault("ALPECCA_FACE", "0")    # webcam expression sense
os.environ.setdefault("ALPECCA_VOICE", "0")   # mic voice-tone sense
os.environ.setdefault("ALPECCA_APPS", "")     # explicit app allowlist only
# The full local stack may share only Alpecca's closed, verified local image
# catalog on Discord. This mirrors the unified launcher and does not enable arbitrary
# file transfer, remote vision, screen capture, or any other sensing capability.
os.environ.setdefault("ALPECCA_DISCORD_MEDIA", "1")
# Match the unified launcher for the creator-approved Discord room: voice is scoped
# to a claimed room, local TTS, and bounded local transcription. It is separate
# from the ambient laptop microphone sensor above, which remains off. An
# explicit ALPECCA_DISCORD_VOICE=0 or ALPECCA_DISCORD_VOICE_RECEIVE=0 still wins.
os.environ.setdefault("ALPECCA_DISCORD_VOICE", "1")
os.environ.setdefault("ALPECCA_DISCORD_VOICE_RECEIVE", "1")
os.environ.setdefault("ALPECCA_CHAT_VOICE_TIMEOUT", "3.0")
os.environ.setdefault("ALPECCA_CLOUD_TTS_TIMEOUT_SECONDS", "2.5")
os.environ.setdefault("ALPECCA_LIVE_TTS_TIMEOUT", "3.0")
os.environ.setdefault("ALPECCA_DISCORD_VOICE_TIMEOUT", "4.0")
os.environ.setdefault("ALPECCA_DISCORD_TRANSCRIBE_TIMEOUT", "6.0")
os.environ.setdefault("ALPECCA_DISCORD_TTS_ENGINE", "cloud")

def _lan_access_point(port: int) -> str:
    """The URL another device on this network uses to reach THIS computer.
    Best-effort local IP via the standard UDP-socket route trick (no packets
    are actually sent); falls back to the hostname form if it can't be found."""
    import socket
    ip = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        ip = ""
    return f"http://{ip or socket.gethostname()}:{port}"


def _f5_worker_health(timeout: float = 0.4) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{F5_WORKER_HOST}:{F5_WORKER_PORT}/health",
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                return False
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return payload.get("ready") is True
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
        kwargs["creationflags"] = _background_creationflags()
    process = subprocess.Popen([sys.executable, "scripts\\f5_tts_worker.py"], **kwargs)
    _CONTINUITY_CHILDREN.append(process)
    print(f"Alpecca F5 voice worker is warming at http://{F5_WORKER_HOST}:{F5_WORKER_PORT} ...")
    print("Kokoro remains available while F5 finishes warming in the background.")


def _start_discord_bridge() -> None:
    """Bring her Discord presence up alongside her app, if a bot token is set, so
    relaunching never leaves her offline. Skips silently when no token exists."""
    if os.environ.get("ALPECCA_CONTINUITY_OFFLINE_ISOLATED") == "1":
        return
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
        kwargs["creationflags"] = _background_creationflags()
    process = subprocess.Popen([sys.executable, "scripts\\run_discord_bridge.py"], **kwargs)
    _CONTINUITY_CHILDREN.append(process)
    print("Alpecca Discord bridge starting -- she'll come online in her server.")


def _wake_cloud_standby() -> None:
    """Wake the passive cloud fallback without promoting a second CoreMind."""
    root = Path(__file__).resolve().parent.parent
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "cwd": str(root),
        "stdout": open(log_dir / "cloud_standby_wake.log", "a", encoding="utf-8"),
        "stderr": open(log_dir / "cloud_standby_wake.err.log", "a", encoding="utf-8"),
    }
    if os.name == "nt":
        kwargs["creationflags"] = _background_creationflags()
    process = subprocess.Popen([sys.executable, "scripts\\wake_cloud_standby.py"], **kwargs)
    _CONTINUITY_CHILDREN.append(process)
    print("Alpecca cloud continuity standby wake requested.")


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
                    kwargs["creationflags"] = _background_creationflags()
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


def _continuity_endpoint() -> str:
    """Return only an explicitly registered public endpoint for this runtime."""
    return (
        os.environ.get("ALPECCA_CONTINUITY_PUBLIC_ENDPOINT", "").strip()
        or os.environ.get("ALPECCA_PUBLIC_URL", "").strip()
    )


def _lease_transport_unavailable(error: BaseException) -> bool:
    """Distinguish an unreachable authority from an explicit lease refusal."""
    return str(error).lower().startswith("lease transport failed:")


def _enter_offline_isolated_mode(reason: str) -> None:
    """Allow one locally locked runtime without exposing split-brain surfaces."""
    os.environ["ALPECCA_CONTINUITY_OFFLINE_ISOLATED"] = "1"
    os.environ.pop("ALPECCA_CONTINUITY_LEASE_ID", None)
    os.environ.pop("ALPECCA_CONTINUITY_FENCING_EPOCH", None)
    os.environ.pop("ALPECCA_CONTINUITY_LEASE_HOLDER", None)
    os.environ.pop("ALPECCA_CONTINUITY_LAUNCHER_PID", None)
    os.environ["ALPECCA_REMOTE"] = "0"
    os.environ["ALPECCA_PUBLIC_URL"] = ""
    os.environ["ALPECCA_CONTINUITY_PUBLIC_ENDPOINT"] = ""
    os.environ["ALPECCA_CHAT_CLOUD_MODEL"] = ""
    os.environ["ALPECCA_CHAT_CLOUD_PAGED_MEMORY"] = "0"
    os.environ["ALPECCA_DEEP_BACKEND"] = "local"
    os.environ["ALPECCA_OLLAMA_CLOUD_MODEL"] = ""
    os.environ["ALPECCA_MINDSCAPE_URL"] = ""
    os.environ["ALPECCA_MINDSCAPE_AUTO_SYNC_INTERVAL"] = "0"
    os.environ["ALPECCA_MINDSCAPE_VAULT"] = "0"
    os.environ["ALPECCA_MINDSCAPE_VAULT_AUTO_SYNC_INTERVAL"] = "0"
    os.environ["ALPECCA_DISCORD_MEDIA"] = "0"
    os.environ["ALPECCA_DISCORD_VOICE"] = "0"
    os.environ["ALPECCA_DISCORD_VOICE_RECEIVE"] = "0"
    print(
        "[continuity] Lease service is unreachable; starting one local-only "
        f"isolated session ({reason}). Cloud sync, Discord, and remote access "
        "will remain off until Alpecca is restarted with internet access.",
        file=sys.stderr,
        flush=True,
    )


def _lease_loss(reason: str) -> None:
    """Fence this runtime before another host can acquire the next epoch."""
    print(
        f"[continuity] Remote singleton lease was lost ({reason}); "
        "stopping this runtime before failover.",
        file=sys.stderr,
        flush=True,
    )
    for process in tuple(_CONTINUITY_CHILDREN):
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass
    os._exit(75)


def _start_continuity_guard() -> ContinuityLeaseGuard | None:
    """Acquire the optional cross-host lease before any runtime side effects."""
    client = client_from_env(role="local-primary")
    if client is None:
        return None

    guard = ContinuityLeaseGuard(
        client,
        renew_seconds=float(os.environ.get("ALPECCA_CONTINUITY_RENEW_SECONDS", "10")),
        endpoint=_continuity_endpoint(),
        on_loss=_lease_loss,
    )
    timeout = max(
        0.0,
        min(60.0, float(os.environ.get("ALPECCA_CONTINUITY_ACQUIRE_TIMEOUT", "40"))),
    )
    deadline = time.monotonic() + timeout
    last_error = "lease denied"
    while True:
        try:
            grant = guard.start()
            os.environ["ALPECCA_CONTINUITY_LEASE_ID"] = grant.lease_id
            os.environ["ALPECCA_CONTINUITY_FENCING_EPOCH"] = str(grant.fencing_epoch)
            os.environ["ALPECCA_CONTINUITY_LEASE_HOLDER"] = grant.holder
            # server.py is imported in this same process. Binding the inherited
            # lease tuple to this PID prevents an accidental direct ASGI launch
            # or a stale copied environment from constructing another CoreMind.
            os.environ["ALPECCA_CONTINUITY_LAUNCHER_PID"] = str(os.getpid())
            print(
                "Alpecca continuity lease acquired "
                f"(local-primary, epoch {grant.fencing_epoch})."
            )
            return guard
        except ContinuityLeaseError as exc:
            last_error = str(exc)
            if _lease_transport_unavailable(exc):
                raise
            if time.monotonic() >= deadline:
                raise ContinuityLeaseError(last_error) from exc
            time.sleep(min(2.0, max(0.05, deadline - time.monotonic())))


def _merge_continuity_before_start() -> None:
    """Apply cloud-created events after lease acquisition and before CoreMind."""
    cloud_url = os.environ.get("ALPECCA_MINDSCAPE_VAULT_URL", "").strip()
    if not cloud_url:
        return
    from config import DB_PATH
    from alpecca import continuity_journal, mindscape_vault

    recovery_key, _key_source = mindscape_vault.load_or_create_encryption_key()
    transport_token, _token_source = mindscape_vault.load_or_create_transport_token()
    result = continuity_journal.fetch_and_merge(
        cloud_url,
        transport_token,
        recovery_key,
        db_path=DB_PATH,
        timeout=float(os.environ.get("ALPECCA_CONTINUITY_MERGE_TIMEOUT", "12")),
    )
    if not result.get("ok"):
        raise ContinuityLeaseError(
            f"continuity journal merge failed: {result.get('status', 'unknown')}"
        )
    print(
        "Alpecca continuity events reconciled "
        f"(merged={result.get('merged', 0)}, duplicates={result.get('duplicates', 0)})."
    )


def _run() -> int:
    """Start the stack after the process-wide instance lock is held."""
    global F5_WORKER_ENABLED, F5_WORKER_HOST, F5_WORKER_PORT, HOST, PORT

    # Import AFTER the env is set and the lock is acquired: config.py creates
    # the home directory and can migrate persistent state at import time.
    import uvicorn
    from config import F5_WORKER_ENABLED, F5_WORKER_HOST, F5_WORKER_PORT
    from config import HOST, PORT, BIND_HOST, REMOTE_ACCESS

    existing = instance_mod.existing_server_url(PORT)
    if existing:
        print(f"Alpecca is already awake at {existing}; reusing the same mind instance.")
        print("Use the already-open authenticated surface; no second server was started.")
        return 0

    _backup_soul()
    _wake_cloud_standby()
    _start_f5_worker()
    _start_discord_bridge()
    _ollama_watchdog()

    from server import app, mind
    import server as server_mod

    print(f"Alpecca is waking up (safe capability defaults) at http://{HOST}:{PORT}")
    print(f"  LLM online: {mind.llm.online}")
    # LOCAL SERVER ACCESS POINT: when ALPECCA_REMOTE=1 she binds every interface
    # (BIND_HOST=0.0.0.0), so the phone/desktop app on your network reaches THIS
    # computer and offloads all the heavy processing (LLM, TTS, vision) here.
    # Still behind her authorization -- binding wider doesn't open the door,
    # alpecca.auth does. Off by default (localhost only) so nothing is exposed
    # until you ask. We print the address other devices connect to.
    if REMOTE_ACCESS:
        lan = _lan_access_point(PORT)
        print("  ACCESS POINT (this computer does the processing):")
        print(f"    On your network:  {lan}")
        print("    Open that on the phone/other PC, or install the app from it.")
        print("    Anywhere (behind her token, needs cloudflared):")
        print("      python scripts/share.py --tunnel")
    else:
        print("  Local only. To let your phone/other devices use THIS computer "
              "for processing, relaunch with ALPECCA_REMOTE=1 (or the launcher's "
              "'Local access point' button).")
    threading.Thread(
        target=_open_local_app_when_ready,
        args=(server_mod,),
        daemon=True,
        name="LocalBootstrap",
    ).start()
    uvicorn.run(app, host=BIND_HOST, port=PORT, log_level="warning")
    return 0


def main() -> int:
    """Run one full stack, refusing a concurrent CoreMind/database writer."""
    try:
        host_roles_mod.require_primary_runtime_host()
    except host_roles_mod.ComputeOnlyHostError as exc:
        print(f"Alpecca full-stack startup refused: {exc}.", file=sys.stderr)
        return 2
    lock = instance_mod.LocalInstanceLock(_instance_lock_path())
    try:
        lock.acquire()
    except instance_mod.InstanceLockError as exc:
        print(f"Alpecca is already awake; no second full stack was started ({exc}).", file=sys.stderr)
        return 1

    continuity_guard = None
    try:
        try:
            continuity_guard = _start_continuity_guard()
            if continuity_guard is not None:
                _merge_continuity_before_start()
        except (ContinuityLeaseError, ValueError) as exc:
            if isinstance(exc, ContinuityLeaseError) and _lease_transport_unavailable(exc):
                _enter_offline_isolated_mode(str(exc))
                return _run()
            print(
                "Alpecca could not acquire the configured cross-host singleton "
                f"lease; startup was refused ({exc}).",
                file=sys.stderr,
            )
            return 2
        return _run()
    finally:
        if continuity_guard is not None:
            continuity_guard.stop()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

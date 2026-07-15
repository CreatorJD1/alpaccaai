"""Alpecca doctor -- one command that tells you why she won't run, and the fix.

Run it any time she won't start, or just to check she's healthy:

    python scripts/doctor.py

It checks the things that actually block a launch -- Python, the few required
packages, Ollama + her model, the port, and which senses are switched on -- and
for anything missing it prints the exact command to fix it. It imports nothing
from config. Authorization probes deliberately reuse ``alpecca.auth`` so the
doctor and server read the same protected credential without exposing it.

Phase 0 of docs/BRINGING_HER_TO_LIFE.md: make her runnable before anything else.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alpecca import auth as auth_mod  # noqa: E402

G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"
try:
    os.system("")          # enable ANSI colours on Windows terminals
except Exception:
    pass

blockers: list[str] = []
notes: list[str] = []
authorization_headers: dict[str, str] = {}
alpecca_server_identified = False


def ok(msg): print(f"  {G}OK{X}    {msg}")
def warn(msg, fix=""): print(f"  {Y}-- {X}   {msg}" + (f"   {B}fix:{X} {fix}" if fix else ""))
def bad(msg, fix=""):
    print(f"  {R}X{X}     {msg}" + (f"   {B}fix:{X} {fix}" if fix else ""))
    blockers.append(msg)


def have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def env_off(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default) in ("", "0", "false", "False")


def env_on(name: str, default: str = "0") -> bool:
    return not env_off(name, default)


def route_url(path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def fetch_json(
    path: str,
    timeout: float = 1.8,
    *,
    authenticated: bool = True,
) -> dict | None:
    if authenticated and not alpecca_server_identified:
        return None
    headers = authorization_headers if authenticated else {}
    req = urllib.request.Request(route_url(path), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return None


def post_tts_preview(preview: str = "tender",
                     timeout: float = 75.0) -> dict | None:
    if not alpecca_server_identified:
        return {"status": 0, "error": "Alpecca is not identified on /healthz"}
    url = route_url("/tts")
    data = json.dumps({
        "text": f"Alpecca {preview} voice preview.",
        "preview": preview,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            **authorization_headers,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "status": resp.status,
                "engine": resp.headers.get("X-Alpecca-TTS-Engine", ""),
                "voice": resp.headers.get("X-Alpecca-Voice", ""),
                "profile": resp.headers.get("X-Alpecca-Voice-Profile", ""),
                "preview": resp.headers.get("X-Alpecca-Voice-Preview", ""),
                "primary": resp.headers.get("X-Alpecca-Voice-Primary", ""),
                "tempo": resp.headers.get("X-Alpecca-Voice-Tempo", ""),
                "rate": resp.headers.get("X-Alpecca-Voice-Rate", ""),
                "speed": resp.headers.get("X-Alpecca-Voice-Speed", ""),
                "style": resp.headers.get("X-Alpecca-Voice-Style", ""),
                "warmth": resp.headers.get("X-Alpecca-Voice-Warmth", ""),
                "breath": resp.headers.get("X-Alpecca-Voice-Breath", ""),
                "identity_lock": resp.headers.get("X-Alpecca-Voice-Identity-Lock", ""),
            }
    except Exception as exc:
        return {"status": 0, "error": f"{type(exc).__name__}: {exc}"}


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
model = os.environ.get("ALPECCA_MODEL", "qwen3.5:9b")
fast = os.environ.get("ALPECCA_FAST_MODEL", "qwen3.5:9b")
vision = os.environ.get("ALPECCA_VISION_MODEL", "qwen3.5:9b")
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
        if not any(n == vision or base(n) == base(vision) for n in names):
            warn(f"vision model '{vision}' is not present -- needed for screen-sight / images",
                 f"ollama pull {vision}")
        else:
            ok("a vision model is present (sight / chat images can work)")
    except Exception as e:
        bad(f"Ollama isn't reachable ({e})",
            "start the Ollama app (it runs in the system tray)")
else:
    bad("the 'ollama' python package is missing", "python -m pip install ollama")

# --- Colab fast accelerator ------------------------------------------------
print("\nColab T4 fast accelerator (optional -- speeds House HQ replies)")
colab_url = os.environ.get("ALPECCA_COLAB_URL", "").rstrip("/")
colab_model = os.environ.get("ALPECCA_COLAB_MODEL", "Qwen/Qwen2.5-7B-Instruct")
if colab_url:
    try:
        from alpecca import colab_t4

        st = colab_t4.status(
            colab_url,
            model=colab_model,
            api_key=os.environ.get("ALPECCA_COLAB_API_KEY", ""),
            timeout=2.5,
        )
        if st.get("ready") and st.get("reachable"):
            ok(f"Colab T4 accelerator ready: {st.get('model') or colab_model} at {colab_url}")
        else:
            warn(f"Colab T4 accelerator configured but offline: {st.get('error')}",
                 st.get("fix") or "restart notebooks/alpecca_colab_t4_server.ipynb and update ALPECCA_COLAB_URL")
    except Exception as exc:
        warn(f"Colab T4 status check failed: {type(exc).__name__}: {exc}")
else:
    warn("Colab T4 accelerator not configured",
         "run notebooks/alpecca_colab_t4_server.ipynb, then set ALPECCA_COLAB_URL")

# --- Deep tier -------------------------------------------------------------
print("\nDeep tier (optional -- for reflection/self-review, not normal chat)")
deep = os.environ.get("ALPECCA_DEEP_BACKEND", "local").lower()
if deep in ("", "local"):
    ok("deep tier is local/off (normal and private)")
elif deep == "zerogpu":
    space = os.environ.get("ALPECCA_ZEROGPU_SPACE", "")
    api = os.environ.get("ALPECCA_ZEROGPU_API", "/chat")
    if have("gradio_client"):
        ok("gradio_client installed")
    else:
        warn("gradio_client missing for ZeroGPU", "python -m pip install gradio_client")
    if space:
        ok(f"ZeroGPU Space configured: {space} {api}")
    else:
        bad("ALPECCA_ZEROGPU_SPACE is blank", "set ALPECCA_ZEROGPU_SPACE=CREATORJD/alpecca-zerogpu")
    if os.environ.get("ALPECCA_ZEROGPU_TOKEN") or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"):
        ok("ZeroGPU/Hugging Face token available")
    else:
        warn("no HF token found; public Spaces may work, private Spaces will not",
             "set HF_TOKEN or ALPECCA_ZEROGPU_TOKEN")
else:
    warn(f"deep tier '{deep}' configured; doctor only verifies local/zerogpu deeply")

# --- Auth -----------------------------------------------------------------
remote = os.environ.get("ALPECCA_REMOTE", "0") not in ("", "0", "false", "False")
repo_root = str(REPO_ROOT)
home_dir = os.environ.get("ALPECCA_HOME", str(REPO_ROOT / "data"))
authorization_error = ""
try:
    authorization_secret = auth_mod.load_or_create_authorization_secret(
        Path(home_dir)
    )
    authorization_headers = {
        auth_mod.AUTHORIZATION_HEADER: authorization_secret,
    }
except Exception as exc:
    authorization_error = f"{type(exc).__name__}: {exc}"

# --- Port -----------------------------------------------------------------
print("\nNetwork")
port = int(os.environ.get("ALPECCA_SERVER_PORT", "8765"))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", port)); ok(f"port {port} is free")
except OSError:
    health = fetch_json("/healthz", timeout=1.2, authenticated=False)
    if health == {"service": "alpecca", "version": 1}:
        alpecca_server_identified = True
        ok(f"port {port} is in use by Alpecca (/healthz identified version 1)")
    else:
        bad(f"port {port} is already in use, but Alpecca routes did not answer",
            f"close the other server window, or:  "
            f"Get-NetTCPConnection -LocalPort {port} | %{{ Stop-Process -Id $_.OwningProcess -Force }}")
finally:
    s.close()

# --- Auth / routes ---------------------------------------------------------
print("\nApp routes")
if authorization_headers:
    if auth_mod.AUTH_ENV_NAME in os.environ:
        provider = f"the {auth_mod.AUTH_ENV_NAME} protected override"
    elif os.name == "nt":
        provider = "Windows Credential Manager"
    else:
        provider = "the process-local authorization fallback"
    ok(f"protected authorization header ready via {provider} (secret not displayed)")
else:
    bad(
        f"protected authorization credential unavailable ({authorization_error})",
        "install pywin32 on Windows, then re-run python scripts\\doctor.py",
    )

ok("loopback browser access uses one-use trusted-device bootstrap")
if remote:
    ok("remote auth uses HTTPS trusted-device enrollment and a signed HttpOnly session")
else:
    ok("remote access is off; its auth path is HTTPS trusted-device enrollment")

def check_route(path: str, label: str):
    if not alpecca_server_identified:
        warn(f"{label} route not checked; no running Alpecca process was identified",
             f"start her, then open http://127.0.0.1:{port}")
        return
    if not authorization_headers:
        warn(f"{label} route not checked; protected authorization is unavailable")
        return
    req = urllib.request.Request(route_url(path), headers=authorization_headers)
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                ok(f"{label} route returns 200")
            else:
                warn(f"{label} route returned {resp.status}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            warn(
                f"{label} rejected the protected authorization header",
                "restart the doctor and server under the same Windows user/credential",
            )
        else:
            warn(f"{label} route returned {exc.code}")
    except Exception:
        warn(f"{label} route not responding yet", f"start her, then open http://127.0.0.1:{port}")

check_route("/state", "/state")
check_route("/cognition/state", "/cognition/state")
check_route("/house-hq", "/house-hq")
check_route("/mindscape", "/mindscape")
check_route("/system/status", "/system/status")
check_route("/system/doctor", "/system/doctor")

dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "apps", "house-hq", "dist", "index.html")
if os.path.exists(dist):
    ok("House HQ build output exists")
else:
    warn("House HQ build output missing", "npm.cmd run house:build")

print("\nRemote preview (phone / mobile data)")
cf_config = os.environ.get(
    "ALPECCA_CLOUDFLARE_CONFIG",
    os.path.join(home_dir, "cloudflared", "config.yml"),
)
cf_hostname = os.environ.get("ALPECCA_CLOUDFLARE_HOSTNAME", "").strip()
public_url = os.environ.get("ALPECCA_PUBLIC_URL", "").strip()
cf_env_hint = os.path.join(home_dir, "cloudflared", "alpecca-cloudflare.env")
cloudflared = shutil.which("cloudflared") or (
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if os.path.exists(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
    else ""
)
if cloudflared:
    ok(f"cloudflared found: {cloudflared}")
else:
    warn("cloudflared is not installed", "winget install cloudflare.cloudflared")
if public_url or cf_hostname:
    enrollment_url = public_url or "https://" + cf_hostname
    if enrollment_url.startswith("https://"):
        ok(f"HTTPS trusted-device enrollment URL configured: {enrollment_url}")
    else:
        warn(
            f"remote URL is not HTTPS: {enrollment_url}",
            "configure an HTTPS Cloudflare URL for trusted-device enrollment",
        )
elif os.path.exists(cf_env_hint):
    warn("stable tunnel env exists but is not loaded for this shell",
         f"type {cf_env_hint} and set those ALPECCA_* values before starting Alpecca")
else:
    warn("stable public URL is not configured",
         "python scripts\\setup_cloudflare_tunnel.py --hostname alpecca.your-domain.com")
if os.path.exists(cf_config):
    ok(f"named Cloudflare config exists: {cf_config}")
else:
    warn("named Cloudflare config missing",
         "python scripts\\setup_cloudflare_tunnel.py --hostname alpecca.your-domain.com")
try:
    with urllib.request.urlopen("https://api.trycloudflare.com/tunnel", timeout=4) as _:
        ok("Cloudflare quick-tunnel API responded")
except urllib.error.HTTPError:
    ok("Cloudflare quick-tunnel API responded")
except Exception:
    warn("Cloudflare quick-tunnel API did not respond quickly; named tunnel is the safer path")

# --- Mindscape --------------------------------------------------------------
print("\nMindscape continuity fallback")
mindscape_url = os.environ.get("ALPECCA_MINDSCAPE_URL", "")
mindscape_token = os.environ.get("ALPECCA_MINDSCAPE_TOKEN", "")
mindscape_interval = float(os.environ.get("ALPECCA_MINDSCAPE_AUTO_SYNC_INTERVAL", "300"))
mindscape_event_interval = float(os.environ.get("ALPECCA_MINDSCAPE_EVENT_SYNC_MIN_INTERVAL", "45"))
worker_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "deploy", "mindscape-worker")
wrangler_file = os.path.join(worker_dir, "wrangler.toml")
if os.path.isdir(worker_dir):
    ok("Mindscape Worker template exists")
else:
    warn("Mindscape Worker template missing", "restore deploy/mindscape-worker")
if os.path.exists(wrangler_file):
    wrangler_text = open(wrangler_file, "r", encoding="utf-8").read()
    if "replace-with-your-kv-namespace-id" in wrangler_text:
        warn("Mindscape Worker KV namespace id is still the placeholder",
             "cd deploy\\mindscape-worker; npx wrangler kv namespace create MINDSCAPE_KV --json; python ..\\..\\scripts\\setup_mindscape_worker.py --from-clipboard --print-next")
    else:
        ok("Mindscape Worker KV namespace id is configured")
if mindscape_url:
    if mindscape_url.startswith("https://") or mindscape_url.startswith("http://127.0.0.1") or mindscape_url.startswith("http://localhost"):
        ok(f"Mindscape cloud target configured: {mindscape_url}")
    else:
        bad("Mindscape cloud target must use https",
            "set ALPECCA_MINDSCAPE_URL=https://.../sync")
    if mindscape_token:
        ok("Mindscape sync token configured")
    else:
        warn("Mindscape cloud target has no token",
             "set ALPECCA_MINDSCAPE_TOKEN to match the Worker secret")
    if mindscape_interval > 0:
        ok(f"Mindscape auto-sync every {mindscape_interval:g}s")
    else:
        warn("Mindscape auto-sync disabled", "set ALPECCA_MINDSCAPE_AUTO_SYNC_INTERVAL=300")
    if mindscape_event_interval > 0:
        ok(f"Mindscape event-sync throttle {mindscape_event_interval:g}s")
    else:
        warn("Mindscape event-sync disabled", "set ALPECCA_MINDSCAPE_EVENT_SYNC_MIN_INTERVAL=45")
else:
    warn("Mindscape cloud target not configured",
         "deploy deploy/mindscape-worker, then set ALPECCA_MINDSCAPE_URL")

# --- Senses / cowork (optional) -------------------------------------------
print("\nSenses & cowork (optional -- on only if you want them)")
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

# --- Spoken voice ----------------------------------------------------------
print("\nSpoken voice (original Alpecca voice + modulation)")
tts_backend = os.environ.get("ALPECCA_TTS_BACKEND", "auto").lower()
kokoro_voice = os.environ.get("ALPECCA_KOKORO_VOICE", "af_heart")
identity_lock = env_on("ALPECCA_KOKORO_IDENTITY_LOCK", "1")
if tts_backend in ("off", "browser", "none"):
    warn(f"server TTS is disabled ({tts_backend}); browser voice will be used",
         "set ALPECCA_TTS_BACKEND=auto")
else:
    ok(f"server TTS backend preference: {tts_backend}")
    if kokoro_voice == "af_heart":
        ok("original Kokoro speaker is selected: af_heart")
    else:
        warn(f"Kokoro speaker is {kokoro_voice!r}, not Alpecca's original af_heart",
             "set ALPECCA_KOKORO_VOICE=af_heart")
    if identity_lock:
        ok("Kokoro identity lock is ON (keeps her timbre stable)")
    else:
        warn("Kokoro identity lock is OFF; pitch shifting can make her sound unlike herself",
             "set ALPECCA_KOKORO_IDENTITY_LOCK=1")
    if have("kokoro") and have("soundfile") and have("numpy"):
        ok("Kokoro local voice packages are installed")
    else:
        warn("Kokoro local voice packages missing",
             "python -m pip install kokoro soundfile numpy")
    if have("edge_tts"):
        ok("edge-tts neural fallback is installed")
    else:
        warn("edge-tts fallback missing", "python -m pip install edge-tts")
    try:
        from alpecca import open_tts

        open_status = open_tts.status()
        cache = open_status.get("cache", {})
        if open_status.get("ready"):
            ok(f"high-quality F5 voice tier is ready: {open_status.get('ready_sample')}")
        elif open_status.get("f5_available"):
            if cache.get("incomplete_count"):
                warn(
                    "high-quality F5 voice tier is installed but its model download is incomplete "
                    f"({cache.get('incomplete_count')} partial blob, largest complete {cache.get('largest_complete_mb')} MB)",
                    "run: python scripts\\warm_open_tts.py --clean-incomplete --download-only ; then python scripts\\warm_open_tts.py",
                )
            else:
                warn(
                    "high-quality F5 voice tier is installed but not warmed",
                    "run: python scripts\\warm_open_tts.py",
                )
        else:
            warn(
                "high-quality F5 voice tier is not installed",
                "run: powershell -ExecutionPolicy Bypass -File scripts\\setup_f5_tts.ps1",
            )
    except Exception as exc:
        warn(f"high-quality F5 voice status failed: {type(exc).__name__}: {exc}")
    warn("first Kokoro line can take a minute while the model warms/downloads")
    live_voice = fetch_json("/voice")
    if live_voice:
        voice = live_voice.get("voice", "")
        profile = live_voice.get("profile", "")
        primary = live_voice.get("primary", "")
        tempo = live_voice.get("tempo", "")
        rate = live_voice.get("rate_pct", "")
        style = live_voice.get("style", "")
        warmth = live_voice.get("warmth", "")
        breath = live_voice.get("breath", "")
        if voice == "af_heart" and live_voice.get("identity_lock"):
            ok(f"live /voice reports original identity: {voice} / {profile}")
        else:
            warn(f"live /voice reports {voice or 'unknown'} / identity_lock={live_voice.get('identity_lock')}",
                 "restart the server after setting ALPECCA_KOKORO_VOICE=af_heart and ALPECCA_KOKORO_IDENTITY_LOCK=1")
        ok(f"live modulation now: {primary or 'content'} / {style or 'present'} / {tempo or 'measured'} / {rate or 100}% / warmth {warmth or 'n/a'} / breath {breath or 'n/a'}")
    else:
        warn("live /voice is not responding yet", f"start her, then open {route_url('/voice')}")
    if fetch_json("/system/status"):
        ok("live /system/status is available for app-side voice diagnostics")
    preview_requested = "--voice-preview" in sys.argv or env_on("ALPECCA_DOCTOR_TTS", "0")
    if preview_requested:
        preview = post_tts_preview("tender")
        if preview and preview.get("status") == 200:
            if preview.get("engine") == "kokoro" and preview.get("voice") == "af_heart" and preview.get("identity_lock") == "1":
                ok(f"live /tts preview uses Kokoro original voice: {preview.get('voice')} / {preview.get('profile')}")
            else:
                warn(
                    "live /tts preview did not report Kokoro + af_heart + identity lock "
                    f"({preview.get('engine')} / {preview.get('voice')} / lock={preview.get('identity_lock')})",
                    "check ALPECCA_KOKORO_VOICE, ALPECCA_KOKORO_IDENTITY_LOCK, and Kokoro install",
                )
            ok(f"live /tts tender modulation: {preview.get('primary')} / {preview.get('style')} / {preview.get('tempo')} / {preview.get('rate')}% / warmth {preview.get('warmth')} / breath {preview.get('breath')}")
        elif preview:
            warn(f"live /tts preview failed: {preview.get('error') or preview.get('status')}",
                 "start the server and wait for Kokoro to warm up")
    else:
        warn("skipping slow live /tts audio preview",
             "run python scripts\\doctor.py --voice-preview to test actual Kokoro audio headers")

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

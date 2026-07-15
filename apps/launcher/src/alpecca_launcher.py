"""Desktop boot surface for Alpecca.

This is the normal Windows entry point for the local companion stack.  It
starts the existing ``scripts/run_full.py`` process without a terminal window,
shows bounded startup progress, and opens House HQ only after the local server
answers.  The launcher deliberately does not own Alpecca's state: the full
stack retains the instance lock, backup, Discord, voice, and server lifecycle.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Mapping
from pathlib import Path

import tkinter as tk
from tkinter import messagebox


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)


def find_repo_root() -> Path | None:
    """Walk upward from the launcher until the project root is found."""
    if getattr(sys, "frozen", False):
        start = Path(sys.executable).resolve().parent
    else:
        start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "server.py").is_file():
            return candidate
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "server.py").is_file():
            return candidate
    return None


REPO_ROOT = find_repo_root()


def _configured_port() -> int:
    """Read the project port when config is importable; otherwise use 8765."""
    if REPO_ROOT is None:
        return 8765
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from config import PORT as configured_port  # noqa: E402

        return int(configured_port)
    except Exception:
        return 8765


PORT = _configured_port()
BASE = f"http://127.0.0.1:{PORT}"
BOOT_STAGES = ("Local runtime", "CoreMind", "House HQ", "Ready")

# A dark neutral base with teal and lavender state accents.  The interface is
# intentionally quiet because it is an operational control, not a landing page.
BG = "#121318"
PANEL = "#1b1e27"
PANEL_HI = "#272c39"
PANEL_DEEP = "#171a22"
TEXT = "#f0f2f8"
MUTED = "#a2a9b8"
TEAL = "#70d6c2"
LAVENDER = "#b6adff"
AMBER = "#efbf6a"
RED = "#e78888"
GREY = "#606877"


def launch_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an inherited environment with local launcher defaults.

    Existing values always win.  The launcher does not grant sensing,
    computer-use, or application-control capabilities; ``run_full.py`` remains
    the single place that applies the safe capability defaults.
    """
    env = dict(os.environ if base is None else base)
    env.setdefault("ALPECCA_LLM_BACKEND", "ollama")
    env.setdefault("ALPECCA_MODEL", "qwen3.5:9b")
    env.setdefault("ALPECCA_FAST_MODEL", "qwen3.5:4b")
    env.setdefault("ALPECCA_NUM_CTX", "8192")
    env.setdefault("ALPECCA_TTS_BACKEND", "auto")
    return env


def _launcher_python() -> str:
    """Prefer a no-console interpreter when the launcher is frozen."""
    if not getattr(sys, "frozen", False):
        return sys.executable or "python"
    return shutil.which("pythonw.exe") or shutil.which("python.exe") or "python"


def _boot_log_path(repo_root: Path) -> Path:
    return repo_root / "data" / "logs" / "launcher_stack.log"


def _start_stack(repo_root: Path, *, environment: Mapping[str, str] | None = None):
    """Start the single supported stack without exposing a terminal window."""
    log_path = _boot_log_path(repo_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n\n=== Alpecca GUI boot %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        log.flush()
        return subprocess.Popen(
            [_launcher_python(), "scripts\\run_full.py"],
            cwd=str(repo_root),
            env=launch_environment(environment),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        )


def _ollama_available(timeout: float = 0.75) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def _start_ollama() -> None:
    """Request Ollama once; its normal daemon owns model lifetime afterwards."""
    if _ollama_available():
        return
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    command = [str(local), "serve"] if local.is_file() else ["ollama", "serve"]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
    )


def _protected_url(path: str) -> str:
    """Mint a one-use loopback bootstrap URL without exposing credentials."""
    target = path if path.startswith("/") else "/" + path
    request = urllib.request.Request(
        f"{BASE}/auth/bootstrap/request?next={urllib.parse.quote(target, safe='/')}",
        data=b"",
        method="POST",
        headers={"Accept": "application/json", "User-Agent": "alpecca-launcher"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read(4096).decode("utf-8"))
        url = str(payload.get("url") or "")
        return url if url.startswith(BASE + "/auth/bootstrap?") else BASE + target
    except Exception:
        return BASE + target


class Launcher:
    """A small, fault-tolerant desktop boot console for the one local instance."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Alpecca")
        self.root.geometry("520x490")
        self.root.minsize(500, 470)
        self.root.configure(bg=BG)

        self._awake = False
        self._booting = False
        self._boot_stage = 0
        self._boot_message = "Ready to wake Alpecca locally."
        self._flash_until = 0.0
        self._auto_open_pending = False
        self._stack_process = None
        self._build_ui()

        threading.Thread(target=self._poll_forever, daemon=True, name="AlpeccaLauncherHealth").start()
        self.root.after(350, self._refresh_status)

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=22, pady=(22, 4))

        mark = tk.Canvas(header, width=42, height=42, bg=BG, highlightthickness=0)
        mark.create_oval(2, 2, 40, 40, fill=LAVENDER, outline="")
        mark.create_text(21, 21, text="A", fill=BG, font=("Segoe UI", 16, "bold"))
        mark.pack(side="left")

        title = tk.Frame(header, bg=BG)
        title.pack(side="left", padx=(12, 0))
        tk.Label(title, text="Alpecca", font=("Segoe UI", 20, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(
            title,
            text="Local companion boot console",
            font=("Segoe UI", 10),
            fg=MUTED,
            bg=BG,
        ).pack(anchor="w", pady=(1, 0))

        status = tk.Frame(self.root, bg=PANEL_DEEP, highlightbackground="#2b3040", highlightthickness=1)
        status.pack(fill="x", padx=22, pady=(12, 8))
        self.dot = tk.Canvas(status, width=18, height=18, bg=PANEL_DEEP, highlightthickness=0)
        self.dot_id = self.dot.create_oval(3, 3, 15, 15, fill=GREY, outline="")
        self.dot.pack(side="left", padx=(12, 8), pady=11)
        self.status_label = tk.Label(
            status,
            text="Asleep",
            font=("Segoe UI", 11, "bold"),
            fg=MUTED,
            bg=PANEL_DEEP,
        )
        self.status_label.pack(side="left", pady=11)
        self.status_detail = tk.Label(
            status,
            text="The local stack is not responding.",
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=PANEL_DEEP,
        )
        self.status_detail.pack(side="right", padx=12, pady=11)

        boot = tk.Frame(self.root, bg=PANEL, highlightbackground="#303647", highlightthickness=1)
        boot.pack(fill="x", padx=22, pady=(0, 12))
        tk.Label(boot, text="Boot status", font=("Segoe UI", 10, "bold"), fg=TEXT, bg=PANEL).pack(
            anchor="w", padx=14, pady=(12, 2)
        )
        self.boot_message = tk.Label(
            boot,
            text=self._boot_message,
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=PANEL,
            anchor="w",
        )
        self.boot_message.pack(fill="x", padx=14, pady=(0, 11))

        stages = tk.Frame(boot, bg=PANEL)
        stages.pack(fill="x", padx=14, pady=(0, 13))
        self.stage_labels: list[tk.Label] = []
        for index, label in enumerate(BOOT_STAGES, start=1):
            stages.columnconfigure(index - 1, weight=1)
            stage = tk.Label(
                stages,
                text=label,
                font=("Segoe UI", 8, "bold"),
                fg=GREY,
                bg=PANEL,
                anchor="center",
            )
            stage.grid(row=0, column=index - 1, sticky="ew")
            self.stage_labels.append(stage)

        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill="both", expand=True, padx=22)
        actions.columnconfigure(0, weight=1, uniform="actions")
        actions.columnconfigure(1, weight=1, uniform="actions")
        actions.rowconfigure(0, weight=1)
        actions.rowconfigure(1, weight=1)
        actions.rowconfigure(2, weight=1)

        self._action_button(actions, "Wake Alpecca", self.wake_her, 0, 0, primary=True)
        self._action_button(actions, "Open House HQ", self.open_home, 0, 1)
        self._action_button(actions, "Open Alpecca App", self.open_app, 1, 0)
        self._action_button(actions, "Phone link", self.phone_access, 1, 1)
        self._action_button(actions, "Discord invite", self.discord_invite, 2, 0)
        self._action_button(actions, "Boot log", self.open_boot_log, 2, 1)

        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=22, pady=(3, 15))
        sleep = tk.Button(
            footer,
            text="Put Alpecca to sleep",
            command=self.put_to_sleep,
            bg=BG,
            fg=RED,
            activebackground=BG,
            activeforeground=RED,
            relief="flat",
            bd=0,
            font=("Segoe UI", 9),
            cursor="hand2",
            highlightthickness=0,
        )
        sleep.pack(side="right")
        sleep.bind("<Enter>", lambda _event: sleep.configure(fg="#ffaaaa"))
        sleep.bind("<Leave>", lambda _event: sleep.configure(fg=RED))

        self.bar = tk.Label(
            self.root,
            text=self._initial_bar_text(),
            font=("Segoe UI", 8),
            fg=MUTED,
            bg="#0d0e12",
            anchor="w",
            padx=12,
            pady=6,
        )
        self.bar.pack(side="bottom", fill="x")

    def _action_button(self, parent: tk.Frame, label: str, command, row: int, column: int, *, primary: bool = False) -> None:
        background = TEAL if primary else PANEL
        foreground = BG if primary else TEXT
        active = "#91ead8" if primary else PANEL_HI
        button = tk.Button(
            parent,
            text=label,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=active,
            activeforeground=BG if primary else TEXT,
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            cursor="hand2",
            highlightthickness=0,
            pady=12,
        )
        button.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)
        button.bind("<Enter>", lambda _event, b=button: b.configure(bg=active))
        button.bind("<Leave>", lambda _event, b=button: b.configure(bg=background))

    def _initial_bar_text(self) -> str:
        if REPO_ROOT is None:
            return "Project root not found. Keep this launcher inside the Alpecca folder."
        return f"Local project: {REPO_ROOT}"

    def say(self, message: str) -> None:
        try:
            self.bar.configure(text=message)
        except Exception:
            pass

    def _set_boot_state(self, stage: int, message: str) -> None:
        self._boot_stage = max(0, min(len(BOOT_STAGES), stage))
        self._boot_message = message

    def _poll_forever(self) -> None:
        while True:
            awake = False
            try:
                with urllib.request.urlopen(f"{BASE}/healthz", timeout=2) as response:
                    awake = 200 <= response.status < 300
            except Exception:
                pass
            self._awake = awake
            time.sleep(3)

    def _refresh_status(self) -> None:
        try:
            if self._awake and self._booting:
                self._booting = False
                self._set_boot_state(4, "Alpecca is awake locally. House HQ is ready.")
                self.say("Alpecca is awake. The terminal-free stack is running.")
                if self._auto_open_pending:
                    self._auto_open_pending = False
                    webbrowser.open(_protected_url("/house-hq"))
            elif self._booting and self._stack_process is not None and self._stack_process.poll() is not None:
                self._booting = False
                self._set_boot_state(0, "The stack stopped before it was ready. Open the boot log for details.")
                self.say("Startup stopped before the local server answered.")

            flashing = time.time() < self._flash_until
            if self._awake:
                color, text, detail = TEAL, "Awake", "Local server is responding."
            elif self._booting:
                color, text, detail = AMBER, "Waking", self._boot_message
            else:
                color, text, detail = GREY, "Asleep", "The local stack is not responding."
            if flashing:
                color = AMBER

            self.dot.itemconfigure(self.dot_id, fill=color)
            self.status_label.configure(text=text, fg=TEXT if self._awake else color)
            self.status_detail.configure(text=detail)
            self.boot_message.configure(text=self._boot_message)
            for index, label in enumerate(self.stage_labels, start=1):
                if index < self._boot_stage:
                    label.configure(fg=TEAL)
                elif index == self._boot_stage and self._boot_stage:
                    label.configure(fg=AMBER if self._booting else LAVENDER)
                else:
                    label.configure(fg=GREY)
        except Exception:
            pass
        self.root.after(350, self._refresh_status)

    def _flash(self) -> None:
        self._flash_until = time.time() + 1.2

    def wake_her(self) -> None:
        """Start one hidden full stack and expose its startup state in this UI."""
        if self._awake:
            self._flash()
            self.say("Alpecca is already awake. No second instance was started.")
            return
        if self._booting:
            self._flash()
            self.say("Alpecca is already waking. The boot stages will update here.")
            return
        if REPO_ROOT is None:
            self.say("Cannot wake Alpecca because the project root was not found.")
            return
        self._booting = True
        self._auto_open_pending = True
        self._set_boot_state(1, "Checking the local language runtime.")
        self.say("Waking Alpecca without opening a terminal window.")
        threading.Thread(target=self._launch_stack, daemon=True, name="AlpeccaLauncherBoot").start()

    def _launch_stack(self) -> None:
        try:
            if not _ollama_available():
                self._set_boot_state(1, "Starting Ollama for the local model.")
                _start_ollama()
                deadline = time.monotonic() + 12.0
                while time.monotonic() < deadline and not _ollama_available():
                    time.sleep(0.25)
            self._set_boot_state(2, "Starting CoreMind, continuity, voice, and Discord services.")
            self._stack_process = _start_stack(REPO_ROOT)
            self._set_boot_state(3, "Waiting for House HQ to answer locally.")
        except Exception as exc:
            self._booting = False
            self._set_boot_state(0, "Launch failed. Open the boot log for details.")
            self.say(f"Could not start Alpecca: {type(exc).__name__}")

    def open_home(self) -> None:
        try:
            webbrowser.open(_protected_url("/house-hq"))
            self.say("Opening House HQ in the browser.")
        except Exception as exc:
            self.say(f"Could not open House HQ: {type(exc).__name__}")

    def open_app(self) -> None:
        try:
            webbrowser.open(_protected_url("/app"))
            self.say("Opening the Alpecca app.")
        except Exception as exc:
            self.say(f"Could not open the Alpecca app: {type(exc).__name__}")

    def phone_access(self) -> None:
        """Keep the tunnel console visible because it displays its public link."""
        try:
            if REPO_ROOT is None:
                self.say("Cannot open a phone link because the project root was not found.")
                return
            subprocess.Popen(
                ["cmd.exe", "/k", _launcher_python(), "scripts\\share.py"],
                cwd=str(REPO_ROOT),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
            )
            self.say("Phone-link console opened. It displays the public address and QR code.")
        except Exception as exc:
            self.say(f"Could not open phone access: {type(exc).__name__}")

    def discord_invite(self) -> None:
        try:
            webbrowser.open(_protected_url("/app/discord/invite"))
            self.say("Opening the Discord invite page.")
        except Exception as exc:
            self.say(f"Could not open the Discord invite: {type(exc).__name__}")

    def open_boot_log(self) -> None:
        try:
            if REPO_ROOT is None:
                self.say("Cannot open a boot log because the project root was not found.")
                return
            path = _boot_log_path(REPO_ROOT)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.as_uri())
            self.say("Opening the local boot log.")
        except Exception as exc:
            self.say(f"Could not open the boot log: {type(exc).__name__}")

    def put_to_sleep(self) -> None:
        try:
            pids = self._pids_on_port(PORT)
            if not pids:
                self._flash()
                self.say(f"Alpecca is not listening on port {PORT}.")
                return
            wording = "process" if len(pids) == 1 else "processes"
            if not messagebox.askyesno(
                "Alpecca",
                f"Put Alpecca to sleep? This ends the server {wording} on port {PORT}.",
            ):
                self.say("Alpecca remains awake.")
                return
            failures: list[str] = []
            for pid in pids:
                result = subprocess.run(
                    ["taskkill", "/PID", pid, "/F", "/T"],
                    capture_output=True,
                    text=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                if result.returncode:
                    failures.append(pid)
            if failures:
                self.say(f"Could not stop PID {', '.join(failures)}.")
            else:
                self._awake = False
                self._booting = False
                self._set_boot_state(0, "Alpecca is resting locally.")
                self.say("Alpecca is asleep now.")
        except Exception as exc:
            self.say(f"Could not stop Alpecca: {type(exc).__name__}")

    @staticmethod
    def _pids_on_port(port: int) -> list[str]:
        output = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
        suffix = f":{port}"
        pids: list[str] = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(suffix) and parts[3].upper() == "LISTENING":
                pid = parts[4]
                if pid.isdigit() and pid != "0" and pid not in pids:
                    pids.append(pid)
        return pids

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    Launcher().run()

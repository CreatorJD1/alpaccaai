"""Alpecca's little desktop remote -- one small dark window that wakes her,
opens her home, and tucks her in.

This is deliberately the dumbest possible companion to START_HERE.bat: it never
tries to BE her, it just knows where she lives (the repo root), whether she's
awake (her public /healthz endpoint answers), and how to reach her front door
(a one-use loopback bootstrap establishes the trusted browser session).
Everything here is Python stdlib only -- tkinter, urllib,
subprocess -- so the launcher runs on any plain Python 3 and freezes cleanly
into a single .exe with PyInstaller (see ../build_exe.bat).

Design rules this file lives by:
  * NEVER crash her way out of an action. Every button lands in try/except and
    reports into the little status bar instead of a traceback dialog.
  * NEVER put an authorization value in a URL or browser-readable store. The
    running server mints a one-use local bootstrap URL for each launch.
  * The background poller may not raise, ever. A dead poll just means the dot
    goes grey; it must not take the window down with it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

# Windows process-creation flags. We define them defensively (falling back to
# the raw numeric values) so this file still parses on non-Windows machines --
# handy for CI-style syntax checks even though the launcher itself is a
# Windows creature through and through.
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# --- Where does she live? ----------------------------------------------------
# The launcher may run from apps/launcher/src inside the repo, or the whole
# launcher folder may have been copied somewhere else INSIDE the repo, or it
# may be a frozen .exe sitting in apps/launcher/dist. In every case the answer
# is the same: walk upward until we find the folder that holds server.py --
# that folder IS her home. No guessing, no hardcoded paths.


def find_repo_root() -> Path | None:
    """Walk up from wherever we're running until we hit server.py's folder."""
    if getattr(sys, "frozen", False):
        # PyInstaller onefile unpacks __file__ into a temp dir that is nowhere
        # near the repo -- the .exe's real location is what matters.
        start = Path(sys.executable).resolve().parent
    else:
        start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "server.py").is_file():
            return candidate
    # Last-ditch: maybe we were launched with the repo as the working dir.
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "server.py").is_file():
            return candidate
    return None


REPO_ROOT = find_repo_root()

# --- Her port ---------------------------------------------------------------
# The launcher needs only the configured local port. Authorization stays in the
# running server and the browser's HttpOnly trusted-device cookie.
PORT = 8765
if REPO_ROOT is not None:
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from config import PORT as _PORT  # noqa: E402

        PORT = int(_PORT)
    except Exception:
        # She might not even be installed properly yet; the launcher should
        # still open and say so rather than die on the doorstep.
        pass

BASE = f"http://127.0.0.1:{PORT}"


def _protected_url(path: str) -> str:
    """Ask the live local server for a one-use browser bootstrap URL."""
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
        # Direct navigation lands on the creator-password enrollment page when
        # this browser has not been trusted yet.
        return BASE + target


# --- The window ---------------------------------------------------------------
# Hand-rolled dark theme: plain tk widgets with explicit colors, because ttk's
# theming on Windows fights dark backgrounds and we vendor nothing external.

BG = "#0b1020"        # the deep night-blue she lives in
PANEL = "#141c36"     # slightly lifted card/button color
PANEL_HI = "#1e2a4f"  # hover
TEXT = "#e6ecff"
MUTED = "#8ea0c8"
GREEN = "#35d07f"     # awake
GREY = "#5a647d"      # asleep
FLASH = "#ffd166"     # brief "hey, look at the status" wink


class Launcher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Alpecca")
        self.root.geometry("420x360")
        self.root.minsize(420, 360)
        self.root.configure(bg=BG)

        # Shared state the poll thread writes and the UI thread reads. A plain
        # attribute is fine here: one writer, one reader, atomic bool swap.
        self._awake = False
        self._flash_until = 0.0

        self._build_ui()

        # Background heartbeat: ask her /system/status every 5 seconds. The
        # thread is a daemon so closing the window never hangs on it.
        threading.Thread(target=self._poll_forever, daemon=True).start()
        # And a gentle UI refresh loop on the Tk side -- Tkinter widgets must
        # only be touched from the main thread, so the poller just sets a flag
        # and this loop paints it.
        self.root.after(500, self._refresh_status)

    # -- layout ---------------------------------------------------------------
    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=18, pady=(16, 6))
        tk.Label(
            header, text="Alpecca", font=("Segoe UI", 18, "bold"),
            fg=TEXT, bg=BG,
        ).pack(side="left")

        status_row = tk.Frame(self.root, bg=BG)
        status_row.pack(fill="x", padx=18, pady=(0, 10))
        # The dot is a tiny canvas circle -- green when she answers, grey when
        # the house is quiet.
        self.dot = tk.Canvas(status_row, width=14, height=14, bg=BG,
                             highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill=GREY, outline="")
        self.dot.pack(side="left")
        self.status_label = tk.Label(
            status_row, text="Asleep", font=("Segoe UI", 11),
            fg=MUTED, bg=BG,
        )
        self.status_label.pack(side="left", padx=(8, 0))

        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill="both", expand=True, padx=18)
        grid.columnconfigure(0, weight=1, uniform="col")
        grid.columnconfigure(1, weight=1, uniform="col")

        buttons = [
            ("Wake her", self.wake_her),
            ("Put her to sleep", self.put_to_sleep),
            ("Open her home", self.open_home),
            ("App site", self.open_app),
            ("Phone access", self.phone_access),
            ("Invite to Discord", self.discord_invite),
        ]
        for i, (label, cmd) in enumerate(buttons):
            btn = tk.Button(
                grid, text=label, command=cmd,
                bg=PANEL, fg=TEXT, activebackground=PANEL_HI,
                activeforeground=TEXT, relief="flat", bd=0,
                font=("Segoe UI", 10), cursor="hand2",
                highlightthickness=0, pady=9,
            )
            btn.grid(row=i // 2, column=i % 2, sticky="nsew", padx=5, pady=5)
            # Tiny hover polish -- default_bg captured per-button.
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=PANEL_HI))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=PANEL))

        # Status bar: every action reports here instead of raising dialogs.
        self.bar = tk.Label(
            self.root, text=self._initial_bar_text(),
            font=("Segoe UI", 9), fg=MUTED, bg="#0d1428",
            anchor="w", padx=10, pady=4,
        )
        self.bar.pack(side="bottom", fill="x")

    def _initial_bar_text(self) -> str:
        if REPO_ROOT is None:
            return "Couldn't find her home (no server.py above this folder)."
        return f"Home: {REPO_ROOT}"

    def say(self, msg: str) -> None:
        """Every button whispers its outcome into the status bar."""
        try:
            self.bar.configure(text=msg)
        except Exception:
            pass

    # -- heartbeat ------------------------------------------------------------
    def _poll_forever(self) -> None:
        """Ask her /healthz every 5s. This loop is allowed to fail every
        single time forever; it just means the dot stays grey."""
        url = f"{BASE}/healthz"
        while True:
            awake = False
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    awake = 200 <= resp.status < 300
            except Exception:
                awake = False
            self._awake = awake
            time.sleep(5)

    def _refresh_status(self) -> None:
        """Main-thread painter for the dot + label (runs every half second)."""
        try:
            flashing = time.time() < self._flash_until
            if flashing:
                color, text = FLASH, ("She is awake" if self._awake else "Asleep")
            elif self._awake:
                color, text = GREEN, "She is awake"
            else:
                color, text = GREY, "Asleep"
            self.dot.itemconfigure(self.dot_id, fill=color)
            self.status_label.configure(
                text=text, fg=TEXT if self._awake else MUTED)
        except Exception:
            pass
        self.root.after(500, self._refresh_status)

    def _flash(self) -> None:
        """A quick amber wink on the dot -- 'look up here, she's already on'."""
        self._flash_until = time.time() + 1.2

    # -- buttons --------------------------------------------------------------
    def wake_her(self) -> None:
        """Start her the same way Jason does by hand: START_HERE.bat, in its
        own console, from the repo root. If she's already awake we do nothing
        destructive -- just flash the status so the answer is visible."""
        try:
            if self._awake:
                self._flash()
                self.say("She's already awake.")
                return
            if REPO_ROOT is None:
                self.say("Can't wake her: repo root not found.")
                return
            bat = REPO_ROOT / "START_HERE.bat"
            if not bat.is_file():
                self.say("Can't wake her: START_HERE.bat is missing.")
                return
            subprocess.Popen(
                ["cmd.exe", "/c", str(bat)],
                cwd=str(REPO_ROOT),
                creationflags=CREATE_NEW_CONSOLE,
            )
            self.say("Waking her -- watch the new console window.")
        except Exception as exc:
            self.say(f"Wake failed: {exc}")

    def open_home(self) -> None:
        """Her House HQ front page through a one-use local browser bootstrap."""
        try:
            webbrowser.open(_protected_url("/"))
            self.say("Opening her home in the browser.")
        except Exception as exc:
            self.say(f"Couldn't open her home: {exc}")

    def open_app(self) -> None:
        """The Alpecca virtual app -- her secondary surface."""
        try:
            webbrowser.open(_protected_url("/app"))
            self.say("Opening the app site.")
        except Exception as exc:
            self.say(f"Couldn't open the app: {exc}")

    def phone_access(self) -> None:
        """Runs scripts/share.py in its own console -- that script handles the
        tunnel + QR so the phone can reach her."""
        try:
            if REPO_ROOT is None:
                self.say("Can't share: repo root not found.")
                return
            # When frozen we ARE the exe, so 'python' from PATH is the right
            # interpreter; from source, prefer the interpreter running us.
            python = "python" if getattr(sys, "frozen", False) else (
                sys.executable or "python")
            subprocess.Popen(
                ["cmd.exe", "/k", python, "scripts\\share.py"],
                cwd=str(REPO_ROOT),
                creationflags=CREATE_NEW_CONSOLE,
            )
            self.say("Phone access console opened (scripts/share.py).")
        except Exception as exc:
            self.say(f"Phone access failed: {exc}")

    def discord_invite(self) -> None:
        """Open her Discord invite page -- the server renders the actual
        invite link there."""
        try:
            webbrowser.open(_protected_url("/app/discord/invite"))
            self.say("Opening her Discord invite page.")
        except Exception as exc:
            self.say(f"Couldn't open the invite page: {exc}")

    def put_to_sleep(self) -> None:
        """Find whatever process is listening on her port and end it -- with a
        confirmation first, because this is the one genuinely blunt action in
        the whole window. taskkill /T takes the child processes too, so her
        worker consoles don't linger orphaned."""
        try:
            pids = self._pids_on_port(PORT)
            if not pids:
                self._flash()
                self.say("She's not running (nothing is listening on "
                         f"port {PORT}).")
                return
            ok = messagebox.askyesno(
                "Alpecca",
                "Put her to sleep? This ends her server process"
                + ("es" if len(pids) > 1 else "")
                + f" (PID {', '.join(pids)}).",
            )
            if not ok:
                self.say("Left her running.")
                return
            failures = []
            for pid in pids:
                r = subprocess.run(
                    ["taskkill", "/PID", pid, "/F", "/T"],
                    capture_output=True, text=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                if r.returncode != 0:
                    failures.append(pid)
            if failures:
                self.say(f"Couldn't stop PID {', '.join(failures)}.")
            else:
                self._awake = False
                self.say("She's asleep now. Good night.")
        except Exception as exc:
            self.say(f"Sleep failed: {exc}")

    @staticmethod
    def _pids_on_port(port: int) -> list[str]:
        """Parse `netstat -ano` for LISTENING sockets on our port. Windows
        prints one line per address family, so the same PID can appear twice
        (0.0.0.0 and [::]) -- we dedupe while keeping order."""
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
        needle = f":{port}"
        pids: list[str] = []
        for line in out.splitlines():
            parts = line.split()
            # Expected shape: TCP  0.0.0.0:8765  0.0.0.0:0  LISTENING  1234
            if len(parts) >= 5 and parts[0].upper() == "TCP" \
                    and parts[1].endswith(needle) \
                    and parts[3].upper() == "LISTENING":
                pid = parts[4]
                if pid.isdigit() and pid != "0" and pid not in pids:
                    pids.append(pid)
        return pids

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    Launcher().run()

# Alpecca Launcher

A terminal-free desktop boot surface for Alpecca. It shows the local stack's
state, startup stages, and the normal entry points for House HQ, the companion
app, phone access, Discord, and the local boot log.

It is stdlib-only (tkinter + urllib + subprocess), so it needs no pip installs
to run from source. It reads only the configured port. For protected pages it
asks the live loopback server for a one-use bootstrap URL; no token or password
is placed in a URL. The resulting HttpOnly cookie trusts that laptop browser
for future playtests.

## How it finds her

On startup it walks upward from its own location until it finds the folder
containing `server.py` -- that folder is the repo root. This means you can run
it from `apps/launcher/src/`, or copy the whole `apps/launcher/` folder
anywhere **inside** the repo and it still works. (Dropped outside the repo it
will open, tell you it couldn't find her home, and disable nothing -- the
buttons just report the problem in the status bar.)

## Run from source

Double-click `START_HERE.bat` for the normal GUI-first launch. It passes the
configured model and capability profile to this launcher, then exits instead
of leaving a terminal window open.

Double-click `src\run_launcher.bat`, or from a terminal:

```powershell
python apps\launcher\src\alpecca_launcher.py
```

Requires the same Python 3 the repo already uses (3.12). No extra packages.

## What the buttons do

| Button | Action |
| --- | --- |
| Wake Alpecca | Starts the existing `scripts/run_full.py` stack in the background without opening a terminal window; once healthy, it also starts the attach-only phone relay and publishes the current mobile endpoint |
| Put her to sleep | Finds the PID listening on her port via `netstat -ano` and `taskkill /F /T`s it, after a yes/no confirm |
| Open House HQ | Opens `/house-hq` through a one-use local bootstrap |
| Open Alpecca App | Opens `/app` through a one-use local bootstrap |
| Phone access | Opens the already-supported relay console for the current tunnel and QR code; normal launcher startup now publishes phone access automatically |
| Invite to Discord | Opens `/app/discord/invite` through a local bootstrap |
| Boot log | Opens `data/logs/launcher_stack.log`, which receives full-stack startup output |

The status dot polls public `/healthz` every 5 seconds: green means she is
awake, grey means asleep. The poll can fail forever without hurting anything.

## Build the .exe

From this folder (or anywhere -- the script `cd`s itself):

```powershell
apps\launcher\build_exe.bat
```

That installs PyInstaller if it's missing, then produces
`apps\launcher\dist\AlpeccaLauncher.exe` -- a single file, no console window.
Keep the .exe somewhere inside the repo (e.g. leave it in `dist\`) so it can
still find `server.py` above itself.

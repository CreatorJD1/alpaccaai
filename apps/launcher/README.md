# Alpecca Launcher

A tiny dark-themed desktop remote for Alpecca -- one window with a status dot
(is she awake?) and six buttons: wake her, open her home, open the app site,
share her to the phone, open her Discord invite, and put her to sleep.

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

Double-click `src\run_launcher.bat`, or from a terminal:

```powershell
python apps\launcher\src\alpecca_launcher.py
```

Requires the same Python 3 the repo already uses (3.12). No extra packages.

## What the buttons do

| Button | Action |
| --- | --- |
| Wake her | Runs the repo's `START_HERE.bat` in a new console (does nothing but flash the status if she's already awake) |
| Put her to sleep | Finds the PID listening on her port via `netstat -ano` and `taskkill /F /T`s it, after a yes/no confirm |
| Open her home | Opens the home through a one-use local bootstrap |
| App site | Opens `/app` through a one-use local bootstrap |
| Phone access | Runs `python scripts\share.py` in a new console (tunnel + QR) |
| Invite to Discord | Opens `/app/discord/invite` through a local bootstrap |

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

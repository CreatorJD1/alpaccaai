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
import sys
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
from config import HOST, PORT                     # noqa: E402
from server import app, mind                      # noqa: E402

if __name__ == "__main__":
    print(f"Alpecca is waking up (full senses) at http://{HOST}:{PORT}")
    print(f"  LLM online: {mind.llm.online}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

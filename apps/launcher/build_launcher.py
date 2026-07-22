"""Build the no-console Alpecca launcher executable.

This is the build entry point used by ``ALPECCA_LAUNCHER.bat build-exe``.
Keeping the build logic in Python avoids chaining Windows BAT wrappers and
makes the command directly testable.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


LAUNCHER_DIR = Path(__file__).resolve().parent
SOURCE = LAUNCHER_DIR / "src" / "alpecca_launcher.py"
DIST_DIR = LAUNCHER_DIR / "dist"
BUILD_DIR = LAUNCHER_DIR / "build"


def pyinstaller_command(python: str | None = None) -> list[str]:
    """Return the reproducible PyInstaller command for the launcher."""
    return [
        python or sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name",
        "AlpeccaLauncher",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        str(SOURCE),
    ]


def ensure_pyinstaller() -> None:
    """Install the launcher-only build dependency when it is unavailable."""
    if importlib.util.find_spec("PyInstaller") is not None:
        return
    print("Installing PyInstaller...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        check=True,
        cwd=LAUNCHER_DIR,
    )


def main() -> int:
    ensure_pyinstaller()
    print("Building AlpeccaLauncher.exe...")
    subprocess.run(pyinstaller_command(), check=True, cwd=LAUNCHER_DIR)
    output = DIST_DIR / "AlpeccaLauncher.exe"
    if not output.is_file():
        raise RuntimeError(f"PyInstaller completed without creating {output}")
    print(f"Done: {output}")
    print("Keep the executable inside the repository so it can find server.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Interactively set Alpecca's remote-device enrollment password.

The value is written only to Windows Credential Manager. It is never printed,
placed in a URL, or stored in the repository.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpecca import auth  # noqa: E402


def main() -> int:
    first = getpass.getpass("Creator device-enrollment password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        print("Passwords did not match.", file=sys.stderr)
        return 2
    auth.set_windows_creator_password(first)
    print("Creator password stored in Windows Credential Manager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

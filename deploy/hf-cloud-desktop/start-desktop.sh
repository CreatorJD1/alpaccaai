#!/bin/sh
set -eu

if [ "${ALPECCA_DESKTOP_ONLY:-}" != "1" ]; then
    echo "desktop-only contract missing" >&2
    exit 78
fi
if [ "$(id -u)" = "0" ]; then
    echo "refusing to run the desktop as root" >&2
    exit 77
fi

state_root="${ALPECCA_DESKTOP_STATE_DIR:-/data/alpecca-desktop}"
case "$state_root" in
    /data/*) ;;
    *) echo "state directory must stay under /data" >&2; exit 78 ;;
esac

mkdir -p "$state_root/home" "$state_root/logs"
export HOME="$state_root/home"
export DISPLAY=:1
mkdir -p "$HOME/.config" "$HOME/Desktop"

vnc_pid=""
session_pid=""
cleanup() {
    [ -z "$session_pid" ] || kill "$session_pid" 2>/dev/null || true
    [ -z "$vnc_pid" ] || kill "$vnc_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

Xtigervnc :1 \
    -rfbport 5901 \
    -localhost yes \
    -SecurityTypes None \
    -geometry "${ALPECCA_DESKTOP_GEOMETRY:-1440x900}" \
    -depth 24 \
    -desktop "Alpecca Cloud Desktop" \
    >"$state_root/logs/vnc.log" 2>&1 &
vnc_pid=$!

python3 - <<'PY'
import socket
import time

deadline = time.monotonic() + 15.0
while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 5901), timeout=0.5):
            raise SystemExit(0)
    except OSError:
        time.sleep(0.25)
raise SystemExit("VNC display did not become ready")
PY

dbus-run-session -- startxfce4 >"$state_root/logs/xfce.log" 2>&1 &
session_pid=$!

exec websockify \
    --web=/usr/share/novnc \
    0.0.0.0:7860 \
    127.0.0.1:5901

#!/usr/bin/env bash
set -euo pipefail

echo "== kernel =="
uname -a

echo "== operating system =="
cat /etc/os-release

echo "== architecture =="
uname -m
getconf LONG_BIT

echo "== Python =="
python3 --version

echo "== disk =="
df -h /

echo "== camera commands =="
command -v rpicam-hello || true
command -v libcamera-hello || true

echo "== Python modules =="
python3 - <<'PY'
import importlib.util

for name in ("picamera2", "pigpio", "cv2", "numpy", "torch", "ultralytics"):
    print(f"{name}: {'present' if importlib.util.find_spec(name) else 'missing'}")
PY

echo "== services =="
systemctl is-enabled pigpiod 2>/dev/null || true
systemctl is-active pigpiod 2>/dev/null || true

echo "== Tailscale =="
tailscale status 2>/dev/null || true

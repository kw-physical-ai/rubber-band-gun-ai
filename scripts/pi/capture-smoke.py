#!/usr/bin/env python3
"""Capture a few unlabeled frames without importing or controlling actuators."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("rbg-smoke"))
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--warmup", type=float, default=2.0)
    args = parser.parse_args()
    if not 1 <= args.frames <= 20:
        parser.error("--frames must be between 1 and 20")
    if args.interval < 0 or args.warmup < 0:
        parser.error("timing values cannot be negative")
    return args


def main() -> None:
    args = parse_args()
    from picamera2 import Picamera2

    pigpiod = subprocess.run(
        ["pgrep", "-x", "pigpiod"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if pigpiod.returncode == 0:
        raise RuntimeError("pigpiod is running; stop it before this actuator-free smoke test")

    capture_id = datetime.now(UTC).strftime("smoke-%Y%m%dT%H%M%SZ")
    output_root = args.output_root.expanduser().resolve()
    partial = output_root / f".{capture_id}.partial"
    completed = output_root / capture_id
    if partial.exists() or completed.exists():
        raise FileExistsError(f"capture already exists: {capture_id}")

    images = partial / "images"
    images.mkdir(parents=True)
    rows: list[dict[str, str]] = []
    camera = Picamera2()
    camera_started = False
    try:
        configuration = camera.create_still_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        camera.configure(configuration)
        camera.start()
        camera_started = True
        time.sleep(args.warmup)
        for index in range(args.frames):
            relative_name = f"images/frame_{index:03d}.jpg"
            camera.capture_file(str(partial / relative_name))
            rows.append(
                {
                    "filename": relative_name,
                    "captured_at_utc": datetime.now(UTC).isoformat(),
                    "label_status": "unlabeled-smoke-only",
                }
            )
            if index + 1 < args.frames:
                time.sleep(args.interval)
    finally:
        if camera_started:
            camera.stop()
        camera.close()

    frames_csv = partial / "frames.csv"
    with frames_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    files = []
    for path in sorted(partial.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(partial).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    manifest = {
        "schema_version": "rbg-smoke/v1",
        "capture_id": capture_id,
        "purpose": "data-flow-only; never use for training or model evaluation",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "requested_frame_count": args.frames,
        "files": files,
    }
    (partial / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    partial.rename(completed)
    print(f"Smoke bundle ready: {completed}")
    print("This bundle is unlabeled and must not be used for training or evaluation.")


if __name__ == "__main__":
    main()

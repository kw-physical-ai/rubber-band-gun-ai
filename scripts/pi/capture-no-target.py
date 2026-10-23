#!/usr/bin/env python3
"""Capture human-confirmed no-target frames without loading actuator libraries."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rubber_band_gun.no_target import NoTargetCaptureSession  # noqa: E402
from rubber_band_gun.preprocessing import (  # noqa: E402
    PreprocessingSpec,
    picamera2_rgb888_to_rgb,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path.home() / "evaluation-captures")
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    if not 1 <= args.frames <= 1000 or args.interval < 0:
        parser.error("--frames must be 1..1000 and --interval cannot be negative")
    if subprocess.run(
        ["pgrep", "-x", "pigpiod"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0:
        raise RuntimeError("pigpiod is running; stop it before actuator-free capture")
    settings = tomllib.loads(args.config.read_text(encoding="utf-8"))
    spec = PreprocessingSpec(**settings["preprocessing"])

    from picamera2 import Picamera2

    session = NoTargetCaptureSession(args.output_root, spec)
    camera = Picamera2()
    started = False
    try:
        camera.configure(
            camera.create_still_configuration(
                main={
                    "size": (int(settings["camera"]["width"]), int(settings["camera"]["height"])),
                    "format": "RGB888",
                }
            )
        )
        camera.start()
        started = True
        time.sleep(2.0)
        print("Confirm the declared target is absent from the entire scene.")
        for index in range(args.frames):
            session.add_frame(picamera2_rgb888_to_rgb(camera.capture_array()))
            print(f"Captured no-target frame {index + 1}/{args.frames}")
            if index + 1 < args.frames:
                time.sleep(args.interval)
    finally:
        if started:
            camera.stop()
        camera.close()
    completed = session.finalize()
    print(f"No-target capture ready: {completed}")


if __name__ == "__main__":
    main()

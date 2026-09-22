#!/usr/bin/env python3
"""Preview or collect yaw-label frames; this program cannot fire the mechanism."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rubber_band_gun.capture import CaptureCalibration, YawCaptureSession  # noqa: E402
from rubber_band_gun.preprocessing import (  # noqa: E402
    PreprocessingSpec,
    orient_and_crop_rgb,
)


@dataclass(frozen=True)
class ServoConfig:
    pin: int
    center: float
    minimum: float
    maximum: float
    step: float

    def __post_init__(self) -> None:
        if not 0 <= self.pin <= 27:
            raise ValueError(f"unsupported GPIO pin: {self.pin}")
        if not 0 <= self.minimum <= self.center <= self.maximum <= 180:
            raise ValueError("servo limits must contain the center within 0..180 degrees")
        if self.step <= 0:
            raise ValueError("servo step must be positive")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path.home() / "captures")
    parser.add_argument(
        "--enable-motion",
        action="store_true",
        help="enable calibrated yaw/pitch servos and allow labeled capture",
    )
    return parser.parse_args()


def _servo_config(value: dict[str, object]) -> ServoConfig:
    return ServoConfig(
        pin=int(value["pin"]),
        center=float(value["center_degrees"]),
        minimum=float(value["min_degrees"]),
        maximum=float(value["max_degrees"]),
        step=float(value["step_degrees"]),
    )


def _set_servo(pi: object, config: ServoConfig, angle: float) -> float:
    bounded = max(config.minimum, min(config.maximum, angle))
    pulse = 500 + (bounded / 180.0) * 2000.0
    pi.set_servo_pulsewidth(config.pin, pulse)
    return bounded


def main() -> None:
    args = parse_args()
    settings = tomllib.loads(args.config.read_text(encoding="utf-8"))
    hardware = settings["hardware"]
    camera_settings = settings["camera"]
    settle_seconds = float(settings["capture"]["settle_seconds"])
    if settle_seconds < 0:
        raise ValueError("capture.settle_seconds cannot be negative")
    preprocessing = PreprocessingSpec(**settings["preprocessing"])
    yaw_config = _servo_config(settings["servo"]["yaw"])
    pitch_config = _servo_config(settings["servo"]["pitch"])

    if args.enable_motion and not hardware.get("calibrated", False):
        raise RuntimeError("motion refused: set calibrated=true only after measuring servo limits")
    if args.enable_motion and (
        str(hardware.get("calibration_id", "")).startswith("replace-")
        or str(hardware.get("aiming_reference", "")).startswith("replace-")
    ):
        raise RuntimeError("motion refused: calibration ID and aiming reference are placeholders")
    if args.enable_motion and yaw_config.pin == pitch_config.pin:
        raise ValueError("yaw and pitch cannot use the same GPIO pin")

    from picamera2 import Picamera2

    pi = None
    if args.enable_motion:
        import pigpio

        pi = pigpio.pi()
        if not pi.connected:
            raise RuntimeError("pigpio is not connected")

    yaw = yaw_config.center
    pitch = pitch_config.center
    session = None
    camera = Picamera2()
    camera_started = False
    last_motion_at = float("-inf")
    try:
        camera.configure(
            camera.create_preview_configuration(
                main={
                    "size": (int(camera_settings["width"]), int(camera_settings["height"])),
                    "format": "RGB888",
                }
            )
        )
        camera.start()
        camera_started = True
        time.sleep(2)
        if pi is not None:
            yaw = _set_servo(pi, yaw_config, yaw)
            pitch = _set_servo(pi, pitch_config, pitch)
            last_motion_at = time.monotonic()

        print("WASD: move | R: center | Space: save | ESC: finish")
        print("Firing is unavailable in this program.")
        if not args.enable_motion:
            print("PREVIEW ONLY: labeled capture and servo motion are disabled")

        while True:
            raw_rgb = camera.capture_array()
            canonical_rgb = orient_and_crop_rgb(raw_rgb, preprocessing)
            display = cv2.cvtColor(canonical_rgb, cv2.COLOR_RGB2BGR)
            cv2.putText(
                display,
                f"yaw={yaw:.1f} pitch={pitch:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 0),
                2,
            )
            is_settled = time.monotonic() - last_motion_at >= settle_seconds
            if args.enable_motion and not is_settled:
                cv2.putText(
                    display,
                    "SETTLING - CAPTURE DISABLED",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 165, 255),
                    2,
                )
            if not args.enable_motion:
                cv2.putText(
                    display,
                    "PREVIEW ONLY - CAPTURE DISABLED",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 165, 255),
                    2,
                )
            cv2.imshow("Yaw data collector (no firing)", display)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if not args.enable_motion:
                continue
            if key == ord("a"):
                yaw = _set_servo(pi, yaw_config, yaw + yaw_config.step)
                last_motion_at = time.monotonic()
            elif key == ord("d"):
                yaw = _set_servo(pi, yaw_config, yaw - yaw_config.step)
                last_motion_at = time.monotonic()
            elif key == ord("w"):
                pitch = _set_servo(pi, pitch_config, pitch + pitch_config.step)
                last_motion_at = time.monotonic()
            elif key == ord("s"):
                pitch = _set_servo(pi, pitch_config, pitch - pitch_config.step)
                last_motion_at = time.monotonic()
            elif key == ord("r"):
                yaw = _set_servo(pi, yaw_config, yaw_config.center)
                pitch = _set_servo(pi, pitch_config, pitch_config.center)
                last_motion_at = time.monotonic()
            elif key == ord(" "):
                if not is_settled:
                    print("Capture ignored while servos are settling")
                    continue
                if session is None:
                    session = YawCaptureSession(
                        args.output_root,
                        preprocessing,
                        CaptureCalibration(
                            yaw_center_degrees=yaw_config.center,
                            calibration_id=str(hardware["calibration_id"]),
                            aiming_reference=str(hardware["aiming_reference"]),
                        ),
                    )
                saved = session.add_frame(
                    raw_rgb,
                    yaw_degrees=yaw,
                    pitch_degrees=pitch,
                )
                print(f"Saved {saved}: yaw_offset={yaw - yaw_config.center:.3f}")
    finally:
        if pi is not None:
            pi.set_servo_pulsewidth(yaw_config.pin, 0)
            pi.set_servo_pulsewidth(pitch_config.pin, 0)
            pi.stop()
        if camera_started:
            camera.stop()
        camera.close()
        cv2.destroyAllWindows()

    if session is None:
        print("No labeled frames captured")
    else:
        completed = session.finalize()
        print(f"Capture bundle ready: {completed}")
        print(f"Upload with: upload-drive-bundle.sh {completed} project-drive:raw")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Interactively record manually positioned Raspberry Pi evaluation trials."""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cv2
import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rubber_band_gun.preprocessing import (  # noqa: E402
    PreprocessingSpec,
    orient_and_crop_rgb,
    picamera2_rgb888_to_rgb,
)
from rubber_band_gun.shot_run import ArtifactReference, ShotRunSession  # noqa: E402


@dataclass(frozen=True)
class ServoConfig:
    pin: int
    center: float
    minimum: float
    maximum: float
    step: float

    def __post_init__(self) -> None:
        values = (self.center, self.minimum, self.maximum, self.step)
        if not 0 <= self.pin <= 27:
            raise ValueError(f"unsupported GPIO pin: {self.pin}")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("servo angles must be finite")
        if not 0 <= self.minimum <= self.center <= self.maximum <= 180:
            raise ValueError("servo limits must contain the center within 0..180 degrees")
        if self.step <= 0:
            raise ValueError("servo step must be positive")


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


def _reference(value: str) -> ArtifactReference:
    try:
        reference_id, raw_path = value.split("=", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("reference must use ID=/path/to/file") from error
    try:
        return ArtifactReference.from_path(reference_id, Path(raw_path))
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _optional_float(prompt: str) -> float | None:
    while True:
        value = input(prompt).strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            print("Enter a number or leave the field blank.")


def _outcome() -> str:
    while True:
        value = input("Outcome [hit/miss/invalid]: ").strip().lower()
        if value in {"hit", "miss", "invalid"}:
            return value
        print("Outcome must be hit, miss, or invalid.")


def _impact_coordinates() -> tuple[float | None, float | None]:
    while True:
        impact_x = _optional_float("Impact x in mm [blank if unavailable]: ")
        impact_y = _optional_float("Impact y in mm [blank if unavailable]: ")
        if (impact_x is None) == (impact_y is None):
            return impact_x, impact_y
        print("Impact x and y must both be supplied or both be blank.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path.home() / "shot-runs")
    parser.add_argument("--run-id")
    parser.add_argument("--shots", type=int, default=1)
    parser.add_argument("--target-distance-m", type=float, required=True)
    parser.add_argument("--calibration-id")
    parser.add_argument("--calibration-reference", type=_reference)
    parser.add_argument("--model-reference", type=_reference, action="append", default=[])
    parser.add_argument(
        "--target-coordinate-system",
        default="origin at declared target center; +x right and +y up as viewed by camera",
    )
    parser.add_argument("--capture-post-evidence", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.shots <= 1000:
        parser.error("--shots must be within 1..1000")
    if not math.isfinite(args.target_distance_m) or args.target_distance_m <= 0:
        parser.error("--target-distance-m must be finite and positive")
    return args


def _validated_hardware(settings: dict[str, object]) -> tuple[ServoConfig, ServoConfig]:
    hardware = settings["hardware"]
    if not isinstance(hardware, dict) or not hardware.get("calibrated", False):
        raise RuntimeError("motion refused: calibrate and measure both axes first")
    for field in ("calibration_id", "aiming_reference"):
        value = str(hardware.get(field, "")).strip()
        if not value or value.startswith("replace-"):
            raise RuntimeError(f"motion refused: hardware.{field} is not configured")
    servo = settings["servo"]
    if not isinstance(servo, dict) or set(servo) != {"yaw", "pitch"}:
        raise ValueError("servo configuration must contain exactly yaw and pitch")
    yaw_config = _servo_config(servo["yaw"])
    pitch_config = _servo_config(servo["pitch"])
    if yaw_config.pin == pitch_config.pin:
        raise ValueError("yaw and pitch cannot use the same GPIO pin")
    return yaw_config, pitch_config


def _overlay(
    canonical_rgb: object,
    *,
    yaw: float,
    pitch: float,
    settled: bool,
    completed: int,
    limit: int,
) -> object:
    display = cv2.cvtColor(canonical_rgb, cv2.COLOR_RGB2BGR)
    cv2.putText(
        display,
        f"yaw={yaw:.1f} pitch={pitch:.1f} trials={completed}/{limit}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 0),
        2,
    )
    status = "READY - SPACE STORES TRIAL" if settled else "SETTLING - SPACE DISABLED"
    cv2.putText(
        display,
        status,
        (10, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 0) if settled else (0, 165, 255),
        2,
    )
    return display


def main() -> None:
    args = _parse_args()
    settings = tomllib.loads(args.config.read_text(encoding="utf-8"))
    camera_settings = settings["camera"]
    preprocessing = PreprocessingSpec(**settings["preprocessing"])
    yaw_config, pitch_config = _validated_hardware(settings)
    settle_seconds = float(settings["capture"]["settle_seconds"])
    if not math.isfinite(settle_seconds) or settle_seconds < 0:
        raise ValueError("capture.settle_seconds must be finite and non-negative")
    hardware = settings["hardware"]
    calibration_id = args.calibration_id or str(hardware["calibration_id"])

    import pigpio
    from picamera2 import Picamera2

    pi = pigpio.pi()
    if not pi.connected:
        raise RuntimeError("pigpio is not connected")
    camera = Picamera2()
    camera_started = False
    session: ShotRunSession | None = None
    completed_trials = 0
    yaw = yaw_config.center
    pitch = pitch_config.center
    last_motion_at = time.monotonic()
    finish_requested = False
    try:
        camera.configure(
            camera.create_preview_configuration(
                main={
                    "size": (
                        int(camera_settings["width"]),
                        int(camera_settings["height"]),
                    ),
                    "format": "RGB888",
                }
            )
        )
        camera.start()
        camera_started = True
        time.sleep(2.0)
        yaw = _set_servo(pi, yaw_config, yaw)
        pitch = _set_servo(pi, pitch_config, pitch)
        last_motion_at = time.monotonic()
        print("A/D: yaw | W/S: pitch | R: center | Space: store trial | ESC: finish")
        print("After Space, independently complete the external event and acknowledge it.")

        while not finish_requested and completed_trials < args.shots:
            raw_rgb = picamera2_rgb888_to_rgb(camera.capture_array())
            canonical_rgb = orient_and_crop_rgb(raw_rgb, preprocessing)
            settled = time.monotonic() - last_motion_at >= settle_seconds
            display = _overlay(
                canonical_rgb,
                yaw=yaw,
                pitch=pitch,
                settled=settled,
                completed=completed_trials,
                limit=args.shots,
            )
            cv2.imshow("Manual shot-run evaluator", display)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                finish_requested = True
            elif key == ord("a"):
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
                if not settled:
                    print("Trial ignored while the axes are settling")
                    continue
                if session is None:
                    session = ShotRunSession(
                        args.output_root,
                        preprocessing,
                        run_id=args.run_id,
                        target_coordinate_system=args.target_coordinate_system,
                        calibration_id=calibration_id,
                        calibration_reference=args.calibration_reference,
                        model_references=tuple(args.model_reference),
                    )
                shot_id = session.begin_shot(
                    raw_rgb,
                    target_distance_m=args.target_distance_m,
                    commanded_yaw_degrees=yaw,
                    commanded_pitch_degrees=pitch,
                    captured_at=datetime.now(UTC),
                )
                cv2.putText(
                    display,
                    f"{shot_id} STORED - COMPLETE EXTERNAL EVENT",
                    (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 255),
                    2,
                )
                cv2.imshow("Manual shot-run evaluator", display)
                cv2.waitKey(1)
                print(f"{shot_id}: pre-event frame and axis commands stored.")
                input("Complete the external event independently, then press Enter: ")
                acknowledged_at = datetime.now(UTC)
                post_event_rgb = None
                post_event_captured_at = None
                if args.capture_post_evidence:
                    post_event_rgb = picamera2_rgb888_to_rgb(camera.capture_array())
                    post_event_captured_at = datetime.now(UTC)
                outcome = _outcome()
                impact_x, impact_y = _impact_coordinates()
                notes = input("Notes [optional]: ")
                session.complete_shot(
                    outcome=outcome,
                    external_event_acknowledged_at=acknowledged_at,
                    impact_x_mm=impact_x,
                    impact_y_mm=impact_y,
                    post_event_rgb=post_event_rgb,
                    post_event_captured_at=post_event_captured_at,
                    notes=notes,
                )
                completed_trials += 1
                print(f"Recorded {shot_id} ({completed_trials}/{args.shots}).")
    except (Exception, KeyboardInterrupt):
        if session is not None:
            print(
                f"Run was not published; partial evidence remains at {session.partial_path}",
                file=sys.stderr,
            )
        raise
    finally:
        pi.set_servo_pulsewidth(yaw_config.pin, 0)
        pi.set_servo_pulsewidth(pitch_config.pin, 0)
        pi.stop()
        if camera_started:
            camera.stop()
        camera.close()
        cv2.destroyAllWindows()

    if session is None or completed_trials == 0:
        print("No completed trials; no completed bundle was created.")
        return
    completed = session.finalize()
    print(f"Immutable shot run ready: {completed}")
    print(f"Verify with: python scripts/check-shot-run.py {completed}")


if __name__ == "__main__":
    main()

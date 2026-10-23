#!/usr/bin/env python3
"""Preview YOLO target detections from the Pi camera without actuator access."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rubber_band_gun.overlay import draw_center_crosshair_bgr  # noqa: E402
from rubber_band_gun.preprocessing import picamera2_rgb888_to_rgb  # noqa: E402
from rubber_band_gun.runtime_models import UltralyticsTargetDetector  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.15)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--tile-grid", type=int, default=2)
    parser.add_argument("--tile-overlap", type=float, default=0.2)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--warmup", type=float, default=2.0)
    parser.add_argument(
        "--frames",
        type=int,
        default=0,
        help="stop after this many frames; zero means run until Q or ESC",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("target-preview"))
    args = parser.parse_args()
    if not 0.0 < args.confidence <= 1.0:
        parser.error("--confidence must be greater than 0 and at most 1")
    if args.width < 1 or args.height < 1:
        parser.error("camera dimensions must be positive")
    if args.image_size < 32 or args.tile_grid < 1:
        parser.error("--image-size must be at least 32 and --tile-grid must be positive")
    if not 0.0 <= args.tile_overlap < 1.0:
        parser.error("--tile-overlap must be within 0..1")
    if args.warmup < 0 or args.frames < 0:
        parser.error("--warmup and --frames cannot be negative")
    if args.headless and args.frames == 0:
        parser.error("--headless requires a positive --frames value")
    return args


def orient_like_legacy_collector(raw_rgb: np.ndarray) -> np.ndarray:
    """Rotate the 640x480 camera frame to match the 480x640 training images."""

    return np.ascontiguousarray(np.rot90(raw_rgb, k=3))


def annotate(frame_rgb: np.ndarray, detection: object | None) -> tuple[np.ndarray, str]:
    display = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    display = draw_center_crosshair_bgr(display)
    if detection is None:
        cv2.putText(
            display,
            "NO CANDIDATE",
            (8, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )
        return display, "NO CANDIDATE"

    x1, y1, x2, y2 = detection.box
    center_x = round((x1 + x2) / 2)
    center_y = round((y1 + y2) / 2)
    cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.drawMarker(
        display,
        (center_x, center_y),
        (0, 255, 255),
        cv2.MARKER_CROSS,
        12,
        2,
    )
    status = (
        f"TOP CANDIDATE {detection.confidence:.2f} "
        f"box=({x1},{y1})-({x2},{y2}) center=({center_x},{center_y})"
    )
    cv2.putText(
        display,
        f"CANDIDATE {detection.confidence:.2f} center=({center_x},{center_y})",
        (8, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 0),
        2,
    )
    return display, status


def main() -> None:
    args = parse_args()
    model_path = args.model.expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"YOLO model not found: {model_path}")

    detector = UltralyticsTargetDetector(
        model_path,
        confidence=args.confidence,
        device=args.device,
        image_size=args.image_size,
        tile_grid=args.tile_grid,
        tile_overlap=args.tile_overlap,
    )

    from picamera2 import Picamera2

    output_dir = args.output_dir.expanduser().resolve()
    if args.headless:
        output_dir.mkdir(parents=True, exist_ok=True)

    camera = Picamera2()
    started = False
    frame_index = 0
    try:
        camera.configure(
            camera.create_preview_configuration(
                main={"size": (args.width, args.height), "format": "RGB888"}
            )
        )
        camera.start()
        started = True
        time.sleep(args.warmup)
        print("TARGET PREVIEW ONLY: no GPIO or actuator library is loaded.")
        print(
            f"YOLO tiled inference: grid={args.tile_grid} overlap={args.tile_overlap:.2f} "
            f"confidence={args.confidence:.2f} imgsz={args.image_size}"
        )
        if args.headless:
            print(f"Saving annotated frames to {output_dir}")
        else:
            print("Q/ESC: quit")

        while True:
            raw_rgb = picamera2_rgb888_to_rgb(camera.capture_array())
            frame_rgb = orient_like_legacy_collector(raw_rgb)
            detection = detector.detect(frame_rgb)
            display, status = annotate(frame_rgb, detection)
            print(f"frame={frame_index:04d} {status}", flush=True)

            if args.headless:
                timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
                output_path = output_dir / f"frame_{frame_index:04d}_{timestamp}.jpg"
                if not cv2.imwrite(str(output_path), display):
                    raise RuntimeError(f"failed to write preview frame: {output_path}")
            else:
                cv2.imshow("YOLO target preview (no motion)", display)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break

            frame_index += 1
            if args.frames and frame_index >= args.frames:
                break
    finally:
        if started:
            camera.stop()
        camera.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Display camera detections and yaw predictions without importing actuator libraries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rubber_band_gun.evaluation import rectangle_mask  # noqa: E402
from rubber_band_gun.preprocessing import (  # noqa: E402
    PreprocessingSpec,
    picamera2_rgb888_to_rgb,
    prepare_model_rgb,
)
from rubber_band_gun.runtime_models import (  # noqa: E402
    TorchYawRegressor,
    UltralyticsTargetDetector,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--yolo-model", type=Path, required=True)
    parser.add_argument("--yaw-model", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    settings = tomllib.loads(args.config.read_text(encoding="utf-8"))
    spec = PreprocessingSpec(**settings["preprocessing"])
    detector = UltralyticsTargetDetector(
        args.yolo_model,
        confidence=args.confidence,
        device=args.device,
    )
    regressor = TorchYawRegressor(
        args.yaw_model,
        image_size=spec.model_width,
        device=args.device,
    )

    from picamera2 import Picamera2

    camera = Picamera2()
    started = False
    try:
        camera.configure(
            camera.create_preview_configuration(
                main={
                    "size": (int(settings["camera"]["width"]), int(settings["camera"]["height"])),
                    "format": "RGB888",
                }
            )
        )
        camera.start()
        started = True
        print("EVALUATION ONLY: no GPIO or actuator library is loaded. ESC/Q: quit")
        while True:
            raw_rgb = picamera2_rgb888_to_rgb(camera.capture_array())
            model_rgb = prepare_model_rgb(raw_rgb, spec)
            detection = detector.detect(model_rgb)
            display = cv2.cvtColor(model_rgb, cv2.COLOR_RGB2BGR)
            if detection is None:
                cv2.putText(
                    display,
                    "NO TARGET",
                    (8, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2,
                )
            else:
                x1, y1, x2, y2 = detection.box
                mask = rectangle_mask(detection, width=spec.model_width, height=spec.model_height)
                yaw = regressor.predict(mask)
                cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    display,
                    f"TARGET {detection.confidence:.2f} yaw={yaw:+.2f}",
                    (8, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                )
            cv2.imshow("Recorded-compatible inference (no motion)", display)
            if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                break
    finally:
        if started:
            camera.stop()
        camera.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Load both course models and run one actuator-free synthetic inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from rubber_band_gun.evaluation import Detection, rectangle_mask, sha256_file
from rubber_band_gun.runtime_models import TorchYawRegressor, UltralyticsTargetDetector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yolo", type=Path, required=True)
    parser.add_argument("--yaw", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--image-size", type=int, default=224)
    args = parser.parse_args()
    yaw = TorchYawRegressor(args.yaw, image_size=args.image_size, device=args.device)
    mask = rectangle_mask(
        Detection((40, 50, 160, 180), 1.0),
        width=args.image_size,
        height=args.image_size,
    )
    yaw_prediction = yaw.predict(mask)
    detector = UltralyticsTargetDetector(args.yolo, confidence=0.5, device=args.device)
    blank_detection = detector.detect(
        np.zeros((args.image_size, args.image_size, 3), dtype=np.uint8)
    )
    print(
        json.dumps(
            {
                "schema_version": "rbg-reference-model-runtime-check/v1",
                "yolo_sha256": sha256_file(args.yolo),
                "yaw_sha256": sha256_file(args.yaw),
                "yaw_range": [yaw.yaw_min, yaw.yaw_max],
                "synthetic_yaw_prediction": yaw_prediction,
                "blank_frame_detection": blank_detection is not None,
                "status": "passed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

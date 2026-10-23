#!/usr/bin/env python3
"""Create a complete, non-overwriting target-box annotation template for one dataset split."""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import cv2

from rubber_band_gun.evaluation import TARGET_ANNOTATION_COLUMNS, dataset_cases
from rubber_band_gun.preprocessing import PreprocessingSpec, resize_model_rgb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "locked-test"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-output", type=Path, required=True)
    args = parser.parse_args()
    cases, manifest = dataset_cases(args.dataset, args.split)
    if not cases:
        raise ValueError(f"dataset split has no target-positive cases: {args.split}")
    if args.image_output.exists():
        raise FileExistsError(f"annotation image output exists: {args.image_output}")
    partial_images = args.image_output.with_name(f".{args.image_output.name}.partial")
    if partial_images.exists():
        raise FileExistsError(f"annotation image staging exists: {partial_images}")
    spec = PreprocessingSpec.from_mapping(manifest["preprocessing"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial_images.mkdir(parents=True)
    try:
        for case in cases:
            source_bgr = cv2.imread(str(case.image_path), cv2.IMREAD_COLOR)
            if source_bgr is None:
                raise ValueError(f"cannot decode dataset image: {case.image_path}")
            model_rgb = resize_model_rgb(cv2.cvtColor(source_bgr, cv2.COLOR_BGR2RGB), spec)
            destination = partial_images / case.case_id
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(destination), cv2.cvtColor(model_rgb, cv2.COLOR_RGB2BGR)):
                raise RuntimeError(f"cannot write annotation image: {destination}")
        with args.output.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=TARGET_ANNOTATION_COLUMNS)
            writer.writeheader()
            for case in cases:
                writer.writerow(
                    {
                        "case_id": case.case_id,
                        "box_x1": "",
                        "box_y1": "",
                        "box_x2": "",
                        "box_y2": "",
                        "annotated_by": "",
                    }
                )
        partial_images.rename(args.image_output)
    except Exception:
        shutil.rmtree(partial_images, ignore_errors=True)
        raise
    print(f"annotation template created for {len(cases)} cases: {args.output}")
    print(f"model-sized annotation images: {args.image_output}")


if __name__ == "__main__":
    main()

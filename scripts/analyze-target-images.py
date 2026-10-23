#!/usr/bin/env python3
"""Run actuator-free YOLO target analysis on a folder of recorded images."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rubber_band_gun.runtime_models import UltralyticsTargetDetector  # noqa: E402

IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.15)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--tile-grid", type=int, default=2)
    parser.add_argument("--tile-overlap", type=float, default=0.2)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 0.0 < args.confidence <= 1.0:
        parser.error("--confidence must be greater than 0 and at most 1")
    if args.image_size < 32 or args.tile_grid < 1:
        parser.error("--image-size must be at least 32 and --tile-grid must be positive")
    if not 0.0 <= args.tile_overlap < 1.0:
        parser.error("--tile-overlap must be within 0..1")
    return args


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contact_sheet(tiles: list[np.ndarray], *, columns: int = 10) -> np.ndarray:
    """Lay out equally sized BGR tiles for fast human review."""

    if not tiles:
        raise ValueError("contact sheet requires at least one tile")
    tile_height, tile_width = tiles[0].shape[:2]
    rows = (len(tiles) + columns - 1) // columns
    sheet = np.full((rows * tile_height, columns * tile_width, 3), 230, dtype=np.uint8)
    for index, tile in enumerate(tiles):
        y = (index // columns) * tile_height
        x = (index % columns) * tile_width
        sheet[y : y + tile_height, x : x + tile_width] = tile
    return sheet


def main() -> None:
    args = parse_args()
    image_dir = args.images.expanduser().resolve()
    model_path = args.model.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    if not image_dir.is_dir():
        raise NotADirectoryError(f"image folder not found: {image_dir}")
    if not model_path.is_file():
        raise FileNotFoundError(f"YOLO model not found: {model_path}")
    images = sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise ValueError(f"no supported images found in: {image_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(
                f"output is not empty; pass --overwrite to replace files: {output_dir}"
            )
        summary_path = output_dir / "summary.json"
        try:
            old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise ValueError(
                "refusing to overwrite a folder without a valid prior analysis summary"
            ) from error
        if old_summary.get("schema_version") != "rbg-target-folder-analysis/v1":
            raise ValueError("refusing to overwrite a folder owned by another workflow")
        shutil.rmtree(output_dir)
    annotated_dir = output_dir / "annotated"
    annotated_dir.mkdir(parents=True, exist_ok=True)

    detector = UltralyticsTargetDetector(
        model_path,
        confidence=args.confidence,
        device=args.device,
        image_size=args.image_size,
        tile_grid=args.tile_grid,
        tile_overlap=args.tile_overlap,
    )
    rows: list[dict[str, object]] = []
    review_tiles: list[np.ndarray] = []
    started = time.perf_counter()
    for index, image_path in enumerate(images, start=1):
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"failed to read image: {image_path}")
        detection = detector.detect(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        height, width = bgr.shape[:2]
        row: dict[str, object] = {
            "file": image_path.name,
            "width": width,
            "height": height,
            "detected": detection is not None,
            "confidence": "" if detection is None else detection.confidence,
            "box_x1": "" if detection is None else detection.box[0],
            "box_y1": "" if detection is None else detection.box[1],
            "box_x2": "" if detection is None else detection.box[2],
            "box_y2": "" if detection is None else detection.box[3],
        }
        rows.append(row)
        if detection is not None:
            x1, y1, x2, y2 = detection.box
            cv2.rectangle(bgr, (x1, y1), (x2, y2), (0, 255, 0), 4)
            cv2.putText(
                bgr,
                f"target {detection.confidence:.3f}",
                (max(0, x1), max(35, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0),
                3,
            )
            if not cv2.imwrite(str(annotated_dir / image_path.name), bgr):
                raise RuntimeError(f"failed to write annotation for: {image_path}")
        thumbnail = cv2.resize(bgr, (130, 231), interpolation=cv2.INTER_AREA)
        tile = np.full((265, 140, 3), 255, dtype=np.uint8)
        tile[30:261, 5:135] = thumbnail
        confidence_label = "none" if detection is None else f"{detection.confidence:.2f}"
        cv2.putText(
            tile,
            f"{image_path.stem.removeprefix('img_')} {confidence_label}",
            (4, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (0, 100, 0) if detection is not None else (0, 0, 180),
            1,
            cv2.LINE_AA,
        )
        review_tiles.append(tile)
        print(
            f"[{index:03d}/{len(images):03d}] {image_path.name}: "
            + ("no target" if detection is None else f"target {detection.confidence:.3f}"),
            flush=True,
        )

    elapsed = time.perf_counter() - started
    fieldnames = tuple(rows[0])
    with (output_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    if not cv2.imwrite(str(output_dir / "contact-sheet.jpg"), contact_sheet(review_tiles)):
        raise RuntimeError("failed to write contact sheet")
    report = {
        "schema_version": "rbg-target-folder-analysis/v1",
        "status": "diagnostic-unlabeled",
        "note": (
            "Detection counts are not recall or accuracy because this folder has no "
            "ground-truth labels."
        ),
        "images": str(image_dir),
        "model": str(model_path),
        "model_sha256": sha256_file(model_path),
        "settings": {
            "confidence": args.confidence,
            "device": args.device,
            "image_size": args.image_size,
            "tile_grid": args.tile_grid,
            "tile_overlap": args.tile_overlap,
            "include_full_frame": True,
        },
        "image_count": len(rows),
        "detection_count": sum(bool(row["detected"]) for row in rows),
        "elapsed_seconds": round(elapsed, 3),
        "mean_seconds_per_image": round(elapsed / len(rows), 4),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

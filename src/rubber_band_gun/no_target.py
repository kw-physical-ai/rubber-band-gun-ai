"""Immutable, actuator-free captures for false-positive evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .preprocessing import PreprocessingSpec

NO_TARGET_SCHEMA = "rbg-no-target-capture/v1"
NO_TARGET_ID_PATTERN = re.compile(r"no-target-\d{8}T\d{6}Z")
NO_TARGET_COLUMNS = ("filename", "captured_at_utc", "expected_target")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class NoTargetCaptureSession:
    def __init__(
        self,
        output_root: Path,
        preprocessing: PreprocessingSpec,
        *,
        capture_id: str | None = None,
    ) -> None:
        self.output_root = output_root.expanduser().resolve()
        self.preprocessing = preprocessing
        self.capture_id = capture_id or datetime.now(UTC).strftime("no-target-%Y%m%dT%H%M%SZ")
        if not NO_TARGET_ID_PATTERN.fullmatch(self.capture_id):
            raise ValueError(f"invalid no-target capture ID: {self.capture_id}")
        self.partial = self.output_root / f".{self.capture_id}.partial"
        self.completed = self.output_root / self.capture_id
        if self.partial.exists() or self.completed.exists():
            raise FileExistsError(f"capture already exists: {self.capture_id}")
        (self.partial / "images").mkdir(parents=True)
        self.rows: list[dict[str, str]] = []
        self.raw_shape: tuple[int, int, int] | None = None

    def add_frame(self, raw_rgb: np.ndarray) -> Path:
        if raw_rgb.dtype != np.uint8 or raw_rgb.ndim != 3 or raw_rgb.shape[2] != 3:
            raise ValueError("raw frame must be RGB uint8 with three channels")
        if self.raw_shape is None:
            self.raw_shape = raw_rgb.shape
        elif self.raw_shape != raw_rgb.shape:
            raise ValueError(f"raw frame shape changed from {self.raw_shape} to {raw_rgb.shape}")
        import cv2

        relative = Path("images") / f"frame_{len(self.rows):06d}.jpg"
        success, encoded = cv2.imencode(".jpg", cv2.cvtColor(raw_rgb, cv2.COLOR_RGB2BGR))
        if not success:
            raise RuntimeError("JPEG encoding failed")
        (self.partial / relative).write_bytes(encoded.tobytes())
        self.rows.append(
            {
                "filename": relative.as_posix(),
                "captured_at_utc": datetime.now(UTC).isoformat(),
                "expected_target": "false",
            }
        )
        return relative

    def finalize(self) -> Path:
        if not self.rows:
            raise ValueError("cannot finalize an empty no-target capture")
        try:
            csv_path = self.partial / "cases.csv"
            with csv_path.open("x", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=NO_TARGET_COLUMNS)
                writer.writeheader()
                writer.writerows(self.rows)
            files = [
                {
                    "path": path.relative_to(self.partial).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in sorted(self.partial.rglob("*"))
                if path.is_file()
            ]
            manifest = {
                "schema_version": NO_TARGET_SCHEMA,
                "capture_id": self.capture_id,
                "created_at_utc": datetime.now(UTC).isoformat(),
                "purpose": "independently labeled no-target false-positive evaluation",
                "preprocessing": self.preprocessing.to_manifest(),
                "frame_count": len(self.rows),
                "raw_frame_height": self.raw_shape[0],
                "raw_frame_width": self.raw_shape[1],
                "files": files,
            }
            (self.partial / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.partial.rename(self.completed)
            return self.completed
        except Exception:
            shutil.rmtree(self.partial, ignore_errors=True)
            raise


def verify_no_target_bundle(bundle: Path) -> dict[str, Any]:
    bundle = bundle.expanduser().resolve()
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest.json must be an ordinary file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != NO_TARGET_SCHEMA:
        raise ValueError("unsupported no-target capture schema")
    capture_id = manifest.get("capture_id")
    if not isinstance(capture_id, str) or not NO_TARGET_ID_PATTERN.fullmatch(capture_id):
        raise ValueError(f"invalid no-target capture ID: {capture_id}")
    if bundle.name != capture_id:
        raise ValueError("bundle directory and capture ID differ")
    preprocessing = PreprocessingSpec.from_mapping(manifest.get("preprocessing", {}))
    try:
        raw_height = int(manifest["raw_frame_height"])
        raw_width = int(manifest["raw_frame_width"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid no-target frame geometry") from error
    if raw_height < 1 or raw_width < 1:
        raise ValueError("invalid no-target frame geometry")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("no-target manifest contains no files")
    expected: set[str] = set()
    for entry in entries:
        name = entry.get("path") if isinstance(entry, dict) else None
        relative = Path(name) if isinstance(name, str) else None
        if relative is None or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe no-target path: {name}")
        if name in expected:
            raise ValueError(f"duplicate no-target path: {name}")
        expected.add(name)
        path = bundle / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing no-target file: {name}")
        if path.stat().st_size != entry.get("bytes") or _sha256(path) != entry.get("sha256"):
            raise ValueError(f"no-target file integrity failed: {name}")
    all_paths = list(bundle.rglob("*"))
    if any(path.is_symlink() for path in all_paths):
        raise ValueError("no-target bundle contains a symbolic link")
    actual = {
        path.relative_to(bundle).as_posix()
        for path in all_paths
        if path.is_file() and path.relative_to(bundle).as_posix() != "manifest.json"
    }
    if actual != expected:
        raise ValueError("no-target bundle files do not exactly match the manifest")
    with (bundle / "cases.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != NO_TARGET_COLUMNS:
            raise ValueError("invalid no-target CSV header")
        rows = list(reader)
    if not rows or len(rows) != manifest.get("frame_count"):
        raise ValueError("no-target frame count mismatch")
    filenames = [row["filename"] for row in rows]
    if len(filenames) != len(set(filenames)):
        raise ValueError("duplicate no-target filename")
    if any(row["expected_target"] != "false" for row in rows):
        raise ValueError("no-target bundle contains a target-positive row")
    if set(filenames) != {name for name in expected if name.startswith("images/")}:
        raise ValueError("no-target labels and images differ")
    import cv2

    for row in rows:
        timestamp = datetime.fromisoformat(row["captured_at_utc"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("no-target timestamp must include a timezone")
        image = cv2.imread(str(bundle / row["filename"]), cv2.IMREAD_COLOR)
        if image is None or image.shape != (raw_height, raw_width, 3):
            raise ValueError(f"invalid no-target image geometry: {row['filename']}")
    return {
        "schema_version": "rbg-no-target-capture-report/v1",
        "capture_id": capture_id,
        "preprocessing": preprocessing.to_manifest(),
        "image_paths": [bundle / filename for filename in filenames],
        "source_manifest_sha256": _sha256(manifest_path),
        "status": "passed",
    }

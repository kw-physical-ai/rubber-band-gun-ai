"""Session bundles for non-firing yaw-label collection."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .preprocessing import PreprocessingSpec, orient_and_crop_rgb

CAPTURE_SCHEMA = "rbg-yaw-capture/v2"
CAPTURE_ID_PATTERN = re.compile(r"capture-\d{8}T\d{6}Z")
CSV_COLUMNS = (
    "filename",
    "captured_at_utc",
    "yaw_degrees",
    "aligned_yaw_degrees",
    "yaw_offset",
    "pitch_degrees",
    "label_status",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_utc(value: datetime | None = None) -> str:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return instant.astimezone(UTC).isoformat()


def _finite_servo_angle(name: str, value: float) -> float:
    try:
        angle = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(angle) or not 0.0 <= angle <= 180.0:
        raise ValueError(f"{name} must be finite and within 0..180 degrees")
    return angle


def _parse_aware_timestamp(name: str, value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed


@dataclass(frozen=True)
class CaptureCalibration:
    yaw_center_degrees: float
    calibration_id: str
    aiming_reference: str

    def __post_init__(self) -> None:
        _finite_servo_angle("yaw_center_degrees", self.yaw_center_degrees)
        if not self.calibration_id.strip():
            raise ValueError("calibration_id is required")
        if not self.aiming_reference.strip():
            raise ValueError("aiming_reference is required")


class YawCaptureSession:
    """Build one immutable capture bundle and publish it by atomic rename."""

    def __init__(
        self,
        output_root: Path,
        preprocessing: PreprocessingSpec,
        calibration: CaptureCalibration,
        *,
        capture_id: str | None = None,
    ) -> None:
        self.output_root = output_root.expanduser().resolve()
        self.preprocessing = preprocessing
        self.calibration = calibration
        self.capture_id = capture_id or datetime.now(UTC).strftime("capture-%Y%m%dT%H%M%SZ")
        if not CAPTURE_ID_PATTERN.fullmatch(self.capture_id):
            raise ValueError(f"invalid capture ID: {self.capture_id}")

        self.partial_path = self.output_root / f".{self.capture_id}.partial"
        self.completed_path = self.output_root / self.capture_id
        if self.partial_path.exists() or self.completed_path.exists():
            raise FileExistsError(f"capture already exists: {self.capture_id}")
        (self.partial_path / "images").mkdir(parents=True)
        self._rows: list[dict[str, str]] = []
        self._stored_frame_shape: tuple[int, int, int] | None = None
        self._finalized = False

    def add_frame(
        self,
        frame_rgb: np.ndarray,
        *,
        yaw_degrees: float,
        aligned_yaw_degrees: float,
        pitch_degrees: float,
        captured_at: datetime | None = None,
        label_status: str = "human-aligned",
    ) -> Path:
        if self._finalized:
            raise RuntimeError("capture is already finalized")
        if label_status not in {"human-aligned", "diagnostic"}:
            raise ValueError(f"unsupported label status: {label_status}")
        yaw_degrees = _finite_servo_angle("yaw_degrees", yaw_degrees)
        aligned_yaw_degrees = _finite_servo_angle(
            "aligned_yaw_degrees", aligned_yaw_degrees
        )
        pitch_degrees = _finite_servo_angle("pitch_degrees", pitch_degrees)

        import cv2

        canonical_rgb = orient_and_crop_rgb(frame_rgb, self.preprocessing)
        if self._stored_frame_shape is None:
            self._stored_frame_shape = canonical_rgb.shape
        elif canonical_rgb.shape != self._stored_frame_shape:
            raise ValueError(
                f"frame shape changed from {self._stored_frame_shape} to {canonical_rgb.shape}"
            )
        filename = f"frame_{len(self._rows):06d}.jpg"
        relative_path = Path("images") / filename
        success, encoded = cv2.imencode(".jpg", cv2.cvtColor(canonical_rgb, cv2.COLOR_RGB2BGR))
        if not success:
            raise RuntimeError("JPEG encoding failed")
        (self.partial_path / relative_path).write_bytes(encoded.tobytes())

        self._rows.append(
            {
                "filename": filename,
                "captured_at_utc": _iso_utc(captured_at),
                "yaw_degrees": f"{yaw_degrees:.3f}",
                "aligned_yaw_degrees": f"{aligned_yaw_degrees:.3f}",
                "yaw_offset": f"{aligned_yaw_degrees - yaw_degrees:.3f}",
                "pitch_degrees": f"{pitch_degrees:.3f}",
                "label_status": label_status,
            }
        )
        return relative_path

    def finalize(self) -> Path:
        if self._finalized:
            raise RuntimeError("capture is already finalized")
        if not self._rows:
            raise ValueError("cannot finalize an empty capture")

        csv_path = self.partial_path / "data_angles.csv"
        with csv_path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(self._rows)

        files = []
        for path in sorted(self.partial_path.rglob("*")):
            if path.is_file():
                files.append(
                    {
                        "path": path.relative_to(self.partial_path).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                )
        manifest = {
            "schema_version": CAPTURE_SCHEMA,
            "capture_id": self.capture_id,
            "created_at_utc": _iso_utc(),
            "source_host": socket.gethostname(),
            "frame_count": len(self._rows),
            "stored_frame_height": self._stored_frame_shape[0],
            "stored_frame_width": self._stored_frame_shape[1],
            "label_contract": "yaw_offset = aligned_yaw_degrees - yaw_degrees",
            "calibration": {
                "calibration_id": self.calibration.calibration_id,
                "yaw_center_degrees": self.calibration.yaw_center_degrees,
                "aiming_reference": self.calibration.aiming_reference,
            },
            "preprocessing": self.preprocessing.to_manifest(),
            "files": files,
        }
        (self.partial_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.partial_path.rename(self.completed_path)
        self._finalized = True
        return self.completed_path


def verify_yaw_capture_bundle(bundle: Path) -> dict[str, Any]:
    """Verify the immutable file and label contract of one capture bundle."""

    bundle = bundle.resolve()
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest.json must be an ordinary file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != CAPTURE_SCHEMA:
        raise ValueError(f"unsupported capture schema: {manifest.get('schema_version')}")
    capture_id = manifest.get("capture_id")
    if not isinstance(capture_id, str) or not CAPTURE_ID_PATTERN.fullmatch(capture_id):
        raise ValueError(f"invalid capture ID: {capture_id}")
    if bundle.name != capture_id:
        raise ValueError("bundle directory and capture ID differ")

    _parse_aware_timestamp("created_at_utc", manifest.get("created_at_utc"))
    preprocessing = PreprocessingSpec.from_mapping(manifest.get("preprocessing", {}))
    calibration = manifest.get("calibration", {})
    if not isinstance(calibration, dict) or "yaw_center_degrees" not in calibration:
        raise ValueError("manifest calibration is incomplete")
    _finite_servo_angle("yaw_center_degrees", calibration["yaw_center_degrees"])
    if not str(calibration.get("calibration_id", "")).strip():
        raise ValueError("manifest calibration_id is required")
    if not str(calibration.get("aiming_reference", "")).strip():
        raise ValueError("manifest aiming_reference is required")
    try:
        stored_height = int(manifest["stored_frame_height"])
        stored_width = int(manifest["stored_frame_width"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("manifest stored frame dimensions are invalid") from error
    if stored_height < 1 or stored_width < 1:
        raise ValueError("manifest stored frame dimensions must be positive")

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest contains no files")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid manifest entry")
        relative_name = entry.get("path")
        relative = Path(relative_name) if isinstance(relative_name, str) else None
        if relative is None or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe manifest path: {relative_name}")
        if relative_name in expected:
            raise ValueError(f"duplicate manifest path: {relative_name}")
        expected.add(relative_name)
        path = bundle / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsupported file: {relative_name}")
        if path.stat().st_size != entry.get("bytes"):
            raise ValueError(f"size mismatch: {relative_name}")
        if _sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"SHA-256 mismatch: {relative_name}")

    all_paths = list(bundle.rglob("*"))
    if any(path.is_symlink() for path in all_paths):
        raise ValueError("bundle contains a symbolic link")
    if any(not path.is_file() and not path.is_dir() for path in all_paths):
        raise ValueError("bundle contains a non-regular filesystem object")
    actual = {
        path.relative_to(bundle).as_posix()
        for path in all_paths
        if path.is_file() and path.relative_to(bundle).as_posix() != "manifest.json"
    }
    if actual != expected:
        raise ValueError("bundle files do not exactly match the manifest")

    csv_path = bundle / "data_angles.csv"
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise ValueError(f"invalid CSV header: {reader.fieldnames}")
        rows = list(reader)
    if len(rows) != manifest.get("frame_count") or not rows:
        raise ValueError("CSV frame count does not match the manifest")
    filenames = [row["filename"] for row in rows]
    if len(set(filenames)) != len(filenames):
        raise ValueError("CSV contains duplicate filenames")
    if any(Path(name).name != name or "\\" in name or not name for name in filenames):
        raise ValueError("CSV contains an unsafe image filename")
    if {f"images/{name}" for name in filenames} != {
        path for path in expected if path.startswith("images/")
    }:
        raise ValueError("CSV image names do not match the manifest")
    import cv2

    for row in rows:
        _parse_aware_timestamp("captured_at_utc", row["captured_at_utc"])
        yaw = _finite_servo_angle("yaw_degrees", row["yaw_degrees"])
        aligned_yaw = _finite_servo_angle(
            "aligned_yaw_degrees", row["aligned_yaw_degrees"]
        )
        offset = float(row["yaw_offset"])
        if not math.isfinite(offset):
            raise ValueError("yaw_offset must be finite")
        if abs(offset - (aligned_yaw - yaw)) > 0.0015:
            raise ValueError(f"yaw offset contract failed: {row['filename']}")
        _finite_servo_angle("pitch_degrees", row["pitch_degrees"])
        if row["label_status"] not in {"human-aligned", "diagnostic"}:
            raise ValueError(f"invalid label status: {row['label_status']}")
        image = cv2.imread(str(bundle / "images" / row["filename"]), cv2.IMREAD_COLOR)
        if image is None or image.shape != (stored_height, stored_width, 3):
            raise ValueError(f"invalid stored image geometry: {row['filename']}")

    return {
        "schema_version": "rbg-yaw-capture-report/v1",
        "capture_id": capture_id,
        "frame_count": len(rows),
        "calibration_id": calibration["calibration_id"],
        "preprocessing": preprocessing.to_manifest(),
        "source_manifest_sha256": _sha256_file(manifest_path),
        "status": "passed",
    }

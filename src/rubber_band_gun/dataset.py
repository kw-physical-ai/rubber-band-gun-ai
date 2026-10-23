"""Versioned datasets assembled from verified yaw-capture bundles."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .capture import CAPTURE_ID_PATTERN, verify_yaw_capture_bundle
from .capture import CSV_COLUMNS as CAPTURE_CSV_COLUMNS
from .preprocessing import PreprocessingSpec

DATASET_SCHEMA = "rbg-yaw-dataset/v1"
DATASET_ID_PATTERN = re.compile(r"dataset-[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
SPLIT_NAMES = ("train", "validation", "locked-test")
DATASET_CSV_COLUMNS = (
    "filename",
    "source_capture_id",
    "source_filename",
    "captured_at_utc",
    "split",
    "yaw_degrees",
    "aligned_yaw_degrees",
    "yaw_offset",
    "pitch_degrees",
    "label_status",
    "calibration_id",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_utc() -> str:
    return datetime.now(UTC).isoformat()


def _package_version() -> str:
    try:
        return version("rubber-band-gun-ai")
    except PackageNotFoundError:
        return "uninstalled"


def _yaw_offset_statistics(
    rows: Sequence[Mapping[str, str]],
) -> dict[str, dict[str, float | int | None]]:
    statistics: dict[str, dict[str, float | int | None]] = {}
    for split in SPLIT_NAMES:
        values = [float(row["yaw_offset"]) for row in rows if row["split"] == split]
        statistics[split] = {
            "count": len(values),
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "mean": sum(values) / len(values) if values else None,
        }
    return statistics


def _safe_relative_path(value: object) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"invalid relative path: {value}")
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"unsafe relative path: {value}")
    return path


def _read_capture_rows(csv_bytes: bytes, bundle: Path) -> list[dict[str, str]]:
    with io.StringIO(csv_bytes.decode("utf-8"), newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CAPTURE_CSV_COLUMNS:
            raise ValueError(f"invalid capture CSV header: {bundle}")
        return list(reader)


def build_yaw_dataset(
    output_root: Path,
    dataset_id: str,
    split_bundles: Mapping[str, Sequence[Path]],
    *,
    source_commit: str,
) -> Path:
    """Copy eligible rows from verified captures into one immutable dataset."""

    if not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError(f"invalid dataset ID: {dataset_id}")
    if not GIT_COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("source_commit must be a full lowercase 40-character Git SHA")
    unknown_splits = set(split_bundles) - set(SPLIT_NAMES)
    if unknown_splits:
        raise ValueError(f"unsupported dataset splits: {sorted(unknown_splits)}")
    if not any(split_bundles.get(split) for split in SPLIT_NAMES):
        raise ValueError("at least one capture bundle is required")

    output_root = output_root.expanduser().resolve()
    partial_path = output_root / f".{dataset_id}.partial"
    completed_path = output_root / dataset_id
    if partial_path.exists() or completed_path.exists():
        raise FileExistsError(f"dataset already exists: {dataset_id}")
    partial_path.mkdir(parents=True)

    try:
        seen_capture_ids: set[str] = set()
        source_captures: list[dict[str, Any]] = []
        output_rows: list[dict[str, str]] = []
        excluded_counts = {"diagnostic": 0}
        preprocessing: dict[str, Any] | None = None

        verified: list[tuple[str, str, Path, dict[str, Any]]] = []
        for split in SPLIT_NAMES:
            for source in split_bundles.get(split, ()):
                bundle = Path(source).expanduser().resolve()
                report = verify_yaw_capture_bundle(bundle)
                capture_id = report["capture_id"]
                if capture_id in seen_capture_ids:
                    raise ValueError(f"capture is assigned more than once: {capture_id}")
                seen_capture_ids.add(capture_id)
                verified.append((split, capture_id, bundle, report))

        for split, capture_id, bundle, report in sorted(
            verified, key=lambda item: (SPLIT_NAMES.index(item[0]), item[1])
        ):
            capture_preprocessing = report["preprocessing"]
            if preprocessing is None:
                preprocessing = capture_preprocessing
            elif preprocessing != capture_preprocessing:
                raise ValueError(f"preprocessing mismatch in capture: {capture_id}")

            manifest_bytes = (bundle / "manifest.json").read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != report["source_manifest_sha256"]:
                raise ValueError(f"capture changed after verification: {capture_id}")
            capture_manifest = json.loads(manifest_bytes)
            source_files = {entry["path"]: entry for entry in capture_manifest["files"]}
            csv_bytes = (bundle / "data_angles.csv").read_bytes()
            if hashlib.sha256(csv_bytes).hexdigest() != source_files["data_angles.csv"]["sha256"]:
                raise ValueError(f"capture CSV changed after verification: {capture_id}")
            calibration = capture_manifest["calibration"]
            calibration_id = str(calibration["calibration_id"])
            included_count = 0
            for row in _read_capture_rows(csv_bytes, bundle):
                if row["label_status"] != "human-aligned":
                    excluded_counts[row["label_status"]] = (
                        excluded_counts.get(row["label_status"], 0) + 1
                    )
                    continue
                source_filename = row["filename"]
                destination_relative = (
                    Path("images") / split / f"{capture_id}__{source_filename}"
                )
                destination = partial_path / destination_relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(bundle / "images" / source_filename, destination)
                source_image = source_files[f"images/{source_filename}"]
                if _sha256_file(destination) != source_image["sha256"]:
                    raise ValueError(f"capture image changed while copying: {capture_id}")
                output_rows.append(
                    {
                        "filename": destination_relative.as_posix(),
                        "source_capture_id": capture_id,
                        "source_filename": source_filename,
                        "captured_at_utc": row["captured_at_utc"],
                        "split": split,
                        "yaw_degrees": row["yaw_degrees"],
                        "aligned_yaw_degrees": row["aligned_yaw_degrees"],
                        "yaw_offset": row["yaw_offset"],
                        "pitch_degrees": row["pitch_degrees"],
                        "label_status": row["label_status"],
                        "calibration_id": calibration_id,
                    }
                )
                included_count += 1
            final_report = verify_yaw_capture_bundle(bundle)
            if final_report["source_manifest_sha256"] != report["source_manifest_sha256"]:
                raise ValueError(f"capture changed while building dataset: {capture_id}")
            source_captures.append(
                {
                    "capture_id": capture_id,
                    "split": split,
                    "source_manifest_sha256": report["source_manifest_sha256"],
                    "calibration_id": calibration_id,
                    "yaw_center_degrees": calibration["yaw_center_degrees"],
                    "aiming_reference": calibration["aiming_reference"],
                    "source_frame_count": report["frame_count"],
                    "included_frame_count": included_count,
                }
            )

        if not output_rows:
            raise ValueError("dataset contains no human-aligned frames")

        labels_path = partial_path / "labels.csv"
        with labels_path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=DATASET_CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(output_rows)

        files = []
        for path in sorted(partial_path.rglob("*")):
            if path.is_file():
                files.append(
                    {
                        "path": path.relative_to(partial_path).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                )
        frame_counts = {
            split: sum(row["split"] == split for row in output_rows) for split in SPLIT_NAMES
        }
        capture_ids = {
            split: [
                entry["capture_id"] for entry in source_captures if entry["split"] == split
            ]
            for split in SPLIT_NAMES
        }
        manifest = {
            "schema_version": DATASET_SCHEMA,
            "dataset_id": dataset_id,
            "created_at_utc": _iso_utc(),
            "builder": {
                "git_commit": source_commit,
                "package_version": _package_version(),
            },
            "preprocessing": preprocessing,
            "included_label_statuses": ["human-aligned"],
            "excluded_frame_counts": excluded_counts,
            "capture_ids": capture_ids,
            "frame_counts": frame_counts,
            "yaw_offset_statistics": _yaw_offset_statistics(output_rows),
            "source_captures": source_captures,
            "files": files,
        }
        (partial_path / "dataset_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        partial_path.rename(completed_path)
        return completed_path
    except Exception:
        shutil.rmtree(partial_path, ignore_errors=True)
        raise


def verify_yaw_dataset(dataset: Path) -> dict[str, Any]:
    """Verify one immutable dataset without needing the original capture folders."""

    dataset = dataset.expanduser().resolve()
    manifest_path = dataset / "dataset_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("dataset_manifest.json must be an ordinary file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != DATASET_SCHEMA:
        raise ValueError(f"unsupported dataset schema: {manifest.get('schema_version')}")
    dataset_id = manifest.get("dataset_id")
    if not isinstance(dataset_id, str) or not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError(f"invalid dataset ID: {dataset_id}")
    if dataset.name != dataset_id:
        raise ValueError("dataset directory and dataset ID differ")

    builder = manifest.get("builder")
    if not isinstance(builder, dict) or not GIT_COMMIT_PATTERN.fullmatch(
        str(builder.get("git_commit", ""))
    ):
        raise ValueError("dataset builder Git commit is invalid")
    created_at = datetime.fromisoformat(str(manifest["created_at_utc"]).replace("Z", "+00:00"))
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("dataset creation timestamp must include a timezone")
    if manifest.get("included_label_statuses") != ["human-aligned"]:
        raise ValueError("unsupported included label statuses")
    PreprocessingSpec.from_mapping(manifest.get("preprocessing", {}))

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("dataset manifest contains no files")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid dataset file entry")
        relative = _safe_relative_path(entry.get("path"))
        relative_name = relative.as_posix()
        if relative_name in expected:
            raise ValueError(f"duplicate dataset path: {relative_name}")
        expected.add(relative_name)
        path = dataset / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsupported dataset file: {relative_name}")
        if path.stat().st_size != entry.get("bytes"):
            raise ValueError(f"dataset size mismatch: {relative_name}")
        if _sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"dataset SHA-256 mismatch: {relative_name}")

    all_paths = list(dataset.rglob("*"))
    if any(path.is_symlink() for path in all_paths):
        raise ValueError("dataset contains a symbolic link")
    actual = {
        path.relative_to(dataset).as_posix()
        for path in all_paths
        if path.is_file() and path.relative_to(dataset).as_posix() != "dataset_manifest.json"
    }
    if actual != expected:
        raise ValueError("dataset files do not exactly match the manifest")

    source_entries = manifest.get("source_captures")
    if not isinstance(source_entries, list) or not source_entries:
        raise ValueError("dataset has no source captures")
    capture_to_split: dict[str, str] = {}
    capture_calibrations: dict[str, str] = {}
    for entry in source_entries:
        if not isinstance(entry, dict) or entry.get("split") not in SPLIT_NAMES:
            raise ValueError("invalid source capture entry")
        capture_id = str(entry.get("capture_id", ""))
        if not CAPTURE_ID_PATTERN.fullmatch(capture_id):
            raise ValueError(f"invalid source capture ID: {capture_id}")
        if capture_id in capture_to_split:
            raise ValueError(f"duplicate source capture: {capture_id}")
        manifest_sha = str(entry.get("source_manifest_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha):
            raise ValueError(f"invalid source manifest hash: {capture_id}")
        try:
            center = float(entry["yaw_center_degrees"])
            source_count = int(entry["source_frame_count"])
            included_count = int(entry["included_frame_count"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid source capture metadata: {capture_id}") from error
        if not math.isfinite(center) or not 0.0 <= center <= 180.0:
            raise ValueError(f"invalid yaw center: {capture_id}")
        if source_count < 1 or included_count < 0 or included_count > source_count:
            raise ValueError(f"invalid source capture counts: {capture_id}")
        if not str(entry.get("calibration_id", "")).strip():
            raise ValueError(f"missing calibration ID: {capture_id}")
        if not str(entry.get("aiming_reference", "")).strip():
            raise ValueError(f"missing aiming reference: {capture_id}")
        capture_to_split[capture_id] = entry["split"]
        capture_calibrations[capture_id] = str(entry["calibration_id"])

    labels_path = dataset / "labels.csv"
    with labels_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != DATASET_CSV_COLUMNS:
            raise ValueError(f"invalid dataset CSV header: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError("dataset contains no labels")
    filenames: set[str] = set()
    counted = {split: 0 for split in SPLIT_NAMES}
    included_by_capture = {capture_id: 0 for capture_id in capture_to_split}
    for row in rows:
        relative = _safe_relative_path(row["filename"])
        relative_name = relative.as_posix()
        if relative_name in filenames:
            raise ValueError(f"duplicate dataset filename: {relative_name}")
        filenames.add(relative_name)
        split = row["split"]
        capture_id = row["source_capture_id"]
        if capture_to_split.get(capture_id) != split:
            raise ValueError(f"capture split mismatch: {capture_id}")
        source_filename = _safe_relative_path(row["source_filename"])
        if len(source_filename.parts) != 1:
            raise ValueError(f"invalid source filename: {row['source_filename']}")
        expected_name = f"images/{split}/{capture_id}__{source_filename.as_posix()}"
        if relative_name != expected_name:
            raise ValueError(f"dataset image path does not match its lineage: {relative_name}")
        if row["label_status"] != "human-aligned":
            raise ValueError("dataset contains a non-training label")
        timestamp = datetime.fromisoformat(row["captured_at_utc"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("dataset timestamp must include a timezone")
        yaw = float(row["yaw_degrees"])
        aligned_yaw = float(row["aligned_yaw_degrees"])
        offset = float(row["yaw_offset"])
        pitch = float(row["pitch_degrees"])
        if not all(math.isfinite(value) for value in (yaw, aligned_yaw, offset, pitch)):
            raise ValueError("dataset contains a non-finite angle")
        if (
            not 0.0 <= yaw <= 180.0
            or not 0.0 <= aligned_yaw <= 180.0
            or not 0.0 <= pitch <= 180.0
        ):
            raise ValueError("dataset servo angle is outside 0..180 degrees")
        if abs(offset - (aligned_yaw - yaw)) > 0.0015:
            raise ValueError(f"yaw offset contract failed: {relative_name}")
        if row["calibration_id"] != capture_calibrations[capture_id]:
            raise ValueError(f"calibration ID mismatch: {capture_id}")
        counted[split] += 1
        included_by_capture[capture_id] += 1

    image_files = {path for path in expected if path.startswith("images/")}
    if filenames != image_files:
        raise ValueError("dataset labels and images do not match")
    if manifest.get("frame_counts") != counted:
        raise ValueError("dataset frame counts do not match labels")
    if manifest.get("yaw_offset_statistics") != _yaw_offset_statistics(rows):
        raise ValueError("dataset yaw statistics do not match labels")
    for entry in source_entries:
        if entry.get("included_frame_count") != included_by_capture[entry["capture_id"]]:
            raise ValueError(f"source capture count mismatch: {entry['capture_id']}")
    expected_capture_ids = {
        split: sorted(
            capture_id for capture_id, assigned in capture_to_split.items() if assigned == split
        )
        for split in SPLIT_NAMES
    }
    actual_capture_ids = {
        split: sorted(manifest.get("capture_ids", {}).get(split, [])) for split in SPLIT_NAMES
    }
    if actual_capture_ids != expected_capture_ids:
        raise ValueError("dataset capture ID lists do not match source entries")
    expected_excluded = {
        "diagnostic": sum(
            int(entry["source_frame_count"]) - int(entry["included_frame_count"])
            for entry in source_entries
        )
    }
    if manifest.get("excluded_frame_counts") != expected_excluded:
        raise ValueError("dataset excluded frame counts do not match source captures")
    if not str(builder.get("package_version", "")).strip():
        raise ValueError("dataset builder package version is missing")

    return {
        "schema_version": "rbg-yaw-dataset-report/v1",
        "dataset_id": dataset_id,
        "frame_counts": counted,
        "capture_counts": {
            split: len(expected_capture_ids[split]) for split in SPLIT_NAMES
        },
        "dataset_manifest_sha256": _sha256_file(manifest_path),
        "status": "passed",
    }

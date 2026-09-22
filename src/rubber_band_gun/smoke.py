"""Validation for non-training camera smoke-test bundles."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = "rbg-smoke/v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_bundle_path(bundle: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe manifest path: {relative_name}")
    return bundle / relative


def verify_smoke_bundle(bundle: Path) -> dict[str, object]:
    """Verify file names, sizes, and hashes in one completed smoke bundle."""

    bundle = bundle.resolve()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported smoke schema: {manifest.get('schema_version')}")
    capture_id = manifest.get("capture_id")
    if not isinstance(capture_id, str) or not re.fullmatch(
        r"smoke-\d{8}T\d{6}Z", capture_id
    ):
        raise ValueError(f"invalid capture ID: {capture_id}")

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest contains no files")

    expected_paths: set[str] = set()
    total_bytes = 0
    for entry in entries:
        relative_name = entry["path"]
        if relative_name in expected_paths:
            raise ValueError(f"duplicate manifest path: {relative_name}")
        expected_paths.add(relative_name)

        path = _safe_bundle_path(bundle, relative_name)
        if not path.is_file():
            raise ValueError(f"missing file: {relative_name}")
        size = path.stat().st_size
        if size != entry["bytes"]:
            raise ValueError(f"size mismatch: {relative_name}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {relative_name}")
        total_bytes += size

    if "frames.csv" not in expected_paths:
        raise ValueError("frames.csv is not covered by the manifest")
    actual_paths = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        raise ValueError("bundle files do not exactly match the manifest")

    with (bundle / "frames.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    frame_paths = {row["filename"] for row in rows}
    image_paths = {path for path in expected_paths if path.startswith("images/")}
    if frame_paths != image_paths:
        raise ValueError("frames.csv image names do not match the manifest")
    requested_frame_count = manifest.get("requested_frame_count")
    if requested_frame_count != len(rows):
        raise ValueError("captured frame count does not match the requested count")

    return {
        "schema_version": "rbg-smoke-report/v1",
        "capture_id": capture_id,
        "source_manifest_sha256": sha256_file(manifest_path),
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "frame_count": len(rows),
        "requested_frame_count": requested_frame_count,
        "verified_file_count": len(entries),
        "verified_bytes": total_bytes,
        "status": "passed",
    }

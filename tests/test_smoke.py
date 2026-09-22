import csv
import json
from pathlib import Path

import pytest

from rubber_band_gun.smoke import sha256_file, verify_smoke_bundle


def make_bundle(root: Path) -> Path:
    bundle = root / "smoke-20260922T000000Z"
    images = bundle / "images"
    images.mkdir(parents=True)
    image = images / "frame_000.jpg"
    image.write_bytes(b"not-a-real-jpeg-but-valid-for-contract-testing")
    frames = bundle / "frames.csv"
    with frames.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("filename", "captured_at_utc", "label_status")
        )
        writer.writeheader()
        writer.writerow(
            {
                "filename": "images/frame_000.jpg",
                "captured_at_utc": "2026-09-22T00:00:00+00:00",
                "label_status": "unlabeled-smoke-only",
            }
        )
    manifest = {
        "schema_version": "rbg-smoke/v1",
        "capture_id": "smoke-20260922T000000Z",
        "requested_frame_count": 1,
        "files": [
            {
                "path": path.relative_to(bundle).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (frames, image)
        ],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bundle


def test_verify_smoke_bundle(tmp_path: Path) -> None:
    report = verify_smoke_bundle(make_bundle(tmp_path))

    assert report["status"] == "passed"
    assert report["frame_count"] == 1
    assert report["requested_frame_count"] == 1
    assert report["verified_file_count"] == 2


def test_verify_smoke_bundle_rejects_changed_file(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    (bundle / "images/frame_000.jpg").write_bytes(b"changed")

    with pytest.raises(ValueError, match="size mismatch|SHA-256 mismatch"):
        verify_smoke_bundle(bundle)


def test_verify_smoke_bundle_rejects_unlisted_file(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    (bundle / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly match"):
        verify_smoke_bundle(bundle)

import json
from pathlib import Path

import numpy as np
import pytest

from rubber_band_gun.no_target import NoTargetCaptureSession, verify_no_target_bundle
from rubber_band_gun.preprocessing import PreprocessingSpec


def _bundle(tmp_path: Path) -> Path:
    session = NoTargetCaptureSession(
        tmp_path,
        PreprocessingSpec(),
        capture_id="no-target-20260926T000000Z",
    )
    session.add_frame(np.zeros((8, 12, 3), dtype=np.uint8))
    session.add_frame(np.ones((8, 12, 3), dtype=np.uint8))
    return session.finalize()


def test_no_target_bundle_round_trip(tmp_path: Path) -> None:
    report = verify_no_target_bundle(_bundle(tmp_path))

    assert report["capture_id"] == "no-target-20260926T000000Z"
    assert len(report["image_paths"]) == 2
    assert report["status"] == "passed"


def test_no_target_bundle_rejects_changed_file(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "images/frame_000000.jpg").write_bytes(b"changed")

    with pytest.raises(ValueError, match="integrity failed"):
        verify_no_target_bundle(bundle)


def test_no_target_bundle_rejects_positive_label(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    cases = bundle / "cases.csv"
    text = cases.read_text(encoding="utf-8").replace("false", "true", 1)
    cases.write_text(text, encoding="utf-8")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["path"] == "cases.csv")
    import hashlib

    entry["bytes"] = cases.stat().st_size
    entry["sha256"] = hashlib.sha256(cases.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="target-positive"):
        verify_no_target_bundle(bundle)

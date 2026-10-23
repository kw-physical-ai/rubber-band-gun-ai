import hashlib
import json
from pathlib import Path

import pytest

from rubber_band_gun.model_manifest import verify_model_manifest
from rubber_band_gun.preprocessing import PreprocessingSpec


def _manifest(tmp_path: Path) -> Path:
    artifact = tmp_path / "yaw.pth"
    artifact.write_bytes(b"model")
    manifest = {
        "schema_version": "rbg-model-manifest/v1",
        "model_id": "model-yaw-v1",
        "model_kind": "yaw-regressor",
        "artifact": artifact.name,
        "sha256": hashlib.sha256(b"model").hexdigest(),
        "source": {"run_id": "run-yaw-v1", "git_commit": "a" * 40},
        "preprocessing": PreprocessingSpec().to_manifest(),
        "metrics": {"yaw_mae_degrees": 1.0},
        "approval": {
            "approved_by": "reviewer",
            "approved_at_utc": "2026-09-26T00:00:00+00:00",
        },
    }
    path = tmp_path / "yaw.pth.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_verify_model_manifest(tmp_path: Path) -> None:
    report = verify_model_manifest(_manifest(tmp_path))

    assert report["model_id"] == "model-yaw-v1"
    assert report["status"] == "passed"


def test_verify_model_manifest_rejects_changed_artifact(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    (tmp_path / "yaw.pth").write_bytes(b"changed")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_model_manifest(path)

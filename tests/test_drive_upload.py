import hashlib
import json
import os
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_SCRIPT = REPOSITORY_ROOT / "scripts" / "pi" / "upload-drive-bundle.sh"


def _make_bundle(
    root: Path,
    capture_id: str = "smoke-20260922T123456Z",
    *,
    identity_key: str = "capture_id",
) -> Path:
    bundle = root / capture_id
    bundle.mkdir()
    payload = b"camera-frame-placeholder"
    (bundle / "frame.jpg").write_bytes(payload)
    manifest = {
        identity_key: capture_id,
        "files": [
            {
                "path": "frame.jpg",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bundle


def _fake_rclone(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    log_path = tmp_path / "rclone.log"
    binary = binary_dir / "rclone"
    binary.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$RCLONE_TEST_LOG"\n')
    binary.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{binary_dir}:{environment['PATH']}"
    environment["RCLONE_TEST_LOG"] = str(log_path)
    return log_path, environment


def test_upload_checks_bundle_and_publishes_manifest_last(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    log_path, environment = _fake_rclone(tmp_path)

    result = subprocess.run(
        ["bash", str(UPLOAD_SCRIPT), str(bundle), "project-drive:smoke"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert calls[0].startswith("copy ")
    assert calls[1].startswith("check ")
    assert calls[2].startswith("check ")
    assert calls[3].startswith("copyto ")
    expected_manifest_target = f"project-drive:smoke/{bundle.name}/manifest.json"
    assert calls[3].endswith(f"{expected_manifest_target} --immutable --checksum --progress")
    assert calls[4].startswith("check ")
    assert "--exclude /manifest.json" in calls[4]
    assert calls[5].startswith("check ")
    assert "--include /manifest.json" in calls[5]
    assert "Drive upload verified" in result.stdout


def test_upload_rejects_files_missing_from_manifest(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    (bundle / "unexpected.txt").write_text("not declared", encoding="utf-8")
    log_path, environment = _fake_rclone(tmp_path)

    result = subprocess.run(
        ["bash", str(UPLOAD_SCRIPT), str(bundle), "project-drive:smoke"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert "bundle files do not exactly match the manifest" in result.stderr
    assert not log_path.exists()


def test_upload_rejects_nested_manifest_named_file(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    nested = bundle / "unexpected" / "manifest.json"
    nested.parent.mkdir()
    nested.write_text("not declared", encoding="utf-8")
    log_path, environment = _fake_rclone(tmp_path)

    result = subprocess.run(
        ["bash", str(UPLOAD_SCRIPT), str(bundle), "project-drive:smoke"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert "bundle files do not exactly match the manifest" in result.stderr
    assert not log_path.exists()


def test_upload_rejects_destination_outside_ingress(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    log_path, environment = _fake_rclone(tmp_path)

    result = subprocess.run(
        ["bash", str(UPLOAD_SCRIPT), str(bundle), "project-drive:runs"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert (
        "destination must be project-drive:raw, project-drive:smoke, or "
        "project-drive:evaluation"
    ) in result.stderr
    assert not log_path.exists()


def test_upload_accepts_evaluation_ingress(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    log_path, environment = _fake_rclone(tmp_path)

    result = subprocess.run(
        ["bash", str(UPLOAD_SCRIPT), str(bundle), "project-drive:evaluation"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "project-drive:evaluation" in log_path.read_text(encoding="utf-8")


def test_upload_accepts_shot_run_identity(tmp_path: Path) -> None:
    bundle = _make_bundle(
        tmp_path,
        "shot-run-20260927T010203Z-test",
        identity_key="run_id",
    )
    log_path, environment = _fake_rclone(tmp_path)

    result = subprocess.run(
        ["bash", str(UPLOAD_SCRIPT), str(bundle), "project-drive:evaluation"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert f"project-drive:evaluation/{bundle.name}" in log_path.read_text(encoding="utf-8")

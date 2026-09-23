import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

import rubber_band_gun.dataset as dataset_module
from rubber_band_gun import (
    CaptureCalibration,
    PreprocessingSpec,
    YawCaptureSession,
    build_yaw_dataset,
    verify_yaw_dataset,
)

COMMIT = "a" * 40


def _capture(
    root: Path,
    capture_id: str,
    *,
    labels: tuple[str, ...] = ("human-aligned",),
    crop_bottom_ratio: float = 0.2,
) -> Path:
    session = YawCaptureSession(
        root,
        PreprocessingSpec(crop_bottom_ratio=crop_bottom_ratio),
        CaptureCalibration(50.0, "bench-v1", "camera reticle center"),
        capture_id=capture_id,
    )
    for index, label in enumerate(labels):
        session.add_frame(
            np.full((8, 12, 3), index, dtype=np.uint8),
            yaw_degrees=50 + index,
            pitch_degrees=90,
            captured_at=datetime(2026, 9, 23, 0, 0, index, tzinfo=UTC),
            label_status=label,
        )
    return session.finalize()


def test_dataset_round_trip_keeps_capture_splits_and_lineage(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    train = _capture(
        raw,
        "capture-20260923T000000Z",
        labels=("human-aligned", "diagnostic"),
    )
    validation = _capture(raw, "capture-20260923T000100Z")

    dataset = build_yaw_dataset(
        tmp_path / "processed",
        "dataset-course-v1",
        {"train": [train], "validation": [validation]},
        source_commit=COMMIT,
    )
    report = verify_yaw_dataset(dataset)

    assert report["status"] == "passed"
    assert report["frame_counts"] == {"train": 1, "validation": 1, "locked-test": 0}
    manifest = json.loads((dataset / "dataset_manifest.json").read_text())
    assert manifest["excluded_frame_counts"] == {"diagnostic": 1}
    assert manifest["capture_ids"] == {
        "train": ["capture-20260923T000000Z"],
        "validation": ["capture-20260923T000100Z"],
        "locked-test": [],
    }
    assert manifest["source_captures"][0]["yaw_center_degrees"] == 50.0
    assert manifest["source_captures"][0]["aiming_reference"] == "camera reticle center"
    assert manifest["yaw_offset_statistics"]["train"] == {
        "count": 1,
        "minimum": 0.0,
        "maximum": 0.0,
        "mean": 0.0,
    }
    with (dataset / "labels.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["source_capture_id"] == "capture-20260923T000000Z"
    assert rows[0]["filename"].startswith("images/train/capture-20260923T000000Z__")


def test_dataset_rejects_capture_in_multiple_splits(tmp_path: Path) -> None:
    capture = _capture(tmp_path / "raw", "capture-20260923T000000Z")

    with pytest.raises(ValueError, match="assigned more than once"):
        build_yaw_dataset(
            tmp_path / "processed",
            "dataset-duplicate",
            {"train": [capture], "validation": [capture]},
            source_commit=COMMIT,
        )


def test_dataset_rejects_preprocessing_mismatch(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    first = _capture(raw, "capture-20260923T000000Z", crop_bottom_ratio=0.2)
    second = _capture(raw, "capture-20260923T000100Z", crop_bottom_ratio=0.25)

    with pytest.raises(ValueError, match="preprocessing mismatch"):
        build_yaw_dataset(
            tmp_path / "processed",
            "dataset-mismatch",
            {"train": [first], "validation": [second]},
            source_commit=COMMIT,
        )


def test_dataset_verifier_rejects_changed_label(tmp_path: Path) -> None:
    capture = _capture(tmp_path / "raw", "capture-20260923T000000Z")
    dataset = build_yaw_dataset(
        tmp_path / "processed",
        "dataset-tampered",
        {"validation": [capture]},
        source_commit=COMMIT,
    )
    labels = dataset / "labels.csv"
    labels.write_text(labels.read_text().replace("0.000", "9.000", 1))

    with pytest.raises(ValueError, match="size mismatch|SHA-256 mismatch"):
        verify_yaw_dataset(dataset)


def test_dataset_verifier_rejects_unlisted_nested_manifest(tmp_path: Path) -> None:
    capture = _capture(tmp_path / "raw", "capture-20260923T000000Z")
    dataset = build_yaw_dataset(
        tmp_path / "processed",
        "dataset-extra-file",
        {"validation": [capture]},
        source_commit=COMMIT,
    )
    extra = dataset / "images" / "validation" / "dataset_manifest.json"
    extra.write_text("{}\n")

    with pytest.raises(ValueError, match="exactly match"):
        verify_yaw_dataset(dataset)


def test_dataset_verifier_rejects_false_exclusion_count(tmp_path: Path) -> None:
    capture = _capture(tmp_path / "raw", "capture-20260923T000000Z")
    dataset = build_yaw_dataset(
        tmp_path / "processed",
        "dataset-false-count",
        {"validation": [capture]},
        source_commit=COMMIT,
    )
    manifest_path = dataset / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["excluded_frame_counts"]["diagnostic"] = 10
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="excluded frame counts"):
        verify_yaw_dataset(dataset)


def test_dataset_requires_human_aligned_frame(tmp_path: Path) -> None:
    capture = _capture(
        tmp_path / "raw",
        "capture-20260923T000000Z",
        labels=("diagnostic",),
    )

    with pytest.raises(ValueError, match="no human-aligned"):
        build_yaw_dataset(
            tmp_path / "processed",
            "dataset-empty",
            {"validation": [capture]},
            source_commit=COMMIT,
        )


def test_dataset_rejects_capture_changed_after_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _capture(tmp_path / "raw", "capture-20260923T000000Z")
    original_verify = dataset_module.verify_yaw_capture_bundle
    call_count = 0

    def verify_then_mutate(bundle: Path) -> dict[str, object]:
        nonlocal call_count
        report = original_verify(bundle)
        call_count += 1
        if call_count == 1:
            manifest_path = bundle / "manifest.json"
            manifest_path.write_text(manifest_path.read_text() + " ")
        return report

    monkeypatch.setattr(dataset_module, "verify_yaw_capture_bundle", verify_then_mutate)
    with pytest.raises(ValueError, match="changed after verification"):
        build_yaw_dataset(
            tmp_path / "processed",
            "dataset-source-race",
            {"validation": [capture]},
            source_commit=COMMIT,
        )

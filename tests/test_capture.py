import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from rubber_band_gun.capture import (
    CSV_COLUMNS,
    CaptureCalibration,
    YawCaptureSession,
    verify_yaw_capture_bundle,
)
from rubber_band_gun.preprocessing import PreprocessingSpec

CAPTURE_ID = "capture-20260923T000000Z"


def _build_capture(tmp_path: Path) -> Path:
    session = YawCaptureSession(
        tmp_path,
        PreprocessingSpec(crop_bottom_ratio=0.25, model_width=32, model_height=32),
        CaptureCalibration(
            yaw_center_degrees=50.0,
            calibration_id="bench-v1",
            aiming_reference="camera reticle center",
        ),
        capture_id=CAPTURE_ID,
    )
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    frame[:, :, 0] = 255
    session.add_frame(
        frame,
        yaw_degrees=53.0,
        aligned_yaw_degrees=50.0,
        pitch_degrees=90.0,
        captured_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    return session.finalize()


def test_capture_bundle_round_trip(tmp_path: Path) -> None:
    bundle = _build_capture(tmp_path)

    report = verify_yaw_capture_bundle(bundle)

    assert report["status"] == "passed"
    assert report["capture_id"] == CAPTURE_ID
    assert report["frame_count"] == 1
    assert report["calibration_id"] == "bench-v1"

    with (bundle / "data_angles.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        row = next(reader)
    assert tuple(reader.fieldnames or ()) == CSV_COLUMNS
    assert row["filename"] == "frame_000000.jpg"
    assert row["aligned_yaw_degrees"] == "50.000"
    assert row["yaw_offset"] == "-3.000"

    stored = cv2.imread(str(bundle / "images" / row["filename"]))
    assert stored.shape[:2] == (45, 40)


def test_capture_manifest_records_shared_preprocessing(tmp_path: Path) -> None:
    bundle = _build_capture(tmp_path)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["preprocessing"]["crop_bottom_ratio"] == 0.25
    assert manifest["preprocessing"]["rotation"] == "clockwise_90"
    assert manifest["label_contract"] == "yaw_offset = aligned_yaw_degrees - yaw_degrees"
    assert (manifest["stored_frame_height"], manifest["stored_frame_width"]) == (45, 40)
    assert manifest["calibration"]["aiming_reference"] == "camera reticle center"


def test_capture_labels_correction_back_to_alignment_on_both_sides(tmp_path: Path) -> None:
    session = YawCaptureSession(
        tmp_path,
        PreprocessingSpec(),
        CaptureCalibration(50.0, "bench-v1", "camera reticle center"),
        capture_id=CAPTURE_ID,
    )
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    session.add_frame(
        frame,
        yaw_degrees=47,
        aligned_yaw_degrees=50,
        pitch_degrees=90,
    )
    session.add_frame(
        frame,
        yaw_degrees=53,
        aligned_yaw_degrees=50,
        pitch_degrees=90,
    )
    bundle = session.finalize()

    with (bundle / "data_angles.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    assert [row["yaw_offset"] for row in rows] == ["3.000", "-3.000"]


def test_capture_verifier_rejects_changed_label(tmp_path: Path) -> None:
    bundle = _build_capture(tmp_path)
    csv_path = bundle / "data_angles.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8").replace("-3.000", "9.000"))

    with pytest.raises(ValueError, match="size mismatch|SHA-256 mismatch"):
        verify_yaw_capture_bundle(bundle)


def test_capture_cannot_finalize_empty_session(tmp_path: Path) -> None:
    session = YawCaptureSession(
        tmp_path,
        PreprocessingSpec(),
        CaptureCalibration(
            yaw_center_degrees=50.0,
            calibration_id="bench-v1",
            aiming_reference="camera reticle center",
        ),
        capture_id=CAPTURE_ID,
    )

    with pytest.raises(ValueError, match="empty"):
        session.finalize()


@pytest.mark.parametrize("angle", [float("nan"), -1.0, 181.0])
def test_capture_rejects_invalid_servo_angles(tmp_path: Path, angle: float) -> None:
    session = YawCaptureSession(
        tmp_path,
        PreprocessingSpec(),
        CaptureCalibration(
            yaw_center_degrees=50.0,
            calibration_id="bench-v1",
            aiming_reference="camera reticle center",
        ),
        capture_id=CAPTURE_ID,
    )

    with pytest.raises(ValueError, match="yaw_degrees"):
        session.add_frame(
            np.zeros((4, 6, 3), dtype=np.uint8),
            yaw_degrees=angle,
            aligned_yaw_degrees=50.0,
            pitch_degrees=90.0,
        )


def test_capture_rejects_frame_geometry_change(tmp_path: Path) -> None:
    session = YawCaptureSession(
        tmp_path,
        PreprocessingSpec(),
        CaptureCalibration(
            yaw_center_degrees=50.0,
            calibration_id="bench-v1",
            aiming_reference="camera reticle center",
        ),
        capture_id=CAPTURE_ID,
    )
    session.add_frame(
        np.zeros((4, 6, 3), dtype=np.uint8),
        yaw_degrees=50,
        aligned_yaw_degrees=50,
        pitch_degrees=90,
    )

    with pytest.raises(ValueError, match="frame shape changed"):
        session.add_frame(
            np.zeros((6, 8, 3), dtype=np.uint8),
            yaw_degrees=50,
            aligned_yaw_degrees=50,
            pitch_degrees=90,
        )


@pytest.mark.parametrize("angle", [float("nan"), -1.0, 181.0])
def test_capture_rejects_invalid_aligned_yaw(tmp_path: Path, angle: float) -> None:
    session = YawCaptureSession(
        tmp_path,
        PreprocessingSpec(),
        CaptureCalibration(
            yaw_center_degrees=50.0,
            calibration_id="bench-v1",
            aiming_reference="camera reticle center",
        ),
        capture_id=CAPTURE_ID,
    )

    with pytest.raises(ValueError, match="aligned_yaw_degrees"):
        session.add_frame(
            np.zeros((4, 6, 3), dtype=np.uint8),
            yaw_degrees=50,
            aligned_yaw_degrees=angle,
            pitch_degrees=90,
        )

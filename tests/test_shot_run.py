import csv
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from rubber_band_gun.preprocessing import PreprocessingSpec, orient_and_crop_rgb
from rubber_band_gun.shot_run import (
    SHOT_RUN_COLUMNS,
    ArtifactReference,
    ShotRunSession,
    verify_shot_run,
)


def _logger_module():
    path = Path(__file__).parents[1] / "scripts/pi/log-shot-run.py"
    spec = importlib.util.spec_from_file_location("log_shot_run", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

RUN_ID = "shot-run-20260927T010203Z-test"
CAPTURED_AT = datetime(2026, 9, 27, 1, 2, 3, tzinfo=UTC)
ACKNOWLEDGED_AT = CAPTURED_AT + timedelta(seconds=2)


def _frame(seed: int = 0) -> np.ndarray:
    return (np.arange(8 * 12 * 3, dtype=np.uint8).reshape(8, 12, 3) + seed).astype(
        np.uint8
    )


def _session(tmp_path: Path, **kwargs: object) -> ShotRunSession:
    return ShotRunSession(
        tmp_path,
        PreprocessingSpec(crop_bottom_ratio=0.25),
        target_coordinate_system="origin=center, +x=right, +y=up",
        run_id=RUN_ID,
        created_at=CAPTURED_AT - timedelta(seconds=1),
        **kwargs,
    )


def _bundle(tmp_path: Path, *, post: bool = True) -> Path:
    session = _session(tmp_path)
    session.begin_shot(
        _frame(),
        target_distance_m=2.5,
        commanded_yaw_degrees=52.0,
        commanded_pitch_degrees=91.0,
        predicted_yaw_offset_degrees=-1.25,
        captured_at=CAPTURED_AT,
    )
    session.complete_shot(
        outcome="miss",
        external_event_acknowledged_at=ACKNOWLEDGED_AT,
        impact_x_mm=-4.5,
        impact_y_mm=8.0,
        post_event_rgb=_frame(1) if post else None,
        post_event_captured_at=ACKNOWLEDGED_AT if post else None,
        notes="human reviewed",
        outcome_recorded_at=ACKNOWLEDGED_AT + timedelta(seconds=1),
    )
    return session.finalize()


def _rehash(bundle: Path, relative: str) -> None:
    path = bundle / relative
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["path"] == relative)
    entry["bytes"] = path.stat().st_size
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_shot_run_round_trip_preserves_canonical_pre_event_pixels(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    report = verify_shot_run(bundle)
    stored_bgr = cv2.imread(
        str(bundle / "evidence/shot-000001/pre.png"), cv2.IMREAD_COLOR
    )
    stored_rgb = cv2.cvtColor(stored_bgr, cv2.COLOR_BGR2RGB)

    assert report["status"] == "passed"
    assert report["shot_count"] == 1
    assert report["outcomes"] == {"hit": 0, "miss": 1, "invalid": 0}
    assert np.array_equal(
        stored_rgb,
        orient_and_crop_rgb(_frame(), PreprocessingSpec(crop_bottom_ratio=0.25)),
    )


def test_manifest_binds_preprocessing_and_external_references(tmp_path: Path) -> None:
    calibration_file = tmp_path / "calibration.json"
    calibration_file.write_text('{"id":"cal-7"}\n', encoding="utf-8")
    model_file = tmp_path / "yaw.pth"
    model_file.write_bytes(b"model bytes")
    session = _session(
        tmp_path,
        calibration_id="cal-7",
        calibration_reference=ArtifactReference.from_path("calibration", calibration_file),
        model_references=(ArtifactReference.from_path("yaw-v3", model_file),),
    )
    session.begin_shot(
        _frame(),
        target_distance_m=1.0,
        commanded_yaw_degrees=50,
        commanded_pitch_degrees=90,
        captured_at=CAPTURED_AT,
    )
    session.complete_shot(
        outcome="hit",
        external_event_acknowledged_at=ACKNOWLEDGED_AT,
        outcome_recorded_at=ACKNOWLEDGED_AT,
    )
    bundle = session.finalize()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manual_axis_control"] == {
        "enabled": True,
        "axes": ["yaw", "pitch"],
        "origin": "local_keyboard",
        "automatic_aiming": False,
    }
    assert manifest["external_event_only"] is True
    assert manifest["calibration"]["calibration_id"] == "cal-7"
    assert manifest["calibration"]["reference"]["sha256"] == hashlib.sha256(
        calibration_file.read_bytes()
    ).hexdigest()
    assert manifest["model_references"][0]["reference_id"] == "yaw-v3"
    assert manifest["preprocessing"]["crop_bottom_ratio"] == 0.25
    assert verify_shot_run(bundle)["status"] == "passed"


def test_shot_results_use_stable_columns_and_optional_fields(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, post=False)

    with (bundle / "shot_results.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        row = next(reader)

    assert tuple(reader.fieldnames or ()) == SHOT_RUN_COLUMNS
    assert row["pre_event_frame"] == "evidence/shot-000001/pre.png"
    assert row["post_event_evidence"] == ""
    assert row["post_event_captured_at_utc"] == ""
    assert row["impact_x_mm"] == "-4.5"


def test_shot_run_rejects_partial_impact_coordinates(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin_shot(
        _frame(),
        target_distance_m=1,
        commanded_yaw_degrees=50,
        commanded_pitch_degrees=90,
        captured_at=CAPTURED_AT,
    )

    with pytest.raises(ValueError, match="both be present"):
        session.complete_shot(
            outcome="miss",
            external_event_acknowledged_at=ACKNOWLEDGED_AT,
            impact_x_mm=2,
        )


def test_shot_run_cannot_finalize_before_outcome(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin_shot(
        _frame(),
        target_distance_m=1,
        commanded_yaw_degrees=50,
        commanded_pitch_degrees=90,
        captured_at=CAPTURED_AT,
    )

    with pytest.raises(RuntimeError, match="needs an outcome"):
        session.finalize()


def test_shot_run_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    _bundle(tmp_path)

    with pytest.raises(FileExistsError, match="already exists"):
        _session(tmp_path)


def test_verifier_rejects_tampered_evidence(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "evidence/shot-000001/pre.png").write_bytes(b"changed")

    with pytest.raises(ValueError, match="integrity failed"):
        verify_shot_run(bundle)


def test_verifier_rejects_unmanifested_file(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly match"):
        verify_shot_run(bundle)


def test_verifier_rejects_nested_file_named_manifest(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "evidence/manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly match"):
        verify_shot_run(bundle)


def test_verifier_rejects_invalid_chronology_even_with_valid_hash(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    csv_path = bundle / "shot_results.csv"
    text = csv_path.read_text(encoding="utf-8")
    text = text.replace(
        ACKNOWLEDGED_AT.isoformat(),
        (CAPTURED_AT - timedelta(seconds=1)).isoformat(),
        1,
    )
    csv_path.write_text(text, encoding="utf-8")
    _rehash(bundle, "shot_results.csv")

    with pytest.raises(ValueError, match="chronology"):
        verify_shot_run(bundle)


def test_verifier_rejects_shot_outside_run_interval(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    csv_path = bundle / "shot_results.csv"
    text = csv_path.read_text(encoding="utf-8")
    text = text.replace(CAPTURED_AT.isoformat(), "2000-01-01T00:00:00+00:00", 1)
    csv_path.write_text(text, encoding="utf-8")
    _rehash(bundle, "shot_results.csv")

    with pytest.raises(ValueError, match="outside run chronology"):
        verify_shot_run(bundle)


def test_reference_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "model.bin"
    target.write_bytes(b"model")
    link = tmp_path / "model-link.bin"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="ordinary file"):
        ArtifactReference.from_path("model", link)


def test_interrupted_attempt_keeps_frame_and_commanded_axes(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin_shot(
        _frame(),
        target_distance_m=2.5,
        commanded_yaw_degrees=52.0,
        commanded_pitch_degrees=91.0,
        captured_at=CAPTURED_AT,
    )

    attempt_dir = session.partial_path / "evidence/shot-000001"
    attempt = json.loads((attempt_dir / "attempt.json").read_text(encoding="utf-8"))
    assert (attempt_dir / "pre.png").is_file()
    assert attempt["status"] == "pre-event-stored"
    assert attempt["commanded_yaw_degrees"] == 52.0
    assert attempt["commanded_pitch_degrees"] == 91.0


def test_completed_trial_is_durable_before_bundle_finalization(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin_shot(
        _frame(),
        target_distance_m=2.5,
        commanded_yaw_degrees=52.0,
        commanded_pitch_degrees=91.0,
        captured_at=CAPTURED_AT,
    )
    session.complete_shot(
        outcome="invalid",
        external_event_acknowledged_at=ACKNOWLEDGED_AT,
        notes="operator interrupted after recording",
        outcome_recorded_at=ACKNOWLEDGED_AT,
    )

    attempt_path = session.partial_path / "evidence/shot-000001/attempt.json"
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    assert attempt["status"] == "completed"
    assert attempt["row"]["outcome"] == "invalid"
    assert attempt["row"]["commanded_yaw_degrees"] == "52.0"


def test_logger_cli_uses_configured_axis_centers_instead_of_fixed_commands() -> None:
    logger = _logger_module()

    args = logger._parse_args(["--config", "pi.toml", "--target-distance-m", "2"])

    assert not hasattr(args, "commanded_yaw_degrees")
    assert not hasattr(args, "commanded_pitch_degrees")


def test_logger_accepts_only_calibrated_yaw_and_pitch_configuration() -> None:
    logger = _logger_module()
    settings = {
        "hardware": {
            "calibrated": True,
            "calibration_id": "cal-1",
            "aiming_reference": "fixed-mark",
        },
        "servo": {
            "yaw": {
                "pin": 18,
                "center_degrees": 50,
                "min_degrees": 40,
                "max_degrees": 60,
                "step_degrees": 2,
            },
            "pitch": {
                "pin": 13,
                "center_degrees": 90,
                "min_degrees": 80,
                "max_degrees": 100,
                "step_degrees": 2,
            },
        },
    }

    yaw, pitch = logger._validated_hardware(settings)
    assert (yaw.center, pitch.center) == (50, 90)
    settings["servo"]["extra"] = settings["servo"]["yaw"]
    with pytest.raises(ValueError, match="exactly yaw and pitch"):
        logger._validated_hardware(settings)


def test_logger_source_limits_actuation_to_manual_yaw_and_pitch() -> None:
    source = (Path(__file__).parents[1] / "scripts/pi/log-shot-run.py").read_text(
        encoding="utf-8"
    )

    forbidden = ("FIRE_PIN", "trigger_pin", "update_fire_button", "automatic_aim")
    assert not any(value in source for value in forbidden)
    assert 'set(servo) != {"yaw", "pitch"}' in source
    assert "set_servo_pulsewidth(config.pin, pulse)" in source
    assert "ord(\"a\")" in source and "ord(\"d\")" in source
    assert "ord(\"w\")" in source and "ord(\"s\")" in source
    assert "camera.capture_array()" in source
    assert "picamera2_rgb888_to_rgb(camera.capture_array())" in source

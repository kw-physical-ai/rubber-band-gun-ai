import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from rubber_band_gun.evaluation import (
    BaselineCase,
    BaselineThresholds,
    Detection,
    evaluate_cases,
    load_target_annotations,
    rectangle_mask,
    verify_baseline_run,
    write_baseline_run,
)
from rubber_band_gun.preprocessing import PreprocessingSpec


class Detector:
    def detect(self, model_rgb: np.ndarray) -> Detection | None:
        if int(model_rgb.mean()) < 10:
            return None
        return Detection((1, 1, 4, 4), 0.9)


class Regressor:
    def predict(self, mask: np.ndarray) -> float:
        assert mask.dtype == np.uint8
        return 2.5


def _image(path: Path, value: int) -> Path:
    image = np.full((8, 12, 3), value, dtype=np.uint8)
    assert cv2.imwrite(str(path), image)
    return path


def test_rectangle_mask_clips_and_fills_box() -> None:
    mask = rectangle_mask(Detection((1, 2, 7, 9), 0.8), width=6, height=5)

    assert mask.shape == (5, 6)
    assert mask[2:, 1:].all()
    assert not mask[:2].any()


def test_evaluate_cases_measures_detection_and_yaw(tmp_path: Path) -> None:
    cases = [
        BaselineCase(
            "target",
            _image(tmp_path / "target.jpg", 255),
            True,
            2.0,
            "test",
            True,
            (1, 1, 4, 4),
        ),
        BaselineCase("empty", _image(tmp_path / "empty.jpg", 0), False, None, "test", False),
    ]

    rows, metrics = evaluate_cases(
        cases,
        Detector(),
        Regressor(),
        PreprocessingSpec(model_width=6, model_height=5),
    )

    assert len(rows) == 2
    assert metrics["target_recall"] == 1.0
    assert metrics["target_detection_rate"] == 1.0
    assert metrics["no_target_false_positive_rate"] == 0.0
    assert metrics["yaw_mae_degrees"] == 0.5
    assert metrics["yaw_bias_degrees"] == 0.5


def test_baseline_case_keeps_target_and_label_consistent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="target cases require"):
        BaselineCase("bad", tmp_path / "image.jpg", False, 1.0, "test", True)


def test_write_and_verify_baseline_run(tmp_path: Path) -> None:
    target = _image(tmp_path / "target.jpg", 255)
    empty = _image(tmp_path / "empty.jpg", 0)
    cases = [
        BaselineCase("target", target, True, 2.0, "test", True, (1, 1, 4, 4)),
        BaselineCase("empty", empty, False, None, "test", False),
    ]
    rows, metrics = evaluate_cases(
        cases,
        Detector(),
        Regressor(),
        PreprocessingSpec(model_width=6, model_height=5),
    )
    dataset_manifest = tmp_path / "dataset_manifest.json"
    dataset_manifest.write_text("{}", encoding="utf-8")
    yolo_model = tmp_path / "yolo.pt"
    yolo_model.write_bytes(b"yolo")
    yaw_model = tmp_path / "yaw.pth"
    yaw_model.write_bytes(b"yaw")

    run = write_baseline_run(
        tmp_path / "runs",
        "run-baseline-v1",
        cases=cases,
        predictions=rows,
        metrics=metrics,
        thresholds=BaselineThresholds(0.9, 0.1, 1.0),
        preprocessing=PreprocessingSpec(model_width=6, model_height=5),
        source_commit="a" * 40,
        dataset_manifest=dataset_manifest,
        yolo_model=yolo_model,
        yaw_model=yaw_model,
    )

    report = verify_baseline_run(run)
    assert report["status"] == "passed"
    assert report["prediction_count"] == 2
    with (run / "predictions.csv").open(newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == 2

    (run / "metrics.json").write_text(json.dumps({"changed": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_baseline_run(run)


def test_missing_no_target_cases_make_run_incomplete(tmp_path: Path) -> None:
    target = _image(tmp_path / "target.jpg", 255)
    cases = [BaselineCase("target", target, True, 2.0, "test", True, (1, 1, 4, 4))]
    rows, metrics = evaluate_cases(
        cases,
        Detector(),
        Regressor(),
        PreprocessingSpec(model_width=6, model_height=5),
    )
    dataset_manifest = tmp_path / "dataset_manifest.json"
    dataset_manifest.write_text("{}", encoding="utf-8")
    yolo_model = tmp_path / "yolo.pt"
    yolo_model.write_bytes(b"yolo")
    yaw_model = tmp_path / "yaw.pth"
    yaw_model.write_bytes(b"yaw")

    run = write_baseline_run(
        tmp_path / "runs",
        "run-incomplete",
        cases=cases,
        predictions=rows,
        metrics=metrics,
        thresholds=BaselineThresholds(0.9, 0.1, 1.0),
        preprocessing=PreprocessingSpec(model_width=6, model_height=5),
        source_commit="b" * 40,
        dataset_manifest=dataset_manifest,
        yolo_model=yolo_model,
        yaw_model=yaw_model,
    )

    assert verify_baseline_run(run)["status"] == "incomplete"


def test_locked_test_run_requires_approval(tmp_path: Path) -> None:
    target = _image(tmp_path / "target.jpg", 255)
    case = BaselineCase("target", target, True, 2.0, "test", True, (1, 1, 4, 4))
    rows, metrics = evaluate_cases(
        [case], Detector(), Regressor(), PreprocessingSpec(model_width=6, model_height=5)
    )
    dataset_manifest = tmp_path / "dataset_manifest.json"
    dataset_manifest.write_text("{}", encoding="utf-8")
    yolo_model = tmp_path / "yolo.pt"
    yolo_model.write_bytes(b"yolo")
    yaw_model = tmp_path / "yaw.pth"
    yaw_model.write_bytes(b"yaw")

    with pytest.raises(ValueError, match="requires approver"):
        write_baseline_run(
            tmp_path / "runs",
            "run-locked",
            cases=[case],
            predictions=rows,
            metrics=metrics,
            thresholds=BaselineThresholds(0.9, 0.1, 1.0),
            preprocessing=PreprocessingSpec(model_width=6, model_height=5),
            source_commit="c" * 40,
            dataset_manifest=dataset_manifest,
            yolo_model=yolo_model,
            yaw_model=yaw_model,
            split="locked-test",
        )


def test_target_annotations_require_exact_independent_coverage(tmp_path: Path) -> None:
    path = tmp_path / "target_annotations.csv"
    path.write_text(
        "case_id,box_x1,box_y1,box_x2,box_y2,annotated_by\n"
        "images/validation/frame.jpg,1,2,5,6,reviewer\n",
        encoding="utf-8",
    )

    annotations = load_target_annotations(
        path,
        {"images/validation/frame.jpg"},
        width=10,
        height=10,
    )

    assert annotations["images/validation/frame.jpg"] == (1, 2, 5, 6)
    with pytest.raises(ValueError, match="exact split"):
        load_target_annotations(
            path,
            {"images/validation/frame.jpg", "images/validation/missing.jpg"},
            width=10,
            height=10,
        )

import csv
from pathlib import Path

import pytest

from rubber_band_gun.shot_results import SHOT_COLUMNS, ShotResult, write_shot_results


def _result(shot_id: str = "shot-001") -> ShotResult:
    return ShotResult(
        shot_id=shot_id,
        captured_frame="images/frame_000001.jpg",
        fired_at_utc="2026-09-23T00:00:00+00:00",
        target_distance_m=2.0,
        commanded_yaw_degrees=52.0,
        commanded_pitch_degrees=90.0,
        predicted_yaw_offset_degrees=2.0,
        outcome="hit",
        impact_x_mm=-4.0,
        impact_y_mm=8.0,
    )


def test_write_shot_results_uses_stable_contract(tmp_path: Path) -> None:
    path = tmp_path / "shot_results.csv"

    write_shot_results(path, [_result()])

    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        row = next(reader)
    assert tuple(reader.fieldnames or ()) == SHOT_COLUMNS
    assert row["outcome"] == "hit"
    assert row["impact_x_mm"] == "-4.0"


def test_shot_result_rejects_partial_impact_coordinates() -> None:
    with pytest.raises(ValueError, match="both be present"):
        ShotResult(
            shot_id="shot-001",
            captured_frame="images/frame.jpg",
            fired_at_utc="2026-09-23T00:00:00+00:00",
            target_distance_m=2.0,
            commanded_yaw_degrees=50.0,
            commanded_pitch_degrees=90.0,
            predicted_yaw_offset_degrees=0.0,
            outcome="miss",
            impact_x_mm=1.0,
        )


def test_write_shot_results_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unique"):
        write_shot_results(tmp_path / "shots.csv", [_result(), _result()])


def test_shot_result_requires_timezone() -> None:
    values = _result().__dict__ | {"fired_at_utc": "2026-09-23T00:00:00"}

    with pytest.raises(ValueError, match="timezone"):
        ShotResult(**values)


def test_write_shot_results_does_not_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "shots.csv"
    path.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        write_shot_results(path, [_result()])

    assert path.read_text(encoding="utf-8") == "existing\n"


def test_shot_result_rejects_out_of_range_command() -> None:
    values = _result().__dict__ | {"commanded_yaw_degrees": 181.0}

    with pytest.raises(ValueError, match="0..180"):
        ShotResult(**values)

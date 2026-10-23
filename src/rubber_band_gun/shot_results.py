"""Legacy standalone shot-result rows retained for compatibility.

New evaluation evidence must use :mod:`rubber_band_gun.shot_run`, whose versioned
bundle binds images, preprocessing, references, timestamps, and hashes. This
module records rows only and contains no actuator or firing command.
"""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

SHOT_COLUMNS = (
    "shot_id",
    "captured_frame",
    "fired_at_utc",
    "target_distance_m",
    "commanded_yaw_degrees",
    "commanded_pitch_degrees",
    "predicted_yaw_offset_degrees",
    "outcome",
    "impact_x_mm",
    "impact_y_mm",
    "notes",
)
SHOT_ID_PATTERN = re.compile(r"shot-[A-Za-z0-9._-]{1,80}")


@dataclass(frozen=True)
class ShotResult:
    shot_id: str
    captured_frame: str
    fired_at_utc: str
    target_distance_m: float
    commanded_yaw_degrees: float
    commanded_pitch_degrees: float
    predicted_yaw_offset_degrees: float
    outcome: str
    impact_x_mm: float | None = None
    impact_y_mm: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not SHOT_ID_PATTERN.fullmatch(self.shot_id):
            raise ValueError(f"invalid shot ID: {self.shot_id}")
        frame = Path(self.captured_frame)
        if (
            frame.is_absolute()
            or ".." in frame.parts
            or "\\" in self.captured_frame
            or not self.captured_frame.strip()
        ):
            raise ValueError(f"unsafe captured frame path: {self.captured_frame}")
        try:
            fired_at = datetime.fromisoformat(self.fired_at_utc.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise ValueError("fired_at_utc must be an ISO 8601 timestamp") from error
        if fired_at.tzinfo is None or fired_at.utcoffset() is None:
            raise ValueError("fired_at_utc must include a timezone")
        if self.target_distance_m <= 0 or not math.isfinite(self.target_distance_m):
            raise ValueError("target_distance_m must be positive and finite")
        for name, value in (
            ("commanded_yaw_degrees", self.commanded_yaw_degrees),
            ("commanded_pitch_degrees", self.commanded_pitch_degrees),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 180.0:
                raise ValueError(f"{name} must be finite and within 0..180 degrees")
        if not math.isfinite(self.predicted_yaw_offset_degrees):
            raise ValueError("predicted_yaw_offset_degrees must be finite")
        if self.outcome not in {"hit", "miss", "invalid"}:
            raise ValueError(f"invalid shot outcome: {self.outcome}")
        if (self.impact_x_mm is None) != (self.impact_y_mm is None):
            raise ValueError("impact coordinates must both be present or both be absent")
        if self.impact_x_mm is not None and not all(
            math.isfinite(value) for value in (self.impact_x_mm, self.impact_y_mm)
        ):
            raise ValueError("impact coordinates must be finite")

    def to_row(self) -> dict[str, str]:
        values = asdict(self)
        return {key: "" if value is None else str(value) for key, value in values.items()}


def write_shot_results(path: Path, rows: Iterable[ShotResult]) -> None:
    """Atomically write a manually reviewed shot-result table."""

    results = list(rows)
    if not results:
        raise ValueError("at least one shot result is required")
    ids = [result.shot_id for result in results]
    if len(set(ids)) != len(ids):
        raise ValueError("shot IDs must be unique")

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    if path.exists():
        raise FileExistsError(f"shot result already exists: {path}")
    if partial.exists():
        raise FileExistsError(f"partial shot result already exists: {partial}")
    with partial.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SHOT_COLUMNS)
        writer.writeheader()
        writer.writerows(result.to_row() for result in results)
    partial.rename(path)

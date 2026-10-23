"""Pure policy for the evaluator's permitted manual axis movement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ControlOrigin(str, Enum):
    LOCAL_KEYBOARD = "local_keyboard"
    REMOTE = "remote"
    MODEL = "model"


@dataclass(frozen=True)
class ManualAxisPolicy:
    """Accept only calibrated, settled, local yaw/pitch commands."""

    axes: tuple[str, str] = ("yaw", "pitch")

    def permits(
        self,
        axis: str,
        *,
        origin: ControlOrigin,
        calibrated: bool,
        settled: bool,
    ) -> bool:
        return (
            axis in self.axes
            and origin is ControlOrigin.LOCAL_KEYBOARD
            and calibrated
            and settled
        )

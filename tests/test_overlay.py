import numpy as np
import pytest

from rubber_band_gun.overlay import draw_center_crosshair_bgr


def test_crosshair_is_centered_and_does_not_modify_source() -> None:
    source = np.zeros((101, 201, 3), dtype=np.uint8)

    display = draw_center_crosshair_bgr(source)

    assert not np.shares_memory(display, source)
    assert not source.any()
    assert display[50, 100].tolist() == [255, 255, 255]
    assert display[50, 90].tolist() == [0, 255, 0]
    assert display[40, 100].tolist() == [0, 255, 0]


def test_crosshair_uses_documented_center_pixel_for_even_dimensions() -> None:
    source = np.zeros((100, 200, 3), dtype=np.uint8)

    display = draw_center_crosshair_bgr(source)

    assert display[50, 100].tolist() == [255, 255, 255]


@pytest.mark.parametrize(
    "frame, error",
    [
        (np.zeros((10, 10), dtype=np.uint8), "shape"),
        (np.zeros((10, 10, 3), dtype=np.float32), "uint8"),
    ],
)
def test_crosshair_rejects_invalid_frames(frame: np.ndarray, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        draw_center_crosshair_bgr(frame)

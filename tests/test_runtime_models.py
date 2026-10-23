import pytest

from rubber_band_gun.runtime_models import target_tile_windows


def test_target_tile_windows_adds_full_frame_and_covers_edges() -> None:
    windows = target_tile_windows(
        480,
        640,
        grid=2,
        overlap=0.2,
        include_full_frame=True,
    )

    assert windows[0] == (0, 0, 480, 640)
    assert len(windows) == 5
    assert windows[1][:2] == (0, 0)
    assert windows[-1][2:] == (480, 640)
    assert windows[1][2] > windows[2][0]
    assert windows[1][3] > windows[3][1]


def test_single_grid_is_exactly_one_full_frame() -> None:
    assert target_tile_windows(
        11,
        13,
        grid=1,
        overlap=0.9,
        include_full_frame=False,
    ) == [(0, 0, 11, 13)]


@pytest.mark.parametrize(
    ("width", "height", "grid", "overlap", "message"),
    [
        (0, 10, 2, 0.2, "dimensions"),
        (10, 10, 0, 0.2, "grid"),
        (10, 10, 2, 1.0, "overlap"),
    ],
)
def test_target_tile_windows_rejects_invalid_settings(
    width: int,
    height: int,
    grid: int,
    overlap: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        target_tile_windows(
            width,
            height,
            grid=grid,
            overlap=overlap,
            include_full_frame=True,
        )

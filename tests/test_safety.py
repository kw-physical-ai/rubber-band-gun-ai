from rubber_band_gun.safety import ControlOrigin, ManualAxisPolicy


def test_manual_axis_policy_accepts_only_yaw_and_pitch() -> None:
    policy = ManualAxisPolicy()

    assert policy.permits(
        "yaw",
        origin=ControlOrigin.LOCAL_KEYBOARD,
        calibrated=True,
        settled=True,
    )
    assert policy.permits(
        "pitch",
        origin=ControlOrigin.LOCAL_KEYBOARD,
        calibrated=True,
        settled=True,
    )
    assert not policy.permits(
        "extra",
        origin=ControlOrigin.LOCAL_KEYBOARD,
        calibrated=True,
        settled=True,
    )


def test_manual_axis_policy_rejects_non_local_origins() -> None:
    policy = ManualAxisPolicy()

    for origin in (ControlOrigin.MODEL, ControlOrigin.REMOTE):
        assert not policy.permits(
            "yaw", origin=origin, calibrated=True, settled=True
        )


def test_manual_axis_policy_requires_calibration_and_settling() -> None:
    policy = ManualAxisPolicy()

    assert not policy.permits(
        "pitch",
        origin=ControlOrigin.LOCAL_KEYBOARD,
        calibrated=False,
        settled=True,
    )
    assert not policy.permits(
        "pitch",
        origin=ControlOrigin.LOCAL_KEYBOARD,
        calibrated=True,
        settled=False,
    )

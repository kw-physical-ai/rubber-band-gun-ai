from pathlib import Path

COLLECTOR = Path(__file__).resolve().parents[1] / "scripts" / "pi" / "collect-yaw-data.py"


def test_collector_has_no_firing_interface() -> None:
    source = COLLECTOR.read_text(encoding="utf-8")

    assert "FIRE_PIN" not in source
    assert "FIRE_SHOOT" not in source
    assert "--enable-motion" in source
    assert "calibrated=true" in source
    assert "SETTLING - CAPTURE DISABLED" in source

from pathlib import Path

from rubber_band_gun import ProjectWorkspace, runtime_summary


def test_workspace_creates_expected_directories(tmp_path: Path) -> None:
    workspace = ProjectWorkspace(tmp_path / "rubber-band-gun-ai-data")

    workspace.create()

    assert workspace.pi_upload == workspace.root / "pi-upload"
    assert workspace.raw == workspace.root / "pi-upload" / "raw"
    assert workspace.smoke == workspace.root / "pi-upload" / "smoke"
    assert workspace.evaluation == workspace.root / "pi-upload" / "evaluation"
    assert not workspace.pi_upload.exists()
    assert workspace.processed.is_dir()
    assert workspace.runs.is_dir()


def test_runtime_summary_contains_stable_keys() -> None:
    summary = runtime_summary()

    assert {"python", "platform", "machine", "packages"} <= summary.keys()
    assert "ultralytics" in summary["packages"]

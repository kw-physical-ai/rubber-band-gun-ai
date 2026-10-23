"""Environment helpers shared by notebooks and command-line tools."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path


@dataclass(frozen=True)
class ProjectWorkspace:
    """External-data layout shared by the Pi uploader and Colab runs."""

    root: Path

    @property
    def pi_upload(self) -> Path:
        return self.root / "pi-upload"

    @property
    def raw(self) -> Path:
        return self.pi_upload / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def smoke(self) -> Path:
        return self.pi_upload / "smoke"

    @property
    def evaluation(self) -> Path:
        return self.pi_upload / "evaluation"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    def create(self) -> None:
        """Create Colab-owned output directories, not Pi upload ingress."""
        for directory in (self.processed, self.runs):
            directory.mkdir(parents=True, exist_ok=True)


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def runtime_summary() -> dict[str, object]:
    """Return portable runtime metadata without importing heavy packages."""

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": {
            name: _package_version(name)
            for name in ("torch", "torchvision", "ultralytics", "opencv-python-headless")
        },
    }

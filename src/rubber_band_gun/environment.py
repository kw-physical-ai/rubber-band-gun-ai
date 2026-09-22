"""Environment helpers shared by notebooks and command-line tools."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path


@dataclass(frozen=True)
class ProjectWorkspace:
    """Versioned external-data layout used by Colab runs."""

    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    def create(self) -> None:
        for directory in (self.raw, self.processed, self.runs):
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

"""Shared project utilities for Colab and Raspberry Pi evaluation."""

from .environment import ProjectWorkspace, runtime_summary
from .smoke import verify_smoke_bundle

__all__ = ["ProjectWorkspace", "runtime_summary", "verify_smoke_bundle"]

"""Application package for the Erfassung project."""

from __future__ import annotations

from pathlib import Path

__all__ = ["__version__"]


def _load_version() -> str:
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return value or "0.0.0"


__version__ = _load_version()


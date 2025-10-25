"""Utilities for running the local slideshow service.

This module exposes the public API that is used by the systemd
integration scripts in production.  The implementation lives in
``slideshow.player`` but keeping the re-export here keeps the import
path stable for the tests while still allowing internal refactors.
"""

from .player import MonitorNotReadyError, SlideshowService

__all__ = ["MonitorNotReadyError", "SlideshowService"]

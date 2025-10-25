"""Slideshow player orchestration utilities.

The production environment starts an ``mpv`` based slideshow via a
systemd service.  When the device is rebooted without a monitor
attached the player historically failed during start-up because the X11
server did not expose a primary display.  Once a monitor was plugged in
no automatic retry happened which left the device in a broken state
until the service was manually restarted.

The :class:`SlideshowService` implemented here keeps retrying until a
monitor becomes available.  The implementation is intentionally
framework agnostic so it can be exercised easily in tests by injecting
simple callables.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Protocol, Sequence

__all__ = ["MonitorNotReadyError", "SlideshowService"]


class MonitorNotReadyError(RuntimeError):
    """Raised when the slideshow cannot start because no monitor is active."""


class PlayerHandle(Protocol):
    """Protocol describing the minimal interface of a player object."""

    def start(self) -> None:  # pragma: no cover - runtime behaviour is mocked in tests
        """Start playback. Implementations may block until shutdown."""

    def stop(self) -> None:  # pragma: no cover - runtime behaviour is mocked in tests
        """Stop playback and release resources."""


@dataclass(slots=True)
class SlideshowConfig:
    """Configuration container for :class:`SlideshowService`."""

    poll_interval: float = 5.0
    shutdown_timeout: float = 10.0


class SlideshowService:
    """Manage the slideshow player lifecycle.

    Parameters
    ----------
    player_factory:
        Callable that returns a fully initialised player instance.  The
        callable may raise :class:`MonitorNotReadyError` when the
        underlying player cannot connect to a monitor yet.
    monitor_probe:
        Callable that returns the currently active monitors.  The
        callable should return an iterable of strings, where each string
        represents a monitor name.  An empty iterable indicates that no
        monitors are available yet.
    config:
        Optional :class:`SlideshowConfig` to tweak timing behaviour.
    logger:
        Optional :class:`logging.Logger` that should receive status
        updates.  When omitted a module level logger is used.
    """

    def __init__(
        self,
        player_factory: Callable[[], PlayerHandle],
        monitor_probe: Callable[[], Iterable[str]],
        *,
        config: Optional[SlideshowConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._player_factory = player_factory
        self._monitor_probe = monitor_probe
        self._config = config or SlideshowConfig()
        self._logger = logger or logging.getLogger("slideshow.player")
        self._thread: Optional[threading.Thread] = None
        self._player: Optional[PlayerHandle] = None
        self._stop_event = threading.Event()
        self._player_ready_event = threading.Event()

    # ------------------------------------------------------------------
    def start(
        self,
        *,
        block_until_ready: bool = False,
        timeout: Optional[float] = None,
    ) -> bool:
        """Start the background thread if it is not running yet.

        Parameters
        ----------
        block_until_ready:
            When ``True`` this call waits until the player reports that it
            has started successfully.  The default behaviour is
            non-blocking so that other services – such as the web
            interface – can continue their own startup sequence even if no
            monitor is attached yet.
        timeout:
            Optional timeout in seconds for the blocking variant.  A
            timeout of ``None`` waits indefinitely.

        Returns
        -------
        bool
            ``True`` when the background thread was launched (and the
            player started successfully if ``block_until_ready`` was
            requested), otherwise ``False``.
        """

        if self._thread and self._thread.is_alive():
            self._logger.debug("Slideshow player already running")
            if block_until_ready:
                return self._wait_until_ready(timeout)
            return True
        self._stop_event.clear()
        self._player_ready_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="slideshow-player")
        self._thread.start()
        if block_until_ready:
            return self._wait_until_ready(timeout)
        return True

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Signal the background thread to stop and join it."""

        self._stop_event.set()
        self._player_ready_event.clear()
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:  # pragma: no cover - defensive shutdown handling
                self._logger.exception("Failed to stop slideshow player cleanly")
        if self._thread is not None:
            self._thread.join(timeout=self._config.shutdown_timeout)

    # ------------------------------------------------------------------
    def wait_until_running(self, timeout: Optional[float] = None) -> bool:
        """Wait until the slideshow player reported a successful start."""

        return self._wait_until_ready(timeout)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        """Background thread body that manages the player lifecycle."""

        self._logger.info("Player thread started")
        self._player_ready_event.clear()
        while not self._stop_event.is_set():
            if not self._wait_for_monitor():
                break
            if not self._stop_event.is_set() and self._attempt_start():
                return
        self._logger.debug("Player thread exiting")

    # ------------------------------------------------------------------
    def _attempt_start(self) -> bool:
        """Attempt to create and start the player.

        Returns
        -------
        bool
            ``True`` when the player was started successfully.
        """

        self._player_ready_event.clear()
        try:
            player = self._player_factory()
        except MonitorNotReadyError:
            self._logger.info("Monitor not ready when creating player, waiting for retry")
            self._wait_interval()
            return False
        except Exception:
            self._logger.exception("Unexpected error while creating slideshow player")
            self._wait_interval()
            return False

        self._player = player
        self._player_ready_event.set()
        try:
            player.start()
        except MonitorNotReadyError:
            self._logger.info("Monitor not ready when starting player, waiting for retry")
            self._player = None
            self._player_ready_event.clear()
            self._wait_interval()
            return False
        except Exception:
            self._logger.exception("Slideshow player crashed during startup")
            self._player = None
            self._player_ready_event.clear()
            self._wait_interval()
            return False

        self._logger.info("Slideshow player started successfully")
        return True

    # ------------------------------------------------------------------
    def _wait_until_ready(self, timeout: Optional[float]) -> bool:
        """Helper that waits for the player to become ready."""

        if self._player_ready_event.is_set():
            return True
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._stop_event.is_set():
                return False
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait_time = min(remaining, self._config.poll_interval)
            else:
                wait_time = self._config.poll_interval
            if self._player_ready_event.wait(wait_time):
                return True

    # ------------------------------------------------------------------
    def _wait_for_monitor(self) -> bool:
        """Block until the monitor probe reports an active monitor."""

        self._logger.debug("Checking for active monitors")
        while not self._stop_event.is_set():
            try:
                monitors = self._normalise_monitors(self._monitor_probe())
            except Exception:
                self._logger.exception("Failed to probe connected monitors")
                monitors = ()
            if monitors:
                self._logger.info("Detected active monitor(s): %s", ", ".join(monitors))
                return True
            self._logger.warning("No active monitors detected - waiting")
            self._wait_interval()
        return False

    # ------------------------------------------------------------------
    def _wait_interval(self) -> None:
        """Wait for the configured poll interval respecting stop requests."""

        self._stop_event.wait(self._config.poll_interval)

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_monitors(monitors: Iterable[str]) -> Sequence[str]:
        """Convert the probe result into a stable tuple of monitor names."""

        if isinstance(monitors, str):
            return (monitors,) if monitors else ()
        try:
            result = tuple(m for m in monitors if m)
        except TypeError:
            # monitor probes might return booleans or integers – treat them as
            # truthy/falsey instead of names.
            return ("primary",) if monitors else ()
        return result


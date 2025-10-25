from __future__ import annotations

import pathlib
import sys
import threading
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from slideshow.player import MonitorNotReadyError, SlideshowConfig, SlideshowService


class DummyPlayer:
    def __init__(self, started: threading.Event, stop_signal: threading.Event) -> None:
        self._started = started
        self._stop_signal = stop_signal

    def start(self) -> None:
        self._started.set()
        self._stop_signal.wait()

    def stop(self) -> None:
        self._stop_signal.set()


@pytest.fixture()
def dummy_player_factory():
    started = threading.Event()
    stop_signal = threading.Event()

    def factory() -> DummyPlayer:
        return DummyPlayer(started, stop_signal)

    return factory, started, stop_signal


def test_start_is_non_blocking_when_monitor_missing(dummy_player_factory):
    factory, started_event, _ = dummy_player_factory
    monitor_ready = threading.Event()

    def monitor_probe():
        return ("HDMI-1",) if monitor_ready.is_set() else ()

    service = SlideshowService(
        factory,
        monitor_probe,
        config=SlideshowConfig(poll_interval=0.01),
    )

    start_time = time.monotonic()
    result = service.start()
    elapsed = time.monotonic() - start_time
    assert result is True
    assert elapsed < 0.05

    monitor_ready.set()
    assert started_event.wait(timeout=1)
    service.stop()


def test_start_can_block_until_ready(dummy_player_factory):
    factory, started_event, _ = dummy_player_factory
    monitor_ready = threading.Event()

    def monitor_probe():
        return ("HDMI-1",) if monitor_ready.is_set() else ()

    service = SlideshowService(
        factory,
        monitor_probe,
        config=SlideshowConfig(poll_interval=0.01),
    )

    def make_monitor_available():
        time.sleep(0.05)
        monitor_ready.set()

    threading.Thread(target=make_monitor_available, daemon=True).start()

    start_time = time.monotonic()
    assert service.start(block_until_ready=True, timeout=1) is True
    elapsed = time.monotonic() - start_time
    assert elapsed >= 0.05
    assert started_event.is_set()
    service.stop()


def test_start_timeout_returns_false(dummy_player_factory):
    factory, started_event, _ = dummy_player_factory

    def monitor_probe():
        return ()

    service = SlideshowService(
        factory,
        monitor_probe,
        config=SlideshowConfig(poll_interval=0.01),
    )

    assert service.start(block_until_ready=True, timeout=0.05) is False
    assert not started_event.is_set()
    service.stop()


class FailingPlayer:
    def __init__(self, attempts: threading.Event) -> None:
        self._attempts = attempts

    def start(self) -> None:
        self._attempts.set()
        raise MonitorNotReadyError()

    def stop(self) -> None:
        pass


def test_wait_until_running_respects_stop():
    attempts = threading.Event()

    def factory() -> FailingPlayer:
        return FailingPlayer(attempts)

    monitor_ready = threading.Event()

    def monitor_probe():
        return ("HDMI-1",) if monitor_ready.is_set() else ()

    service = SlideshowService(
        factory,
        monitor_probe,
        config=SlideshowConfig(poll_interval=0.01),
    )

    service.start()
    monitor_ready.set()
    assert attempts.wait(timeout=1)
    service.stop()
    assert service.wait_until_running(timeout=0.01) is False

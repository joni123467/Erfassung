"""TimeMoto terminal driver (§0.9.8).

Wraps the existing low-level TimeMoto client/synchronisation (``app.integrations.
timemoto``) behind the generic :class:`TerminalDriver` interface. All connection
details are read from the ``Terminal`` model row, so there is no TimeMoto-specific
configuration point or hardcoded logic anywhere in the UI.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from .. import timemoto
from .base import TerminalDriver, TerminalSyncOutcome, TerminalTestResult


def _terminal_to_config(terminal) -> "timemoto.TimeMotoConfig":
    """Build a :class:`TimeMotoConfig` from a generic terminal record."""

    extra: dict[str, object] = {}
    raw = getattr(terminal, "config_json", "") or ""
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                extra = parsed
        except (TypeError, ValueError):
            extra = {}

    config = timemoto.TimeMotoConfig()
    payload: dict[str, object] = {
        "host": terminal.host or "",
        "port": terminal.port or 80,
        "use_ssl": bool(terminal.use_ssl),
        "verify_ssl": bool(terminal.verify_ssl),
        "username": terminal.username or "",
        "timezone": terminal.timezone or "Europe/Berlin",
        "last_event_id": terminal.last_event_id,
    }
    if terminal.password:
        payload["password"] = terminal.password
    # Optional driver-specific endpoints / limits.
    for key in ("login_path", "users_path", "events_path", "events_limit", "timeout"):
        if key in extra and extra[key] not in (None, ""):
            payload[key] = extra[key]
    config.update_from_dict(payload)
    return config


class TimeMotoDriver(TerminalDriver):
    key = "timemoto"
    label = "TimeMoto"

    def test_connection(self, terminal) -> TerminalTestResult:
        config = _terminal_to_config(terminal)
        if not config.host:
            return TerminalTestResult(False, "Host/IP-Adresse fehlt.")
        try:
            with timemoto.TimeMotoClient(config) as client:
                client.authenticate()
                # A lightweight read confirms credentials + reachability.
                client.fetch_users()
        except timemoto.TimeMotoError as exc:
            return TerminalTestResult(False, str(exc))
        return TerminalTestResult(True, f"Verbindung erfolgreich ({config.base_url}).")

    def synchronize(
        self, db: Session, terminal, *, full_sync: bool = False
    ) -> TerminalSyncOutcome:
        config = _terminal_to_config(terminal)
        if not config.host:
            return TerminalSyncOutcome("error", message="Host/IP-Adresse fehlt.")
        try:
            result = timemoto.synchronize(db, config, full_sync=full_sync)
        except timemoto.TimeMotoError as exc:
            return TerminalSyncOutcome("error", message=str(exc))
        status = "success" if result.unmatched_events == 0 else "warning"
        message = (
            f"{result.created_entries} neue Buchungen, "
            f"{result.unmatched_events} nicht zugeordnet, "
            f"{result.skipped_events} übersprungen."
        )
        return TerminalSyncOutcome(
            status=status,
            imported=result.created_entries,
            errors=result.unmatched_events + result.skipped_events,
            message=message,
            last_event_id=config.last_event_id,
        )

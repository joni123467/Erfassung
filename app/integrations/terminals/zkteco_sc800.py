"""Conservative parser for the documented ZKTeco PUSH/ADMS ATTLOG format.

Only inbound attendance rows are implemented.  Server commands and user/card
provisioning deliberately remain unsupported until the exact SC800 firmware
protocol has been verified; see the compatibility report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .base import TerminalDriver, TerminalSyncOutcome, TerminalTestResult


@dataclass(frozen=True)
class AttendanceEvent:
    user_identifier: str
    timestamp: datetime
    status: str = "0"
    verify_mode: str = ""
    work_code: str = ""
    card_identifier: str = ""
    external_event_id: str = ""
    raw_line: str = ""


def parse_attlog(body: bytes) -> list[AttendanceEvent]:
    """Parse tab-separated ``ATTLOG`` rows without guessing missing fields."""
    try:
        text = body.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        text = body.decode("latin-1", errors="strict")
    events: list[AttendanceEvent] = []
    for raw in text.splitlines():
        line = raw.strip("\r\n ")
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            raise ValueError("ATTLOG-Zeile hat weniger als zwei Felder")
        try:
            timestamp = datetime.strptime(fields[1].strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("Ungültiger ATTLOG-Zeitstempel") from exc
        events.append(AttendanceEvent(
            user_identifier=fields[0].strip(), timestamp=timestamp,
            status=fields[2].strip() if len(fields) > 2 else "0",
            verify_mode=fields[3].strip() if len(fields) > 3 else "",
            work_code=fields[4].strip() if len(fields) > 4 else "",
            external_event_id=fields[5].strip() if len(fields) > 5 else "",
            raw_line=line,
        ))
    return events


class ZkTecoSc800Terminal(TerminalDriver):
    key = "zkteco_sc800"
    label = "ZKTeco SC800 (Push)"

    def test_connection(self, terminal) -> TerminalTestResult:
        return TerminalTestResult(
            False,
            "Push-Gerät: Verbindung wird durch den nächsten Gerätekontakt geprüft.",
        )

    def synchronize(self, db, terminal, *, full_sync: bool = False) -> TerminalSyncOutcome:
        return TerminalSyncOutcome(
            "warning", message="SC800 synchronisiert per Push; ausgehende Befehle sind nicht freigegeben."
        )


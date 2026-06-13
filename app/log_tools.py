"""Reading, filtering, exporting and cleaning the structured log files."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from . import logging_setup, paths

# A structured line looks like:
# 2026-06-13 12:00:00 | INFO     | api         | user=admin | message text
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| "
    r"(?P<level>\w+)\s*\| "
    r"(?P<channel>[\w-]+)\s*\| "
    r"user=(?P<user>\S*) \| "
    r"(?P<message>.*)$"
)

_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


@dataclass
class LogLine:
    raw: str
    timestamp: Optional[datetime]
    level: str
    channel: str
    user: str
    message: str


def available_logs() -> list[dict[str, object]]:
    """Metadata for every known log channel (existing or not)."""

    result: list[dict[str, object]] = []
    for channel, filename in logging_setup.CHANNELS.items():
        path = paths.LOGS_DIR / filename
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        modified = datetime.fromtimestamp(path.stat().st_mtime) if exists else None
        result.append(
            {
                "channel": channel,
                "filename": filename,
                "exists": exists,
                "size_bytes": size,
                "size_human": paths.format_size(size),
                "modified": modified,
            }
        )
    return result


def _parse_line(raw: str) -> LogLine:
    match = _LINE_RE.match(raw)
    if not match:
        return LogLine(raw=raw, timestamp=None, level="", channel="", user="", message=raw)
    try:
        timestamp = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        timestamp = None
    return LogLine(
        raw=raw,
        timestamp=timestamp,
        level=match.group("level").upper(),
        channel=match.group("channel"),
        user=match.group("user"),
        message=match.group("message"),
    )


def read_log(
    channel: str,
    *,
    search: str = "",
    level: str = "",
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = 1000,
) -> list[LogLine]:
    """Return parsed log lines (newest first) matching the filters."""

    if channel not in logging_setup.CHANNELS:
        raise KeyError(channel)
    path = paths.LOGS_DIR / logging_setup.CHANNELS[channel]
    if not path.exists():
        return []

    search_lower = (search or "").strip().lower()
    level_threshold = _LEVEL_ORDER.get((level or "").upper())

    lines: list[LogLine] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            raw = raw.rstrip("\n")
            if not raw:
                continue
            parsed = _parse_line(raw)
            if level_threshold is not None:
                line_level = _LEVEL_ORDER.get(parsed.level, 0)
                if line_level < level_threshold:
                    continue
            if start and parsed.timestamp and parsed.timestamp.date() < start:
                continue
            if end and parsed.timestamp and parsed.timestamp.date() > end:
                continue
            if search_lower and search_lower not in raw.lower():
                continue
            lines.append(parsed)

    lines.reverse()
    if limit and limit > 0:
        lines = lines[:limit]
    return lines


def clear_log(channel: str) -> None:
    """Truncate a single log file (rotated siblings are removed too)."""

    if channel not in logging_setup.CHANNELS:
        raise KeyError(channel)
    filename = logging_setup.CHANNELS[channel]
    path = paths.LOGS_DIR / filename
    if path.exists():
        path.write_text("", encoding="utf-8")
    for sibling in paths.LOGS_DIR.glob(f"{filename}.*"):
        try:
            sibling.unlink()
        except OSError:
            continue


def clear_all_logs() -> None:
    for channel in logging_setup.CHANNELS:
        clear_log(channel)


def build_zip(channels: Iterable[str]) -> io.BytesIO:
    """Bundle the requested log files into an in-memory ZIP archive."""

    buffer = io.BytesIO()
    selected = [c for c in channels if c in logging_setup.CHANNELS] or list(
        logging_setup.CHANNELS
    )
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for channel in selected:
            path = paths.LOGS_DIR / logging_setup.CHANNELS[channel]
            if path.exists():
                archive.write(path, arcname=logging_setup.CHANNELS[channel])
    buffer.seek(0)
    return buffer


def single_log_bytes(channel: str) -> bytes:
    if channel not in logging_setup.CHANNELS:
        raise KeyError(channel)
    path = paths.LOGS_DIR / logging_setup.CHANNELS[channel]
    return path.read_bytes() if path.exists() else b""


def error_overview() -> dict[str, object]:
    """Aggregate statistics from the error log for the admin dashboard."""

    now = datetime.now()
    last_24h = 0
    last_7d = 0
    by_message: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    total = 0

    path = paths.LOGS_DIR / logging_setup.CHANNELS["error"]
    if path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                raw = raw.rstrip("\n")
                if not raw:
                    continue
                parsed = _parse_line(raw)
                total += 1
                if parsed.timestamp:
                    age = now - parsed.timestamp
                    if age.total_seconds() <= 24 * 3600:
                        last_24h += 1
                    if age.total_seconds() <= 7 * 24 * 3600:
                        last_7d += 1
                key = parsed.message[:120] if parsed.message else parsed.raw[:120]
                by_message[key] = by_message.get(key, 0) + 1
                channel = parsed.channel or "application"
                by_channel[channel] = by_channel.get(channel, 0) + 1

    most_common = sorted(by_message.items(), key=lambda item: item[1], reverse=True)[:10]
    return {
        "total": total,
        "last_24h": last_24h,
        "last_7d": last_7d,
        "most_common": [{"message": msg, "count": count} for msg, count in most_common],
        "by_channel": [
            {"channel": channel, "count": count}
            for channel, count in sorted(by_channel.items(), key=lambda i: i[1], reverse=True)
        ],
    }


def cleanup_old_logs(max_age_days: int) -> int:
    """Remove rotated log files older than ``max_age_days``. Returns count."""

    if max_age_days <= 0:
        return 0
    cutoff = datetime.now().timestamp() - max_age_days * 24 * 3600
    removed = 0
    for path in paths.LOGS_DIR.glob("*.log.*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed

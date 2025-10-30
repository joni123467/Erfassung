"""Local integration helpers for TimeMoto TM-616 terminals."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import crud, models, schemas

LOGGER = logging.getLogger(__name__)

def _discover_project_root() -> Path:
    """Return the root folder that contains the application package."""

    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "requirements.txt").exists():
            return candidate
    for candidate in current.parents:
        if (candidate / "app").is_dir():
            return candidate
    try:
        return current.parents[3]
    except IndexError:  # pragma: no cover - defensive fallback
        return current.parent


_PROJECT_ROOT = _discover_project_root()
_CONFIG_DIR = _PROJECT_ROOT / "config"
_CONFIG_PATH = _CONFIG_DIR / "timemoto.json"
_LEGACY_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "timemoto.json"


class TimeMotoError(RuntimeError):
    """Raised when communication with the TimeMoto device fails."""


def _ensure_config_dir() -> None:
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TimeMotoError(f"Konfigurationsordner konnte nicht erstellt werden: {exc}") from exc


def _migrate_legacy_config() -> None:
    if _LEGACY_CONFIG_PATH == _CONFIG_PATH:
        return
    if not _LEGACY_CONFIG_PATH.exists() or _CONFIG_PATH.exists():
        return
    try:
        _ensure_config_dir()
        shutil.move(str(_LEGACY_CONFIG_PATH), str(_CONFIG_PATH))
        try:
            _LEGACY_CONFIG_PATH.parent.rmdir()
        except OSError:
            pass
    except OSError as exc:
        LOGGER.warning("TimeMoto-Altkonfiguration konnte nicht übernommen werden: %s", exc)


@dataclass
class TimeMotoConfig:
    """Persisted configuration for the TimeMoto integration."""

    host: str = ""
    port: int = 80
    use_ssl: bool = False
    verify_ssl: bool = True
    username: str = ""
    password: str = ""
    timezone: str = "Europe/Berlin"
    login_path: str = "/api/v1/login"
    users_path: str = "/api/v1/users"
    events_path: str = "/api/v1/events"
    events_limit: int = 500
    timeout: float = 10.0
    last_event_id: int | None = None
    last_sync_at: str | None = None

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        if (self.use_ssl and self.port == 443) or (not self.use_ssl and self.port == 80):
            return f"{scheme}://{self.host.strip()}"
        return f"{scheme}://{self.host.strip()}:{self.port}"

    @property
    def zoneinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone or "UTC")
        except ZoneInfoNotFoundError:
            LOGGER.warning("Unbekannte Zeitzone '%s', verwende UTC", self.timezone)
            return ZoneInfo("UTC")

    @property
    def has_credentials(self) -> bool:
        return bool(self.username)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "use_ssl": self.use_ssl,
            "verify_ssl": self.verify_ssl,
            "username": self.username,
            "password": self.password,
            "timezone": self.timezone,
            "login_path": self.login_path,
            "users_path": self.users_path,
            "events_path": self.events_path,
            "events_limit": self.events_limit,
            "timeout": self.timeout,
            "last_event_id": self.last_event_id,
            "last_sync_at": self.last_sync_at,
        }

    def update_from_dict(self, payload: dict[str, Any]) -> None:
        if "host" in payload and payload["host"] is not None:
            self.host = str(payload["host"]).strip()
        if "port" in payload and payload["port"] is not None:
            try:
                self.port = max(int(payload["port"]), 1)
            except (TypeError, ValueError):
                self.port = 80
        if "use_ssl" in payload:
            self.use_ssl = bool(payload["use_ssl"])
        if "verify_ssl" in payload:
            self.verify_ssl = bool(payload["verify_ssl"])
        if "username" in payload and payload["username"] is not None:
            self.username = str(payload["username"]).strip()
        if "password" in payload and payload["password"] not in (None, ""):
            self.password = str(payload["password"])
        if "timezone" in payload and payload["timezone"] is not None:
            self.timezone = str(payload["timezone"]).strip() or self.timezone
        if "login_path" in payload and payload["login_path"] is not None:
            self.login_path = str(payload["login_path"]).strip() or "/api/v1/login"
        if "users_path" in payload and payload["users_path"] is not None:
            self.users_path = str(payload["users_path"]).strip() or "/api/v1/users"
        if "events_path" in payload and payload["events_path"] is not None:
            self.events_path = str(payload["events_path"]).strip() or "/api/v1/events"
        if "events_limit" in payload and payload["events_limit"] is not None:
            try:
                limit = int(payload["events_limit"])
            except (TypeError, ValueError):
                limit = self.events_limit
            self.events_limit = max(limit, 1)
        if "timeout" in payload and payload["timeout"] is not None:
            try:
                timeout = float(payload["timeout"])
            except (TypeError, ValueError):
                timeout = self.timeout
            self.timeout = max(timeout, 1.0)
        if "last_event_id" in payload and payload["last_event_id"] not in (None, ""):
            try:
                self.last_event_id = int(payload["last_event_id"])
            except (TypeError, ValueError):
                self.last_event_id = None
        if "last_sync_at" in payload and payload["last_sync_at"] not in (None, ""):
            self.last_sync_at = str(payload["last_sync_at"]).strip()

    def save(self) -> None:
        _ensure_config_dir()
        data = self.to_dict()
        try:
            _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            raise TimeMotoError(f"TimeMoto-Konfiguration konnte nicht gespeichert werden: {exc}") from exc

    @classmethod
    def load(cls) -> "TimeMotoConfig":
        config = cls()
        _migrate_legacy_config()
        if not _CONFIG_PATH.exists():
            return config
        try:
            payload = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TimeMotoError(f"TimeMoto-Konfigurationsdatei ist ungültig: {exc}") from exc
        if isinstance(payload, dict):
            config.update_from_dict(payload)
        return config


@dataclass
class TimeMotoUser:
    code: str | None = None
    full_name: str | None = None
    email: str | None = None
    rfid: str | None = None
    aliases: set[str] = field(default_factory=set)
    raw: dict[str, Any] = field(default_factory=dict)

    def identifiers(self) -> set[str]:
        values: set[str] = set()
        candidates: Iterable[str | int | None] = [self.code, self.full_name, self.email]
        for item in candidates:
            if item is None:
                continue
            normalized = str(item).strip().lower()
            if normalized:
                values.add(normalized)
        for alias in self.aliases:
            normalized = str(alias).strip().lower()
            if normalized:
                values.add(normalized)
        return values


@dataclass
class TimeMotoEvent:
    record_id: int | None
    timestamp: datetime
    direction: str | None = None
    user_code: str | None = None
    rfid: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def direction_label(self) -> str:
        return (self.direction or "").strip().lower()

    def is_clock_in(self) -> bool:
        return self.direction_label in {
            "in",
            "check-in",
            "checkin",
            "clock-in",
            "clockin",
            "entrada",
            "an",
            "start",
            "on",
            "0",
        }

    def is_clock_out(self) -> bool:
        return self.direction_label in {
            "out",
            "checkout",
            "check-out",
            "clockout",
            "clock-out",
            "saida",
            "aus",
            "end",
            "off",
            "1",
        }


def _extract_first(payload: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if value not in (None, ""):
            return value
    return None


def _try_parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            try:
                return datetime.fromtimestamp(int(text), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        patterns = [
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%Y-%m-%d %H:%M",
        ]
        for pattern in patterns:
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
    return None


def _ensure_datetime(payload: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "datetime", "date_time", "event_time", "time", "log_time"):
        candidate = payload.get(key)
        parsed = _try_parse_datetime(candidate)
        if parsed:
            return parsed
    date_value = _extract_first(payload, ["date", "log_date"])
    time_value = _extract_first(payload, ["time", "log_time"])
    if isinstance(date_value, str) and isinstance(time_value, str):
        combined = f"{date_value.strip()} {time_value.strip()}"
        parsed = _try_parse_datetime(combined)
        if parsed:
            return parsed
    return None


class TimeMotoClient:
    """HTTP client that talks to the TimeMoto device."""

    def __init__(self, config: TimeMotoConfig):
        if not config.host:
            raise TimeMotoError("TimeMoto-Gerät ist nicht konfiguriert.")
        self._config = config
        try:
            self._client = httpx.Client(
                base_url=config.base_url,
                timeout=config.timeout,
                verify=config.verify_ssl,
            )
        except httpx.HTTPError as exc:
            raise TimeMotoError(f"HTTP-Client konnte nicht initialisiert werden: {exc}") from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TimeMotoClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - resource cleanup
        self.close()

    def authenticate(self) -> None:
        if not self._config.has_credentials:
            return
        login_path = (self._config.login_path or "").strip()
        if not login_path:
            return
        payload = {
            "username": self._config.username,
            "password": self._config.password,
        }
        attempts: list[tuple[str, dict[str, Any]]] = [
            ("json", {"json": payload}),
            ("form", {"data": payload}),
        ]
        errors: list[str] = []
        for mode, kwargs in attempts:
            try:
                response = self._client.post(login_path, **kwargs)
            except httpx.HTTPError as exc:
                errors.append(f"{mode}: {exc}")
                continue
            if response.status_code >= 400:
                errors.append(f"{mode}: HTTP {response.status_code}")
                continue
            token = self._extract_token(response)
            if token:
                self._client.headers["Authorization"] = f"Bearer {token}"
            return
        if errors:
            raise TimeMotoError("Anmeldung am TimeMoto-Gerät fehlgeschlagen: " + "; ".join(errors))

    @staticmethod
    def _extract_token(response: httpx.Response) -> str | None:
        try:
            data = response.json()
        except ValueError:
            return None
        if isinstance(data, dict):
            for key in ("token", "access_token", "accessToken", "session"):
                token = data.get(key)
                if isinstance(token, str) and token:
                    return token
            nested = data.get("data")
            if isinstance(nested, dict):
                for key in ("token", "access_token", "accessToken"):
                    token = nested.get(key)
                    if isinstance(token, str) and token:
                        return token
        return None

    def fetch_users(self) -> list[TimeMotoUser]:
        response = self._request("get", self._config.users_path)
        payload = self._parse_json(response)
        records = self._extract_collection(payload, ["users", "data", "items", "records", "result"])
        users: list[TimeMotoUser] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            code = _extract_first(
                record,
                [
                    "code",
                    "username",
                    "user_code",
                    "userCode",
                    "id",
                    "uid",
                    "userid",
                    "pin",
                ],
            )
            full_name = _extract_first(record, ["full_name", "name", "display_name"])
            email = _extract_first(record, ["email", "mail"])
            rfid = _extract_first(record, ["rfid", "card", "card_number", "cardNo", "tag"])
            aliases: set[str] = set()
            for key in ("id", "uid", "user_id", "employee_id", "empcode", "code", "pin"):
                value = record.get(key)
                if value in (None, ""):
                    continue
                aliases.add(str(value))
            users.append(
                TimeMotoUser(
                    code=str(code) if code not in (None, "") else None,
                    full_name=str(full_name) if full_name not in (None, "") else None,
                    email=str(email) if email not in (None, "") else None,
                    rfid=str(rfid).strip() if rfid not in (None, "") else None,
                    aliases=aliases,
                    raw=record,
                )
            )
        return users

    def fetch_events(self, since_id: int | None = None) -> list[TimeMotoEvent]:
        params: list[tuple[str, Any]] = []
        if since_id is not None:
            for key in ("since_id", "after_id", "start_id", "last_id", "min_id", "after"):
                params.append((key, since_id))
        if self._config.events_limit:
            params.append(("limit", self._config.events_limit))
        response = self._request("get", self._config.events_path, params=params)
        payload = self._parse_json(response)
        records = self._extract_collection(
            payload,
            ["events", "records", "items", "data", "result", "attlog"],
        )
        events: list[TimeMotoEvent] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            timestamp = _ensure_datetime(record)
            if not timestamp:
                LOGGER.debug("Ignoriere TimeMoto-Ereignis ohne Zeitstempel: %s", record)
                continue
            record_id = _extract_first(
                record,
                [
                    "id",
                    "record_id",
                    "recordId",
                    "log_id",
                    "logId",
                    "event_id",
                ],
            )
            direction = _extract_first(
                record,
                ["direction", "type", "status", "io", "mode", "event"],
            )
            user_code = _extract_first(
                record,
                ["user", "user_code", "userid", "uid", "pin", "empcode", "userId"],
            )
            rfid = _extract_first(
                record,
                ["rfid", "card", "card_number", "cardNo", "tag", "cardcode"],
            )
            try:
                parsed_id = int(record_id) if record_id not in (None, "") else None
            except (TypeError, ValueError):
                parsed_id = None
            events.append(
                TimeMotoEvent(
                    record_id=parsed_id,
                    timestamp=timestamp,
                    direction=str(direction) if direction not in (None, "") else None,
                    user_code=str(user_code) if user_code not in (None, "") else None,
                    rfid=str(rfid).strip() if rfid not in (None, "") else None,
                    raw=record,
                )
            )
        return events

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Iterable[tuple[str, Any]] | None = None,
    ) -> httpx.Response:
        request_path = path or "/"
        try:
            response = self._client.request(method, request_path, params=params)
        except httpx.HTTPError as exc:
            raise TimeMotoError(f"Verbindung zum TimeMoto-Gerät fehlgeschlagen: {exc}") from exc
        if response.status_code >= 400:
            raise TimeMotoError(
                f"TimeMoto-Gerät antwortete mit HTTP {response.status_code}: {response.text.strip()}"
            )
        return response

    @staticmethod
    def _parse_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise TimeMotoError("Antwort des TimeMoto-Geräts ist kein gültiges JSON.") from exc

    @staticmethod
    def _extract_collection(payload: Any, keys: Iterable[str]) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    nested = value.get("items") or value.get("records")
                    if isinstance(nested, list):
                        return nested
        return []


@dataclass
class TimeMotoSyncResult:
    remote_users: int = 0
    matched_users: int = 0
    updated_rfids: int = 0
    remote_events: int = 0
    processed_events: int = 0
    unmatched_events: int = 0
    skipped_events: int = 0
    created_entries: int = 0
    last_event_id: int | None = None
    last_sync_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "remote_users": self.remote_users,
            "matched_users": self.matched_users,
            "updated_rfids": self.updated_rfids,
            "remote_events": self.remote_events,
            "processed_events": self.processed_events,
            "unmatched_events": self.unmatched_events,
            "skipped_events": self.skipped_events,
            "created_entries": self.created_entries,
            "last_event_id": self.last_event_id,
            "last_sync_at": self.last_sync_at,
        }


def _prepare_user_lookups(users: list[models.User]) -> dict[str, dict[str, models.User]]:
    by_username = {user.username.lower(): user for user in users if user.username}
    by_email = {user.email.lower(): user for user in users if user.email}
    by_rfid = {user.rfid_tag: user for user in users if user.rfid_tag}
    by_name = {user.full_name.strip().lower(): user for user in users if user.full_name}
    return {
        "username": by_username,
        "email": by_email,
        "rfid": by_rfid,
        "name": by_name,
    }


def _resolve_user(
    lookups: dict[str, dict[str, models.User]],
    remote: TimeMotoUser,
) -> models.User | None:
    by_rfid = lookups["rfid"]
    by_username = lookups["username"]
    by_email = lookups["email"]
    by_name = lookups["name"]
    if remote.rfid and remote.rfid in by_rfid:
        return by_rfid[remote.rfid]
    if remote.code and remote.code.lower() in by_username:
        return by_username[remote.code.lower()]
    if remote.email and remote.email.lower() in by_email:
        return by_email[remote.email.lower()]
    if remote.full_name:
        normalized = remote.full_name.strip().lower()
        if normalized in by_name:
            return by_name[normalized]
    return None


def _match_event_user(
    lookups: dict[str, dict[str, models.User]],
    alias_map: dict[str, models.User],
    event: TimeMotoEvent,
) -> models.User | None:
    if event.rfid:
        by_rfid = lookups["rfid"]
        if event.rfid in by_rfid:
            return by_rfid[event.rfid]
    if event.user_code:
        normalized = str(event.user_code).strip().lower()
        if normalized in alias_map:
            return alias_map[normalized]
        by_username = lookups["username"]
        if normalized in by_username:
            return by_username[normalized]
    return None


def _to_local(dt: datetime, zone: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def synchronize(
    db: Session,
    config: TimeMotoConfig,
    *,
    full_sync: bool = False,
) -> TimeMotoSyncResult:
    """Synchronises users and time records from the TimeMoto device."""

    with TimeMotoClient(config) as client:
        client.authenticate()
        remote_users = client.fetch_users()
        result = TimeMotoSyncResult(remote_users=len(remote_users))
        existing_users = crud.get_users(db)
        lookups = _prepare_user_lookups(existing_users)
        alias_map: dict[str, models.User] = {}
        for remote_user in remote_users:
            user = _resolve_user(lookups, remote_user)
            if not user:
                continue
            result.matched_users += 1
            updated = False
            if remote_user.rfid and remote_user.rfid != user.rfid_tag:
                user.rfid_tag = remote_user.rfid
                lookups["rfid"][remote_user.rfid] = user
                updated = True
            if updated:
                result.updated_rfids += 1
                db.add(user)
            for identifier in remote_user.identifiers():
                alias_map.setdefault(identifier, user)
        if result.updated_rfids:
            db.commit()
        since_id = None if full_sync else config.last_event_id
        events = client.fetch_events(since_id)
        result.remote_events = len(events)
        zone = config.zoneinfo
        filtered_events: list[TimeMotoEvent] = []
        for event in events:
            if not full_sync and config.last_event_id is not None and event.record_id is not None:
                if event.record_id <= config.last_event_id:
                    continue
            filtered_events.append(event)
        filtered_events.sort(
            key=lambda entry: (
                entry.timestamp,
                entry.record_id if entry.record_id is not None else 0,
            )
        )
        max_event_id = config.last_event_id or None
        events_by_user: dict[int, list[TimeMotoEvent]] = {}
        users_by_id = {user.id: user for user in existing_users}
        for event in filtered_events:
            user = _match_event_user(lookups, alias_map, event)
            if not user:
                result.unmatched_events += 1
                continue
            events_by_user.setdefault(user.id, []).append(event)
            if event.record_id is not None:
                if max_event_id is None or event.record_id > max_event_id:
                    max_event_id = event.record_id
        for user_id, user_events in events_by_user.items():
            user = users_by_id.get(user_id)
            if not user:
                continue
            pending_event: TimeMotoEvent | None = None
            user_events.sort(
                key=lambda entry: (
                    entry.timestamp,
                    entry.record_id if entry.record_id is not None else 0,
                )
            )
            for event in user_events:
                is_in = event.is_clock_in()
                is_out = event.is_clock_out()
                if not is_in and not is_out:
                    if pending_event is None:
                        is_in = True
                    else:
                        is_out = True
                if is_in:
                    if pending_event is None:
                        pending_event = event
                    else:
                        result.skipped_events += 1
                        pending_event = event
                elif is_out:
                    if pending_event is None:
                        result.skipped_events += 1
                        continue
                    start_event = pending_event
                    pending_event = None
                    start_local = _to_local(start_event.timestamp, zone)
                    end_local = _to_local(event.timestamp, zone)
                    work_date = start_local.date()
                    start_time = start_local.time().replace(microsecond=0)
                    end_time = end_local.time().replace(microsecond=0)
                    external_id = None
                    if start_event.record_id is not None and event.record_id is not None:
                        external_id = f"{start_event.record_id}:{event.record_id}"
                    elif start_event.record_id is not None:
                        external_id = f"{start_event.record_id}-{int(end_local.timestamp())}"
                    elif event.record_id is not None:
                        external_id = f"{int(start_local.timestamp())}-{event.record_id}"
                    else:
                        external_id = f"{user_id}-{int(start_local.timestamp())}-{int(end_local.timestamp())}"
                    entry = schemas.TimeEntryCreate(
                        user_id=user_id,
                        company_id=None,
                        work_date=work_date,
                        start_time=start_time,
                        end_time=end_time,
                        break_minutes=0,
                        break_started_at=None,
                        is_open=False,
                        notes="Importiert über TimeMoto TM-616",
                        status=models.TimeEntryStatus.APPROVED,
                        is_manual=False,
                        source="timemoto",
                        external_id=external_id,
                    )
                    result.processed_events += 2
                    duplicate = False
                    if entry.source and entry.external_id:
                        existing_entry = crud.get_time_entry_by_external_reference(
                            db, entry.source, entry.external_id
                        )
                        duplicate = existing_entry is not None
                    if duplicate:
                        continue
                    try:
                        crud.create_time_entry(db, entry)
                    except ValueError:
                        result.skipped_events += 1
                    else:
                        result.created_entries += 1
            if pending_event is not None:
                result.skipped_events += 1
        if max_event_id is not None:
            config.last_event_id = max_event_id
        config.last_sync_at = datetime.utcnow().replace(microsecond=0).isoformat()
        result.last_event_id = config.last_event_id
        result.last_sync_at = config.last_sync_at
        return result

from __future__ import annotations

import json
import os
import shutil
import logging
import socket
import subprocess
from calendar import monthrange
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import __version__ as APP_VERSION
from . import crud, database, holiday_calculator, models, schemas, services
from .excel_export import export_time_entries
from .pdf_export import export_team_overview_pdf, export_time_overview_pdf

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="Erfassung",
    description="Zeiterfassung mit Überstunden & Urlaub",
    version=APP_VERSION,
)

app.add_middleware(SessionMiddleware, secret_key="zeit-erfassung-secret-key")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.utcnow
templates.env.globals["app_version"] = APP_VERSION

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UPDATE_REPO = os.environ.get("ERFASSUNG_REPO_URL", "https://github.com/joni123467/Erfassung")
UPDATE_SCRIPT_PATH = APP_ROOT / "update.sh"
UPDATE_LOG_PATH = APP_ROOT / "logs" / "update.log"


def _parse_overtime_limit_hours(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    normalized = text.replace(",", ".")
    try:
        hours = float(normalized)
    except ValueError as exc:
        raise ValueError("Ungültiges Überstundenlimit") from exc
    if hours < 0:
        raise ValueError("Überstundenlimit darf nicht negativ sein")
    return int(round(hours * 60))


def _format_minutes(value: object) -> str:
    if value is None:
        return "00:00"
    try:
        minutes = int(round(float(value)))
    except (TypeError, ValueError):
        return "00:00"
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    hours, remainder = divmod(minutes, 60)
    return f"{sign}{hours:02d}:{remainder:02d}"


templates.env.filters["format_minutes"] = _format_minutes

HOLIDAY_STATE_CHOICES = sorted(holiday_calculator.GERMAN_STATES.items(), key=lambda item: item[1])
HOLIDAY_STATE_CODES = set(holiday_calculator.GERMAN_STATES.keys())

TIME_ENTRY_STATUS_LABELS = {
    models.TimeEntryStatus.APPROVED: "Freigegeben",
    models.TimeEntryStatus.PENDING: "Wartet auf Freigabe",
    models.TimeEntryStatus.REJECTED: "Abgelehnt",
}


def _read_update_log(limit: int = 400) -> str:
    try:
        with UPDATE_LOG_PATH.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return ""
    if not lines:
        return ""
    tail = lines[-limit:]
    return "".join(tail)


def _update_ref_sort_key(value: str) -> tuple:
    if value == "main":
        return (0, 0, 0, 0, value)
    if value.startswith("version-"):
        number_part = value[len("version-") :]
        segments: list[int] = []
        for piece in number_part.split("."):
            try:
                segments.append(int(piece))
            except ValueError:
                segments.append(0)
        while len(segments) < 3:
            segments.append(0)
        major, minor, patch = segments[:3]
        return (1, -major, -minor, -patch, value)
    return (2, value.lower())


def _fetch_remote_refs_via_http(repo_url: str) -> set[str]:
    parsed = urlparse(repo_url)
    netloc = parsed.netloc.lower()
    if "github.com" not in netloc:
        return set()
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return set()
    owner, repository = parts[0], parts[1]
    if repository.endswith(".git"):
        repository = repository[:-4]
    api_base = f"https://api.github.com/repos/{owner}/{repository}"
    endpoints = [
        f"{api_base}/branches?per_page=100",
        f"{api_base}/tags?per_page=100",
    ]
    headers = {"Accept": "application/vnd.github+json"}
    refs: set[str] = set()
    for endpoint in endpoints:
        try:
            http_request = URLRequest(endpoint, headers=headers)
            with urlopen(http_request, timeout=10) as response:
                payload = response.read()
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError):
            continue
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        refs.add(name)
    return refs


def _list_remote_branches(repo_url: str) -> List[str]:
    refs: set[str] = set()
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", repo_url],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    else:
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            ref = parts[1]
            if ref.endswith("^{}"):
                continue
            if ref.startswith("refs/heads/"):
                refs.add(ref[len("refs/heads/") :])
            elif ref.startswith("refs/tags/"):
                refs.add(ref[len("refs/tags/") :])
    if not refs:
        refs.update(_fetch_remote_refs_via_http(repo_url))
    if not refs:
        return []
    return sorted(refs, key=_update_ref_sort_key)


def _execute_update(ref: str, repo_url: str) -> bool:
    UPDATE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    shell = shutil.which("bash") or shutil.which("sh")
    if not shell:
        raise FileNotFoundError("Keine Shell zum Ausführen des Update-Skripts gefunden")
    command = [
        shell,
        str(UPDATE_SCRIPT_PATH),
        "--app-dir",
        str(APP_ROOT),
        "--repo-url",
        repo_url,
        "--ref",
        ref,
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    with UPDATE_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] Starte Update auf '{ref}'\n")
        log_file.flush()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(APP_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:
            error_stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"[{error_stamp}] ❌ Update konnte nicht gestartet werden: {exc}\n\n")
            log_file.flush()
            raise
        assert process.stdout is not None
        with process.stdout:
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
        return_code = process.wait()
        end_stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if return_code == 0:
            log_file.write(f"[{end_stamp}] ✅ Update abgeschlossen\n\n")
            log_file.flush()
            return True
        log_file.write(f"[{end_stamp}] ❌ Update fehlgeschlagen (Exit {return_code})\n\n")
        log_file.flush()
        return False


def get_logged_in_user(request: Request, db: Session) -> Optional[models.User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return crud.get_user(db, user_id)


def _row_get(row: object, key: str, fallback_index: int | None = None):
    """Return a value from a SQLite PRAGMA row that may be tuple-like."""

    mapping = getattr(row, "_mapping", None)
    if mapping and key in mapping:
        return mapping[key]
    if fallback_index is not None:
        try:
            return row[fallback_index]  # type: ignore[index]
        except (IndexError, KeyError, TypeError):
            pass
    return None


logger = logging.getLogger(__name__)


def ensure_schema() -> None:
    with database.engine.begin() as connection:
        inspector = inspect(connection)
        table_names = inspector.get_table_names()
        if "companies" not in table_names:
            models.Base.metadata.tables["companies"].create(bind=connection)
        if "time_entries" in table_names:
            columns = {column["name"] for column in inspector.get_columns("time_entries")}
            if "company_id" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN company_id INTEGER"))
            if "break_started_at" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN break_started_at TIME"))
            if "is_open" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN is_open INTEGER DEFAULT 0"))
            if "status" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN status VARCHAR DEFAULT 'approved'"))
            if "is_manual" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN is_manual INTEGER DEFAULT 0"))
            connection.execute(text("UPDATE time_entries SET is_open = 0 WHERE is_open IS NULL"))
        if "users" in table_names:
            columns = {column["name"] for column in inspector.get_columns("users")}
            if "standard_weekly_hours" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN standard_weekly_hours FLOAT DEFAULT 40"))
                connection.execute(
                    text(
                        "UPDATE users SET standard_weekly_hours = COALESCE(standard_daily_minutes, 480) * 5.0 / 60.0"
                    )
                )
            if "time_account_enabled" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN time_account_enabled BOOLEAN DEFAULT 0")
                )
            if "overtime_vacation_enabled" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN overtime_vacation_enabled BOOLEAN DEFAULT 0")
                )
            if "annual_vacation_days" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN annual_vacation_days INTEGER DEFAULT 30")
                )
            if "vacation_carryover_enabled" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN vacation_carryover_enabled BOOLEAN DEFAULT 0")
                )
            if "vacation_carryover_days" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN vacation_carryover_days INTEGER DEFAULT 0")
                )
            if "rfid_tag" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN rfid_tag VARCHAR"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_rfid_tag ON users(rfid_tag)"))
            if "monthly_overtime_limit_minutes" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN monthly_overtime_limit_minutes INTEGER DEFAULT 1200"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE users SET monthly_overtime_limit_minutes = 1200 "
                        "WHERE monthly_overtime_limit_minutes IS NULL"
                    )
                )
        if "groups" in table_names:
            columns = {column["name"] for column in inspector.get_columns("groups")}
            if "can_manage_users" not in columns:
                connection.execute(text("ALTER TABLE groups ADD COLUMN can_manage_users BOOLEAN DEFAULT 0"))
            if "can_manage_vacations" not in columns:
                connection.execute(text("ALTER TABLE groups ADD COLUMN can_manage_vacations BOOLEAN DEFAULT 0"))
            if "can_approve_manual_entries" not in columns:
                connection.execute(
                    text("ALTER TABLE groups ADD COLUMN can_approve_manual_entries BOOLEAN DEFAULT 0")
                )
            if "can_create_companies" not in columns:
                connection.execute(
                    text("ALTER TABLE groups ADD COLUMN can_create_companies BOOLEAN DEFAULT 0")
                )
            if "can_view_time_reports" not in columns:
                connection.execute(
                    text("ALTER TABLE groups ADD COLUMN can_view_time_reports BOOLEAN DEFAULT 0")
                )
                connection.execute(
                    text("UPDATE groups SET can_view_time_reports = 1 WHERE is_admin = 1")
                )
        if "holidays" in table_names:
            index_rows = connection.execute(text("PRAGMA index_list('holidays')")).fetchall()
            legacy_unique_index = None
            for row in index_rows:
                name = _row_get(row, "name", 1)
                is_unique = _row_get(row, "unique", 2)
                if not is_unique or not str(name).startswith("sqlite_autoindex"):
                    continue
                index_info = connection.execute(text(f"PRAGMA index_info('{name}')")).fetchall()
                columns = [
                    _row_get(info, "name", 2)
                    for info in index_info
                ]
                if columns == ["date"]:
                    legacy_unique_index = name
                    break
            if legacy_unique_index:
                connection.execute(text("DROP TABLE IF EXISTS holidays_migrated"))
                connection.execute(
                    text(
                        """
CREATE TABLE holidays_migrated (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    date DATE NOT NULL,
    region VARCHAR DEFAULT 'DE',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, region)
)
"""
                    )
                )
                connection.execute(
                    text(
                        """
INSERT INTO holidays_migrated (id, name, date, region, created_at)
SELECT id, name, date, region, created_at FROM holidays
"""
                    )
                )
                connection.execute(text("DROP TABLE holidays"))
                connection.execute(text("ALTER TABLE holidays_migrated RENAME TO holidays"))
        if "vacation_requests" in table_names:
            columns = {column["name"] for column in inspector.get_columns("vacation_requests")}
            if "use_overtime" not in columns:
                connection.execute(
                    text("ALTER TABLE vacation_requests ADD COLUMN use_overtime BOOLEAN DEFAULT 0")
                )
            if "overtime_minutes" not in columns:
                connection.execute(
                    text("ALTER TABLE vacation_requests ADD COLUMN overtime_minutes INTEGER DEFAULT 0")
                )


def _sanitize_next(next_url: str, default: str = "/time") -> str:
    if not next_url:
        return default
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return default
    path = parsed.path or default
    if not path.startswith("/"):
        return default
    return path


def _build_redirect(path: str, **params: str) -> str:
    query = urlencode({key: value for key, value in params.items() if value})
    if query:
        return f"{path}?{query}"
    return path


def _resolve_month_period(month_param: Optional[str]) -> tuple[date, date, date]:
    try:
        if month_param:
            year, month = map(int, month_param.split("-"))
            selected_month = date(year, month, 1)
        else:
            selected_month = date.today().replace(day=1)
    except ValueError:
        selected_month = date.today().replace(day=1)
    last_day = monthrange(selected_month.year, selected_month.month)[1]
    start_date = selected_month
    end_date = date(selected_month.year, selected_month.month, last_day)
    return selected_month, start_date, end_date


def _aggregate_company_totals(source_entries: List[models.TimeEntry]):
    totals: dict[str, dict[str, object]] = {}
    for entry in source_entries:
        key = "none" if entry.company_id is None else str(entry.company_id)
        record = totals.setdefault(
            key,
            {
                "company_id": entry.company_id,
                "name": entry.company.name if entry.company else "Allgemein",
                "minutes": 0,
                "count": 0,
            },
        )
        record["minutes"] = int(record["minutes"]) + entry.worked_minutes
        record["count"] = int(record["count"]) + 1
    return sorted(totals.values(), key=lambda item: str(item["name"]).lower())


def _format_week_value(moment: date) -> str:
    iso_year, iso_week, _ = moment.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def _resolve_week_period(week_param: Optional[str]) -> tuple[date, date]:
    today = date.today()
    if week_param:
        try:
            start = datetime.strptime(f"{week_param}-1", "%G-W%V-%u").date()
        except ValueError:
            start = today - timedelta(days=today.weekday())
    else:
        start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def _parse_date_param(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_range_period(start_param: Optional[str], end_param: Optional[str]) -> tuple[date, date]:
    today = date.today()
    start = _parse_date_param(start_param) or today.replace(day=1)
    end = _parse_date_param(end_param) or start
    if end < start:
        start, end = end, start
    return start, end


def _build_user_totals(entries: List[models.TimeEntry]) -> List[dict[str, object]]:
    summary: dict[int, dict[str, object]] = {}
    for entry in entries:
        if not entry.user:
            continue
        record = summary.setdefault(
            entry.user_id,
            {
                "user": entry.user,
                "minutes": 0,
                "count": 0,
                "status_counts": Counter(),
                "companies": {},
            },
        )
        record["minutes"] = int(record["minutes"]) + entry.worked_minutes
        record["count"] = int(record["count"]) + 1
        record["status_counts"][entry.status] += 1
        company_name = entry.company.name if entry.company else "Allgemein"
        company_record = record["companies"].setdefault(
            company_name,
            {"name": company_name, "minutes": 0, "count": 0},
        )
        company_record["minutes"] = int(company_record["minutes"]) + entry.worked_minutes
        company_record["count"] = int(company_record["count"]) + 1

    results: List[dict[str, object]] = []
    for payload in summary.values():
        companies = list(payload["companies"].values())
        companies.sort(key=lambda item: (-int(item["minutes"]), str(item["name"]).lower()))
        primary_company = companies[0]["name"] if companies else "Allgemein"
        status_counts: Counter = payload["status_counts"]
        status_breakdown = [
            {
                "status": status,
                "label": TIME_ENTRY_STATUS_LABELS.get(status, status.title()),
                "count": status_counts.get(status, 0),
            }
            for status in (
                models.TimeEntryStatus.APPROVED,
                models.TimeEntryStatus.PENDING,
                models.TimeEntryStatus.REJECTED,
            )
            if status_counts.get(status, 0)
        ]
        results.append(
            {
                "user": payload["user"],
                "minutes": int(payload["minutes"]),
                "count": int(payload["count"]),
                "status_counts": status_counts,
                "status_breakdown": status_breakdown,
                "companies": companies,
                "primary_company": primary_company,
            }
        )
    return results


def _build_time_report_data(params, db: Session) -> dict[str, object]:
    view = params.get("view", "month")
    if view not in {"month", "week", "range"}:
        view = "month"
    status_param = params.get("status", "approved")
    if status_param not in {"approved", "pending", "rejected", "all"}:
        status_param = "approved"
    sort_param = params.get("sort", "name")
    if sort_param not in {"name", "minutes_desc", "entries_desc", "company"}:
        sort_param = "name"
    company_param = params.get("company", "")

    if view == "week":
        start_date, end_date = _resolve_week_period(params.get("week"))
        reference_month = start_date.replace(day=1)
        month_value = f"{reference_month.year:04d}-{reference_month.month:02d}"
        week_value = _format_week_value(start_date)
    elif view == "range":
        start_date, end_date = _resolve_range_period(params.get("start"), params.get("end"))
        month_value = f"{start_date.year:04d}-{start_date.month:02d}"
        week_value = _format_week_value(start_date)
    else:
        selected_month, start_date, end_date = _resolve_month_period(params.get("month"))
        month_value = f"{selected_month.year:04d}-{selected_month.month:02d}"
        week_value = _format_week_value(start_date)

    range_start_value = start_date.strftime("%Y-%m-%d")
    range_end_value = end_date.strftime("%Y-%m-%d")

    status_filters = {
        "approved": [models.TimeEntryStatus.APPROVED],
        "pending": [models.TimeEntryStatus.PENDING],
        "rejected": [models.TimeEntryStatus.REJECTED],
        "all": None,
    }
    statuses = status_filters[status_param]

    entries = list(
        crud.get_time_entries(
            db,
            start=start_date,
            end=end_date,
            statuses=statuses,
        )
    )

    company_filter_id: Optional[int] = None
    company_filter_none = False
    company_param_value = company_param
    if company_param == "none":
        company_filter_none = True
    elif company_param:
        try:
            company_filter_id = int(company_param)
        except ValueError:
            company_filter_id = None

    if company_filter_none:
        entries = [entry for entry in entries if entry.company_id is None]
    elif company_filter_id is not None:
        entries = [entry for entry in entries if entry.company_id == company_filter_id]

    entries_sorted = sorted(
        entries,
        key=lambda item: (
            item.work_date,
            item.start_time,
            item.user.full_name.lower() if item.user else "",
        ),
    )

    total_minutes = sum(entry.worked_minutes for entry in entries)
    total_entries = len(entries)
    unique_users = len({entry.user_id for entry in entries})

    status_counts = Counter(entry.status for entry in entries)
    status_order = [
        models.TimeEntryStatus.APPROVED,
        models.TimeEntryStatus.PENDING,
        models.TimeEntryStatus.REJECTED,
    ]
    status_summary = [
        {
            "key": status,
            "label": TIME_ENTRY_STATUS_LABELS.get(status, status.title()),
            "count": status_counts.get(status, 0),
        }
        for status in status_order
        if status_counts.get(status, 0)
    ]

    company_totals = _aggregate_company_totals(entries)
    company_totals.sort(key=lambda row: (-int(row["minutes"]), str(row["name"]).lower()))

    user_totals = _build_user_totals(entries)
    if sort_param == "minutes_desc":
        user_totals.sort(key=lambda item: (-int(item["minutes"]), item["user"].full_name.lower()))
    elif sort_param == "entries_desc":
        user_totals.sort(key=lambda item: (-int(item["count"]), item["user"].full_name.lower()))
    elif sort_param == "company":
        user_totals.sort(key=lambda item: (item["primary_company"].lower(), item["user"].full_name.lower()))
    else:
        user_totals.sort(key=lambda item: item["user"].full_name.lower())

    period_range = (
        f"{start_date.strftime('%d.%m.%Y')} – {end_date.strftime('%d.%m.%Y')}"
        if start_date != end_date
        else start_date.strftime("%d.%m.%Y")
    )

    if view == "week":
        iso_year, iso_week, _ = start_date.isocalendar()
        period_label = f"KW {iso_week:02d}/{iso_year}"
        period_filename = f"{iso_year}_KW{iso_week:02d}"
    elif view == "range":
        period_label = period_range
        period_filename = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
    else:
        period_label = start_date.strftime("%m/%Y")
        period_filename = start_date.strftime("%Y_%m")

    status_options = [
        {"value": "approved", "label": TIME_ENTRY_STATUS_LABELS[models.TimeEntryStatus.APPROVED]},
        {"value": "pending", "label": TIME_ENTRY_STATUS_LABELS[models.TimeEntryStatus.PENDING]},
        {"value": "rejected", "label": TIME_ENTRY_STATUS_LABELS[models.TimeEntryStatus.REJECTED]},
        {"value": "all", "label": "Alle Stände"},
    ]
    sort_options = [
        {"value": "name", "label": "Name A–Z"},
        {"value": "minutes_desc", "label": "Arbeitszeit (absteigend)"},
        {"value": "entries_desc", "label": "Buchungen (absteigend)"},
        {"value": "company", "label": "Firma A–Z"},
    ]

    query_params = {
        "view": view,
        "status": status_param,
        "sort": sort_param,
    }
    if view == "month":
        query_params["month"] = month_value
    elif view == "week":
        query_params["week"] = week_value
    else:
        query_params["start"] = range_start_value
        query_params["end"] = range_end_value
    if company_param_value:
        query_params["company"] = company_param_value
    export_query = urlencode({key: value for key, value in query_params.items() if value})

    companies = crud.get_companies(db)
    company_filter_label = "Alle Firmen"
    if company_filter_none:
        company_filter_label = "Allgemeine Arbeitszeit"
    elif company_filter_id is not None:
        for company in companies:
            if company.id == company_filter_id:
                company_filter_label = company.name
                break

    return {
        "view": view,
        "status_param": status_param,
        "sort_param": sort_param,
        "month_value": month_value,
        "week_value": week_value,
        "range_start_value": range_start_value,
        "range_end_value": range_end_value,
        "company_filter_id": company_filter_id,
        "company_filter_none": company_filter_none,
        "company_param": company_param_value,
        "company_filter_label": company_filter_label,
        "companies": companies,
        "entries": entries,
        "entries_sorted": entries_sorted,
        "total_minutes": total_minutes,
        "total_entries": total_entries,
        "unique_users": unique_users,
        "status_summary": status_summary,
        "status_counts": status_counts,
        "company_totals": company_totals,
        "user_totals": user_totals,
        "period_label": period_label,
        "period_range": period_range,
        "period_filename": period_filename,
        "start_date": start_date,
        "end_date": end_date,
        "status_options": status_options,
        "sort_options": sort_options,
        "export_query": export_query,
        "status_labels": TIME_ENTRY_STATUS_LABELS,
    }
def _seed_default_records() -> None:
    db = database.SessionLocal()
    try:
        if not crud.get_groups(db):
            admin_group = crud.create_group(
                db,
                schemas.GroupCreate(
                    name="Administration",
                    is_admin=True,
                    can_manage_users=True,
                    can_manage_vacations=True,
                    can_approve_manual_entries=True,
                    can_create_companies=True,
                    can_view_time_reports=True,
                ),
            )
        else:
            admin_group = (
                db.query(models.Group)
                .filter(models.Group.is_admin == True)  # noqa: E712
                .first()
            )
            if admin_group:
                admin_group.can_manage_users = True
                admin_group.can_manage_vacations = True
                admin_group.can_approve_manual_entries = True
                admin_group.can_create_companies = True
                admin_group.can_view_time_reports = True
                db.commit()
        if not crud.get_companies(db):
            crud.create_company(db, schemas.CompanyCreate(name="Allgemein"))
        if not crud.get_users(db):
            crud.create_user(
                db,
                schemas.UserCreate(
                    username="admin",
                    full_name="Administrator",
                    email="admin@example.com",
                    group_id=admin_group.id if admin_group else None,
                    standard_weekly_hours=40.0,
                    pin_code="0000",
                ),
            )
    finally:
        db.close()


@app.on_event("startup")
def ensure_seed_data():
    ensure_schema()
    try:
        _seed_default_records()
    except OperationalError as exc:
        logger.warning(
            "Database schema mismatch detected during startup. Attempting automatic repair.",
            exc_info=exc,
        )
        ensure_schema()
        try:
            _seed_default_records()
        except OperationalError:
            logger.error(
                "Automatic schema repair failed; manual intervention required.",
                exc_info=True,
            )
            raise


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    response = await call_next(request)
    return response


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "user": None})


@app.post("/login")
def login_submit(request: Request, pin_code: str = Form(...), db: Session = Depends(database.get_db)):
    user = crud.get_user_by_pin(db, pin_code)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "PIN konnte nicht gefunden werden.", "user": None},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    today = date.today()
    reference_month = today
    metrics = services.calculate_dashboard_metrics(db, user.id, reference_month)
    active_entry = crud.get_open_time_entry(db, user.id)
    holiday_region = crud.get_default_holiday_region(db)
    holiday_region_label = holiday_calculator.GERMAN_STATES.get(holiday_region, holiday_region)
    holidays = crud.get_holidays_for_year(db, date.today().year, holiday_region)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    companies = crud.get_companies(db)
    daily_entries = crud.get_time_entries_for_user(db, user.id, start=today, end=today)
    daily_entries = sorted(daily_entries, key=lambda entry: (entry.start_time, entry.id))
    daily_total_minutes = sum(entry.worked_minutes for entry in daily_entries)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    weekly_entries = crud.get_time_entries_for_user(db, user.id, start=week_start, end=week_end)
    weekly_total_minutes = sum(entry.worked_minutes for entry in weekly_entries)
    weekly_target_minutes = int(round(user.weekly_target_minutes or 0)) if user else 0
    daily_target_minutes = int(round(user.daily_target_minutes or 0)) if user else 0
    elapsed_workdays = sum(
        1
        for offset in range((today - week_start).days + 1)
        if (week_start + timedelta(days=offset)).weekday() < 5 and (week_start + timedelta(days=offset)) <= today
    )
    expected_minutes_to_date = elapsed_workdays * daily_target_minutes
    remaining_week_minutes = max(weekly_target_minutes - weekly_total_minutes, 0)
    progress_percent = (
        min(int(round((weekly_total_minutes / weekly_target_minutes) * 100)), 100)
        if weekly_target_minutes
        else 0
    )
    progress_to_date_percent = (
        min(int(round((weekly_total_minutes / expected_minutes_to_date) * 100)), 100)
        if expected_minutes_to_date
        else 0
    )
    week_days = []
    current_day = week_start
    while current_day <= week_end:
        day_minutes = sum(entry.worked_minutes for entry in weekly_entries if entry.work_date == current_day)
        target_for_day = daily_target_minutes if current_day.weekday() < 5 else 0
        week_days.append(
            {
                "date": current_day,
                "minutes": day_minutes,
                "target_minutes": target_for_day,
                "is_today": current_day == today,
            }
        )
        current_day += timedelta(days=1)
    weekly_summary = {
        "week_start": week_start,
        "week_end": week_end,
        "total_minutes": weekly_total_minutes,
        "target_minutes": weekly_target_minutes,
        "expected_minutes_to_date": expected_minutes_to_date,
        "remaining_minutes": remaining_week_minutes,
        "progress_percent": progress_percent,
        "progress_to_date_percent": progress_to_date_percent,
        "days": week_days,
    }
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "metrics": metrics,
            "holidays": holidays,
            "holiday_region": holiday_region,
            "holiday_region_label": holiday_region_label,
            "companies": companies,
            "message": message,
            "error": error,
            "active_entry": active_entry,
            "metrics_month": reference_month.replace(day=1),
            "can_create_companies": _can_create_companies(user),
            "daily_entries": daily_entries,
            "daily_total_minutes": daily_total_minutes,
            "today": today,
            "weekly_summary": weekly_summary,
        },
    )


@app.post("/time")
def submit_time_entry(
    request: Request,
    work_date: date = Form(...),
    start_time: time = Form(...),
    end_time: time = Form(...),
    break_minutes: int = Form(0),
    notes: str = Form(""),
    company_id: Optional[str] = Form(None),
    new_company_name: Optional[str] = Form(None),
    next_url: str = Form("/time"),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if break_minutes < 0:
        break_minutes = 0
    if end_time <= start_time:
        redirect = _build_redirect(_sanitize_next(next_url), error="Endzeit muss nach der Startzeit liegen")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    new_company_value = (new_company_name or "").strip()
    company_value: Optional[int] = None
    if new_company_value:
        if not _can_create_companies(user):
            redirect = _build_redirect(
                _sanitize_next(next_url), error="Du darfst keine neuen Firmen anlegen."
            )
            return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
        existing_company = crud.get_company_by_name(db, new_company_value)
        if existing_company:
            company_value = existing_company.id
        else:
            created_company = crud.create_company(db, schemas.CompanyCreate(name=new_company_value))
            company_value = created_company.id
    elif company_id:
        try:
            company_value = int(company_id)
        except (TypeError, ValueError):
            redirect = _build_redirect(_sanitize_next(next_url), error="Ungültige Firmenauswahl")
            return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    try:
        entry = schemas.TimeEntryCreate(
            user_id=user.id,
            company_id=company_value,
            work_date=work_date,
            start_time=start_time,
            end_time=end_time,
            break_minutes=break_minutes,
            break_started_at=None,
            is_open=False,
            notes=notes,
            status=models.TimeEntryStatus.PENDING,
            is_manual=True,
        )
        crud.create_time_entry(db, entry)
    except ValueError:
        redirect = _build_redirect(_sanitize_next(next_url), error="Ungültige Zeiteingabe")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        _sanitize_next(next_url), msg="Zeitbuchung eingereicht und wartet auf Freigabe"
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/punch")
def punch_action(
    request: Request,
    action: str = Form(...),
    company_id: Optional[str] = Form(None),
    new_company_name: Optional[str] = Form(None),
    notes: str = Form(""),
    next_url: str = Form("/dashboard"),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    target = _sanitize_next(next_url)
    active_entry = crud.get_open_time_entry(db, user.id)
    now = datetime.now()
    message = ""
    error = ""

    if action == "start_work":
        if active_entry:
            error = "Es läuft bereits eine Arbeitszeit."
        else:
            crud.start_running_entry(db, user_id=user.id, started_at=now, notes=notes.strip())
            message = "Arbeitszeit gestartet."
    elif action == "start_company":
        new_company_value = (new_company_name or "").strip()
        target_company = None
        created_company = False
        if new_company_value:
            if not _can_create_companies(user):
                error = "Du darfst keine neuen Firmen anlegen."
            else:
                existing_company = crud.get_company_by_name(db, new_company_value)
                if existing_company:
                    target_company = existing_company
                else:
                    try:
                        target_company = crud.create_company(
                            db,
                            schemas.CompanyCreate(name=new_company_value, description=""),
                        )
                        created_company = True
                    except IntegrityError:
                        db.rollback()
                        error = "Firma existiert bereits."
        else:
            if not company_id:
                error = "Bitte eine Firma auswählen oder neu anlegen."
            else:
                try:
                    company_value = int(company_id)
                except ValueError:
                    error = "Ungültige Firma ausgewählt."
                else:
                    target_company = crud.get_company(db, company_value)
                    if not target_company:
                        error = "Firma wurde nicht gefunden."
        if not error and target_company:
            if active_entry and active_entry.company_id == target_company.id:
                error = "Dieser Auftrag läuft bereits."
            else:
                previous_company = active_entry.company if active_entry else None
                if active_entry:
                    crud.finish_running_entry(db, active_entry, now)
                crud.start_running_entry(
                    db,
                    user_id=user.id,
                    started_at=now,
                    company_id=target_company.id,
                    notes=notes.strip(),
                )
                if created_company:
                    message = f"Neue Firma {target_company.name} angelegt und Auftrag gestartet."
                elif previous_company and previous_company.id != target_company.id:
                    message = f"Auftrag zu {target_company.name} gewechselt."
                else:
                    message = f"Auftrag bei {target_company.name} gestartet."
    elif action == "end_work":
        if not active_entry:
            error = "Keine laufende Arbeitszeit vorhanden."
        else:
            crud.finish_running_entry(db, active_entry, now)
            message = "Arbeitszeit beendet."
    elif action == "end_company":
        if not active_entry or active_entry.company_id is None:
            error = "Es läuft kein Auftrag."
        else:
            crud.finish_running_entry(db, active_entry, now)
            crud.start_running_entry(
                db,
                user_id=user.id,
                started_at=now,
                notes=notes.strip(),
            )
            message = "Auftrag beendet. Arbeitszeit läuft weiter."
    elif action == "start_break":
        if not active_entry:
            error = "Keine laufende Arbeitszeit vorhanden."
        elif active_entry.break_started_at:
            error = "Pause läuft bereits."
        else:
            crud.start_break(db, active_entry, now)
            message = "Pause gestartet."
    elif action == "end_break":
        if not active_entry:
            error = "Keine laufende Arbeitszeit vorhanden."
        elif not active_entry.break_started_at:
            error = "Es läuft keine Pause."
        else:
            crud.end_break(db, active_entry, now)
            message = "Pause beendet."
    else:
        error = "Unbekannte Aktion."

    params = {}
    if message and not error:
        params["msg"] = message
    if error:
        params["error"] = error
    redirect = _build_redirect(target, **params)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/vacations", response_class=HTMLResponse)
def vacation_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    params = dict(request.query_params)
    redirect = _build_redirect("/records/vacations", **params)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/vacations")
def submit_vacation(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    comment: str = Form(""),
    use_overtime: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if end_date < start_date:
        return RedirectResponse(
            url="/records/vacations?error=Enddatum+darf+nicht+vor+dem+Startdatum+liegen",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    use_overtime_value = bool(use_overtime == "on" and user.overtime_vacation_enabled)
    overtime_minutes = 0
    if use_overtime_value:
        overtime_minutes = services.calculate_required_vacation_minutes(user, start_date, end_date)
    crud.create_vacation_request(
        db,
        schemas.VacationRequestCreate(
            user_id=user.id,
            start_date=start_date,
            end_date=end_date,
            comment=comment,
            use_overtime=use_overtime_value,
            overtime_minutes=overtime_minutes,
        ),
    )
    return RedirectResponse(
        url="/records/vacations?msg=Urlaubsantrag+erstellt",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/records", response_class=HTMLResponse)
def records_bookings_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    month_param = request.query_params.get("month")
    selected_month, start_date, end_date = _resolve_month_period(month_param)
    company_param = request.query_params.get("company")
    company_filter_id: Optional[int] = None
    company_filter_none = False
    if company_param == "none":
        company_filter_none = True
    elif company_param:
        try:
            company_filter_id = int(company_param)
        except ValueError:
            company_filter_id = None
    month_entries = list(
        crud.get_time_entries(
            db,
            user.id,
            start=start_date,
            end=end_date,
        )
    )
    entries = list(month_entries)
    if company_filter_none:
        entries = [entry for entry in entries if entry.company_id is None]
    elif company_filter_id is not None:
        entries = [entry for entry in entries if entry.company_id == company_filter_id]
    approved_month_entries = [
        entry for entry in month_entries if entry.status == models.TimeEntryStatus.APPROVED
    ]
    approved_entries = [entry for entry in entries if entry.status == models.TimeEntryStatus.APPROVED]
    total_work_minutes = sum(entry.worked_minutes for entry in approved_month_entries)
    target_minutes = services.calculate_monthly_target_minutes(
        user, selected_month.year, selected_month.month
    )
    vacations = crud.get_vacations_for_user(db, user.id)
    overtime_taken_minutes = services.calculate_vacation_overtime_in_range(
        user, vacations, start_date, end_date
    )
    effective_minutes = total_work_minutes + overtime_taken_minutes
    balance = effective_minutes - target_minutes
    total_overtime_minutes = max(balance, 0)
    total_undertime_minutes = max(-balance, 0) if user.time_account_enabled else 0
    vacation_summary = services.calculate_vacation_summary(user, vacations, selected_month.year)

    company_totals_all = _aggregate_company_totals(approved_month_entries)
    company_totals_filtered = _aggregate_company_totals(approved_entries)

    companies = crud.get_companies(db)
    month_value = f"{selected_month.year:04d}-{selected_month.month:02d}"
    return templates.TemplateResponse(
        "records/bookings.html",
        {
            "request": request,
            "user": user,
            "message": message,
            "error": error,
            "entries": entries,
            "approved_entries": approved_entries,
            "total_work_minutes": total_work_minutes,
            "total_overtime_minutes": total_overtime_minutes,
            "total_undertime_minutes": total_undertime_minutes,
            "target_minutes": target_minutes,
            "overtime_taken_minutes": overtime_taken_minutes,
            "company_totals_all": company_totals_all,
            "company_totals_filtered": company_totals_filtered,
            "companies": companies,
            "vacations": vacations,
            "vacation_summary": vacation_summary,
            "selected_month": selected_month,
            "month_value": month_value,
            "company_filter_id": company_filter_id,
            "company_filter_none": company_filter_none,
        },
    )


@app.get("/records/vacations", response_class=HTMLResponse)
def records_vacations_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    vacations = crud.get_vacations_for_user(db, user.id)
    today = date.today()
    vacation_summary = services.calculate_vacation_summary(user, vacations, today.year)
    pending_vacations = sum(1 for vacation in vacations if vacation.status == models.VacationRequestStatus.PENDING)
    return templates.TemplateResponse(
        "records/vacations.html",
        {
            "request": request,
            "user": user,
            "message": message,
            "error": error,
            "vacations": vacations,
            "vacation_summary": vacation_summary,
            "pending_vacations": pending_vacations,
        },
    )


@app.get("/records/pdf")
def export_records_pdf(request: Request, month: Optional[str] = None, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    selected_month, start_date, end_date = _resolve_month_period(month)
    month_entries = list(
        crud.get_time_entries(
            db,
            user.id,
            start=start_date,
            end=end_date,
        )
    )
    approved_month_entries = [
        entry for entry in month_entries if entry.status == models.TimeEntryStatus.APPROVED
    ]
    total_work_minutes = sum(entry.worked_minutes for entry in approved_month_entries)
    target_minutes = services.calculate_monthly_target_minutes(
        user, selected_month.year, selected_month.month
    )
    vacations = crud.get_vacations_for_user(db, user.id)
    overtime_taken_minutes = services.calculate_vacation_overtime_in_range(
        user, vacations, start_date, end_date
    )
    effective_minutes = total_work_minutes + overtime_taken_minutes
    balance = effective_minutes - target_minutes
    total_overtime_minutes = max(balance, 0)
    total_undertime_minutes = max(-balance, 0) if user.time_account_enabled else 0
    vacation_summary = services.calculate_vacation_summary(user, vacations, selected_month.year)
    company_totals_all = _aggregate_company_totals(approved_month_entries)
    overtime_limit_minutes = int(user.monthly_overtime_limit_minutes or 0)
    overtime_limit_exceeded = bool(
        overtime_limit_minutes and total_overtime_minutes > overtime_limit_minutes
    )
    overtime_limit_excess_minutes = (
        total_overtime_minutes - overtime_limit_minutes if overtime_limit_exceeded else 0
    )
    overtime_limit_remaining_minutes = (
        overtime_limit_minutes - total_overtime_minutes
        if overtime_limit_minutes and not overtime_limit_exceeded
        else 0
    )
    try:
        buffer = export_time_overview_pdf(
            user=user,
            selected_month=selected_month,
            entries=month_entries,
            total_work_minutes=total_work_minutes,
            target_minutes=target_minutes,
            overtime_taken_minutes=overtime_taken_minutes,
            total_overtime_minutes=total_overtime_minutes,
            total_undertime_minutes=total_undertime_minutes,
            vacation_summary=vacation_summary,
            company_totals=company_totals_all,
            overtime_limit_minutes=overtime_limit_minutes,
            overtime_limit_exceeded=overtime_limit_exceeded,
            overtime_limit_excess_minutes=overtime_limit_excess_minutes,
            overtime_limit_remaining_minutes=overtime_limit_remaining_minutes,
        )
    except RuntimeError as exc:
        redirect_params = []
        if month:
            redirect_params.append(("month", month))
        redirect_params.append(("error", str(exc)))
        query = urlencode(redirect_params)
        url = "/records"
        if query:
            url = f"{url}?{query}"
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    filename = f"arbeitszeit_{user.username}_{selected_month.strftime('%Y_%m')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _ensure_admin(user: models.User) -> bool:
    return bool(user.group and user.group.is_admin)


def _has_group_permission(user: models.User, attribute: str) -> bool:
    if _ensure_admin(user):
        return True
    if not user.group:
        return False
    return bool(getattr(user.group, attribute, False))


def _can_manage_users(user: models.User) -> bool:
    return _has_group_permission(user, "can_manage_users")


def _can_manage_vacations(user: models.User) -> bool:
    return _has_group_permission(user, "can_manage_vacations")


def _can_approve_manual_entries(user: models.User) -> bool:
    return _has_group_permission(user, "can_approve_manual_entries")


def _can_create_companies(user: models.User) -> bool:
    return _has_group_permission(user, "can_create_companies")


def _can_view_time_reports(user: models.User) -> bool:
    if _ensure_admin(user):
        return True
    return _has_group_permission(user, "can_view_time_reports")


def _resolve_admin_permissions(user: models.User) -> dict[str, bool]:
    permissions = {
        "users": _can_manage_users(user),
        "groups": _ensure_admin(user),
        "companies": _ensure_admin(user),
        "holidays": _ensure_admin(user),
        "approvals_manual": _can_approve_manual_entries(user),
        "approvals_vacations": _can_manage_vacations(user),
        "updates": _ensure_admin(user),
        "reports": _can_view_time_reports(user),
    }
    permissions["approvals"] = permissions["approvals_manual"] or permissions["approvals_vacations"]
    permissions["create_companies"] = _can_create_companies(user)
    return permissions


def _admin_template(
    template: str,
    request: Request,
    user: models.User,
    *,
    message: Optional[str] = None,
    error: Optional[str] = None,
    **context,
):
    payload = {
        "request": request,
        "user": user,
        "message": message,
        "error": error,
        "admin_permissions": _resolve_admin_permissions(user),
    }
    payload.update(context)
    return templates.TemplateResponse(template, payload)


@app.get("/admin", include_in_schema=False)
def admin_portal(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_list(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    users = crud.get_users(db)
    return _admin_template(
        "admin/users_list.html",
        request,
        user,
        message=message,
        error=error,
        users=users,
    )


@app.get("/admin/users/new", response_class=HTMLResponse)
def admin_users_new(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    groups = crud.get_groups(db)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/users_form.html",
        request,
        user,
        message=message,
        error=error,
        groups=groups,
        form_user=None,
    )


@app.get("/admin/users/{user_id}", response_class=HTMLResponse)
def admin_users_edit(request: Request, user_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    target = crud.get_user(db, user_id)
    if not target:
        return RedirectResponse(
            url="/admin/users?error=Benutzer+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    groups = crud.get_groups(db)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/users_form.html",
        request,
        user,
        message=message,
        error=error,
        groups=groups,
        form_user=target,
    )


@app.get("/admin/groups", response_class=HTMLResponse)
def admin_groups_list(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    groups = crud.get_groups(db)
    return _admin_template(
        "admin/groups_list.html",
        request,
        user,
        message=message,
        error=error,
        groups=groups,
    )


@app.get("/admin/groups/new", response_class=HTMLResponse)
def admin_groups_new(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/group_form.html",
        request,
        user,
        message=message,
        error=error,
        group=None,
    )


@app.get("/admin/groups/{group_id}", response_class=HTMLResponse)
def admin_groups_edit(request: Request, group_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    group = crud.get_group(db, group_id)
    if not group:
        return RedirectResponse(
            url="/admin/groups?error=Gruppe+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/group_form.html",
        request,
        user,
        message=message,
        error=error,
        group=group,
    )


@app.get("/admin/companies", response_class=HTMLResponse)
def admin_companies_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    companies = crud.get_companies(db)
    return _admin_template(
        "admin/companies.html",
        request,
        user,
        message=message,
        error=error,
        companies=companies,
    )


@app.get("/admin/companies/new", response_class=HTMLResponse)
def admin_companies_new(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/company_form.html",
        request,
        user,
        message=message,
        error=error,
        company=None,
    )


@app.get("/admin/companies/{company_id}", response_class=HTMLResponse)
def admin_companies_edit(request: Request, company_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    company = crud.get_company(db, company_id)
    if not company:
        return RedirectResponse(
            url="/admin/companies?error=Firma+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/company_form.html",
        request,
        user,
        message=message,
        error=error,
        company=company,
    )


@app.get("/admin/holidays", response_class=HTMLResponse)
def admin_holidays_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    selected_state_param = request.query_params.get("state")
    if selected_state_param:
        selected_state_param = selected_state_param.upper()
    selected_year_param = request.query_params.get("holiday_year")
    default_region = crud.get_default_holiday_region(db)
    selected_state = selected_state_param if selected_state_param in HOLIDAY_STATE_CODES else None
    if not selected_state:
        selected_state = default_region if default_region in HOLIDAY_STATE_CODES else "DE"
    try:
        selected_year = int(selected_year_param) if selected_year_param else date.today().year
    except ValueError:
        selected_year = date.today().year
    holidays = crud.get_holidays_for_year(db, selected_year, selected_state)
    return _admin_template(
        "admin/holidays.html",
        request,
        user,
        message=message,
        error=error,
        holidays=holidays,
        holiday_states=HOLIDAY_STATE_CHOICES,
        selected_state=selected_state,
        selected_year=selected_year,
    )


@app.get("/admin/approvals", response_class=HTMLResponse)
def admin_approvals_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    can_manual = _can_approve_manual_entries(user)
    can_vacation = _can_manage_vacations(user)
    if not (can_manual or can_vacation):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    pending_entries = (
        crud.get_time_entries(
            db,
            statuses=[models.TimeEntryStatus.PENDING],
            is_manual=True,
        )
        if can_manual
        else []
    )
    pending_vacations = (
        crud.get_vacation_requests(db, status=models.VacationStatus.PENDING)
        if can_vacation
        else []
    )
    return _admin_template(
        "admin/approvals.html",
        request,
        user,
        message=message,
        error=error,
        pending_entries=pending_entries,
        pending_vacations=pending_vacations,
        show_manual_section=can_manual,
        show_vacation_section=can_vacation,
    )


@app.get("/admin/reports/time", response_class=HTMLResponse)
def admin_time_reports_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_view_time_reports(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    report_data = _build_time_report_data(request.query_params, db)
    return _admin_template(
        "admin/time_reports.html",
        request,
        user,
        message=message,
        error=error,
        **report_data,
    )


@app.get("/admin/reports/time/pdf")
def admin_time_reports_pdf(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_view_time_reports(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    report_data = _build_time_report_data(request.query_params, db)
    try:
        buffer = export_team_overview_pdf(
            period_label=report_data["period_label"],
            period_range=report_data["period_range"],
            start_date=report_data["start_date"],
            end_date=report_data["end_date"],
            total_minutes=report_data["total_minutes"],
            total_entries=report_data["total_entries"],
            unique_users=report_data["unique_users"],
            status_summary=report_data["status_summary"],
            company_totals=report_data["company_totals"],
            user_totals=report_data["user_totals"],
            entries=report_data["entries_sorted"],
        )
    except RuntimeError as exc:
        params = list(request.query_params.multi_items())
        params.append(("error", str(exc)))
        query = urlencode(params)
        url = "/admin/reports/time"
        if query:
            url = f"{url}?{query}"
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    filename = f"team_zeit_{report_data['period_filename']}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/admin/reports/time/excel")
def admin_time_reports_excel(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_view_time_reports(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    report_data = _build_time_report_data(request.query_params, db)
    buffer = export_time_entries(report_data["entries_sorted"])
    filename = f"team_zeit_{report_data['period_filename']}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/admin/groups/create")
def create_group_html(
    request: Request,
    name: str = Form(...),
    is_admin: Optional[str] = Form(None),
    can_manage_users: Optional[str] = Form(None),
    can_manage_vacations: Optional[str] = Form(None),
    can_approve_manual_entries: Optional[str] = Form(None),
    can_create_companies: Optional[str] = Form(None),
    can_view_time_reports: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    is_admin_value = is_admin == "on"
    manage_users_value = can_manage_users == "on"
    manage_vacations_value = can_manage_vacations == "on"
    approve_manual_value = can_approve_manual_entries == "on"
    create_companies_value = can_create_companies == "on"
    view_time_reports_value = can_view_time_reports == "on"
    if is_admin_value:
        manage_users_value = True
        manage_vacations_value = True
        approve_manual_value = True
        create_companies_value = True
        view_time_reports_value = True
    try:
        crud.create_group(
            db,
            schemas.GroupCreate(
                name=name,
                is_admin=is_admin_value,
                can_manage_users=manage_users_value,
                can_manage_vacations=manage_vacations_value,
                can_approve_manual_entries=approve_manual_value,
                can_create_companies=create_companies_value,
                can_view_time_reports=view_time_reports_value,
            ),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/groups/new?error=Gruppe+existiert+bereits",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/groups?msg=Gruppe+angelegt", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/groups/{group_id}/update")
def update_group_html(
    request: Request,
    group_id: int,
    name: str = Form(...),
    is_admin: Optional[str] = Form(None),
    can_manage_users: Optional[str] = Form(None),
    can_manage_vacations: Optional[str] = Form(None),
    can_approve_manual_entries: Optional[str] = Form(None),
    can_create_companies: Optional[str] = Form(None),
    can_view_time_reports: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    is_admin_value = is_admin == "on"
    manage_users_value = can_manage_users == "on"
    manage_vacations_value = can_manage_vacations == "on"
    approve_manual_value = can_approve_manual_entries == "on"
    create_companies_value = can_create_companies == "on"
    view_time_reports_value = can_view_time_reports == "on"
    if is_admin_value:
        manage_users_value = True
        manage_vacations_value = True
        approve_manual_value = True
        create_companies_value = True
        view_time_reports_value = True
    try:
        updated = crud.update_group(
            db,
            group_id,
            schemas.GroupCreate(
                name=name,
                is_admin=is_admin_value,
                can_manage_users=manage_users_value,
                can_manage_vacations=manage_vacations_value,
                can_approve_manual_entries=approve_manual_value,
                can_create_companies=create_companies_value,
                can_view_time_reports=view_time_reports_value,
            ),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/admin/groups/{group_id}?error=Gruppenname+bereits+vergeben",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(
            url="/admin/groups?error=Gruppe+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/groups?msg=Gruppe+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/groups/{group_id}/delete")
def delete_group_html(request: Request, group_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    deleted = crud.delete_group(db, group_id)
    if not deleted:
        return RedirectResponse(
            url="/admin/groups?error=Gruppe+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/groups?msg=Gruppe+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/create")
def create_user_html(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    pin_code: str = Form(...),
    standard_weekly_hours: float = Form(40.0),
    monthly_overtime_limit_hours: Optional[str] = Form(None),
    group_id: Optional[str] = Form(None),
    time_account_enabled: Optional[str] = Form(None),
    overtime_vacation_enabled: Optional[str] = Form(None),
    annual_vacation_days: int = Form(30),
    vacation_carryover_enabled: Optional[str] = Form(None),
    vacation_carryover_days: int = Form(0),
    rfid_tag: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    group_value = int(group_id) if group_id else None
    time_account_value = time_account_enabled == "on"
    overtime_vacation_value = overtime_vacation_enabled == "on"
    if not time_account_value:
        overtime_vacation_value = False
    carryover_enabled = vacation_carryover_enabled == "on"
    carryover_days_value = vacation_carryover_days if carryover_enabled else 0
    rfid_value = (rfid_tag or "").strip() or None
    try:
        overtime_limit_minutes = _parse_overtime_limit_hours(monthly_overtime_limit_hours)
    except ValueError:
        return RedirectResponse(
            url="/admin/users/new?error=Ung%C3%BCltiges+%C3%9Cberstundenlimit",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name=full_name,
                email=email,
                pin_code=pin_code,
                standard_weekly_hours=standard_weekly_hours,
                group_id=group_value,
                time_account_enabled=time_account_value,
                overtime_vacation_enabled=overtime_vacation_value,
                annual_vacation_days=annual_vacation_days,
                vacation_carryover_enabled=carryover_enabled,
                vacation_carryover_days=carryover_days_value,
                rfid_tag=rfid_value,
                monthly_overtime_limit_minutes=overtime_limit_minutes,
            ),
        )
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        message = "Ungültige+Eingabe" if isinstance(exc, ValueError) else "Benutzer+konnte+nicht+angelegt+werden"
        return RedirectResponse(
            url=f"/admin/users/new?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/users?msg=Benutzer+angelegt", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/update")
def update_user_html(
    request: Request,
    user_id: int,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    pin_code: str = Form(...),
    standard_weekly_hours: float = Form(40.0),
    monthly_overtime_limit_hours: Optional[str] = Form(None),
    group_id: Optional[str] = Form(None),
    time_account_enabled: Optional[str] = Form(None),
    overtime_vacation_enabled: Optional[str] = Form(None),
    annual_vacation_days: int = Form(30),
    vacation_carryover_enabled: Optional[str] = Form(None),
    vacation_carryover_days: int = Form(0),
    rfid_tag: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    group_value = int(group_id) if group_id else None
    time_account_value = time_account_enabled == "on"
    overtime_vacation_value = overtime_vacation_enabled == "on"
    if not time_account_value:
        overtime_vacation_value = False
    carryover_enabled = vacation_carryover_enabled == "on"
    carryover_days_value = vacation_carryover_days if carryover_enabled else 0
    rfid_value = (rfid_tag or "").strip() or None
    try:
        overtime_limit_minutes = _parse_overtime_limit_hours(monthly_overtime_limit_hours)
    except ValueError:
        return RedirectResponse(
            url=f"/admin/users/{user_id}?error=Ung%C3%BCltiges+%C3%9Cberstundenlimit",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        updated = crud.update_user(
            db,
            user_id,
            schemas.UserUpdate(
                username=username,
                full_name=full_name,
                email=email,
                pin_code=pin_code,
                standard_weekly_hours=standard_weekly_hours,
                group_id=group_value,
                time_account_enabled=time_account_value,
                overtime_vacation_enabled=overtime_vacation_value,
                annual_vacation_days=annual_vacation_days,
                vacation_carryover_enabled=carryover_enabled,
                vacation_carryover_days=carryover_days_value,
                rfid_tag=rfid_value,
                monthly_overtime_limit_minutes=overtime_limit_minutes,
            ),
        )
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        message = "Ungültige+Eingabe" if isinstance(exc, ValueError) else "Aktualisierung+fehlgeschlagen"
        return RedirectResponse(
            url=f"/admin/users/{user_id}?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(
            url="/admin/users?error=Benutzer+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/users?msg=Benutzer+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/delete")
def delete_user_html(request: Request, user_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_user(db, user_id):
        return RedirectResponse(
            url="/admin/users?error=Benutzer+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/users?msg=Benutzer+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/companies/create")
def create_company_html(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    try:
        crud.create_company(
            db,
            schemas.CompanyCreate(name=name.strip(), description=description.strip()),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/companies/new?error=Firma+existiert+bereits",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/companies?msg=Firma+angelegt", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/companies/{company_id}/update")
def update_company_html(
    request: Request,
    company_id: int,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    try:
        updated = crud.update_company(
            db,
            company_id,
            schemas.CompanyUpdate(name=name.strip(), description=description.strip()),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/admin/companies/{company_id}?error=Firmenname+bereits+vergeben",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(
            url="/admin/companies?error=Firma+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/companies?msg=Firma+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/companies/{company_id}/delete")
def delete_company_html(request: Request, company_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_company(db, company_id):
        return RedirectResponse(
            url="/admin/companies?error=Firma+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/companies?msg=Firma+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/time-entries/{entry_id}/update")
def update_time_entry_html(
    request: Request,
    entry_id: int,
    user_id: int = Form(...),
    work_date: date = Form(...),
    start_time: time = Form(...),
    end_time: time = Form(...),
    break_minutes: int = Form(0),
    company_id: Optional[str] = Form(None),
    notes: str = Form(""),
    redirect_user: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if end_time <= start_time:
        redirect = _build_redirect(
            "/admin/users",
            error="Endzeit muss nach der Startzeit liegen",
            user=redirect_user,
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    company_value = int(company_id) if company_id else None
    try:
        updated = crud.update_time_entry(
            db,
            entry_id,
            schemas.TimeEntryCreate(
                user_id=user_id,
                company_id=company_value,
                work_date=work_date,
                start_time=start_time,
                end_time=end_time,
                break_minutes=max(break_minutes, 0),
                break_started_at=None,
                is_open=False,
                notes=notes,
            ),
        )
    except ValueError:
        redirect = _build_redirect(
            "/admin/users", error="Ungültige Angaben", user=redirect_user
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if not updated:
        redirect = _build_redirect(
            "/admin/users", error="Buchung nicht gefunden", user=redirect_user
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect("/admin/users", msg="Buchung aktualisiert", user=redirect_user)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/time-entries/{entry_id}/delete")
def delete_time_entry_html(
    request: Request,
    entry_id: int,
    redirect_user: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_time_entry(db, entry_id):
        redirect = _build_redirect(
            "/admin/users", error="Buchung konnte nicht gelöscht werden", user=redirect_user
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/admin/users", msg="Buchung gelöscht", user=redirect_user
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/time-entries/{entry_id}/status")
def set_time_entry_status_admin(
    request: Request,
    entry_id: int,
    action: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_approve_manual_entries(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if action == "approve":
        new_status = models.TimeEntryStatus.APPROVED
    elif action == "reject":
        new_status = models.TimeEntryStatus.REJECTED
    else:
        redirect = _build_redirect("/admin/approvals", error="Ungültige Aktion")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    updated = crud.set_time_entry_status(db, entry_id, new_status)
    if not updated:
        redirect = _build_redirect("/admin/approvals", error="Buchung nicht gefunden")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    message = "Buchung freigegeben" if new_status == models.TimeEntryStatus.APPROVED else "Buchung abgelehnt"
    redirect = _build_redirect("/admin/approvals", msg=message)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/holidays/sync")
def sync_holidays_admin(
    request: Request,
    state: str = Form(...),
    year: int = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    state = state.upper()
    if state not in HOLIDAY_STATE_CODES:
        redirect = _build_redirect(
            "/admin/holidays",
            error="Ungültiges Bundesland",
            state=state,
            holiday_year=str(year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if year < 1900 or year > 2100:
        redirect = _build_redirect(
            "/admin/holidays",
            error="Jahr muss zwischen 1900 und 2100 liegen",
            state=state,
            holiday_year=str(year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    holidays = holiday_calculator.ensure_holidays(db, year, state)
    redirect = _build_redirect(
        "/admin/holidays",
        msg=f"{len(holidays)}+Feiertage+aktualisiert",
        state=state,
        holiday_year=str(year),
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/vacations/{vacation_id}/status")
def set_vacation_status_admin(
    request: Request,
    vacation_id: int,
    action: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_vacations(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if action == "approve":
        new_status = models.VacationStatus.APPROVED
    elif action == "reject":
        new_status = models.VacationStatus.REJECTED
    else:
        redirect = _build_redirect("/admin/approvals", error="Ungültige Aktion")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    updated = crud.update_vacation_status(db, vacation_id, new_status)
    if not updated:
        redirect = _build_redirect("/admin/approvals", error="Urlaubsantrag nicht gefunden")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    message = "Urlaub genehmigt" if new_status == models.VacationStatus.APPROVED else "Urlaub abgelehnt"
    redirect = _build_redirect("/admin/approvals", msg=message)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/holidays/create")
def create_holiday_admin(
    request: Request,
    name: str = Form(...),
    holiday_date: date = Form(...),
    state: str = Form(...),
    region: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    state = state.upper()
    selected_state = state if state in HOLIDAY_STATE_CODES else "DE"
    custom_region = (region or "").strip()
    target_region = custom_region if custom_region else selected_state
    try:
        crud.upsert_holidays(
            db,
            [
                schemas.HolidayCreate(
                    name=name.strip(),
                    date=holiday_date,
                    region=target_region,
                )
            ],
        )
    except IntegrityError:
        db.rollback()
        redirect = _build_redirect(
            "/admin/holidays",
            error="Feiertag konnte nicht gespeichert werden",
            state=selected_state,
            holiday_year=str(holiday_date.year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/admin/holidays",
        msg="Feiertag+gespeichert",
        state=selected_state,
        holiday_year=str(holiday_date.year),
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/holidays/{holiday_id}/delete")
def delete_holiday_admin(
    request: Request,
    holiday_id: int,
    state: str = Form(...),
    year: int = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    state = state.upper()
    if not crud.delete_holiday(db, holiday_id):
        redirect = _build_redirect(
            "/admin/holidays",
            error="Feiertag konnte nicht gelöscht werden",
            state=state,
            holiday_year=str(year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/admin/holidays", msg="Feiertag gelöscht", state=state, holiday_year=str(year)
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/system", response_class=HTMLResponse)
def admin_system_overview(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    repo_url = DEFAULT_UPDATE_REPO
    branches = _list_remote_branches(repo_url)
    preferred_branch = f"version-{APP_VERSION}"
    selected = request.query_params.get("ref")
    if not selected:
        if preferred_branch in branches:
            selected = preferred_branch
        elif "main" in branches:
            selected = "main"
        elif branches:
            selected = branches[0]
        else:
            selected = preferred_branch
    if selected not in branches:
        branches = [selected] + [branch for branch in branches if branch != selected]
    if not branches:
        branches = [selected]
    updater_available = UPDATE_SCRIPT_PATH.exists()
    update_log = _read_update_log()
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/system.html",
        request,
        user,
        message=message,
        error=error,
        branches=branches,
        selected_branch=selected,
        repo_url=repo_url,
        updater_available=updater_available,
        update_log=update_log,
    )


@app.post("/admin/system/update")
def admin_system_trigger_update(
    request: Request,
    ref: str = Form(...),
    custom_ref: str = Form(""),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    preferred_branch = f"version-{APP_VERSION}"
    if not UPDATE_SCRIPT_PATH.exists():
        redirect = _build_redirect("/admin/system", error="Updater-Skript wurde nicht gefunden.")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    chosen_ref = (custom_ref or "").strip() or (ref or preferred_branch)
    repo_url = DEFAULT_UPDATE_REPO
    try:
        success = _execute_update(chosen_ref, repo_url)
    except Exception:
        redirect = _build_redirect(
            "/admin/system",
            error="Update konnte nicht gestartet werden. Bitte Log prüfen.",
            ref=chosen_ref,
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if success:
        redirect = _build_redirect(
            "/admin/system",
            msg="Update erfolgreich abgeschlossen.",
            ref=chosen_ref,
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/admin/system",
        error="Update fehlgeschlagen. Details im Update-Protokoll.",
        ref=chosen_ref,
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/api/groups", response_model=schemas.Group)
def create_group(group: schemas.GroupCreate, db: Session = Depends(database.get_db)):
    return crud.create_group(db, group)


@app.get("/api/groups", response_model=List[schemas.Group])
def list_groups(db: Session = Depends(database.get_db)):
    return crud.get_groups(db)


@app.post("/api/users", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    if crud.get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Benutzername bereits vergeben")
    return crud.create_user(db, user)


@app.get("/api/users", response_model=List[schemas.User])
def list_users(db: Session = Depends(database.get_db)):
    return crud.get_users(db)


@app.post("/api/time-entries", response_model=schemas.TimeEntry)
def create_time_entry(entry: schemas.TimeEntryCreate, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, entry.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    db_entry = crud.create_time_entry(db, entry)
    return schemas.TimeEntry.model_validate(db_entry)


@app.delete("/api/time-entries/{entry_id}")
def delete_time_entry(entry_id: int, db: Session = Depends(database.get_db)):
    if not crud.delete_time_entry(db, entry_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return {"detail": "Zeitbuchung gelöscht"}


@app.post("/api/vacations", response_model=schemas.VacationRequest)
def create_vacation(vacation: schemas.VacationRequestCreate, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, vacation.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    use_overtime = bool(vacation.use_overtime and user.overtime_vacation_enabled)
    overtime_minutes = (
        services.calculate_required_vacation_minutes(user, vacation.start_date, vacation.end_date)
        if use_overtime
        else 0
    )
    payload = vacation.model_copy(
        update={
            "use_overtime": use_overtime,
            "overtime_minutes": overtime_minutes,
        }
    )
    db_vacation = crud.create_vacation_request(db, payload)
    return schemas.VacationRequest.model_validate(db_vacation)


@app.post("/api/vacations/{vacation_id}/status", response_model=schemas.VacationRequest)
def update_vacation_status(vacation_id: int, status: str, db: Session = Depends(database.get_db)):
    updated = crud.update_vacation_status(db, vacation_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Urlaubseintrag nicht gefunden")
    return schemas.VacationRequest.model_validate(updated)


@app.post("/api/holidays/sync")
def sync_holidays(year: int, state: str = "BY", db: Session = Depends(database.get_db)):
    state = state.upper()
    region = state if state in HOLIDAY_STATE_CODES else "DE"
    holidays = holiday_calculator.ensure_holidays(db, year, region)
    return {"count": len(holidays), "state": region}


@app.get("/api/users/{user_id}/excel")
def export_user_time_entries(user_id: int, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    entries = crud.get_time_entries_for_user(db, user_id)
    buffer = export_time_entries(entries)
    filename = f"arbeitszeiten_{user.username}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}

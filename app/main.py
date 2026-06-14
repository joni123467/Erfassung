from __future__ import annotations

import os
import logging
import base64
import hashlib
import hmac
from calendar import monthrange
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse

import secrets

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status

try:  # FastAPI <=0.75 did not re-export BackgroundTasks
    from fastapi import BackgroundTasks
except ImportError:  # pragma: no cover - fallback for older FastAPI releases
    from starlette.background import BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import __version__ as APP_VERSION
from . import (
    app_config,
    backup_manager,
    backup_scheduler,
    crud,
    database,
    holiday_calculator,
    log_tools,
    logging_setup,
    models,
    paths,
    restore_jobs,
    restore_manager,
    schemas,
    security,
    services,
    system_info,
)
from .integrations import timemoto
from .excel_export import export_time_entries, export_user_summary_excel
from .pdf_export import (
    export_team_overview_pdf,
    export_time_overview_pdf,
    export_user_summary_pdf,
)

models.Base.metadata.create_all(bind=database.engine)

_SESSION_SECRET = os.environ.get("SESSION_SECRET_KEY", "zeit-erfassung-secret-key")
_HTTPS_ONLY_SESSION = os.environ.get("HTTPS_ONLY_SESSION", "false").lower() == "true"


def get_csrf_token(request: Request) -> str:
    """Return the CSRF token for the current session, creating it if absent."""
    if "session" not in request.scope:
        return ""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


class CSRFMiddleware:
    """Validate synchronizer CSRF tokens on all state-changing requests.

    Implemented as a pure ASGI middleware (not ``BaseHTTPMiddleware``): to read
    the ``csrf_token`` from a form POST we must consume the request body, which
    would otherwise leave nothing for the downstream endpoint to parse (causing
    a 422 "Field required" on e.g. /login). We therefore buffer the body and
    replay it to the application via a fresh ASGI ``receive`` callable.

    SessionMiddleware is registered *after* this middleware so that it runs
    further out; by the time we execute, ``scope["session"]`` is populated.
    """

    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
    _CSRF_ERROR_HTML = (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        "<title>Sitzungsfehler – Erfassung</title></head><body>"
        "<h1>403 – Ungültige Sitzung</h1>"
        "<p>Das Sicherheitstoken ist abgelaufen oder ungültig. "
        "Bitte lade die Seite neu.</p>"
        "<a href='/'>Zurück zur Startseite</a></body></html>"
    )

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def _replay(body: bytes):
        """Return an ASGI ``receive`` that yields the buffered body once."""
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        return receive

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        if request.method in self._SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        session = scope.get("session")
        session_token = session.get("csrf_token") if isinstance(session, dict) else None

        # Accept the token from an explicit header (fetch/XHR) …
        submitted_token = request.headers.get("x-csrf-token")

        # … or from the form body. Only then do we consume + replay the stream.
        if not submitted_token:
            content_type = request.headers.get("content-type", "")
            if (
                "application/x-www-form-urlencoded" in content_type
                or "multipart/form-data" in content_type
            ):
                body = await request.body()
                form = await Request(scope, self._replay(body)).form()
                submitted_token = form.get("csrf_token")  # type: ignore[assignment]
                receive = self._replay(body)  # replay for the downstream app

        if (
            not session_token
            or not submitted_token
            or not hmac.compare_digest(str(session_token), str(submitted_token))
        ):
            response = HTMLResponse(content=self._CSRF_ERROR_HTML, status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


app = FastAPI(
    title="Erfassung",
    description="Zeiterfassung mit Überstunden & Urlaub",
    version=APP_VERSION,
)

# NOTE: Starlette applies middleware in reverse registration order, so the
# LAST middleware added becomes the OUTERMOST (runs first). SessionMiddleware
# must run before CSRFMiddleware, otherwise request.session is not yet populated
# when the CSRF check reads it — which would reject every POST (incl. /login)
# with a 403 "Ungültige Sitzung". Therefore register CSRF first, Session last.
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    https_only=_HTTPS_ONLY_SESSION,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    """Serve the service worker from the application ROOT.

    A service worker can only control URLs under the path it is served from,
    unless the `Service-Worker-Allowed` header widens that scope. The app needs
    scope "/" so the worker can serve the `/mobile` start_url offline. Serving
    the script from /sw.js (root) with the header below makes scope "/" valid;
    a /static/sw.js registration with {scope:'/'} would be rejected by browsers.
    """
    content = (_STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    return Response(
        content,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            # The SW script itself must never be served stale, otherwise updates
            # (new cache version) would not roll out.
            "Cache-Control": "no-cache",
        },
    )


templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.utcnow
templates.env.globals["app_version"] = APP_VERSION
templates.env.globals["get_csrf_token"] = get_csrf_token

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


MOBILE_AUTOLOGIN_TTL_SECONDS = 60 * 60 * 24 * 30


def _mobile_autologin_secret() -> bytes:
    return os.getenv("MOBILE_AUTOLOGIN_SECRET", "erfassung-mobile-autologin-secret").encode("utf-8")


def _create_mobile_autologin_token(user_id: int, ttl_seconds: int = MOBILE_AUTOLOGIN_TTL_SECONDS) -> str:
    expires = int(datetime.utcnow().timestamp()) + ttl_seconds
    payload = f"{user_id}:{expires}"
    signature = hmac.new(_mobile_autologin_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _verify_mobile_autologin_token(token: str) -> Optional[int]:
    if not token:
        return None
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        user_id_text, expires_text, signature = decoded.split(":", 2)
        payload = f"{user_id_text}:{expires_text}"
        expected = hmac.new(_mobile_autologin_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        if int(expires_text) < int(datetime.utcnow().timestamp()):
            return None
        return int(user_id_text)
    except (ValueError, TypeError):
        return None

TIME_ENTRY_STATUS_LABELS = {
    models.TimeEntryStatus.APPROVED: "Freigegeben",
    models.TimeEntryStatus.PENDING: "Wartet auf Freigabe",
    models.TimeEntryStatus.REJECTED: "Abgelehnt",
}





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

if _SESSION_SECRET == "zeit-erfassung-secret-key":
    logger.warning(
        "SESSION_SECRET_KEY ist nicht gesetzt – unsicherer Standard wird verwendet. "
        "Bitte SESSION_SECRET_KEY als Umgebungsvariable setzen."
    )


def get_logged_in_user(request: Request, db: Session) -> Optional[models.User]:
    """Return the user referenced by the active session, if any."""

    if "session" not in request.scope:
        return None

    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        request.session.pop("user_id", None)
        return None

    user = crud.get_user(db, parsed_user_id)
    if user is None:
        request.session.pop("user_id", None)
    return user


def _should_force_password_change(path: str) -> bool:
    if path.startswith("/static"):
        return False
    allowed_paths = {"/logout", "/account/password"}
    return path not in allowed_paths


def ensure_schema() -> None:
    # ensure_schema() is a legacy SQLite upgrade helper using SQLite-specific
    # SQL (PRAGMA, "CREATE UNIQUE INDEX IF NOT EXISTS", length-less VARCHAR).
    # On MySQL the full current schema is created by metadata.create_all() and
    # any incremental column changes are applied by the dialect-aware versioned
    # migrations (app/db_migrations.py + app/db_schema.py).
    if not database.IS_SQLITE:
        return
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
            if "deleted_company_name" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN deleted_company_name VARCHAR"))
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
            if "auto_break_deduction" not in columns:
                # Default 1 keeps the existing behaviour for all current users.
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN auto_break_deduction BOOLEAN DEFAULT 1")
                )
                connection.execute(
                    text("UPDATE users SET auto_break_deduction = 1 WHERE auto_break_deduction IS NULL")
                )
            if "password_hash" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR"))
            if "must_change_password" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 1")
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
            if "can_edit_time_entries" not in columns:
                connection.execute(
                    text("ALTER TABLE groups ADD COLUMN can_edit_time_entries BOOLEAN DEFAULT 0")
                )
                connection.execute(
                    text("UPDATE groups SET can_edit_time_entries = 1 WHERE is_admin = 1")
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
                columns = [_row_get(info, "name", 2) for info in index_info]
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
        if "mobile_sync_actions" not in table_names:
            models.Base.metadata.tables["mobile_sync_actions"].create(bind=connection)
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
            if "previous_status" not in columns:
                connection.execute(
                    text("ALTER TABLE vacation_requests ADD COLUMN previous_status VARCHAR")
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
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path

def _build_redirect(path: str, **params: str) -> str:
    query = urlencode({key: value for key, value in params.items() if value})
    if query:
        return f"{path}?{query}"
    return path


def _build_redirect_with_next(
    default_path: str, next_url: Optional[str], **params: str
) -> str:
    sanitized = _sanitize_next(next_url or "", default_path)
    parsed = urlparse(sanitized)
    base_path = parsed.path or default_path
    merged_params = dict(parse_qsl(parsed.query))
    merged_params.update({key: value for key, value in params.items() if value})
    query = urlencode(merged_params)
    if query:
        return f"{base_path}?{query}"
    return base_path


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
                "name": entry.company.name if entry.company else "Allgemeine Arbeitszeit",
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


def _build_user_totals(
    entries: List[models.TimeEntry],
    vacation_minutes: Optional[dict[int, int]] = None,
) -> List[dict[str, object]]:
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
                "vacation_minutes": 0,
            },
        )
        record["minutes"] = int(record["minutes"]) + entry.worked_minutes
        record["count"] = int(record["count"]) + 1
        record["status_counts"][entry.status] += 1
        company_name = entry.company.name if entry.company else "Allgemeine Arbeitszeit"
        company_record = record["companies"].setdefault(
            company_name,
            {"name": company_name, "minutes": 0, "count": 0},
        )
        company_record["minutes"] = int(company_record["minutes"]) + entry.worked_minutes
        company_record["count"] = int(company_record["count"]) + 1
        if vacation_minutes and entry.user_id in vacation_minutes:
            record["vacation_minutes"] = vacation_minutes[entry.user_id]

    results: List[dict[str, object]] = []
    for payload in summary.values():
        companies = list(payload["companies"].values())
        companies.sort(key=lambda item: (-int(item["minutes"]), str(item["name"]).lower()))
        primary_company = companies[0]["name"] if companies else "Allgemeine Arbeitszeit"
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
                "vacation_minutes": int(payload.get("vacation_minutes", 0)),
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

    vacations = crud.get_vacations_in_range(
        db,
        start_date,
        end_date,
        statuses=[models.VacationStatus.APPROVED],
    )
    vacation_minutes_total = 0
    vacation_minutes_by_user: dict[int, int] = {}
    vacation_records: list[dict[str, object]] = []
    for vacation in vacations:
        if not vacation.user:
            continue
        overlap_start = max(start_date, vacation.start_date)
        overlap_end = min(end_date, vacation.end_date)
        credited = services.calculate_required_vacation_minutes(
            vacation.user,
            overlap_start,
            overlap_end,
        )
        if credited <= 0:
            continue
        vacation_minutes_total += credited
        vacation_minutes_by_user[vacation.user_id] = (
            vacation_minutes_by_user.get(vacation.user_id, 0) + credited
        )
        vacation_records.append(
            {
                "vacation": vacation,
                "start": overlap_start,
                "end": overlap_end,
                "minutes": credited,
            }
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

    # Anzeige-/Export-Reihenfolge: neueste Einträge zuerst (Datum + Startzeit
    # absteigend), Name als Tiebreaker aufsteigend. Stabile Zwei-Schritt-Sortierung;
    # ändert ausschließlich die Reihenfolge, keine Daten oder Berechnungen.
    entries_sorted = sorted(
        entries,
        key=lambda item: item.user.full_name.lower() if item.user else "",
    )
    entries_sorted = sorted(
        entries_sorted,
        key=lambda item: (item.work_date, item.start_time),
        reverse=True,
    )

    total_minutes = sum(entry.worked_minutes for entry in entries)
    effective_minutes = total_minutes + vacation_minutes_total
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

    user_totals = _build_user_totals(entries, vacation_minutes_by_user)
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
        "effective_minutes": effective_minutes,
        "vacation_minutes_total": vacation_minutes_total,
        "total_entries": total_entries,
        "unique_users": unique_users,
        "status_summary": status_summary,
        "status_counts": status_counts,
        "company_totals": company_totals,
        "user_totals": user_totals,
        "vacations": vacations,
        "vacation_records": vacation_records,
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
                    can_edit_time_entries=True,
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
                admin_group.can_edit_time_entries = True
                db.commit()
        companies = crud.get_companies(db)
        if not companies:
            crud.create_company(db, schemas.CompanyCreate(name="Firma"))
        else:
            legacy_default = (
                db.query(models.Company)
                .filter(models.Company.name == "Allgemein")
                .first()
            )
            if legacy_default:
                legacy_default.name = "Firma"
                db.commit()
        if not crud.get_users(db):
            crud.create_user(
                db,
                schemas.UserCreate(
                    username="admin",
                    full_name="Administrator",
                    email="admin@example.com",
                    group_id=admin_group.id if admin_group else None,
                    standard_weekly_hours=40.0,
                    password="Admin!0000",
                ),
            )
            admin_user = crud.get_user_by_username(db, "admin")
            if admin_user:
                admin_user.password_hash = security.hash_password("0000")
                admin_user.must_change_password = True
                db.commit()
        existing_users = crud.get_users(db)
        for item in existing_users:
            if not item.password_hash:
                legacy_password = item.pin_code or "0000"
                item.password_hash = security.hash_password(legacy_password)
                item.must_change_password = True
        db.commit()
    finally:
        db.close()


def _ensure_holiday_data() -> None:
    """Automatic holiday management: keep the current and the next year
    populated for the configured region without any manual sync action."""
    db = database.SessionLocal()
    try:
        region = crud.get_default_holiday_region(db)
        today = date.today()
        for year in (today.year, today.year + 1):
            if not crud.get_holidays_for_year(db, year, region):
                holiday_calculator.ensure_holidays(db, year, region)
    except Exception:  # pragma: no cover - never block startup on holiday data
        logger.warning("Feiertage konnten beim Start nicht aktualisiert werden", exc_info=True)
    finally:
        db.close()


def _initialize_runtime() -> None:
    """Prepare persistent volumes and the logging system on start-up.

    Section 16 of the 0.9.0 spec: verify that config/data/logs exist, create
    them if missing and document the result in ``application.log``.
    """

    volume_report = paths.ensure_directories()
    logging_config = app_config.load_logging_config()
    logging_setup.configure_logging(logging_config)

    logging_setup.log_application(f"Erfassung {APP_VERSION} startet")
    for name, info in volume_report.items():
        if info.get("error"):
            logging_setup.log_error(
                f"Volume '{name}' konnte nicht angelegt werden: {info['error']}",
                exc_info=False,
            )
        elif info.get("created"):
            logging_setup.log_application(f"Volume '{name}' neu angelegt: {info['path']}")
        else:
            logging_setup.log_application(
                f"Volume '{name}' vorhanden: {info['path']} "
                f"(schreibbar={info['writable']})"
            )
    if logging_config.auto_cleanup_enabled:
        removed = log_tools.cleanup_old_logs(logging_config.auto_cleanup_days)
        if removed:
            logging_setup.log_application(
                f"Automatische Logbereinigung: {removed} alte Dateien entfernt"
            )


@app.on_event("startup")
def initialize_runtime():
    _initialize_runtime()


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
    _apply_versioned_migrations()
    _ensure_holiday_data()
    _migrate_legacy_backup_config()
    if os.environ.get("ERFASSUNG_DISABLE_SCHEDULER", "").lower() not in {"1", "true", "yes"}:
        try:
            interval = int(os.environ.get("BACKUP_SCHEDULER_INTERVAL", "60"))
        except ValueError:
            interval = 60
        backup_scheduler.start(interval)


@app.on_event("shutdown")
def _stop_scheduler():
    backup_scheduler.stop()


def _migrate_legacy_backup_config() -> None:
    """Carry a pre-0.9.2 single backup configuration over into a Backup-Job."""
    from pathlib import Path

    legacy_path = paths.CONFIG_DIR / "backup.json"
    if not legacy_path.exists():
        return
    db = database.SessionLocal()
    try:
        if crud.get_backup_jobs(db):
            return
        cfg = app_config.load_backup_config()
        contents = "database,config" + (",logs" if getattr(cfg, "include_logs", False) else "")
        smb_path = cfg.smb_server or ""
        if cfg.smb_share:
            server = cfg.smb_server.strip("\\/")
            share = cfg.smb_share.strip("\\/")
            smb_path = "\\\\" + server + "\\" + share
            if cfg.smb_path:
                smb_path += "\\" + cfg.smb_path.strip("\\/")
        smb_user = cfg.smb_username
        if cfg.smb_domain and smb_user and "\\" not in smb_user and "@" not in smb_user:
            smb_user = f"{cfg.smb_domain}\\{smb_user}"
        crud.create_backup_job(
            db,
            name="Übernommener Backup-Job",
            active=False,
            schedule="manual",
            contents=contents,
            target_type=cfg.target,
            ftp_host=cfg.ftp_host,
            ftp_port=cfg.ftp_port,
            ftp_username=cfg.ftp_username,
            ftp_password=cfg.ftp_password,
            ftp_path=cfg.ftp_remote_dir,
            ftp_use_tls=cfg.ftp_use_tls,
            smb_path=smb_path,
            smb_username=smb_user,
            smb_password=cfg.smb_password,
            retention_count=cfg.retention_count,
            retention_days=cfg.retention_days,
        )
        try:
            legacy_path.rename(legacy_path.with_suffix(".json.migrated"))
        except OSError:
            pass
        logging_setup.log_application("Alte Backup-Konfiguration in Backup-Job übernommen")
    except Exception:  # pragma: no cover - never block startup
        logging_setup.log_error("Migration der Backup-Konfiguration fehlgeschlagen")
    finally:
        db.close()


def _apply_versioned_migrations() -> None:
    """Apply all versioned, dialect-aware migrations automatically at start-up.

    Works for SQLite and MySQL/MariaDB. Migration state is tracked in the
    portable ``schema_migrations`` table, so every schema change is applied
    exactly once and existing data is preserved (§23).
    """
    try:
        from . import db_migrations

        db_migrations._apply_migrations(database.engine, db_migrations.MIGRATIONS)
    except Exception:  # pragma: no cover - never block startup on migrations
        logging_setup.log_error("Automatische Migrationen fehlgeschlagen")


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    if "session" in request.scope and _should_force_password_change(request.url.path):
        db = database.SessionLocal()
        try:
            user = get_logged_in_user(request, db)
            if user and user.must_change_password:
                return RedirectResponse(
                    url="/account/password?error=Bitte+ändern+Sie+zuerst+Ihr+Kennwort",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
        finally:
            db.close()
    response = await call_next(request)
    return response


@app.middleware("http")
async def api_logging_middleware(request: Request, call_next):
    path = request.url.path
    is_api = path.startswith("/api/")
    response = await call_next(request)
    if is_api:
        try:
            logging_setup.log_api(
                f"{request.method} {path} -> {response.status_code}",
                level=logging.WARNING if response.status_code >= 400 else logging.INFO,
            )
        except Exception:  # pragma: no cover - logging must never break a request
            pass
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
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = crud.get_user_by_username(db, username.strip())
    if not user or not security.verify_password(password, user.password_hash):
        logging_setup.log_security(
            f"Fehlgeschlagener Login für '{username.strip()}'",
            level=logging.WARNING,
            user=username.strip() or "-",
        )
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Benutzername oder Kennwort ist ungültig.", "user": None},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    request.session["user_id"] = user.id
    logging_setup.log_security("Erfolgreiche Anmeldung", user=user)
    if user.must_change_password:
        return RedirectResponse(url="/account/password", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if user:
        logging_setup.log_security("Abmeldung", user=user)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/account/password", response_class=HTMLResponse)
def account_password_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "account/password.html",
        {"request": request, "user": user, "error": None, "message": None, "hide_navigation": True},
    )


@app.post("/account/password")
def account_password_update(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not security.verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(
            "account/password.html",
            {"request": request, "user": user, "error": "Aktuelles Kennwort ist ungültig.", "hide_navigation": True},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if new_password != confirm_password:
        return templates.TemplateResponse(
            "account/password.html",
            {"request": request, "user": user, "error": "Die neuen Kennwörter stimmen nicht überein.", "hide_navigation": True},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        security.validate_password_strength(new_password)
    except ValueError as exc:
        return templates.TemplateResponse(
            "account/password.html",
            {"request": request, "user": user, "error": str(exc), "hide_navigation": True},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user.password_hash = security.hash_password(new_password)
    user.must_change_password = False
    db.commit()
    logging_setup.log_audit("Passwort geändert", user=user)
    logging_setup.log_security("Passwortänderung durchgeführt", user=user)
    return RedirectResponse(url="/dashboard?msg=Kennwort+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


def _build_daily_overview(db: Session, user_id: int, target_date: date) -> dict[str, object]:
    entries = crud.get_time_entries_for_user(db, user_id, start=target_date, end=target_date)
    entries = [entry for entry in entries if entry.status != models.TimeEntryStatus.REJECTED]
    # Anzeige-Reihenfolge: neueste Buchung zuerst. Reine Sortierung – Zeitstempel,
    # Arbeits-/Pausenzeiten und die Summenberechnung bleiben unverändert.
    entries = sorted(entries, key=lambda entry: (entry.start_time, entry.id), reverse=True)
    total_minutes = sum(entry.worked_minutes for entry in entries)
    return {
        "date": target_date,
        "entries": entries,
        "total_minutes": total_minutes,
    }


def _build_weekly_overview(
    db: Session,
    user: models.User,
    reference_date: date,
    today: Optional[date] = None,
) -> dict[str, object]:
    reference_today = today or date.today()
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)
    weekly_entries = crud.get_time_entries_for_user(db, user.id, start=week_start, end=week_end)
    weekly_entries = [
        entry for entry in weekly_entries if entry.status != models.TimeEntryStatus.REJECTED
    ]
    weekly_vacations = crud.get_vacations_in_range(
        db,
        week_start,
        week_end,
        user_id=user.id,
        statuses=[models.VacationStatus.APPROVED],
    )
    vacation_minutes_by_day = services.calculate_vacation_minutes_by_day(
        user,
        weekly_vacations,
        week_start,
        week_end,
    )
    weekly_vacation_minutes = sum(vacation_minutes_by_day.values())
    weekly_total_minutes = sum(entry.worked_minutes for entry in weekly_entries) + weekly_vacation_minutes
    weekly_target_minutes = int(round(user.weekly_target_minutes or 0)) if user else 0
    daily_target_minutes = int(round(user.daily_target_minutes or 0)) if user else 0

    if week_end < reference_today:
        expected_minutes_to_date = weekly_target_minutes
    elif week_start > reference_today:
        expected_minutes_to_date = 0
    else:
        days_delta = (min(reference_today, week_end) - week_start).days + 1
        elapsed_workdays = sum(
            1
            for offset in range(days_delta)
            if (week_start + timedelta(days=offset)).weekday() < 5
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
        work_minutes = sum(
            entry.worked_minutes for entry in weekly_entries if entry.work_date == current_day
        )
        vacation_minutes = vacation_minutes_by_day.get(current_day, 0)
        day_minutes = work_minutes + vacation_minutes
        target_for_day = daily_target_minutes if current_day.weekday() < 5 else 0
        week_days.append(
            {
                "date": current_day,
                "minutes": day_minutes,
                "worked_minutes": work_minutes,
                "vacation_minutes": vacation_minutes,
                "target_minutes": target_for_day,
                "is_today": current_day == reference_today,
            }
        )
        current_day += timedelta(days=1)

    return {
        "week_start": week_start,
        "week_end": week_end,
        "total_minutes": weekly_total_minutes,
        "target_minutes": weekly_target_minutes,
        "expected_minutes_to_date": expected_minutes_to_date,
        "remaining_minutes": remaining_week_minutes,
        "progress_percent": progress_percent,
        "progress_to_date_percent": progress_to_date_percent,
        "days": week_days,
        "vacation_minutes": weekly_vacation_minutes,
    }


def _build_dashboard_context(db: Session, user: models.User):
    today = date.today()
    reference_month = today
    metrics = services.calculate_dashboard_metrics(db, user.id, reference_month)
    active_entry = crud.get_open_time_entry(db, user.id)
    holiday_region = crud.get_default_holiday_region(db)
    holiday_region_label = holiday_calculator.GERMAN_STATES.get(holiday_region, holiday_region)
    holidays = crud.get_holidays_for_year(db, date.today().year, holiday_region)
    companies = crud.get_companies(db)
    vacations = crud.get_vacations_for_user(db, user.id)
    daily_overview = _build_daily_overview(db, user.id, today)
    weekly_summary = _build_weekly_overview(db, user, today, today=today)
    daily_entries = daily_overview["entries"]
    daily_total_minutes = daily_overview["total_minutes"]
    daily_target_minutes = int(round(user.daily_target_minutes or 0)) if user else 0
    show_overtime_metrics = bool(user.time_account_enabled or user.overtime_vacation_enabled)
    return {
        "metrics": metrics,
        "holidays": holidays,
        "holiday_region": holiday_region,
        "holiday_region_label": holiday_region_label,
        "companies": companies,
        "active_entry": active_entry,
        "metrics_month": reference_month.replace(day=1),
        "can_create_companies": _can_create_companies(user),
        "vacations": vacations,
        "pending_vacations": sum(
            1
            for vacation in vacations
            if vacation.status
            in (models.VacationStatus.PENDING, models.VacationStatus.WITHDRAW_REQUESTED)
        ),
        "daily_entries": daily_entries,
        "daily_total_minutes": daily_total_minutes,
        "today": today,
        "weekly_summary": weekly_summary,
        "daily_target_minutes": daily_target_minutes,
        "show_overtime_metrics": show_overtime_metrics,
        "status_labels": TIME_ENTRY_STATUS_LABELS,
    }


def _build_mobile_tab_urls(request: Request, tab_names: tuple[str, ...]) -> dict[str, str]:
    try:
        base_items = [item for item in request.query_params.multi_items() if item[0] != "tab"]
    except AttributeError:  # pragma: no cover - older Starlette versions
        base_items = [(key, value) for key, value in request.query_params.items() if key != "tab"]

    base_path = request.url.path
    base_prefix = ""
    if request.scope.get("root_path"):
        base_prefix = request.scope["root_path"].rstrip("/")

    def build_url(tab_name: str) -> str:
        params = base_items + [("tab", tab_name)]
        query = urlencode(params, doseq=True)
        path = f"{base_prefix}{base_path}" or base_path
        return f"{path}?{query}" if query else path

    return {tab: build_url(tab) for tab in tab_names}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    context = _build_dashboard_context(db, user)
    context.update(
        {
            "request": request,
            "user": user,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/mobile", response_class=HTMLResponse)
def mobile_dashboard(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    context = _build_dashboard_context(db, user)
    tab_param = request.query_params.get("tab", "buchung").lower()
    if tab_param not in {"buchung", "uebersicht", "salden", "urlaub"}:
        tab_param = "buchung"

    overview_mode = request.query_params.get("overview", "day").lower()
    if overview_mode not in {"day", "week"}:
        overview_mode = "day"
    reference_param = request.query_params.get("date")
    reference_date: Optional[date] = None
    if reference_param:
        try:
            reference_date = date.fromisoformat(reference_param)
        except ValueError:
            reference_date = None
    if reference_date is None:
        reference_date = context["today"]

    overview_context: dict[str, object] = {
        "overview_mode": overview_mode,
        "overview_reference_date": reference_date,
    }
    if overview_mode == "week":
        week_overview = _build_weekly_overview(db, user, reference_date, today=context["today"])
        week_overview.update(
            {
                "reference_date": reference_date,
                "prev": week_overview["week_start"] - timedelta(days=7),
                "next": week_overview["week_start"] + timedelta(days=7),
                "can_go_next": week_overview["week_end"] < context["today"],
                "week_number": week_overview["week_start"].isocalendar()[1],
                "balance_minutes": week_overview["total_minutes"] - week_overview["target_minutes"],
                "is_current_week": week_overview["week_start"] <= context["today"] <= week_overview["week_end"],
            }
        )
        overview_context["overview_week"] = week_overview
    else:
        day_overview = _build_daily_overview(db, user.id, reference_date)
        target_minutes = int(context.get("daily_target_minutes", 0))
        day_overview.update(
            {
                "prev": day_overview["date"] - timedelta(days=1),
                "next": day_overview["date"] + timedelta(days=1),
                "can_go_next": day_overview["date"] < context["today"],
                "is_today": day_overview["date"] == context["today"],
                "target_minutes": target_minutes,
                "balance_minutes": day_overview["total_minutes"] - target_minutes,
            }
        )
        overview_context["overview_day"] = day_overview
    context.update(
        {
            "request": request,
            "user": user,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
            "mobile": True,
            "active_tab": tab_param,
            "tab_urls": _build_mobile_tab_urls(request, ("buchung", "uebersicht", "salden", "urlaub", "einstellungen")),
            "hide_navigation": True,
        }
    )
    context.update(overview_context)
    return templates.TemplateResponse("mobile/dashboard.html", context)


@app.get("/mobile/quick-login")
def mobile_quick_login(request: Request, token: str = "", db: Session = Depends(database.get_db)):
    user_id = _verify_mobile_autologin_token(token)
    if user_id is None:
        return RedirectResponse(url="/login?error=Ung%C3%BCltiger+QR-Code", status_code=status.HTTP_303_SEE_OTHER)
    user = crud.get_user(db, user_id)
    if user is None:
        return RedirectResponse(url="/login?error=Benutzer+nicht+gefunden", status_code=status.HTTP_303_SEE_OTHER)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/mobile", status_code=status.HTTP_303_SEE_OTHER)



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
    except ValueError as exc:
        error_message = "Ungültige Zeiteingabe"
        if str(exc) == "OVERLAPPING_TIME_ENTRY":
            error_message = "Zeit überschneidet sich mit einer bestehenden Buchung"
        redirect = _build_redirect(_sanitize_next(next_url), error=error_message)
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        _sanitize_next(next_url), msg="Zeitbuchung eingereicht und wartet auf Freigabe"
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


def _serialize_mobile_entry(entry: models.TimeEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "work_date": entry.work_date.isoformat(),
        "start_time": entry.start_time.strftime("%H:%M:%S") if entry.start_time else "",
        "end_time": entry.end_time.strftime("%H:%M:%S") if entry.end_time else "",
        "break_minutes": entry.break_minutes,
        "break_started_at": entry.break_started_at.strftime("%H:%M:%S") if entry.break_started_at else None,
        "is_open": bool(entry.is_open),
        "notes": entry.notes or "",
        "status": entry.status,
        "company_id": entry.company_id,
        "company_name": entry.company_display_name if (entry.company or entry.deleted_company_name) else "",
        "worked_minutes": entry.worked_minutes,
        "total_break_minutes": entry.total_break_minutes,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _serialize_mobile_vacation(vacation: models.VacationRequest) -> dict[str, object]:
    return {
        "id": vacation.id,
        "start_date": vacation.start_date.isoformat(),
        "end_date": vacation.end_date.isoformat(),
        "status": vacation.status,
        "comment": vacation.comment or "",
        "use_overtime": bool(vacation.use_overtime),
        "overtime_minutes": vacation.overtime_minutes,
        "created_at": vacation.created_at.isoformat() if vacation.created_at else None,
    }


@app.get("/api/ping")
def api_ping(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
    return JSONResponse({"status": "ok", "version": APP_VERSION, "timestamp": datetime.utcnow().isoformat()})


@app.get("/api/csrf")
def api_csrf(request: Request):
    """Return a fresh CSRF token for the current session.
    Used by the mobile app to refresh the token before syncing offline actions."""
    return JSONResponse({"csrf_token": get_csrf_token(request)})

@app.get("/mobile/sync-data")
def mobile_sync_data(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")

    today = date.today()
    since_date = today - timedelta(days=days)
    until_date = today + timedelta(days=days)

    entries = crud.get_mobile_history_time_entries(db, user.id, since_date)
    # Urlaubsanträge des gesamten laufenden Jahres mitliefern (nicht nur das
    # `days`-Fenster), damit die mobile Ansicht alle Anträge des Jahres zeigt –
    # unabhängig von Status oder Synchronisationszeitpunkt.
    vacation_since = min(since_date, date(today.year, 1, 1))
    vacations = crud.get_mobile_history_vacations(db, user.id, vacation_since)
    companies = crud.get_companies(db)
    active_entry = crud.get_open_time_entry(db, user.id)
    metrics = services.calculate_dashboard_metrics(db, user.id, today.replace(day=1))

    payload = {
        "version": APP_VERSION,
        "generated_at": datetime.utcnow().isoformat(),
        "period": {
            "from": since_date.isoformat(),
            "to": until_date.isoformat(),
            "days": days,
        },
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "group": user.group.name if user.group else "",
            "daily_target_minutes": int(round(user.daily_target_minutes or 0)),
            "weekly_target_minutes": int(round(user.weekly_target_minutes or 0)),
        },
        "companies": [
            {
                "id": company.id,
                "name": company.name,
                "description": company.description or "",
            }
            for company in companies
        ],
        "entries": [_serialize_mobile_entry(entry) for entry in entries],
        "vacations": [_serialize_mobile_vacation(vacation) for vacation in vacations],
        "active_entry": _serialize_mobile_entry(active_entry) if active_entry else None,
        "metrics": {
            "worked_minutes": metrics.total_work_minutes + metrics.vacation_minutes,
            "target_minutes": metrics.target_minutes,
            "balance_minutes": (metrics.total_work_minutes + metrics.vacation_minutes) - metrics.target_minutes,
            "vacation_minutes": metrics.vacation_minutes,
            "vacation_summary": {
                "total_days": metrics.vacation_summary.total_days,
                "used_days": metrics.vacation_summary.used_days,
                "planned_days": metrics.vacation_summary.planned_days,
                "remaining_days": metrics.vacation_summary.remaining_days,
                "carryover_days": metrics.vacation_summary.carryover_days,
            },
        },
    }
    return JSONResponse(payload)


def _parse_event_time(value: Optional[str]) -> datetime:
    """Use the client-supplied wall-clock time of the punch (so an event made
    offline keeps its real time instead of the much later sync time), falling
    back to the server clock when absent/implausible.

    The client sends local naive ISO ("YYYY-MM-DDTHH:MM:SS"), matching how the
    server records online punches via datetime.now(); a trailing 'Z' or an
    explicit offset is normalised away. Values far outside a sane window are
    rejected to guard against a badly skewed device clock.
    """
    if value:
        text_value = value.strip()
        if text_value.endswith("Z"):
            text_value = text_value[:-1]
        try:
            parsed = datetime.fromisoformat(text_value)
        except (ValueError, TypeError):
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            server_now = datetime.now()
            if server_now - timedelta(days=400) <= parsed <= server_now + timedelta(days=1):
                return parsed
    return datetime.now()


def _wants_json(request: Request) -> bool:
    """True for offline-sync / XHR callers that send `Accept: application/json`.

    Normal browser form posts (Accept: text/html) keep the classic 303 redirect
    behaviour, so the desktop web UI is unaffected.
    """
    return "application/json" in request.headers.get("accept", "").lower()


def _auth_required_response(request: Request):
    """401 JSON for sync clients (so they can keep the queued action and retry
    after re-authentication), 303 to /login for normal browsers."""
    if _wants_json(request):
        return JSONResponse(
            {"ok": False, "duplicate": False, "retryable": True, "message": "Sitzung abgelaufen"},
            status_code=401,
        )
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


def _sync_result(
    request: Request,
    *,
    target: str,
    message: str = "",
    error: str = "",
    duplicate: bool = False,
    retryable: bool = False,
):
    """Return a machine-readable JSON outcome for offline-sync callers, or the
    classic 303 redirect for normal browser form submissions.

    The JSON shape lets the client decide reliably whether to remove an action
    from its offline queue:
      - ok / duplicate  -> action is done on the server -> delete locally
      - retryable       -> transient/ordering issue     -> keep, retry later
      - neither         -> definitive rejection          -> drop (won't succeed)
    """
    ok = bool(message) and not error
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": ok or duplicate,
                "duplicate": duplicate,
                "retryable": retryable,
                "message": message or error,
            },
            status_code=200,
        )
    params = {}
    if message and not error:
        params["msg"] = message
    if error:
        params["error"] = error
    redirect = _build_redirect(target, **params)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/punch")
def punch_action(
    request: Request,
    action: str = Form(...),
    company_id: Optional[str] = Form(None),
    new_company_name: Optional[str] = Form(None),
    notes: str = Form(""),
    next_url: str = Form("/dashboard"),
    client_action_id: Optional[str] = Form(None),
    event_time: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return _auth_required_response(request)
    target = _sanitize_next(next_url)
    if client_action_id:
        existing_action = crud.get_mobile_sync_action(db, user.id, client_action_id)
        if existing_action:
            return _sync_result(
                request,
                target=target,
                message="Aktion bereits synchronisiert",
                duplicate=True,
            )
    active_entry = crud.get_open_time_entry(db, user.id)
    now = _parse_event_time(event_time)
    message = ""
    error = ""

    def _safe_start_running_entry(*, company_id: Optional[int] = None, notes_value: str = "") -> bool:
        nonlocal error
        try:
            crud.start_running_entry(
                db,
                user_id=user.id,
                started_at=now,
                company_id=company_id,
                notes=notes_value,
            )
            return True
        except ValueError as exc:
            if str(exc) == "OVERLAPPING_TIME_ENTRY":
                overlapping_active = crud.get_open_time_entry(db, user.id)
                if overlapping_active:
                    return False
                # No open entry but the new interval collides with an existing
                # (closed) booking. Surface a clean, definitive error instead of
                # letting the exception become a 500 (which an offline client
                # would retry forever).
                db.rollback()
                error = "Zeitraum überschneidet sich mit einer vorhandenen Buchung."
                return False
            raise

    if action == "start_work":
        if active_entry:
            if client_action_id:
                message = "Arbeitszeit läuft bereits."
            else:
                error = "Es läuft bereits eine Arbeitszeit."
        else:
            created = _safe_start_running_entry(notes_value=notes.strip())
            if created:
                message = "Arbeitszeit gestartet."
            elif not error:
                message = "Arbeitszeit läuft bereits."
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
                if client_action_id:
                    message = "Dieser Auftrag läuft bereits."
                else:
                    error = "Dieser Auftrag läuft bereits."
            else:
                previous_company = active_entry.company if active_entry else None
                if active_entry:
                    crud.finish_running_entry(db, active_entry, now)
                created = _safe_start_running_entry(
                    company_id=target_company.id,
                    notes_value=notes.strip(),
                )
                if not created:
                    message = f"Auftrag bei {target_company.name} läuft bereits."
                elif created_company:
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
            created = _safe_start_running_entry(notes_value=notes.strip())
            if created:
                message = "Auftrag beendet. Arbeitszeit läuft weiter."
            else:
                message = "Auftrag beendet. Arbeitszeit läuft bereits."
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

    if message and not error and client_action_id:
        existing_action = crud.get_mobile_sync_action(db, user.id, client_action_id)
        if not existing_action:
            crud.create_mobile_sync_action(
                db,
                user_id=user.id,
                client_action_id=client_action_id,
                action=action,
            )

    # An end_* / break action that found no open entry is most likely an
    # ordering issue (the matching start_work hasn't been applied on the server
    # yet). Mark it retryable so the offline client keeps it and retries after
    # the earlier action has synced, instead of dropping the clock-out.
    retryable = bool(error) and active_entry is None and action in {
        "end_work",
        "end_company",
        "start_break",
        "end_break",
    }
    return _sync_result(
        request,
        target=target,
        message=message,
        error=error,
        retryable=retryable,
    )


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
    client_action_id: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return _auth_required_response(request)
    vac_target = "/records/vacations"
    if client_action_id:
        existing_action = crud.get_mobile_sync_action(db, user.id, client_action_id)
        if existing_action:
            return _sync_result(
                request,
                target=vac_target,
                message="Aktion bereits synchronisiert",
                duplicate=True,
            )
    if end_date < start_date:
        return _sync_result(
            request,
            target=vac_target,
            error="Enddatum darf nicht vor dem Startdatum liegen",
        )
    use_overtime_value = bool(use_overtime == "on" and user.overtime_vacation_enabled)
    overtime_minutes = 0
    if use_overtime_value:
        overtime_minutes = services.calculate_required_vacation_minutes(user, start_date, end_date)
    try:
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
    except ValueError as exc:
        error_message = "Urlaubsantrag konnte nicht gespeichert werden"
        if str(exc) == "VACATION_OVERLAP":
            error_message = "Es besteht bereits ein Urlaubsantrag für diesen Zeitraum"
        return _sync_result(request, target=vac_target, error=error_message)
    if client_action_id:
        existing_action = crud.get_mobile_sync_action(db, user.id, client_action_id)
        if not existing_action:
            crud.create_mobile_sync_action(
                db,
                user_id=user.id,
                client_action_id=client_action_id,
                action="create_vacation",
            )
    return _sync_result(request, target=vac_target, message="Urlaubsantrag erstellt")


@app.post("/vacations/{vacation_id}/withdraw")
def withdraw_vacation_request(
    request: Request,
    vacation_id: int,
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    vacation = (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.id == vacation_id)
        .filter(models.VacationRequest.user_id == user.id)
        .first()
    )
    if not vacation:
        redirect = _build_redirect("/records/vacations", error="Urlaubsantrag nicht gefunden")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    updated = crud.request_vacation_withdrawal(db, vacation_id)
    if not updated:
        redirect = _build_redirect(
            "/records/vacations",
            error="Urlaubsantrag kann nicht zurückgezogen werden",
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/records/vacations",
        msg="Rücknahme angefragt",
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


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
    vacation_minutes = services.calculate_approved_vacation_minutes(
        user, vacations, start_date, end_date
    )
    overtime_taken_minutes = services.calculate_vacation_overtime_in_range(
        user, vacations, start_date, end_date
    )
    effective_minutes = total_work_minutes + vacation_minutes
    balance_minutes = effective_minutes - target_minutes
    total_overtime_minutes = max(balance_minutes, 0)
    total_undertime_minutes = max(-balance_minutes, 0)
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
            "vacation_minutes": vacation_minutes,
            "total_overtime_minutes": total_overtime_minutes,
            "total_undertime_minutes": total_undertime_minutes,
            "target_minutes": target_minutes,
            "balance_minutes": balance_minutes,
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
    pending_vacations = sum(
        1
        for vacation in vacations
        if vacation.status
        in (models.VacationStatus.PENDING, models.VacationStatus.WITHDRAW_REQUESTED)
    )
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
    vacation_minutes = services.calculate_approved_vacation_minutes(
        user, vacations, start_date, end_date
    )
    overtime_taken_minutes = services.calculate_vacation_overtime_in_range(
        user, vacations, start_date, end_date
    )
    effective_minutes = total_work_minutes + vacation_minutes
    balance_minutes = effective_minutes - target_minutes
    total_overtime_minutes = max(balance_minutes, 0)
    total_undertime_minutes = max(-balance_minutes, 0)
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
    # All requests overlapping the period (any status) – the PDF vacation
    # overview shows pending/rejected/cancelled entries with their status.
    period_vacations = [
        vacation
        for vacation in vacations
        if vacation.start_date <= end_date and vacation.end_date >= start_date
    ]
    try:
        buffer = export_time_overview_pdf(
            user=user,
            selected_month=selected_month,
            entries=month_entries,
            total_work_minutes=total_work_minutes,
            target_minutes=target_minutes,
            vacation_minutes=vacation_minutes,
            overtime_taken_minutes=overtime_taken_minutes,
            total_overtime_minutes=total_overtime_minutes,
            total_undertime_minutes=total_undertime_minutes,
            vacation_summary=vacation_summary,
            company_totals=company_totals_all,
            overtime_limit_minutes=overtime_limit_minutes,
            overtime_limit_exceeded=overtime_limit_exceeded,
            overtime_limit_excess_minutes=overtime_limit_excess_minutes,
            overtime_limit_remaining_minutes=overtime_limit_remaining_minutes,
            vacations=period_vacations,
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


def _can_edit_time_entries(user: models.User) -> bool:
    return _has_group_permission(user, "can_edit_time_entries")


def _resolve_admin_permissions(user: models.User) -> dict[str, bool]:
    permissions = {
        "users": _can_manage_users(user),
        "groups": _ensure_admin(user),
        "companies": _ensure_admin(user),
        "holidays": _ensure_admin(user),
        "approvals_manual": _can_approve_manual_entries(user),
        "approvals_vacations": _can_manage_vacations(user),
        "reports": _can_view_time_reports(user),
        "edit_time_entries": _can_edit_time_entries(user),
        "integrations": _ensure_admin(user),
        "system": _ensure_admin(user),
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
    mobile_install_url = str(request.url_for("mobile_dashboard"))
    mobile_quick_login_urls = {
        item.id: f"{request.url_for('mobile_quick_login')}?token={_create_mobile_autologin_token(item.id)}"
        for item in users
    }
    return _admin_template(
        "admin/users_list.html",
        request,
        user,
        message=message,
        error=error,
        users=users,
        mobile_install_url=mobile_install_url,
        mobile_quick_login_urls=mobile_quick_login_urls,
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
    quick_login_url = (
        f"{request.url_for('mobile_quick_login')}?token={_create_mobile_autologin_token(target.id)}"
    )
    return _admin_template(
        "admin/users_form.html",
        request,
        user,
        message=message,
        error=error,
        groups=groups,
        form_user=target,
        mobile_quick_login_url=quick_login_url,
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


def _resolve_holiday_state(db: Session, raw_state: Optional[str]) -> str:
    if raw_state:
        candidate = raw_state.upper()
        if candidate in HOLIDAY_STATE_CODES:
            return candidate
    default_region = crud.get_default_holiday_region(db)
    return default_region if default_region in HOLIDAY_STATE_CODES else "DE"


@app.get("/admin/holidays", response_class=HTMLResponse)
def admin_holidays_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    # §22: kein Jahres-Dropdown mehr – es gilt automatisch das aktuelle Jahr.
    current_year = date.today().year
    selected_state = _resolve_holiday_state(db, request.query_params.get("state"))
    holidays = crud.get_holidays_for_year(db, current_year, selected_state)
    return _admin_template(
        "admin/holidays.html",
        request,
        user,
        message=message,
        error=error,
        holidays=holidays,
        holiday_states=HOLIDAY_STATE_CHOICES,
        selected_state=selected_state,
        current_year=current_year,
    )


@app.post("/admin/holidays/apply")
def admin_holidays_apply(
    request: Request,
    state: str = Form(...),
    db: Session = Depends(database.get_db),
):
    """§22: Gesetzliche Feiertage des aktuellen Jahres für das gewählte
    Bundesland übernehmen. Eigene (benutzerdefinierte) Feiertage bleiben
    erhalten, es entstehen keine Duplikate."""
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    selected_state = state.upper() if state and state.upper() in HOLIDAY_STATE_CODES else "DE"
    current_year = date.today().year
    statutory = list(holiday_calculator.calculate_german_holidays(current_year, selected_state))
    result = crud.apply_statutory_holidays(db, selected_state, current_year, statutory)
    logging_setup.log_audit(
        "Feiertage übernommen",
        user=user,
        detail=f"{selected_state} {current_year}: {result['created']} gesetzlich, "
        f"{result['preserved_custom']} eigene erhalten",
    )
    redirect = _build_redirect(
        "/admin/holidays",
        msg=f"{result['created']} gesetzliche Feiertage übernommen, {result['preserved_custom']} eigene erhalten",
        state=selected_state,
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


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
    pending_vacations: list[models.VacationRequest] = []
    withdrawal_requests: list[models.VacationRequest] = []
    if can_vacation:
        pending_vacations = crud.get_vacation_requests(
            db, statuses=[models.VacationStatus.PENDING]
        )
        withdrawal_requests = crud.get_vacation_requests(
            db, statuses=[models.VacationStatus.WITHDRAW_REQUESTED]
        )
    return _admin_template(
        "admin/approvals.html",
        request,
        user,
        message=message,
        error=error,
        pending_entries=pending_entries,
        pending_vacations=pending_vacations,
        withdrawal_requests=withdrawal_requests,
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


def _build_user_report_data(params, db: Session) -> dict[str, object]:
    """Per-user evaluation for a selectable set of users and period."""
    today = date.today()
    default_start = today.replace(day=1)
    default_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    start_date = _parse_date_param(params.get("start")) or default_start
    end_date = _parse_date_param(params.get("end")) or default_end
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    all_users = crud.get_users(db)
    selected_ids: set[int] = set()
    for raw in params.getlist("users"):
        try:
            selected_ids.add(int(raw))
        except (TypeError, ValueError):
            continue
    report_users = [item for item in all_users if item.id in selected_ids] if selected_ids else list(all_users)

    rows: list[dict[str, object]] = []
    totals = {
        "count": 0,
        "work_minutes": 0,
        "break_minutes": 0,
        "target_minutes": 0,
        "vacation_minutes": 0,
        "overtime_taken_minutes": 0,
        "balance_minutes": 0,
    }
    for report_user in report_users:
        entries = list(
            crud.get_time_entries(
                db,
                report_user.id,
                start=start_date,
                end=end_date,
                statuses=[models.TimeEntryStatus.APPROVED],
            )
        )
        work_minutes = sum(entry.worked_minutes for entry in entries)
        break_minutes = sum(entry.applied_break_minutes for entry in entries)
        target_minutes = services.calculate_target_minutes_in_range(report_user, start_date, end_date)
        user_vacations = crud.get_vacations_in_range(
            db,
            start_date,
            end_date,
            user_id=report_user.id,
            statuses=[models.VacationStatus.APPROVED],
        )
        vacation_minutes = services.calculate_approved_vacation_minutes(
            report_user, user_vacations, start_date, end_date
        )
        overtime_taken_minutes = services.calculate_vacation_overtime_in_range(
            report_user, user_vacations, start_date, end_date
        )
        balance_minutes = work_minutes + vacation_minutes - target_minutes
        rows.append(
            {
                "user": report_user,
                "count": len(entries),
                "work_minutes": work_minutes,
                "break_minutes": break_minutes,
                "target_minutes": target_minutes,
                "vacation_minutes": vacation_minutes,
                "overtime_taken_minutes": overtime_taken_minutes,
                "balance_minutes": balance_minutes,
            }
        )
        totals["count"] += len(entries)
        totals["work_minutes"] += work_minutes
        totals["break_minutes"] += break_minutes
        totals["target_minutes"] += target_minutes
        totals["vacation_minutes"] += vacation_minutes
        totals["overtime_taken_minutes"] += overtime_taken_minutes
        totals["balance_minutes"] += balance_minutes

    period_range = f"{start_date.strftime('%d.%m.%Y')} – {end_date.strftime('%d.%m.%Y')}"
    export_query = urlencode(
        [("start", start_date.strftime("%Y-%m-%d")), ("end", end_date.strftime("%Y-%m-%d"))]
        + [("users", str(user_id)) for user_id in sorted(selected_ids)]
    )
    return {
        "report_rows": rows,
        "report_totals": totals,
        "all_users": all_users,
        "selected_user_ids": selected_ids,
        "start_value": start_date.strftime("%Y-%m-%d"),
        "end_value": end_date.strftime("%Y-%m-%d"),
        "start_date": start_date,
        "end_date": end_date,
        "period_range": period_range,
        "period_filename": f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}",
        "export_query": export_query,
    }


@app.get("/admin/reports/users", response_class=HTMLResponse)
def admin_user_reports_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_view_time_reports(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    report_data = _build_user_report_data(request.query_params, db)
    return _admin_template(
        "admin/user_reports.html",
        request,
        user,
        message=request.query_params.get("msg"),
        error=request.query_params.get("error"),
        **report_data,
    )


@app.get("/admin/reports/users/pdf")
def admin_user_reports_pdf(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_view_time_reports(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    report_data = _build_user_report_data(request.query_params, db)
    try:
        buffer = export_user_summary_pdf(
            period_range=report_data["period_range"],
            rows=report_data["report_rows"],
            totals=report_data["report_totals"],
        )
    except RuntimeError as exc:
        params = list(request.query_params.multi_items())
        params.append(("error", str(exc)))
        return RedirectResponse(
            url=f"/admin/reports/users?{urlencode(params)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    filename = f"benutzer_zeit_{report_data['period_filename']}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/admin/reports/users/excel")
def admin_user_reports_excel(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_view_time_reports(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    report_data = _build_user_report_data(request.query_params, db)
    buffer = export_user_summary_excel(
        rows=report_data["report_rows"],
        totals=report_data["report_totals"],
        period_range=report_data["period_range"],
    )
    filename = f"benutzer_zeit_{report_data['period_filename']}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/admin/reports/time/pdf")
def admin_time_reports_pdf(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_view_time_reports(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    report_data = _build_time_report_data(request.query_params, db)
    # report_data["vacations"] only contains approved requests (KPI basis);
    # the PDF vacation overview lists every request in the period with status.
    period_vacations = crud.get_vacations_in_range(
        db,
        report_data["start_date"],
        report_data["end_date"],
    )
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
            vacation_minutes_total=report_data["vacation_minutes_total"],
            effective_minutes=report_data["effective_minutes"],
            vacations=period_vacations,
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
    buffer = export_time_entries(
        report_data["entries_sorted"],
        report_data.get("vacations"),
        period_start=report_data["start_date"],
        period_end=report_data["end_date"],
    )
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
    can_edit_time_entries: Optional[str] = Form(None),
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
    edit_time_entries_value = can_edit_time_entries == "on"
    if is_admin_value:
        manage_users_value = True
        manage_vacations_value = True
        approve_manual_value = True
        create_companies_value = True
        view_time_reports_value = True
        edit_time_entries_value = True
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
                can_edit_time_entries=edit_time_entries_value,
            ),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/groups/new?error=Gruppe+existiert+bereits",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    logging_setup.log_audit("Gruppe/Rolle angelegt", user=user, detail=name)
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
    can_edit_time_entries: Optional[str] = Form(None),
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
    edit_time_entries_value = can_edit_time_entries == "on"
    if is_admin_value:
        manage_users_value = True
        manage_vacations_value = True
        approve_manual_value = True
        create_companies_value = True
        view_time_reports_value = True
        edit_time_entries_value = True
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
                can_edit_time_entries=edit_time_entries_value,
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
    logging_setup.log_audit("Gruppe/Rolle geändert", user=user, detail=name)
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
    logging_setup.log_audit("Gruppe/Rolle gelöscht", user=user, detail=f"id={group_id}")
    return RedirectResponse(url="/admin/groups?msg=Gruppe+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/create")
def create_user_html(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    standard_weekly_hours: float = Form(40.0),
    monthly_overtime_limit_hours: Optional[str] = Form(None),
    group_id: Optional[str] = Form(None),
    time_account_enabled: Optional[str] = Form(None),
    overtime_vacation_enabled: Optional[str] = Form(None),
    annual_vacation_days: int = Form(30),
    vacation_carryover_enabled: Optional[str] = Form(None),
    vacation_carryover_days: int = Form(0),
    rfid_tag: Optional[str] = Form(None),
    auto_break_deduction: Optional[str] = Form(None),
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
    carryover_enabled = vacation_carryover_enabled == "on"
    carryover_days_value = vacation_carryover_days if carryover_enabled else 0
    rfid_value = (rfid_tag or "").strip() or None
    auto_break_value = auto_break_deduction == "on"
    try:
        overtime_limit_minutes = _parse_overtime_limit_hours(monthly_overtime_limit_hours)
    except ValueError:
        return RedirectResponse(
            url="/admin/users/new?error=Ung%C3%BCltiges+%C3%9Cberstundenlimit",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        if password != password_confirm:
            raise ValueError("PASSWORD_CONFIRM_MISMATCH")
        security.validate_password_strength(password)
        crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name=full_name,
                email=email,
                password=password,
                standard_weekly_hours=standard_weekly_hours,
                group_id=group_value,
                time_account_enabled=time_account_value,
                overtime_vacation_enabled=overtime_vacation_value,
                annual_vacation_days=annual_vacation_days,
                vacation_carryover_enabled=carryover_enabled,
                vacation_carryover_days=carryover_days_value,
                rfid_tag=rfid_value,
                monthly_overtime_limit_minutes=overtime_limit_minutes,
                auto_break_deduction=auto_break_value,
            ),
        )
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        if isinstance(exc, ValueError):
            message = "Ungültige+Eingabe"
            if str(exc) == "PASSWORD_CONFIRM_MISMATCH":
                message = "Kennw%C3%B6rter+stimmen+nicht+%C3%BCberein"
        else:
            message = "Benutzer+konnte+nicht+angelegt+werden"
        return RedirectResponse(
            url=f"/admin/users/new?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    logging_setup.log_audit("Benutzer angelegt", user=user, detail=username)
    return RedirectResponse(url="/admin/users?msg=Benutzer+angelegt", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/update")
def update_user_html(
    request: Request,
    user_id: int,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    reset_password: str = Form(""),
    reset_password_confirm: str = Form(""),
    standard_weekly_hours: float = Form(40.0),
    monthly_overtime_limit_hours: Optional[str] = Form(None),
    group_id: Optional[str] = Form(None),
    time_account_enabled: Optional[str] = Form(None),
    overtime_vacation_enabled: Optional[str] = Form(None),
    annual_vacation_days: int = Form(30),
    vacation_carryover_enabled: Optional[str] = Form(None),
    vacation_carryover_days: int = Form(0),
    rfid_tag: Optional[str] = Form(None),
    auto_break_deduction: Optional[str] = Form(None),
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
    carryover_enabled = vacation_carryover_enabled == "on"
    carryover_days_value = vacation_carryover_days if carryover_enabled else 0
    rfid_value = (rfid_tag or "").strip() or None
    auto_break_value = auto_break_deduction == "on"
    try:
        overtime_limit_minutes = _parse_overtime_limit_hours(monthly_overtime_limit_hours)
    except ValueError:
        return RedirectResponse(
            url=f"/admin/users/{user_id}?error=Ung%C3%BCltiges+%C3%9Cberstundenlimit",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        reset_password_value = reset_password.strip()
        if reset_password_value:
            if reset_password != reset_password_confirm:
                raise ValueError("PASSWORD_CONFIRM_MISMATCH")
            security.validate_password_strength(reset_password)
        updated = crud.update_user(
            db,
            user_id,
            schemas.UserUpdate(
                username=username,
                full_name=full_name,
                email=email,
                password=reset_password_value or None,
                standard_weekly_hours=standard_weekly_hours,
                group_id=group_value,
                time_account_enabled=time_account_value,
                overtime_vacation_enabled=overtime_vacation_value,
                annual_vacation_days=annual_vacation_days,
                vacation_carryover_enabled=carryover_enabled,
                vacation_carryover_days=carryover_days_value,
                rfid_tag=rfid_value,
                monthly_overtime_limit_minutes=overtime_limit_minutes,
                auto_break_deduction=auto_break_value,
            ),
        )
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        if isinstance(exc, ValueError):
            message = "Ungültige+Eingabe"
            if str(exc) == "PASSWORD_CONFIRM_MISMATCH":
                message = "Kennw%C3%B6rter+stimmen+nicht+%C3%BCberein"
        else:
            message = "Aktualisierung+fehlgeschlagen"
        return RedirectResponse(
            url=f"/admin/users/{user_id}?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(
            url="/admin/users?error=Benutzer+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    logging_setup.log_audit("Benutzer geändert", user=user, detail=f"id={user_id}")
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
    logging_setup.log_audit("Benutzer gelöscht", user=user, detail=f"id={user_id}")
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
            url="/admin/companies?error=Firma+konnte+nicht+gel%C3%B6scht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/companies?msg=Firma+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/time-entries/{entry_id}/edit", response_class=HTMLResponse)
def edit_time_entry_page(request: Request, entry_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not (_ensure_admin(user) or _can_edit_time_entries(user)):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    entry = crud.get_time_entry(db, entry_id)
    next_param = request.query_params.get("next")
    redirect_user = request.query_params.get("user")
    default_redirect = _build_redirect(
        "/admin/users",
        user=redirect_user or (str(entry.user_id) if entry else None),
    )
    sanitized_next = _sanitize_next(next_param or default_redirect, default_redirect)
    if not entry:
        redirect = _build_redirect_with_next(
            "/admin/users", next_param, error="Buchung nicht gefunden"
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    companies = crud.get_companies(db)
    active_tab = "approvals" if sanitized_next.startswith("/admin/approvals") else "users"
    return _admin_template(
        "admin/time_entry_form.html",
        request,
        user,
        entry=entry,
        companies=companies,
        next_url=sanitized_next,
        redirect_user=redirect_user or (str(entry.user_id) if entry.user_id else None),
        active_tab=active_tab,
    )


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
    next_url: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not (_ensure_admin(user) or _can_edit_time_entries(user)):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if end_time <= start_time:
        redirect = _build_redirect_with_next(
            "/admin/users",
            next_url,
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
    except ValueError as exc:
        error_message = "Ungültige Angaben"
        if str(exc) == "OVERLAPPING_TIME_ENTRY":
            error_message = "Zeiten überschneiden sich mit einer bestehenden Buchung"
        redirect = _build_redirect_with_next(
            "/admin/users", next_url, error=error_message, user=redirect_user
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if not updated:
        redirect = _build_redirect_with_next(
            "/admin/users",
            next_url,
            error="Buchung nicht gefunden",
            user=redirect_user,
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect_with_next(
        "/admin/users",
        next_url,
        msg="Buchung aktualisiert",
        user=redirect_user,
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/time-entries/{entry_id}/delete")
def delete_time_entry_html(
    request: Request,
    entry_id: int,
    redirect_user: Optional[str] = Form(None),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not (_ensure_admin(user) or _can_edit_time_entries(user)):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_time_entry(db, entry_id):
        redirect = _build_redirect_with_next(
            "/admin/users",
            next_url,
            error="Buchung konnte nicht gelöscht werden",
            user=redirect_user,
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect_with_next(
        "/admin/users",
        next_url,
        msg="Buchung gelöscht",
        user=redirect_user,
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
        updated = crud.update_vacation_status(db, vacation_id, models.VacationStatus.APPROVED)
        message = "Urlaub genehmigt"
    elif action == "reject":
        updated = crud.update_vacation_status(db, vacation_id, models.VacationStatus.REJECTED)
        message = "Urlaub abgelehnt"
    elif action == "approve_withdraw":
        updated = crud.approve_vacation_withdrawal(db, vacation_id)
        message = "Urlaub wurde zurückgezogen"
    elif action == "deny_withdraw":
        updated = crud.deny_vacation_withdrawal(db, vacation_id)
        message = "Rücknahme abgelehnt"
    else:
        redirect = _build_redirect("/admin/approvals", error="Ungültige Aktion")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if not updated:
        redirect = _build_redirect("/admin/approvals", error="Urlaubsantrag nicht gefunden")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    logging_setup.log_audit("Urlaubsfreigabe", user=user, detail=f"{message} (id={vacation_id})")
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
    logging_setup.log_audit(
        "Feiertag angelegt", user=user, detail=f"{name.strip()} {holiday_date} ({target_region})"
    )
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
    logging_setup.log_audit("Feiertag gelöscht", user=user, detail=f"id={holiday_id}")
    redirect = _build_redirect(
        "/admin/holidays", msg="Feiertag gelöscht", state=state, holiday_year=str(year)
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)



def _parse_checkbox(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"1", "true", "on", "yes"}


@app.get("/admin/integrations/timemoto", response_class=HTMLResponse)
def admin_timemoto_overview(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    try:
        config = timemoto.TimeMotoConfig.load()
    except timemoto.TimeMotoError as exc:
        config = timemoto.TimeMotoConfig()
        error = str(exc)
    else:
        error = request.query_params.get("error")
    message = request.query_params.get("msg")
    return _admin_template(
        "admin/timemoto.html",
        request,
        user,
        message=message,
        error=error,
        config=config,
        sync_result=None,
    )


@app.post("/admin/integrations/timemoto", response_class=HTMLResponse)
def admin_timemoto_save(
    request: Request,
    host: str = Form(""),
    port: str = Form(""),
    use_ssl: str | None = Form(None),
    verify_ssl: str | None = Form(None),
    username: str = Form(""),
    password: str = Form(""),
    timezone_value: str = Form(""),
    login_path: str = Form(""),
    users_path: str = Form(""),
    events_path: str = Form(""),
    events_limit: str = Form(""),
    timeout_value: str = Form(""),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    try:
        config = timemoto.TimeMotoConfig.load()
    except timemoto.TimeMotoError:
        config = timemoto.TimeMotoConfig()
    payload = {
        "host": host,
        "port": port or None,
        "use_ssl": _parse_checkbox(use_ssl),
        "verify_ssl": _parse_checkbox(verify_ssl),
        "username": username,
        "password": password,
        "timezone": timezone_value,
        "login_path": login_path,
        "users_path": users_path,
        "events_path": events_path,
        "events_limit": events_limit or None,
        "timeout": timeout_value or None,
    }
    try:
        config.update_from_dict(payload)
    except timemoto.TimeMotoError as exc:
        return _admin_template(
            "admin/timemoto.html",
            request,
            user,
            error=str(exc),
            config=config,
            sync_result=None,
        )
    if not config.host:
        return _admin_template(
            "admin/timemoto.html",
            request,
            user,
            error="Bitte Hostname oder IP-Adresse des TimeMoto-Geräts angeben.",
            config=config,
            sync_result=None,
        )
    try:
        config.save()
    except timemoto.TimeMotoError as exc:
        return _admin_template(
            "admin/timemoto.html",
            request,
            user,
            error=str(exc),
            config=config,
            sync_result=None,
        )
    redirect = _build_redirect(
        "/admin/integrations/timemoto",
        msg="Einstellungen gespeichert.",
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/integrations/timemoto/sync", response_class=HTMLResponse)
def admin_timemoto_sync(
    request: Request,
    full_sync: str | None = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    try:
        config = timemoto.TimeMotoConfig.load()
    except timemoto.TimeMotoError as exc:
        config = timemoto.TimeMotoConfig()
        return _admin_template(
            "admin/timemoto.html",
            request,
            user,
            error=str(exc),
            config=config,
            sync_result=None,
        )
    if not config.host:
        return _admin_template(
            "admin/timemoto.html",
            request,
            user,
            error="Bitte konfigurieren Sie das TimeMoto-Gerät, bevor Sie synchronisieren.",
            config=config,
            sync_result=None,
        )
    full_flag = _parse_checkbox(full_sync)
    try:
        result = timemoto.synchronize(db, config, full_sync=full_flag)
    except timemoto.TimeMotoError as exc:
        logging_setup.log_sync(
            f"Synchronisierung fehlgeschlagen: {exc}", level=logging.ERROR, user=user
        )
        return _admin_template(
            "admin/timemoto.html",
            request,
            user,
            error=str(exc),
            config=config,
            sync_result=None,
        )
    logging_setup.log_sync(
        f"Synchronisierung (full={full_flag}) – {result.created_entries} neue Buchungen",
        user=user,
    )
    try:
        config.save()
    except timemoto.TimeMotoError as exc:
        return _admin_template(
            "admin/timemoto.html",
            request,
            user,
            error=f"Synchronisierung erfolgreich, aber Konfiguration konnte nicht gespeichert werden: {exc}",
            config=config,
            sync_result=result,
        )
    if result.created_entries:
        message = (
            f"Synchronisierung abgeschlossen – {result.created_entries} neue Buchungen übernommen."
        )
    else:
        message = "Synchronisierung abgeschlossen."
    return _admin_template(
        "admin/timemoto.html",
        request,
        user,
        message=message,
        error=None,
        config=config,
        sync_result=result,
    )


@app.post("/api/integrations/timemoto/sync")
def api_timemoto_sync(
    request: Request,
    full: bool = False,
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen synchronisieren.")
    try:
        config = timemoto.TimeMotoConfig.load()
    except timemoto.TimeMotoError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not config.host:
        raise HTTPException(status_code=400, detail="TimeMoto-Gerät ist nicht konfiguriert.")
    try:
        result = timemoto.synchronize(db, config, full_sync=bool(full))
    except timemoto.TimeMotoError as exc:
        logging_setup.log_sync(
            f"API-Synchronisierung fehlgeschlagen: {exc}", level=logging.ERROR, user=user
        )
        raise HTTPException(status_code=502, detail=str(exc))
    logging_setup.log_sync(
        f"API-Synchronisierung – {result.created_entries} neue Buchungen", user=user
    )
    try:
        config.save()
    except timemoto.TimeMotoError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Synchronisierung erfolgreich, aber Konfiguration konnte nicht gespeichert werden: {exc}",
        )
    return result.to_dict()


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
    try:
        db_entry = crud.create_time_entry(db, entry)
    except ValueError as exc:
        detail = "Ungültige Zeiterfassung"
        if str(exc) == "OVERLAPPING_TIME_ENTRY":
            detail = "Zeitüberschneidung mit bestehender Buchung"
        raise HTTPException(status_code=400, detail=detail)
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
    try:
        db_vacation = crud.create_vacation_request(db, payload)
    except ValueError as exc:
        detail = "Urlaubsantrag konnte nicht gespeichert werden"
        if str(exc) == "VACATION_OVERLAP":
            detail = "Urlaubsantrag überschneidet sich mit vorhandenem Antrag"
        raise HTTPException(status_code=400, detail=detail)
    return schemas.VacationRequest.model_validate(db_vacation)


@app.post("/api/vacations/{vacation_id}/status", response_model=schemas.VacationRequest)
def update_vacation_status(vacation_id: int, status: str, db: Session = Depends(database.get_db)):
    updated = crud.update_vacation_status(db, vacation_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Urlaubseintrag nicht gefunden")
    return schemas.VacationRequest.model_validate(updated)


@app.get("/api/users/{user_id}/excel")
def export_user_time_entries(user_id: int, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    entries = crud.get_time_entries_for_user(db, user_id)
    vacations = [
        vacation
        for vacation in crud.get_vacations_for_user(db, user_id)
        if vacation.status == models.VacationStatus.APPROVED
    ]
    buffer = export_time_entries(entries, vacations)
    filename = f"arbeitszeiten_{user.username}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/health")
def health_check(db: Session = Depends(database.get_db)):
    report = system_info.health_report(db)
    status_code = status.HTTP_200_OK if report["status"] == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(report, status_code=status_code)


# ---------------------------------------------------------------------------
# Administration → System (Logs, Status, Fehler, Einstellungen, Backups)
# ---------------------------------------------------------------------------

LOG_LEVEL_CHOICES = list(app_config.VALID_LEVELS)


def _require_system_admin(request: Request, db: Session):
    user = get_logged_in_user(request, db)
    if not user:
        return None, RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return None, RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return user, None


@app.get("/admin/system/logs", response_class=HTMLResponse)
def admin_system_logs(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    params = request.query_params
    channel = params.get("channel") or "application"
    if channel not in logging_setup.CHANNELS:
        channel = "application"
    search = params.get("search", "")
    level = params.get("level", "")
    start = _parse_date_param(params.get("start"))
    end = _parse_date_param(params.get("end"))
    try:
        lines = log_tools.read_log(
            channel, search=search, level=level, start=start, end=end, limit=2000
        )
    except KeyError:
        lines = []
    return _admin_template(
        "admin/system_logs.html",
        request,
        user,
        message=params.get("msg"),
        error=params.get("error"),
        admin_active="system_logs",
        logs=log_tools.available_logs(),
        selected_channel=channel,
        log_lines=lines,
        search=search,
        level_filter=level,
        level_choices=LOG_LEVEL_CHOICES,
        start_value=params.get("start", ""),
        end_value=params.get("end", ""),
        auto_refresh=params.get("auto_refresh") == "1",
    )


@app.get("/admin/system/logs/download")
def admin_system_logs_download(request: Request, name: str = "", db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    if name not in logging_setup.CHANNELS:
        return RedirectResponse(
            url="/admin/system/logs?error=Unbekanntes+Log", status_code=status.HTTP_303_SEE_OTHER
        )
    content = log_tools.single_log_bytes(name)
    logging_setup.log_audit("Log heruntergeladen", user=user, detail=name)
    return Response(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={logging_setup.CHANNELS[name]}"},
    )


@app.get("/admin/system/logs/download-zip")
def admin_system_logs_download_zip(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    requested = request.query_params.getlist("names")
    buffer = log_tools.build_zip(requested)
    logging_setup.log_audit("Logs als ZIP heruntergeladen", user=user, detail=",".join(requested) or "alle")
    filename = f"logs_{date.today().strftime('%Y-%m-%d')}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/admin/system/logs/clear")
def admin_system_logs_clear(
    request: Request,
    channel: str = Form("all"),
    db: Session = Depends(database.get_db),
):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    if channel == "all":
        log_tools.clear_all_logs()
        logging_setup.log_audit("Alle Logs geleert", user=user)
    elif channel in logging_setup.CHANNELS:
        log_tools.clear_log(channel)
        logging_setup.log_audit("Log geleert", user=user, detail=channel)
    else:
        return RedirectResponse(
            url="/admin/system/logs?error=Unbekanntes+Log", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        url=f"/admin/system/logs?channel={channel if channel != 'all' else 'application'}&msg=Logs+geleert",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/admin/system/status", response_class=HTMLResponse)
def admin_system_status(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_status.html",
        request,
        user,
        admin_active="system_status",
        status_data=system_info.system_status(db),
        latest_backup=system_info.latest_backup_run(db),
        backup_overview=system_info.backup_overview(db),
    )


@app.get("/admin/system/sync", response_class=HTMLResponse)
def admin_system_sync(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_sync.html",
        request,
        user,
        admin_active="system_sync",
        diagnostics=system_info.sync_diagnostics(db),
    )


@app.get("/admin/system/errors", response_class=HTMLResponse)
def admin_system_errors(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_errors.html",
        request,
        user,
        admin_active="system_errors",
        errors=log_tools.error_overview(),
    )


@app.get("/admin/system/settings", response_class=HTMLResponse)
def admin_system_settings(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_settings.html",
        request,
        user,
        message=request.query_params.get("msg"),
        error=request.query_params.get("error"),
        admin_active="system_settings",
        logging_config=app_config.load_logging_config(),
        system_settings=app_config.load_system_settings(),
        level_choices=LOG_LEVEL_CHOICES,
        db_backend="SQLite" if database.IS_SQLITE else "MySQL/MariaDB",
    )


@app.post("/admin/system/settings")
def admin_system_settings_save(
    request: Request,
    level: str = Form("INFO"),
    api_logging: Optional[str] = Form(None),
    security_logging: Optional[str] = Form(None),
    audit_logging: Optional[str] = Form(None),
    sync_logging: Optional[str] = Form(None),
    backup_logging: Optional[str] = Form(None),
    restore_logging: Optional[str] = Form(None),
    rotation_max_mb: str = Form("5"),
    rotation_backup_count: str = Form("5"),
    auto_cleanup_enabled: Optional[str] = Form(None),
    auto_cleanup_days: str = Form("90"),
    sync_enabled: Optional[str] = Form(None),
    sync_interval_minutes: str = Form("60"),
    sync_full_on_start: Optional[str] = Form(None),
    auto_holiday_management: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    try:
        max_mb = max(float(rotation_max_mb.replace(",", ".")), 0.1)
    except ValueError:
        max_mb = 5.0
    logging_config = app_config.LoggingConfig.from_dict(
        {
            "level": level,
            "api_logging": _parse_checkbox(api_logging),
            "security_logging": _parse_checkbox(security_logging),
            "audit_logging": _parse_checkbox(audit_logging),
            "sync_logging": _parse_checkbox(sync_logging),
            "backup_logging": _parse_checkbox(backup_logging),
            "restore_logging": _parse_checkbox(restore_logging),
            "rotation_max_bytes": int(max_mb * 1024 * 1024),
            "rotation_backup_count": rotation_backup_count,
            "auto_cleanup_enabled": _parse_checkbox(auto_cleanup_enabled),
            "auto_cleanup_days": auto_cleanup_days,
        }
    )
    system_settings = app_config.SystemSettings.from_dict(
        {
            "sync_enabled": _parse_checkbox(sync_enabled),
            "sync_interval_minutes": sync_interval_minutes,
            "sync_full_on_start": _parse_checkbox(sync_full_on_start),
            "auto_holiday_management": _parse_checkbox(auto_holiday_management),
        }
    )
    # Audit the change while the previous logging policy is still active, so the
    # entry is never lost when the new settings disable audit logging.
    logging_setup.log_audit("Systemeinstellungen geändert", user=user, detail=f"level={logging_config.level}")
    app_config.save_logging_config(logging_config)
    app_config.save_system_settings(system_settings)
    logging_setup.configure_logging(logging_config)
    return RedirectResponse(
        url="/admin/system/settings?msg=Einstellungen+gespeichert", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/admin/system/settings/export")
def admin_system_settings_export(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    import json

    payload = json.dumps(app_config.export_all(), indent=2, sort_keys=True)
    logging_setup.log_audit("Systemeinstellungen exportiert", user=user)
    filename = f"erfassung_settings_{date.today().strftime('%Y-%m-%d')}.json"
    return Response(
        payload,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/admin/system/settings/import")
async def admin_system_settings_import(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    import json

    form = await request.form()
    upload = form.get("settings_file")
    raw = form.get("settings_json") or ""
    if upload is not None and hasattr(upload, "read"):
        raw = (await upload.read()).decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return RedirectResponse(
            url="/admin/system/settings?error=Ungültiges+JSON", status_code=status.HTTP_303_SEE_OTHER
        )
    valid, message = app_config.validate_import(payload)
    if not valid:
        return RedirectResponse(
            url=f"/admin/system/settings?error={message}", status_code=status.HTTP_303_SEE_OTHER
        )
    app_config.import_all(payload)
    logging_setup.configure_logging(app_config.load_logging_config())
    logging_setup.log_audit("Systemeinstellungen importiert", user=user)
    return RedirectResponse(
        url="/admin/system/settings?msg=Einstellungen+importiert", status_code=status.HTTP_303_SEE_OTHER
    )


BACKUP_TARGETS = ("local", "ftp", "smb")
BACKUP_SCHEDULES = ("manual", "daily", "weekly", "monthly")
BACKUP_CONTENTS = ("database", "config", "logs")


@app.get("/admin/system/backups", response_class=HTMLResponse)
def admin_system_backups(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_backups.html",
        request,
        user,
        message=request.query_params.get("msg"),
        error=request.query_params.get("error"),
        admin_active="system_backups",
        jobs=crud.get_backup_jobs(db),
        backup_targets=BACKUP_TARGETS,
        backup_schedules=BACKUP_SCHEDULES,
        backup_contents=BACKUP_CONTENTS,
        active_tab=request.query_params.get("tab", "jobs"),
    )


@app.get("/admin/system/backups/history", response_class=HTMLResponse)
def admin_system_backups_history(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_backups_history.html",
        request,
        user,
        message=request.query_params.get("msg"),
        error=request.query_params.get("error"),
        admin_active="system_backups_history",
        runs=crud.get_backup_runs(db, limit=200),
    )


def _backup_job_fields_from_form(form, *, keep_passwords_from=None) -> dict:
    contents = [c for c in form.getlist("contents") if c in BACKUP_CONTENTS]
    target = form.get("target_type", "local")
    if target not in BACKUP_TARGETS:
        target = "local"
    schedule = form.get("schedule", "manual")
    if schedule not in BACKUP_SCHEDULES:
        schedule = "manual"
    fields = {
        "name": (form.get("name") or "Backup-Job").strip(),
        "active": _parse_checkbox(form.get("active")),
        "schedule": schedule,
        "cron": (form.get("cron") or "").strip(),
        "contents": ",".join(contents) if contents else "database,config",
        "target_type": target,
        "local_path": (form.get("local_path") or "").strip(),
        "ftp_host": (form.get("ftp_host") or "").strip(),
        "ftp_port": _safe_int(form.get("ftp_port"), 21),
        "ftp_username": (form.get("ftp_username") or "").strip(),
        "ftp_password": form.get("ftp_password") or "",
        "ftp_path": (form.get("ftp_path") or "/").strip() or "/",
        "ftp_use_tls": _parse_checkbox(form.get("ftp_use_tls")),
        "smb_path": (form.get("smb_path") or "").strip(),
        "smb_username": (form.get("smb_username") or "").strip(),
        "smb_password": form.get("smb_password") or "",
        "retention_count": _safe_int(form.get("retention_count"), 10),
        "retention_days": _safe_int(form.get("retention_days"), 30),
    }
    # Keep stored passwords when the form leaves them blank (masked field).
    if keep_passwords_from is not None:
        if not fields["ftp_password"]:
            fields["ftp_password"] = keep_passwords_from.ftp_password
        if not fields["smb_password"]:
            fields["smb_password"] = keep_passwords_from.smb_password
    return fields


def _safe_int(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


@app.post("/admin/system/backups/jobs")
async def admin_backup_job_save(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    form = await request.form()
    job_id = _safe_int(form.get("job_id"), 0)
    if job_id:
        existing = crud.get_backup_job(db, job_id)
        if not existing:
            return RedirectResponse(
                url=_build_redirect("/admin/system/backups", error="Backup-Job nicht gefunden"),
                status_code=status.HTTP_303_SEE_OTHER,
            )
        fields = _backup_job_fields_from_form(form, keep_passwords_from=existing)
        crud.update_backup_job(db, job_id, **fields)
        logging_setup.log_audit("Backup-Job geändert", user=user, detail=fields["name"])
        msg = "Backup-Job gespeichert"
    else:
        fields = _backup_job_fields_from_form(form)
        crud.create_backup_job(db, **fields)
        logging_setup.log_audit("Backup-Job angelegt", user=user, detail=fields["name"])
        msg = "Backup-Job angelegt"
    return RedirectResponse(
        url=_build_redirect("/admin/system/backups", msg=msg), status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/admin/system/backups/jobs/{job_id}/run")
def admin_backup_job_run(request: Request, job_id: int, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    job = crud.get_backup_job(db, job_id)
    if not job:
        return RedirectResponse(
            url=_build_redirect("/admin/system/backups", error="Backup-Job nicht gefunden"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    run = backup_manager.run_job(db, job, triggered_by=f"manuell ({user.username})", user=user)
    logging_setup.log_audit("Backup-Job ausgeführt", user=user, detail=f"{job.name}: {run.status}")
    key = "msg" if run.status in {"success", "warning"} else "error"
    return RedirectResponse(
        url=_build_redirect("/admin/system/backups", **{key: f"{job.name}: {run.message}"}),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/system/backups/jobs/{job_id}/toggle")
def admin_backup_job_toggle(request: Request, job_id: int, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    job = crud.get_backup_job(db, job_id)
    if job:
        crud.update_backup_job(db, job_id, active=not bool(job.active))
        logging_setup.log_audit(
            "Backup-Job " + ("aktiviert" if not job.active else "deaktiviert"), user=user, detail=job.name
        )
    return RedirectResponse(
        url=_build_redirect("/admin/system/backups", msg="Backup-Job aktualisiert"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/system/backups/jobs/{job_id}/delete")
def admin_backup_job_delete(request: Request, job_id: int, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    job = crud.get_backup_job(db, job_id)
    name = job.name if job else ""
    crud.delete_backup_job(db, job_id)
    logging_setup.log_audit("Backup-Job gelöscht", user=user, detail=name)
    return RedirectResponse(
        url=_build_redirect("/admin/system/backups", msg="Backup-Job gelöscht"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/system/backups/test")
async def admin_backup_job_test(request: Request, db: Session = Depends(database.get_db)):
    """Connection test for the values currently entered in the modal (JSON)."""
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return JSONResponse({"ok": False, "message": "Nicht angemeldet"}, status_code=401)
    form = await request.form()
    job_id = _safe_int(form.get("job_id"), 0)
    existing = crud.get_backup_job(db, job_id) if job_id else None
    fields = _backup_job_fields_from_form(form, keep_passwords_from=existing)
    probe = models.BackupJob(**fields)
    ok, message = backup_manager.test_connection(probe, user=user)
    logging_setup.log_audit(
        "Backup-Verbindungstest", user=user, detail=f"{probe.target_type}: {'ok' if ok else 'fehlgeschlagen'}"
    )
    return JSONResponse({"ok": ok, "message": message})


@app.get("/admin/system/backups/runs/{run_id}/download")
def admin_backup_run_download(request: Request, run_id: int, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    run = crud.get_backup_run(db, run_id)
    if not run or not run.filename or not Path(run.filename).exists():
        return RedirectResponse(
            url=_build_redirect("/admin/system/backups", error="Backup-Datei nicht verfügbar"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    path = Path(run.filename)
    logging_setup.log_audit("Backup heruntergeladen", user=user, detail=path.name)
    backup_manager.log_backup(f"Download: {path.name}", user=user)
    return StreamingResponse(
        path.open("rb"),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={path.name}"},
    )


# ---------------------------------------------------------------------------
# Administration → Sicherung → Wiederherstellung (§1-§9)
# ---------------------------------------------------------------------------

_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB streaming chunks (never load file into RAM)


@app.get("/admin/system/restore", response_class=HTMLResponse)
def admin_restore_page(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_restore.html",
        request,
        user,
        message=request.query_params.get("msg"),
        error=request.query_params.get("error"),
        admin_active="system_restore",
        backups=backup_manager.list_local_backups(),
    )


@app.get("/admin/system/restore/history", response_class=HTMLResponse)
def admin_restore_history(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_restore_history.html",
        request,
        user,
        admin_active="system_restore_history",
        runs=crud.get_restore_runs(db, limit=100),
    )


@app.get("/admin/system/restore/download")
def admin_restore_download(request: Request, file: str = "", db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    path = backup_manager.resolve_backup_path(file)
    if not path:
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error="Datei nicht gefunden"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    logging_setup.log_audit("Backup heruntergeladen", user=user, detail=path.name)
    backup_manager.log_backup(f"Download: {path.name}", user=user)
    return StreamingResponse(
        path.open("rb"),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={path.name}"},
    )


@app.post("/admin/system/restore/verify")
def admin_restore_verify(request: Request, file: str = Form(...), db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return JSONResponse({"ok": False, "message": "Nicht angemeldet"}, status_code=401)
    path = backup_manager.resolve_backup_path(file)
    if not path:
        return JSONResponse({"ok": False, "message": "Datei nicht gefunden"}, status_code=404)
    result = backup_manager.verify(path, user=user)
    return JSONResponse(result)


@app.post("/admin/system/restore/upload")
async def admin_restore_upload(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    form = await request.form()
    upload = form.get("backup_file")
    if upload is None or not hasattr(upload, "read"):
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error="Keine Datei ausgewählt"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    original = getattr(upload, "filename", "") or "upload"
    # §24: only accept our archive extensions; storage name is generated server-side.
    if not original.lower().endswith((".zip",)):
        backup_manager.log_backup(
            f"Upload abgelehnt (Dateityp): {original}", level=logging.WARNING, user=user
        )
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error="Nur .zip-Backups werden akzeptiert"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    backup_manager.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    backup_manager.log_backup(f"Upload gestartet: {original}", user=user)
    import tempfile as _tempfile

    fd, tmp_name = _tempfile.mkstemp(prefix="upload_", suffix=".zip", dir=str(backup_manager.UPLOAD_DIR))
    os.close(fd)
    tmp_path = Path(tmp_name)
    size = 0
    try:
        with tmp_path.open("wb") as handle:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                size += len(chunk)
    except Exception as exc:  # pragma: no cover
        tmp_path.unlink(missing_ok=True)
        backup_manager.log_backup(
            f"Upload fehlgeschlagen: {original}: {exc}", level=logging.ERROR, user=user
        )
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error="Upload fehlgeschlagen"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    backup_manager.log_backup(
        f"Upload erfolgreich: {original} ({paths.format_size(size)})", user=user
    )
    analysis = backup_manager.verify(tmp_path, user=user)
    if not analysis["integrity"]:
        tmp_path.unlink(missing_ok=True)
        backup_manager.log_backup(
            f"Integritätsprüfung fehlgeschlagen für Upload {original}", level=logging.WARNING, user=user
        )
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error="Hochgeladene Datei ist kein gültiges Backup-Archiv"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    final = backup_manager.register_uploaded_file(tmp_path, original)
    logging_setup.log_audit("Backup hochgeladen", user=user, detail=f"{original} -> {final.name}")
    backup_manager.log_backup(f"Integritätsprüfung erfolgreich, übernommen als {final.name}", user=user)
    return RedirectResponse(
        url=_build_redirect("/admin/system/restore", msg=f"Backup hochgeladen: {final.name}"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/system/restore/run")
def admin_restore_run(
    request: Request,
    file: str = Form(...),
    confirm: str = Form(""),
    db: Session = Depends(database.get_db),
):
    """Validate and *queue* a restore. The actual restore runs asynchronously
    in a background worker so the database swap never tears down this request
    (§0.9.5 – no more "Internal Server Error")."""
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    # Schritt 2: validate permissions (above), confirmation, file, integrity & compatibility.
    if confirm.strip() != "WIEDERHERSTELLEN":
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error="Bestätigung fehlt oder falsch"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    path = backup_manager.resolve_backup_path(file)
    if not path:
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error="Datei nicht gefunden"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    ok, reason, _meta = restore_manager.validate_restore(path)
    if not ok:
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore", error=reason),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if restore_jobs.is_active():
        return RedirectResponse(
            url=_build_redirect("/admin/system/restore/progress", error="Es läuft bereits eine Wiederherstellung"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    # Schritt 3+4: create the job, respond immediately (redirect to progress).
    token = restore_jobs.start_restore(path, username=user.username)
    logging_setup.log_audit("Backup wiederhergestellt (gestartet)", user=user, detail=f"{path.name} (Job {token})")
    return RedirectResponse(
        url="/admin/system/restore/progress", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/admin/system/restore/progress", response_class=HTMLResponse)
def admin_restore_progress(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    return _admin_template(
        "admin/system_restore_progress.html",
        request,
        user,
        admin_active="system_restore",
        status=restore_jobs.read_status(),
    )


@app.get("/api/restore/status")
def api_restore_status(request: Request):
    """Lightweight status endpoint (§ Restore-Status API).

    Reads only the JSON status file – it never touches the database, so it keeps
    working while the database is being swapped. Authorisation is by session
    only (no DB lookup) so polling survives the restore window.
    """
    if not request.session.get("user_id"):
        return JSONResponse({"state": "unauthorized"}, status_code=401)
    return JSONResponse(restore_jobs.read_status())


@app.post("/admin/system/restore/delete")
def admin_restore_delete(request: Request, file: str = Form(...), db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    path = backup_manager.resolve_backup_path(file)
    if path:
        try:
            path.unlink()
            logging_setup.log_audit("Backup gelöscht", user=user, detail=path.name)
            backup_manager.log_backup(f"Backup gelöscht: {path.name}", user=user)
        except OSError:
            pass
    return RedirectResponse(
        url=_build_redirect("/admin/system/restore", msg="Backup gelöscht"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/admin/holidays/export")
def admin_holidays_export(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    import json

    holidays = crud.get_holidays(db)
    payload = json.dumps(
        {
            "version": 1,
            "holidays": [
                {"name": h.name, "date": h.date.isoformat(), "region": h.region}
                for h in holidays
            ],
        },
        indent=2,
        ensure_ascii=False,
    )
    logging_setup.log_audit("Feiertage exportiert", user=user, detail=f"{len(holidays)} Einträge")
    filename = f"feiertage_{date.today().strftime('%Y-%m-%d')}.json"
    return Response(
        payload,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/admin/holidays/import")
async def admin_holidays_import(request: Request, db: Session = Depends(database.get_db)):
    user, redirect = _require_system_admin(request, db)
    if redirect:
        return redirect
    import json

    form = await request.form()
    upload = form.get("holidays_file")
    raw = form.get("holidays_json") or ""
    if upload is not None and hasattr(upload, "read"):
        raw = (await upload.read()).decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return RedirectResponse(
            url="/admin/holidays?error=Ungültiges+JSON", status_code=status.HTTP_303_SEE_OTHER
        )
    entries = payload.get("holidays") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return RedirectResponse(
            url="/admin/holidays?error=Ungültiges+Format", status_code=status.HTTP_303_SEE_OTHER
        )
    to_create: list[schemas.HolidayCreate] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        try:
            to_create.append(
                schemas.HolidayCreate(
                    name=str(item["name"]).strip(),
                    date=date.fromisoformat(str(item["date"])),
                    region=str(item.get("region") or "DE").strip() or "DE",
                )
            )
        except (KeyError, ValueError):
            continue
    if to_create:
        crud.upsert_holidays(db, to_create)
    logging_setup.log_audit("Feiertage importiert", user=user, detail=f"{len(to_create)} Einträge")
    return RedirectResponse(
        url=f"/admin/holidays?msg={len(to_create)}+Feiertage+importiert",
        status_code=status.HTTP_303_SEE_OTHER,
    )


if __name__ == "__main__":
    import uvicorn

    default_host = os.environ.get("UVICORN_HOST", "0.0.0.0")
    default_port = int(os.environ.get("UVICORN_PORT", "8000"))
    uvicorn.run(app, host=default_host, port=default_port)

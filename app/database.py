"""Database engine bootstrap with runtime-switchable backend (§0.9.7).

Historically the backend was fixed at process start via the ``DATABASE_URL``
environment variable. Since 0.9.7 the active database can be switched from the
web UI (Administration → System → Datenbank). The chosen backend is persisted
as ``config/database.json`` in the *config* volume and takes precedence over the
environment variable, so the selection survives restarts.

To avoid a circular import (``paths``/``app_config`` both import this module),
the config file is read here with a tiny, dependency-free JSON reader. The URL
builder :func:`build_url` is the single source of truth and is reused by
:class:`app.app_config.DatabaseConfig`.

Supported logical types:

* ``sqlite``     – file based (default, recommended for single-user/test)
* ``mysql``      – MySQL 8+ via PyMySQL
* ``mariadb``    – MariaDB 10.6+ via PyMySQL (same dialect as MySQL)
* ``postgresql`` – PostgreSQL 14+ via psycopg2

The engine can be rebuilt at runtime via :func:`reconfigure` after a successful
migration; all other modules reference ``database.engine`` /
``database.SessionLocal`` lazily, so the swap is picked up by new sessions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import declarative_base, sessionmaker

# Logical database types exposed in the UI (order = default recommendation).
DB_TYPES = ("postgresql", "mariadb", "mysql", "sqlite")

# Logical type -> SQLAlchemy driver + default port.
_DRIVERS = {
    "sqlite": ("sqlite", None),
    "mysql": ("mysql+pymysql", 3306),
    "mariadb": ("mysql+pymysql", 3306),
    "postgresql": ("postgresql+psycopg2", 5432),
}

Base = declarative_base()


def _config_dir() -> Path:
    """Resolve the config volume without importing :mod:`app.paths`."""
    value = os.environ.get("ERFASSUNG_CONFIG_DIR")
    if value:
        return Path(value).expanduser()
    return Path(__file__).resolve().parent.parent / "config"


DATABASE_CONFIG_FILE = _config_dir() / "database.json"

DEFAULT_SQLITE_PATH = "./erfassung.db"


def normalise_type(value: Any) -> str:
    db_type = str(value or "").strip().lower()
    return db_type if db_type in _DRIVERS else "sqlite"


def build_url(config: dict[str, Any]) -> str:
    """Build a SQLAlchemy URL string from a configuration mapping.

    ``config`` keys: ``type``, ``sqlite_path``, ``host``, ``port``, ``name``,
    ``user``, ``password``. Credentials are URL-encoded by SQLAlchemy.
    """
    db_type = normalise_type(config.get("type"))
    driver, default_port = _DRIVERS[db_type]
    if db_type == "sqlite":
        path = str(config.get("sqlite_path") or DEFAULT_SQLITE_PATH).strip() or DEFAULT_SQLITE_PATH
        return f"sqlite:///{path}"
    port = config.get("port")
    try:
        port = int(port) if port not in (None, "") else default_port
    except (TypeError, ValueError):
        port = default_port
    url = URL.create(
        driver,
        username=str(config.get("user") or "") or None,
        password=str(config.get("password") or "") or None,
        host=str(config.get("host") or "localhost") or None,
        port=port,
        database=str(config.get("name") or "") or None,
    )
    return url.render_as_string(hide_password=False)


def _engine_options(db_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """connect_args / pool options per backend (timeout + SSL)."""
    options: dict[str, Any] = {}
    connect_args: dict[str, Any] = {}
    if db_type == "sqlite":
        connect_args["check_same_thread"] = False
    else:
        # pool_pre_ping recycles stale connections (proxies / idle periods).
        options["pool_pre_ping"] = True
        options["pool_recycle"] = int(os.environ.get("DB_POOL_RECYCLE", "1800"))
        timeout = config.get("timeout")
        try:
            timeout = int(timeout) if timeout not in (None, "") else 0
        except (TypeError, ValueError):
            timeout = 0
        ssl_enabled = bool(config.get("ssl"))
        if db_type in ("mysql", "mariadb"):
            if timeout > 0:
                connect_args["connect_timeout"] = timeout
            if ssl_enabled:
                # A non-empty ssl mapping enables TLS in PyMySQL (default ctx).
                connect_args["ssl"] = {"ssl": True}
        elif db_type == "postgresql":
            if timeout > 0:
                connect_args["connect_timeout"] = timeout
            if ssl_enabled:
                connect_args["sslmode"] = "require"
    options["connect_args"] = connect_args
    return options


def _read_config_file() -> dict[str, Any] | None:
    try:
        data = json.loads(DATABASE_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_initial() -> tuple[str, str, dict[str, Any]]:
    """Return (url, logical_type, config) honouring the persisted selection."""
    config = _read_config_file()
    if config:
        db_type = normalise_type(config.get("type"))
        return build_url(config), db_type, config
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        backend = make_url(env_url).get_backend_name()
        if backend.startswith("postgresql"):
            db_type = "postgresql"
        elif backend.startswith("mysql"):
            db_type = "mysql"
        else:
            db_type = "sqlite"
        return env_url, db_type, {"type": db_type}
    return f"sqlite:///{DEFAULT_SQLITE_PATH}", "sqlite", {"type": "sqlite"}


def _prepare_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    raw_path = url.replace("sqlite:///", "", 1)
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _build_engine(url: str, db_type: str, config: dict[str, Any]):
    _prepare_sqlite_dir(url)
    return create_engine(url, **_engine_options(db_type, config))


# -- module-level state (rebindable at runtime) ----------------------------

SQLALCHEMY_DATABASE_URL, DB_TYPE, ACTIVE_CONFIG = _resolve_initial()
DB_BACKEND = make_url(SQLALCHEMY_DATABASE_URL).get_backend_name()  # sqlite/mysql/postgresql
IS_SQLITE = DB_BACKEND == "sqlite"

engine = _build_engine(SQLALCHEMY_DATABASE_URL, DB_TYPE, ACTIVE_CONFIG)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def reconfigure(config: dict[str, Any]) -> None:
    """Rebind the global engine/session to a new backend configuration.

    Disposes the previous engine and rebuilds the module globals so that new
    requests/sessions use the freshly selected database. Existing in-flight
    sessions keep their (old) connection until closed.
    """
    global SQLALCHEMY_DATABASE_URL, DB_BACKEND, IS_SQLITE, DB_TYPE, ACTIVE_CONFIG
    global engine, SessionLocal

    db_type = normalise_type(config.get("type"))
    url = build_url(config)
    new_engine = _build_engine(url, db_type, config)
    old_engine = engine

    SQLALCHEMY_DATABASE_URL = url
    DB_TYPE = db_type
    ACTIVE_CONFIG = dict(config)
    DB_BACKEND = make_url(url).get_backend_name()
    IS_SQLITE = DB_BACKEND == "sqlite"
    engine = new_engine
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    try:
        old_engine.dispose()
    except Exception:  # pragma: no cover - defensive
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

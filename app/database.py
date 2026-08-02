"""Aufbau der Datenbankverbindung – im Betrieb umschaltbar.

Früher stand das Backend beim Start fest, festgelegt über ``DATABASE_URL``.
Seit 0.9.7 lässt es sich in der Oberfläche wechseln (Administration → System →
Datenbank). Die Wahl liegt als ``config/database.json`` im config-Volume und
geht der Umgebungsvariablen vor – so überlebt sie jeden Neustart.

Die Konfigurationsdatei wird hier mit einem winzigen, abhängigkeitsfreien
JSON-Leser eingelesen. Grund ist ein Importzyklus: ``paths`` und ``app_config``
laden beide dieses Modul. Der URL-Bau :func:`build_url` ist die einzige Quelle
und wird von :class:`app.app_config.DatabaseConfig` mitbenutzt.

Unterstützte Typen:

* ``sqlite``     – dateibasiert (Vorgabe, für Einzelplatz und Test)
* ``mysql``      – MySQL 8+ über PyMySQL
* ``mariadb``    – MariaDB 10.6+ über PyMySQL (derselbe Dialekt wie MySQL)
* ``postgresql`` – PostgreSQL 14+ über psycopg2

Nach einer erfolgreichen Migration lässt sich die Verbindung mit
:func:`reconfigure` neu aufbauen. Alle übrigen Module greifen erst bei Bedarf
auf ``database.engine`` und ``database.SessionLocal`` zu; neue Sitzungen
übernehmen den Wechsel damit von selbst.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import declarative_base, sessionmaker


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
    """SQLAlchemy-URL aus einer Konfigurationsstruktur bauen.

    Ausgewertet werden ``type``, ``sqlite_path``, ``host``, ``port``, ``name``,
    ``user`` und ``password``. Um die URL-Kodierung der Zugangsdaten kümmert
    sich SQLAlchemy.
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


def _env_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _config_from_env() -> dict[str, Any] | None:
    """Datenbankkonfiguration aus den ``DB_*``-Umgebungsvariablen – nur bei der
    Erstinstallation.

    Ausgewertet werden ``DB_TYPE`` (sqlite/mysql/mariadb/postgresql) sowie
    ``DB_HOST``, ``DB_PORT``, ``DB_NAME``, ``DB_USER``, ``DB_PASSWORD``,
    ``DB_SSL`` und ``DB_PATH`` (für SQLite).

    Ohne ``DB_TYPE`` kommt ``None`` zurück. Der Weg ist damit rein freiwillig
    und kommt einer ``DATABASE_URL``-Einrichtung nie in die Quere.
    """
    raw_type = os.environ.get("DB_TYPE")
    if not raw_type:
        return None
    db_type = normalise_type(raw_type)
    config: dict[str, Any] = {"type": db_type, "created_by": "env"}
    if db_type == "sqlite":
        path = os.environ.get("DB_PATH") or DEFAULT_SQLITE_PATH
        config["sqlite_path"] = path
        return config
    config["host"] = os.environ.get("DB_HOST", "")
    port = os.environ.get("DB_PORT")
    if port:
        try:
            config["port"] = int(port)
        except (TypeError, ValueError):
            pass
    config["name"] = os.environ.get("DB_NAME", "")
    config["user"] = os.environ.get("DB_USER", "")
    config["password"] = os.environ.get("DB_PASSWORD", "")
    config["ssl"] = _env_bool(os.environ.get("DB_SSL"))
    return config


def _persist_config_file(config: dict[str, Any]) -> bool:
    """Datenbankkonfiguration ins config-Volume schreiben.

    Eine vorhandene Datei wird **nie** überschrieben: Was einmal eingerichtet
    ist, bleibt eingerichtet.
    """
    if DATABASE_CONFIG_FILE.exists():
        return False
    try:
        DATABASE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATABASE_CONFIG_FILE.write_text(
            json.dumps(config, indent=2, sort_keys=True), encoding="utf-8"
        )
        return True
    except OSError:  # pragma: no cover - depends on environment
        return False


def _resolve_initial() -> tuple[str, str, dict[str, Any]]:
    """``(URL, Typ, Konfiguration)`` unter Beachtung der gespeicherten Wahl.

    Reihenfolge:

    1. eine vorhandene ``config/database.json`` (aus der Oberfläche oder einer
       früheren Erstinitialisierung über ENV),
    2. die ``DB_*``-Umgebungsvariablen bei der Erstinstallation – sie werden
       gespeichert und greifen dadurch genau einmal,
    3. die althergebrachte ``DATABASE_URL``,
    4. das mitgelieferte SQLite.
    """
    global INIT_SOURCE
    config = _read_config_file()
    if config:
        # Fall 2: Eine vorhandene Konfiguration bleibt immer bestehen – die
        # Umgebungsvariablen werden dann übergangen.
        INIT_SOURCE = "file"
        db_type = normalise_type(config.get("type"))
        return build_url(config), db_type, config

    # Fall 1: no configuration yet -> ENV first-initialisation (if provided).
    env_config = _config_from_env()
    if env_config:
        _persist_config_file(env_config)
        INIT_SOURCE = "env"
        db_type = normalise_type(env_config.get("type"))
        return build_url(env_config), db_type, env_config

    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        INIT_SOURCE = "url"
        backend = make_url(env_url).get_backend_name()
        if backend.startswith("postgresql"):
            db_type = "postgresql"
        elif backend.startswith("mysql"):
            db_type = "mysql"
        else:
            db_type = "sqlite"
        return env_url, db_type, {"type": db_type}
    INIT_SOURCE = "default"
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

# Woher die aktive Konfiguration beim Start kam: „file" (gespeichert), „env"
# (Erstinitialisierung über Docker), „url" (``DATABASE_URL``) oder „default".
INIT_SOURCE = "default"

SQLALCHEMY_DATABASE_URL, DB_TYPE, ACTIVE_CONFIG = _resolve_initial()
DB_BACKEND = make_url(SQLALCHEMY_DATABASE_URL).get_backend_name()  # sqlite/mysql/postgresql
IS_SQLITE = DB_BACKEND == "sqlite"

engine = _build_engine(SQLALCHEMY_DATABASE_URL, DB_TYPE, ACTIVE_CONFIG)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def reconfigure(config: dict[str, Any]) -> None:
    """Verbindung und Sitzungsfabrik auf eine neue Konfiguration umhängen.

    Die bisherige Verbindung wird geschlossen und die Modulvariablen neu
    aufgebaut, sodass folgende Anfragen und Sitzungen die frisch gewählte
    Datenbank benutzen. Bereits laufende Sitzungen behalten ihre alte
    Verbindung, bis sie geschlossen werden.
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

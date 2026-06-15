"""Logical, database-independent data export/import (§0.9.9).

The backup/restore subsystem must be fully database independent: backups store a
*logical* representation of all business data (JSON per table) instead of a raw
SQLite file or a vendor-specific dump. The same logical representation can be
imported into **any** configured backend (SQLite, MySQL, MariaDB, PostgreSQL),
which is what makes cross-database restore possible.

Values are read through the typed SQLAlchemy ``Table`` objects (so they come back
as native Python types) and serialised to JSON-safe primitives. On import the
column types drive the conversion back to native Python objects, so every dialect
binds them correctly. The import runs inside a single transaction and never
leaves a partial state behind.
"""

from __future__ import annotations

import base64
import datetime as _dt
import logging
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine

from . import models

LOGGER = logging.getLogger("erfassung.application")

# Current on-disk layout of the logical export inside a backup archive.
BACKUP_FORMAT_VERSION = 1


def ordered_tables() -> list:
    """Business tables in foreign-key dependency order (parents first)."""
    return list(models.Base.metadata.sorted_tables)


# -- serialisation ----------------------------------------------------------

def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    # Decimal and any other exotic type -> string (lossless enough for our data).
    return str(value)


def _deserialize(value: Any, python_type: type | None) -> Any:
    if value is None:
        return None
    if isinstance(value, dict) and "__bytes__" in value:
        try:
            return base64.b64decode(value["__bytes__"])
        except (ValueError, TypeError):
            return None
    if python_type is None:
        return value
    try:
        if python_type is _dt.datetime and isinstance(value, str):
            return _dt.datetime.fromisoformat(value)
        if python_type is _dt.date and isinstance(value, str):
            return _dt.date.fromisoformat(value)
        if python_type is _dt.time and isinstance(value, str):
            return _dt.time.fromisoformat(value)
        if python_type is bool:
            return bool(value)
    except (ValueError, TypeError):
        return value
    return value


def _column_python_types(table) -> dict[str, type | None]:
    types: dict[str, type | None] = {}
    for column in table.columns:
        try:
            types[column.name] = column.type.python_type
        except (NotImplementedError, AttributeError):  # pragma: no cover - exotic types
            types[column.name] = None
    return types


# -- export -----------------------------------------------------------------

def export_database(engine: Engine) -> dict[str, Any]:
    """Return a JSON-serialisable logical dump of every model table."""
    tables: dict[str, list[dict[str, Any]]] = {}
    with engine.connect() as conn:
        for table in ordered_tables():
            rows: list[dict[str, Any]] = []
            result = conn.execute(table.select())
            for row in result.mappings():
                rows.append({key: _serialize(value) for key, value in row.items()})
            tables[table.name] = rows
    return {"format_version": BACKUP_FORMAT_VERSION, "tables": tables}


def table_counts_from_export(payload: dict[str, Any]) -> dict[str, int]:
    tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
    return {name: len(rows) for name, rows in tables.items() if isinstance(rows, list)}


# -- import -----------------------------------------------------------------

def _fix_postgres_sequences(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for table in ordered_tables():
            if "id" not in table.c:
                continue
            conn.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:tbl, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table.name + "), 1), "
                    "(SELECT COUNT(*) FROM " + table.name + ") > 0)"
                ),
                {"tbl": table.name},
            )


def import_database(engine: Engine, payload: dict[str, Any]) -> dict[str, int]:
    """Replace all model-table data with ``payload`` inside one transaction.

    Only columns present in the *current* schema are imported; unknown columns in
    the backup are ignored and missing columns fall back to their model default.
    Returns the per-table imported row counts. Raises on any error (the
    transaction is rolled back, so no partial import remains).
    """
    tables_data = payload.get("tables", {}) if isinstance(payload, dict) else {}
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    imported: dict[str, int] = {}

    ordered = [t for t in ordered_tables() if t.name in existing]
    with engine.begin() as conn:
        # Clear existing rows in reverse FK order (children first).
        for table in reversed(ordered):
            conn.execute(table.delete())
        # Insert backup rows in FK order (parents first).
        for table in ordered:
            rows = tables_data.get(table.name)
            if not rows:
                imported[table.name] = 0
                continue
            col_types = _column_python_types(table)
            valid_columns = set(col_types)
            prepared = []
            for row in rows:
                clean = {
                    key: _deserialize(value, col_types.get(key))
                    for key, value in row.items()
                    if key in valid_columns
                }
                prepared.append(clean)
            if prepared:
                conn.execute(table.insert(), prepared)
            imported[table.name] = len(prepared)
    _fix_postgres_sequences(engine)
    return imported


def current_row_counts(engine: Engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in ordered_tables():
            counts[table.name] = int(
                conn.execute(select(func.count()).select_from(table)).scalar() or 0
            )
    return counts

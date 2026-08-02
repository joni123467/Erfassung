"""Logischer, datenbankunabhängiger Export und Import.

Sicherung und Rücksicherung müssen von der Datenbank unabhängig sein. Ein
Archiv enthält deshalb eine **logische** Abbildung aller Geschäftsdaten – je
Tabelle eine JSON-Struktur – statt einer SQLite-Datei oder eines
herstellerspezifischen Abzugs. Dieselbe Abbildung lässt sich in **jedes**
konfigurierte Backend einspielen (SQLite, MySQL, MariaDB, PostgreSQL); erst das
macht eine Rücksicherung über Datenbankgrenzen hinweg möglich.

Gelesen wird über die typisierten ``Table``-Objekte von SQLAlchemy, sodass
native Python-Werte zurückkommen; geschrieben wird als JSON-taugliche
Grundtypen. Beim Import führen die Spaltentypen zurück zu nativen Werten, damit
jeder Dialekt sie korrekt bindet. Der Import läuft in **einer** Transaktion und
hinterlässt nie einen halben Stand.
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

# So liegt der logische Export im Sicherungsarchiv.
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
    # ``Decimal`` und alles weitere Ausgefallene wird zur Zeichenkette – für
    # unsere Daten verlustfrei genug.
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
    """Logischer Abzug aller Modelltabellen als JSON-taugliche Struktur."""
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
    """Alle Modelltabellen in **einer** Transaktion durch ``payload`` ersetzen.

    Übernommen werden nur Spalten, die es im **aktuellen** Schema gibt: Spalten,
    die das Archiv zusätzlich mitbringt, werden übergangen; fehlende Spalten
    bekommen den Vorgabewert des Modells. So lässt sich auch eine ältere
    Sicherung einspielen.

    Rückgabe sind die übernommenen Zeilenzahlen je Tabelle. Bei jedem Fehler
    wird die Transaktion zurückgerollt – ein halber Import bleibt nie zurück.
    """
    tables_data = payload.get("tables", {}) if isinstance(payload, dict) else {}
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    imported: dict[str, int] = {}

    ordered = [t for t in ordered_tables() if t.name in existing]
    with engine.begin() as conn:
        # Bestand in umgekehrter Fremdschlüsselreihenfolge leeren – Kinder zuerst.
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

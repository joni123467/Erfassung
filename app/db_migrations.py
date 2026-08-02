"""Versionierter, dialektunabhängiger Migrationslauf.

Läuft auf SQLite (Vorgabe), MySQL 8+/MariaDB und PostgreSQL. Der Stand steht in
der portablen Tabelle ``schema_migrations`` (siehe :mod:`app.db_schema`).

Jede Migration ist mehrfach ausführbar, ohne Schaden anzurichten, läuft nur
vorwärts und erhält vorhandene Daten. Eine einmal veröffentlichte Migration
wird nie geändert und nie umnummeriert – sonst liefe sie auf bestehenden
Installationen nicht mehr oder ein zweites Mal.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy import Index, text
from sqlalchemy.engine import Engine

from . import database, db_schema
from . import models  # noqa: F401 - ensure models are imported for side-effects

try:  # ensure_schema lives in app.main and maintains legacy structures
    from .main import ensure_schema
except Exception:  # pragma: no cover - fallback if import fails
    ensure_schema = None  # type: ignore[assignment]

LOGGER = logging.getLogger("erfassung.application")

MigrationFn = Callable[[Engine], None]


def _baseline(_engine: Engine) -> None:
    """Ausgangspunkt der Zählung; hält den Platz für spätere Schritte frei."""
    return None


def _legacy_groups_present(engine: Engine) -> bool:
    """Trägt die Datenbank noch die alten Gruppenrechte?

    Auf neuen Installationen (und nach Migration 14) gibt es die Spalte
    ``groups.is_admin`` nicht mehr – die historischen Rechte-Migrationen
    werden dann übersprungen, statt Spalten neu anzulegen.
    """
    return db_schema.has_column(engine, "groups", "is_admin")


def _add_group_time_report_permission(engine: Engine) -> None:
    if not _legacy_groups_present(engine):
        return
    if db_schema.add_column(
        engine, "groups", "can_view_time_reports", "INTEGER", default="0"
    ):
        with engine.begin() as connection:
            from sqlalchemy import text

            connection.execute(
                text("UPDATE groups SET can_view_time_reports = 1 WHERE is_admin = 1")
            )


def _add_time_entry_external_columns(engine: Engine) -> None:
    db_schema.add_column(engine, "time_entries", "source", "VARCHAR(255)")
    db_schema.add_column(engine, "time_entries", "external_id", "VARCHAR(255)")
    # Den eindeutigen Index legen ``ensure_schema``/``create_all`` dialektsicher an.


def _add_user_auto_break_deduction(engine: Engine) -> None:
    # Vorgabe 1 erhält das bisherige Verhalten – gesetzliche Pausen werden
    # abgezogen – für jeden Benutzer, den es vor dieser Migration schon gab.
    db_schema.add_column(
        engine, "users", "auto_break_deduction", "BOOLEAN", default="1", backfill_null_to="1"
    )


def _add_holiday_source(engine: Engine) -> None:
    """Distinguish statutory (auto-loaded) holidays from custom ones (§22).

    Existing rows default to 'custom' so that nothing an administrator entered
    manually is ever overwritten by the "Feiertage übernehmen" action. Freshly
    loaded statutory holidays are written with source='statutory'.
    """

    db_schema.add_column(
        engine,
        "holidays",
        "source",
        "VARCHAR(20)",
        default="'custom'",
        backfill_null_to="'custom'",
    )


def _add_backup_job_tables(engine: Engine) -> None:
    """Tabellen der auftragsbasierten Sicherung anlegen, falls sie fehlen.

    ``create_all`` ergänzt ausschließlich fehlende Tabellen und kennt keinen
    Dialektunterschied – der Schritt ist damit beliebig oft wiederholbar.
    """

    models.Base.metadata.create_all(
        bind=engine,
        tables=[models.BackupJob.__table__, models.BackupRun.__table__],
    )


def _add_restore_history_table(engine: Engine) -> None:
    """Historientabelle der Rücksicherungen anlegen."""

    models.Base.metadata.create_all(bind=engine, tables=[models.RestoreRun.__table__])


def _add_restore_run_details(engine: Engine) -> None:
    """Dauer und Protokollkennung in der Rücksicherungshistorie ergänzen."""

    db_schema.add_column(engine, "restore_runs", "duration_seconds", "FLOAT", default="0")
    db_schema.add_column(engine, "restore_runs", "log_token", "VARCHAR(40)", default="''")


def _add_terminal_tables(engine: Engine) -> None:
    """Tabellen der allgemeinen Terminalverwaltung anlegen.

    ``create_all`` ergänzt ausschließlich fehlende Tabellen und kennt keinen
    Dialektunterschied – der Schritt ist beliebig oft wiederholbar.

    Anschließend zieht eine vorhandene ``config/timemoto.json`` aus der Zeit
    davor in eine Terminalzeile um. Bestehende TimeMoto-Installationen laufen
    dadurch ohne neue Einrichtung und ohne Datenverlust weiter.
    """

    models.Base.metadata.create_all(
        bind=engine,
        tables=[models.Terminal.__table__, models.TerminalSyncRun.__table__],
    )
    _migrate_legacy_timemoto_config(engine)


def _migrate_legacy_timemoto_config(engine: Engine) -> None:
    """Eine ``timemoto.json`` aus der Zeit vor 0.9.8 in die Terminaltabelle holen.

    Gesucht wird im regulären config-Volume (``paths.CONFIG_DIR``) und
    zusätzlich im paketeigenen ``config``-Verzeichnis, das die alte Anbindung
    benutzte. So übersteht eine bestehende TimeMoto-Einrichtung das Upgrade,
    ohne neu eingerichtet werden zu müssen.
    """

    import json

    from sqlalchemy.orm import Session

    from . import paths
    from .integrations import timemoto

    candidates = [
        paths.CONFIG_DIR / "timemoto.json",
        timemoto._CONFIG_PATH,  # type: ignore[attr-defined]
        timemoto._LEGACY_CONFIG_PATH,  # type: ignore[attr-defined]
    ]
    payload: dict | None = None
    for candidate in candidates:
        try:
            if candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("host"):
                    payload = data
                    break
        except (OSError, ValueError):  # pragma: no cover - defensive
            continue
    if not payload:
        return

    config = timemoto.TimeMotoConfig()
    config.update_from_dict(payload)
    if not config.host:
        return

    with Session(bind=engine) as session:
        existing = session.execute(
            models.Terminal.__table__.select().where(
                models.Terminal.__table__.c.type == "timemoto"
            )
        ).first()
        if existing:
            return
        extra = {
            "login_path": config.login_path,
            "users_path": config.users_path,
            "events_path": config.events_path,
            "events_limit": config.events_limit,
            "timeout": config.timeout,
        }
        last_sync = None
        if config.last_sync_at:
            try:
                last_sync = datetime.fromisoformat(config.last_sync_at)
            except ValueError:
                last_sync = None
        session.add(
            models.Terminal(
                name="TimeMoto TM-616",
                type="timemoto",
                active=True,
                host=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                use_ssl=config.use_ssl,
                verify_ssl=config.verify_ssl,
                timezone=config.timezone,
                sync_interval_minutes=60,
                config_json=json.dumps(extra),
                status="unknown",
                last_sync_at=last_sync,
                last_event_id=config.last_event_id,
            )
        )
        session.commit()
        LOGGER.info("Legacy-TimeMoto-Konfiguration in Terminalverwaltung übernommen")


def _add_group_permission_overhaul(engine: Engine) -> None:
    """Neue Gruppenberechtigungen (§0.9.11).

    Selbstbedienungsrechte (manuelle Buchungen, eigene Kommentare bearbeiten,
    Urlaubsanträge stellen) erhalten Default 1, damit sich das Verhalten für
    Bestandsgruppen nicht ändert. ``can_manage_companies`` startet mit 0 und
    wird für Administratorgruppen auf 1 gesetzt (Bestandsverhalten: Firmen-
    verwaltung war Admin-only).
    """
    if not _legacy_groups_present(engine):
        return

    if db_schema.add_column(
        engine, "groups", "can_manage_companies", "BOOLEAN", default="0", backfill_null_to="0"
    ):
        with engine.begin() as connection:
            from sqlalchemy import text

            connection.execute(
                text("UPDATE groups SET can_manage_companies = 1 WHERE is_admin = 1")
            )
    for column_name in ("can_manual_time_entries", "can_edit_own_notes", "can_request_vacations"):
        db_schema.add_column(
            engine, "groups", column_name, "BOOLEAN", default="1", backfill_null_to="1"
        )


def _add_group_permission_scopes(engine: Engine) -> None:
    """Geltungsbereich der Team-Rechte (§0.9.12).

    ``'group'`` beschränkt ein Recht auf Benutzer der eigenen Gruppe (Team),
    ``'all'`` gilt für alle Benutzer. Default 'all' erhält das
    Bestandsverhalten (Rechte galten bisher immer für alle Benutzer).
    """
    if not _legacy_groups_present(engine):
        return

    for column_name in (
        "can_manage_vacations_scope",
        "can_approve_manual_entries_scope",
        "can_view_time_reports_scope",
        "can_edit_time_entries_scope",
    ):
        db_schema.add_column(
            engine, "groups", column_name, "VARCHAR(10)", default="'all'", backfill_null_to="'all'"
        )


def _add_manage_users_scope(engine: Engine) -> None:
    """Geltungsbereich für „Benutzer verwalten“ (§0.9.19).

    Ermöglicht Abteilungsadministratoren, die Benutzer der eigenen Gruppe zu
    verwalten. Default 'all' erhält das Bestandsverhalten.
    """
    if not _legacy_groups_present(engine):
        return

    db_schema.add_column(
        engine, "groups", "can_manage_users_scope", "VARCHAR(10)",
        default="'all'", backfill_null_to="'all'",
    )


def _add_remote_location_flags(engine: Engine) -> None:
    """Einsatzort einer Buchung: Remote (z. B. Telefon) oder vor Ort (§0.9.21).

    ``users.remote_flag_enabled`` schaltet das Feld je Benutzer frei (wie das
    Zeitkonto), ``time_entries.is_remote`` hält die Angabe an der Buchung.
    Default 0 erhält das Bestandsverhalten: alle Buchungen gelten als vor Ort,
    und das Feld erscheint erst, wenn es bewusst aktiviert wird.
    """

    db_schema.add_column(
        engine, "users", "remote_flag_enabled", "BOOLEAN", default="0", backfill_null_to="0"
    )
    db_schema.add_column(
        engine, "time_entries", "is_remote", "BOOLEAN", default="0", backfill_null_to="0"
    )


#: Abbildung der alten Gruppenrechte auf die neuen Berechtigungs-Keys.
#: ``can_manage_users`` deckte früher alle Benutzeroperationen ab.
_LEGACY_PERMISSION_MAP: dict[str, tuple[str, ...]] = {
    "can_manual_time_entries": ("Own.Time.Edit",),
    "can_edit_own_notes": ("Own.Comment.Edit",),
    "can_request_vacations": ("Own.Vacation.Request",),
    "can_create_companies": ("Company.Create",),
    "can_manage_companies": ("Company.Manage",),
    "can_approve_manual_entries": ("Time.Approve",),
    "can_edit_time_entries": ("Time.Edit",),
    "can_view_time_reports": ("Time.View",),
    "can_manage_vacations": ("Vacation.Manage",),
    "can_manage_users": ("User.View", "User.Create", "User.Edit", "User.Delete"),
}


def _ensure_system_roles(connection) -> dict[str, int]:
    """Systemrollen anlegen bzw. auf den aktuellen Rechtestand bringen."""
    from sqlalchemy import text

    from . import permissions as registry

    role_ids: dict[str, int] = {}
    for name in registry.SYSTEM_ROLE_NAMES:
        row = connection.execute(
            text("SELECT id FROM roles WHERE name = :name"), {"name": name}
        ).first()
        if row:
            role_id = int(row[0])
        else:
            description = (
                "Uneingeschränkter Zugriff inklusive Rollen, Systemeinstellungen "
                "und Sicherungen."
                if name == registry.ROLE_SUPERADMINISTRATOR
                else "Vollständige Administration ohne Rollen-, System- und Sicherungsverwaltung."
            )
            connection.execute(
                text(
                    "INSERT INTO roles (name, description, is_system, is_active) "
                    "VALUES (:name, :description, 1, 1)"
                ),
                {"name": name, "description": description},
            )
            role_id = int(
                connection.execute(
                    text("SELECT id FROM roles WHERE name = :name"), {"name": name}
                ).scalar()
            )
        role_ids[name] = role_id
        # Rechte der Systemrollen sind fest vorgegeben und werden bei jedem
        # Lauf neu gesetzt, damit neue Rechte automatisch enthalten sind.
        connection.execute(
            text("DELETE FROM role_permissions WHERE role_id = :role_id"),
            {"role_id": role_id},
        )
        for key, scope in registry.system_role_grants(name).items():
            connection.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_key, scope) "
                    "VALUES (:role_id, :key, :scope)"
                ),
                {"role_id": role_id, "key": key, "scope": scope},
            )
    return role_ids


def _migrate_groups_to_roles(engine: Engine) -> None:
    """Rollenmodell einführen und den Bestand übernehmen (§0.10.0).

    1. Neue Tabellen anlegen (idempotent).
    2. Bisherige Gruppenzugehörigkeit nach ``user_groups`` übernehmen.
    3. Systemrollen anlegen; Mitglieder von Administratorgruppen erhalten
       „Superadministrator“ (sie durften bisher alles).
    4. Jede Gruppe mit Rechten wird zur Rolle „Migration – <Name>“; ihre
       Mitglieder erhalten diese Rolle.
    5. Anschließend werden die Rechte-Spalten der Gruppen geleert.

    Bestehende Installationen behalten dadurch exakt ihre bisherigen Rechte.
    """
    from sqlalchemy import text

    from . import models
    from . import permissions as registry

    # 1. Tabellen des Rollenmodells sicherstellen (auch bei Restore alter Backups).
    models.Base.metadata.create_all(
        bind=engine,
        tables=[
            models.Role.__table__,
            models.RolePermission.__table__,
            models.user_roles,
            models.user_groups,
        ],
    )
    db_schema.add_column(engine, "groups", "description", "TEXT")

    with engine.begin() as connection:
        # 2. Zugehörigkeit übernehmen (nur, was noch nicht vorhanden ist).
        if db_schema.has_column(engine, "users", "group_id"):
            rows = connection.execute(
                text("SELECT id, group_id FROM users WHERE group_id IS NOT NULL")
            ).all()
            existing = {
                (int(r[0]), int(r[1]))
                for r in connection.execute(
                    text("SELECT user_id, group_id FROM user_groups")
                ).all()
            }
            for user_id, group_id in rows:
                if (int(user_id), int(group_id)) in existing:
                    continue
                connection.execute(
                    text(
                        "INSERT INTO user_groups (user_id, group_id) "
                        "VALUES (:user_id, :group_id)"
                    ),
                    {"user_id": int(user_id), "group_id": int(group_id)},
                )

        # 3. Systemrollen.
        system_roles = _ensure_system_roles(connection)

        legacy_columns = [
            column
            for column in _LEGACY_PERMISSION_MAP
            if db_schema.has_column(engine, "groups", column)
        ]
        has_is_admin = db_schema.has_column(engine, "groups", "is_admin")
        if not legacy_columns and not has_is_admin:
            return

        selected = ["id", "name"] + legacy_columns
        if has_is_admin:
            selected.append("is_admin")
        for column in legacy_columns:
            scope_column = f"{column}_scope"
            if db_schema.has_column(engine, "groups", scope_column):
                selected.append(scope_column)
        groups = connection.execute(
            text(f"SELECT {', '.join(selected)} FROM groups")
        ).mappings().all()

        def _members(group_id: int) -> list[int]:
            rows = connection.execute(
                text("SELECT user_id FROM user_groups WHERE group_id = :group_id"),
                {"group_id": group_id},
            ).all()
            return [int(row[0]) for row in rows]

        def _assign(user_id: int, role_id: int) -> None:
            exists = connection.execute(
                text(
                    "SELECT 1 FROM user_roles WHERE user_id = :user_id AND role_id = :role_id"
                ),
                {"user_id": user_id, "role_id": role_id},
            ).first()
            if exists:
                return
            connection.execute(
                text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                {"user_id": user_id, "role_id": role_id},
            )

        for group in groups:
            group_id = int(group["id"])
            members = _members(group_id)

            # 3b. Administratorgruppen → Superadministrator (bisher alles erlaubt).
            if has_is_admin and group.get("is_admin"):
                for user_id in members:
                    _assign(user_id, system_roles[registry.ROLE_SUPERADMINISTRATOR])
                continue

            # 4. Rechte der Gruppe in eine Rolle überführen.
            grants: dict[str, str] = {}
            for column in legacy_columns:
                if not group.get(column):
                    continue
                legacy_scope = group.get(f"{column}_scope") or registry.SCOPE_ALL
                scope = (
                    registry.SCOPE_GROUPS
                    if str(legacy_scope) == "group"
                    else registry.SCOPE_ALL
                )
                for key in _LEGACY_PERMISSION_MAP[column]:
                    permission = registry.PERMISSIONS_BY_KEY[key]
                    grants[key] = scope if permission.scoped else registry.default_scope(permission)
            if not grants:
                continue

            role_name = f"Migration – {group['name']}"
            row = connection.execute(
                text("SELECT id FROM roles WHERE name = :name"), {"name": role_name}
            ).first()
            if row:
                role_id = int(row[0])
            else:
                connection.execute(
                    text(
                        "INSERT INTO roles (name, description, is_system, is_active) "
                        "VALUES (:name, :description, 0, 1)"
                    ),
                    {
                        "name": role_name,
                        "description": (
                            f"Automatisch aus den Berechtigungen der Gruppe "
                            f"„{group['name']}“ erzeugt (Umstellung auf Rollen)."
                        ),
                    },
                )
                role_id = int(
                    connection.execute(
                        text("SELECT id FROM roles WHERE name = :name"), {"name": role_name}
                    ).scalar()
                )
                for key, scope in grants.items():
                    connection.execute(
                        text(
                            "INSERT INTO role_permissions (role_id, permission_key, scope) "
                            "VALUES (:role_id, :key, :scope)"
                        ),
                        {"role_id": role_id, "key": key, "scope": scope},
                    )
            for user_id in members:
                _assign(user_id, role_id)

        # 5. Rechte aus den Gruppen entfernen.
        for column in legacy_columns:
            connection.execute(text(f"UPDATE groups SET {column} = 0"))
        if has_is_admin:
            connection.execute(text("UPDATE groups SET is_admin = 0"))


def _add_half_vacation_days(engine: Engine) -> None:
    """Halbe Urlaubstage (ab 0.11.1).

    Bestandsantraege bleiben ganze Tage: Beide Kennzeichen sind ``False``,
    die Berechnung verhaelt sich damit exakt wie bisher.
    """
    db_schema.add_column(
        engine, "vacation_requests", "half_day_start", "BOOLEAN",
        default="0", backfill_null_to="0",
    )
    db_schema.add_column(
        engine, "vacation_requests", "half_day_end", "BOOLEAN",
        default="0", backfill_null_to="0",
    )


def _add_company_locations(engine: Engine) -> None:
    """Standorte je Firma und Einsatzort an der Buchung (ab 0.13.0).

    Bestandsdaten bleiben unangetastet: ``companies.is_internal`` ist ``0``
    (jede vorhandene Firma ist ein Kunde), ``time_entries.location_id`` bleibt
    ``NULL``. Eine Buchung ohne Standort verhält sich damit exakt wie bisher –
    der Einsatzort ergibt sich weiterhin allein aus ``is_remote``.
    """
    if not db_schema.has_table(engine, "company_locations"):
        models.Base.metadata.tables["company_locations"].create(bind=engine, checkfirst=True)

    db_schema.add_column(
        engine, "companies", "is_internal", "BOOLEAN", default="0", backfill_null_to="0"
    )
    db_schema.add_column(engine, "time_entries", "location_id", "INTEGER")
    db_schema.add_column(
        engine, "time_entries", "deleted_location_name", "VARCHAR(255)"
    )


def _add_compliance_and_revisions(engine: Engine) -> None:
    """Revisionssicherheit, Pausenintervalle, Verstöße, Perioden (ab 0.14.0).

    Datenerhaltend und ohne Verhaltensänderung für Bestandsdaten:

    * ``time_entries.break_rule`` bekommt für **vorhandene** Buchungen
      ``legacy_auto``. Damit rechnen abgeschlossene Monate exakt weiter wie
      bisher; nur neue Buchungen folgen der korrigierten Regel, die eine nicht
      genommene Pause nicht mehr als genommen verbucht.
    * Die UTC-Stempel bleiben zunächst ``NULL``. Sie werden nicht geraten:
      Ohne bekannte Zeitzone der Vergangenheit wäre jede Umrechnung eine
      Behauptung. Anzeige und Auswertung nutzen weiterhin ``work_date`` und
      die Ortszeiten.
    * Für jede vorhandene Buchung wird **eine** Revision ``created``
      angelegt, damit die Historie lückenlos bei der Bestandsaufnahme
      beginnt. Als Bearbeiter steht dort die Migration.
    """
    for table in (
        "break_intervals",
        "time_entry_revisions",
        "compliance_flags",
        "payroll_periods",
        "period_confirmations",
        "data_access_log",
    ):
        if not db_schema.has_table(engine, table):
            models.Base.metadata.tables[table].create(bind=engine, checkfirst=True)

    added_rule = db_schema.add_column(
        engine, "time_entries", "break_rule", "VARCHAR(32)", default="'actual'"
    )
    db_schema.add_column(engine, "time_entries", "started_at_utc", "DATETIME")
    db_schema.add_column(engine, "time_entries", "ended_at_utc", "DATETIME")
    db_schema.add_column(engine, "time_entries", "tz_name", "VARCHAR(64)")
    db_schema.add_column(engine, "time_entries", "cancelled_at", "DATETIME")
    db_schema.add_column(engine, "time_entries", "cancelled_by_id", "INTEGER")
    db_schema.add_column(engine, "time_entries", "cancel_reason", "VARCHAR(500)")
    db_schema.add_column(engine, "time_entries", "replaced_by_id", "INTEGER")
    db_schema.add_column(engine, "time_entries", "replaces_id", "INTEGER")

    with engine.begin() as connection:
        if added_rule:
            # Nur beim erstmaligen Anlegen: Bestandsbuchungen behalten die alte
            # Rechnung. Ein späterer Lauf darf das nicht erneut überschreiben.
            connection.execute(
                text("UPDATE time_entries SET break_rule = 'legacy_auto'")
            )
        connection.execute(
            text("UPDATE time_entries SET break_rule = 'actual' WHERE break_rule IS NULL")
        )

        # Laufende Pausen der Altstruktur in ein Intervall überführen, damit
        # eine gerade laufende Pause den Umstieg übersteht.
        rows = connection.execute(
            text(
                "SELECT id, work_date, break_started_at FROM time_entries "
                "WHERE break_started_at IS NOT NULL"
            )
        ).fetchall()
        for row in rows:
            existing = connection.execute(
                text("SELECT COUNT(*) FROM break_intervals WHERE entry_id = :entry_id"),
                {"entry_id": row[0]},
            ).scalar()
            if existing:
                continue
            started = _combine_legacy(row[1], row[2])
            if started is None:
                continue
            connection.execute(
                text(
                    "INSERT INTO break_intervals (entry_id, started_at_utc, ended_at_utc, "
                    "source, created_at) VALUES (:entry_id, :started, NULL, 'legacy', :now)"
                ),
                {"entry_id": row[0], "started": started, "now": datetime.utcnow()},
            )

        # Lückenlose Historie: je Bestandsbuchung ein Anlagevermerk.
        connection.execute(
            text(
                "INSERT INTO time_entry_revisions "
                "(entry_id, revision_no, action, changed_at_utc, actor_label, reason, source) "
                "SELECT t.id, 1, 'created', COALESCE(t.created_at, :now), "
                "'Migration 0.14.0', 'Bestandsaufnahme beim Umstieg auf die "
                "revisionssichere Erfassung', COALESCE(t.source, 'legacy') "
                "FROM time_entries t "
                "WHERE NOT EXISTS (SELECT 1 FROM time_entry_revisions r WHERE r.entry_id = t.id)"
            ),
            {"now": datetime.utcnow()},
        )


def _combine_legacy(work_date: object, clock: object) -> datetime | None:
    """``work_date`` + ``break_started_at`` aus der Datenbank zusammensetzen.

    Die Treiber liefern je nach Backend ``date``/``time`` oder Text; beides
    muss hier ankommen, ohne die Migration zu kippen.
    """
    from datetime import date as date_cls, time as time_cls

    if work_date is None or clock is None:
        return None
    if isinstance(work_date, str):
        try:
            work_date = date_cls.fromisoformat(work_date[:10])
        except ValueError:
            return None
    if isinstance(clock, str):
        try:
            clock = time_cls.fromisoformat(clock[:8])
        except ValueError:
            return None
    if isinstance(work_date, datetime):
        work_date = work_date.date()
    if not isinstance(work_date, date_cls) or not isinstance(clock, time_cls):
        return None
    return datetime.combine(work_date, clock)


def _add_compliance_lifecycle(engine: Engine) -> None:
    """Lebenszyklus der Compliance-Feststellungen (ab 0.15.0).

    Bis 0.14.2 wurden offene Kennzeichnungen bei jeder Neuberechnung physisch
    gelöscht. Diese Migration ergänzt die Felder, mit denen sie stattdessen
    fortgeschrieben werden.

    Datenerhaltend: Vorhandene Kennzeichnungen behalten ihren Inhalt und
    bekommen einen passenden Zustand – bereits bestätigte ``acknowledged``,
    alle übrigen ``detected``. Die Prüfsumme bleibt zunächst ``NULL``; sie wird
    bei der nächsten Neuberechnung gesetzt. Bis dahin gilt eine Bestätigung
    weiter, denn eine leere Prüfsumme wird nicht als Änderung gewertet.
    """
    if not db_schema.has_table(engine, "compliance_flags"):
        models.Base.metadata.tables["compliance_flags"].create(
            bind=engine, checkfirst=True
        )
        return

    added_state = db_schema.add_column(
        engine, "compliance_flags", "state", "VARCHAR(16)", default="'detected'"
    )
    db_schema.add_column(engine, "compliance_flags", "fingerprint", "VARCHAR(64)")
    db_schema.add_column(
        engine, "compliance_flags", "acknowledged_fingerprint", "VARCHAR(64)"
    )
    db_schema.add_column(engine, "compliance_flags", "resolved_at", "DATETIME")
    db_schema.add_column(engine, "compliance_flags", "reopened_at", "DATETIME")
    db_schema.add_column(
        engine, "compliance_flags", "revision_no", "INTEGER", default="1"
    )
    db_schema.add_column(engine, "compliance_flags", "updated_at", "DATETIME")

    with engine.begin() as connection:
        # Immer absichern (idempotent): NULL-Werte auffüllen …
        connection.execute(
            text("UPDATE compliance_flags SET state = 'detected' WHERE state IS NULL")
        )
        connection.execute(
            text("UPDATE compliance_flags SET revision_no = 1 WHERE revision_no IS NULL")
        )
        connection.execute(
            text(
                "UPDATE compliance_flags SET updated_at = detected_at "
                "WHERE updated_at IS NULL"
            )
        )
        if added_state:
            # … und beim ersten Anlegen den Zustand aus dem Bestand ableiten.
            connection.execute(
                text(
                    "UPDATE compliance_flags SET state = 'acknowledged' "
                    "WHERE acknowledged_at IS NOT NULL"
                )
            )


def _add_finding_keys_and_holiday_notes(engine: Engine) -> None:
    """Feststellungsschlüssel und Sonn-/Feiertagsvermerke (ab 0.16.0).

    Zwei Ergänzungen an ``compliance_flags``:

    * ``finding_key`` und ``shift_start_utc`` machen eine Feststellung je
      **Schicht** eindeutig. Bis 0.15.0 wurde nur über ``code`` zugeordnet –
      zwei fehlende Ruhepausen an einem Tag fielen dadurch zu einer
      Feststellung zusammen.
    * Vermerke zur Sonn- und Feiertagsarbeit (§§ 9 ff. ArbZG): Ausnahmegrund,
      Rechts-/Betriebsgrundlage, Ersatzruhetag und Bearbeitungsstand.

    Datenerhaltend: Vorhandene Feststellungen behalten Inhalt, Zustand und
    Bestätigung. ``finding_key`` bleibt zunächst ``NULL``; die nächste
    Neuberechnung trägt ihn nach und ordnet dabei über den Code zu, damit keine
    Bestätigung verlorengeht.
    """
    if not db_schema.has_table(engine, "compliance_flags"):
        models.Base.metadata.tables["compliance_flags"].create(
            bind=engine, checkfirst=True
        )
        return

    db_schema.add_column(engine, "compliance_flags", "finding_key", "VARCHAR(64)")
    db_schema.add_column(engine, "compliance_flags", "shift_start_utc", "DATETIME")
    db_schema.add_column(engine, "compliance_flags", "exception_reason", "VARCHAR(500)")
    db_schema.add_column(engine, "compliance_flags", "legal_basis", "VARCHAR(255)")
    db_schema.add_column(engine, "compliance_flags", "replacement_rest_date", "DATE")
    db_schema.add_column(
        engine, "compliance_flags", "handling_state", "VARCHAR(32)", default="'open'"
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE compliance_flags SET handling_state = 'open' "
                "WHERE handling_state IS NULL"
            )
        )


def _add_compliance_logs(engine: Engine) -> None:
    """Append-only Historie der Compliance-Bewertung (ab 0.17.0).

    Bis 0.16.0 wurden Ausnahmegrund, Rechtsgrundlage, Ersatzruhetag und
    Bearbeitungsstand an der Feststellung **überschrieben**. Wer eine
    Begründung nachträglich austauschte, hinterließ keine Spur. Diese Migration
    legt ``compliance_logs`` an; ab hier wird jede Änderung ergänzt statt
    ersetzt.

    Für den **Bestand** wird je vorhandener Feststellung genau ein
    ``migrated``-Vermerk geschrieben. Er behauptet nicht, die frühere Historie
    zu kennen – er hält den Stand fest, wie er bei der Umstellung vorlag, und
    macht damit sichtbar, ab welchem Zeitpunkt die Historie lückenlos ist.

    Idempotent: Die Tabelle wird mit ``checkfirst`` angelegt, und der
    Bestandsvermerk wird nur für Feststellungen geschrieben, die noch keinen
    haben. Datenerhaltend: An ``compliance_flags`` ändert sich nichts.
    """
    models.Base.metadata.tables["compliance_logs"].create(bind=engine, checkfirst=True)

    if not db_schema.has_table(engine, "compliance_flags"):
        return

    # Kein ``INSERT … SELECT`` mit Zeitfunktion: ``NOW()``/``datetime('now')``
    # heißen je Backend anders. Der Zeitstempel kommt deshalb als Parameter.
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO compliance_logs "
                "(flag_id, action, changed_at_utc, actor_label, reason, source, after_json) "
                "SELECT f.id, 'migrated', :now, 'System', "
                "'Bestandsvermerk bei Einfuehrung der Compliance-Historie (0.17.0)', "
                "'migration', NULL FROM compliance_flags f "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM compliance_logs l WHERE l.flag_id = f.id"
                ")"
            ),
            {"now": datetime.utcnow()},
        )


def _add_user_deactivation(engine: Engine) -> None:
    """Aufbewahrungssichere Kontodeaktivierung (0.19.0)."""
    if not db_schema.has_table(engine, "users"):
        models.Base.metadata.tables["users"].create(bind=engine, checkfirst=True)
        return
    db_schema.add_column(
        engine, "users", "is_active", "BOOLEAN NOT NULL",
        default="1", backfill_null_to="1",
    )
    db_schema.add_column(engine, "users", "deactivated_at", "DATETIME")
    db_schema.add_column(engine, "users", "deactivation_reason", "VARCHAR(500)")


def _add_employment_period(engine: Engine) -> None:
    """Beschäftigungszeitraum am Benutzer (ab 0.20.2).

    Die Jahresprüfung der freien Sonntage nach § 11 Abs. 1 ArbZG rechnete bis
    0.20.1 über das **ganze** Kalenderjahr. Wer im September eingetreten war,
    bekam damit die Sonntage von Januar bis August als „beschäftigungsfrei"
    gutgeschrieben – Sonntage, an denen es überhaupt kein
    Beschäftigungsverhältnis gab. Das Ergebnis war eine Zusicherung, die die
    Daten nicht hergaben.

    Beide Spalten sind ``DATE NULL``. Bestandskonten bekommen ausdrücklich
    **kein** erfundenes Eintrittsdatum: Ein geratenes Datum wäre in einem
    gesetzlichen Nachweis schlimmer als eine ehrliche Lücke. Ohne Beginn weist
    die Anwendung „Beschäftigungsbeginn fehlt" aus und trifft kein positives
    Prüfurteil.

    Portabel über SQLite, MySQL/MariaDB und PostgreSQL, beliebig oft
    wiederholbar und datenerhaltend: ``db_schema.add_column`` prüft die
    Spaltenexistenz vorher und rührt vorhandene Zeilen nicht an.
    """
    if not db_schema.has_table(engine, "users"):
        models.Base.metadata.tables["users"].create(bind=engine, checkfirst=True)
        return
    # Kein ``default`` und kein ``backfill_null_to``: NULL ist hier die
    # richtige Antwort und soll NULL bleiben.
    db_schema.add_column(engine, "users", "employment_start_date", "DATE")
    db_schema.add_column(engine, "users", "employment_end_date", "DATE")


def _add_planning_and_calendar(engine: Engine) -> None:
    """Arbeitspläne, Abwesenheiten, Urlaubskonto und ICS-Feeds (0.20.5)."""
    for table_name in (
        "work_schedules", "absence_types", "vacation_entitlement_entries", "calendar_feeds"
    ):
        models.Base.metadata.tables[table_name].create(bind=engine, checkfirst=True)
    if db_schema.has_table(engine, "vacation_requests"):
        db_schema.add_column(
            engine, "vacation_requests", "absence_type_key", "VARCHAR(64) NOT NULL",
            default="'vacation'", backfill_null_to="'vacation'",
        )
    defaults = (
        ("vacation", "Urlaub", 1, 1, 0, 1, 0),
        ("overtime", "Überstundenabbau", 1, 0, 1, 1, 0),
        ("sick", "Abwesend", 0, 0, 0, 1, 1),
        ("special", "Sonderurlaub", 1, 0, 0, 1, 0),
        ("parental", "Elternzeit", 1, 0, 0, 0, 1),
        ("unpaid", "Unbezahlte Freistellung", 1, 0, 0, 0, 0),
    )
    with engine.begin() as connection:
        for row in defaults:
            exists = connection.execute(
                text("SELECT 1 FROM absence_types WHERE key = :key"), {"key": row[0]}
            ).first()
            if not exists:
                connection.execute(text(
                    "INSERT INTO absence_types (key,label,requires_approval,deducts_vacation,"
                    "deducts_overtime,credits_target_time,confidential,active) "
                    "VALUES (:key,:label,:approval,:vacation,:overtime,:credit,:confidential,1)"
                ), dict(key=row[0], label=row[1], approval=row[2], vacation=row[3],
                        overtime=row[4], credit=row[5], confidential=row[6]))


def _add_entitlement_source_key(engine: Engine) -> None:
    """Idempotente Anspruchsbuchungen für automatische Jahresüberträge (0.20.5)."""
    if not db_schema.has_table(engine, "vacation_entitlement_entries"):
        models.Base.metadata.tables["vacation_entitlement_entries"].create(bind=engine, checkfirst=True)
        return
    db_schema.add_column(engine, "vacation_entitlement_entries", "source_key", "VARCHAR(191)")
    Index(
        "uq_vacation_entitlement_source_key",
        models.Base.metadata.tables["vacation_entitlement_entries"].c.source_key,
        unique=True,
    ).create(bind=engine, checkfirst=True)


MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _baseline),
    (2, _add_group_time_report_permission),
    (3, _add_time_entry_external_columns),
    (4, _add_user_auto_break_deduction),
    (5, _add_holiday_source),
    (6, _add_backup_job_tables),
    (7, _add_restore_history_table),
    (8, _add_restore_run_details),
    (9, _add_terminal_tables),
    (10, _add_group_permission_overhaul),
    (11, _add_group_permission_scopes),
    (12, _add_manage_users_scope),
    (13, _add_remote_location_flags),
    (14, _migrate_groups_to_roles),
    (15, _add_half_vacation_days),
    (16, _add_company_locations),
    (17, _add_compliance_and_revisions),
    (18, _add_compliance_lifecycle),
    (19, _add_finding_keys_and_holiday_notes),
    (20, _add_compliance_logs),
    (21, _add_user_deactivation),
    (22, _add_employment_period),
    (23, _add_planning_and_calendar),
    (24, _add_entitlement_source_key),
]


def _apply_migrations(engine: Engine, migrations: Iterable[tuple[int, MigrationFn]]) -> None:
    applied = db_schema.applied_versions(engine)
    for version, upgrade in migrations:
        if version in applied:
            continue
        LOGGER.info("Migration %s wird angewendet", version)
        upgrade(engine)
        db_schema.mark_applied(engine, version)


def run(database_path: Path | None = None) -> None:
    if database.IS_SQLITE and database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    if ensure_schema is not None:
        ensure_schema()
    _apply_migrations(database.engine, MIGRATIONS)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Führt Datenbankmigrationen für Erfassung aus.")
    parser.add_argument(
        "--database",
        default=None,
        help="Optionaler Pfad zur SQLite-Datenbank (nur für SQLite relevant)",
    )
    args = parser.parse_args(argv)
    run(Path(args.database) if args.database else None)


if __name__ == "__main__":
    main()

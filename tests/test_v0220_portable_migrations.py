"""Boolean-Parameter und Legacy-Rechte auf allen SQL-Dialekten erhalten."""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

import pytest

from test_v0209 import main


def test_seed_migrations_bind_real_booleans_and_are_idempotent(main, tmp_path):
    from app import db_migrations, models, permissions

    engine = create_engine(f"sqlite:///{tmp_path}/portable-seeds.db")
    models.Base.metadata.create_all(engine)
    boolean_parameters = []

    @event.listens_for(engine, "before_execute")
    def check_boolean_bindings(connection, statement, multiparams, params, options):
        sql = str(statement)
        if sql.startswith("INSERT INTO roles "):
            assert type(params["is_system"]) is bool
            assert type(params["is_active"]) is bool
            boolean_parameters.append(params.copy())
        if sql.startswith("INSERT INTO absence_types "):
            compiled = statement.compile().params
            for name in ("requires_approval", "deducts_vacation", "deducts_overtime", "credits_target_time", "confidential", "active"):
                assert type(compiled[name]) is bool
            boolean_parameters.append(compiled.copy())
            from sqlalchemy.dialects import mysql, postgresql

            assert "`key`" in str(statement.compile(dialect=mysql.dialect()))
            assert "requires_approval" in str(statement.compile(dialect=postgresql.dialect()))
        if sql.startswith("SELECT absence_types.key"):
            from sqlalchemy.dialects import mysql

            assert "absence_types.`key`" in str(statement.compile(dialect=mysql.dialect()))

    for _ in range(2):
        with engine.begin() as connection:
            role_ids = db_migrations._ensure_system_roles(connection)
        db_migrations._add_planning_and_calendar(engine)
    assert set(role_ids) == set(permissions.SYSTEM_ROLE_NAMES)
    assert len(boolean_parameters) == len(role_ids) + 6
    with Session(engine) as db:
        assert db.query(models.Role).count() == len(role_ids)
        for role in db.query(models.Role):
            assert role.is_system and role.is_active
            assert {grant.permission_key: grant.scope for grant in role.permissions} == permissions.system_role_grants(role.name)
        vacation = db.get(models.AbsenceType, "vacation")
        assert vacation.requires_approval and vacation.deducts_vacation and vacation.active
        assert not vacation.deducts_overtime and not vacation.confidential
        assert db.query(models.AbsenceType).count() == 6
    engine.dispose()


@pytest.mark.parametrize("flag_type", ["BOOLEAN", "INTEGER"])
def test_legacy_boolean_and_integer_group_rights_keep_members_and_scopes(main, tmp_path, flag_type):
    from app import db_migrations, models, permissions

    engine = create_engine(f"sqlite:///{tmp_path}/legacy-{flag_type}.db")
    models.Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE groups ADD COLUMN is_admin {flag_type} DEFAULT FALSE"))
        connection.execute(text(f"ALTER TABLE groups ADD COLUMN can_edit_time_entries {flag_type} DEFAULT FALSE"))
        connection.execute(text("ALTER TABLE groups ADD COLUMN can_edit_time_entries_scope VARCHAR(10) DEFAULT 'group'"))
        connection.execute(text("INSERT INTO groups (id, name, is_admin, can_edit_time_entries) VALUES (1, 'Verwaltung', TRUE, FALSE), (2, 'Team', FALSE, TRUE)"))
    with Session(engine) as db:
        db.add_all([models.User(id=n, username=f"legacy-{n}", full_name=f"Bestand {n}", email=f"legacy-{n}@example.invalid", pin_code=f"120{n}", group_id=n) for n in (1, 2)])
        db.commit()
    db_migrations._add_group_time_report_permission(engine)
    db_migrations._add_group_permission_overhaul(engine)
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT is_admin, can_manage_companies, can_view_time_reports FROM groups ORDER BY id")).all()
        assert rows == [(1, 1, 1), (0, 0, 0)]
    db_migrations._migrate_groups_to_roles(engine)
    db_migrations._migrate_groups_to_roles(engine)
    with Session(engine) as db:
        admin = db.get(models.User, 1)
        member = db.get(models.User, 2)
        assert [role.name for role in admin.roles] == [permissions.ROLE_SUPERADMINISTRATOR]
        role = next(role for role in member.roles if role.name == "Migration – Team")
        assert not role.is_system and role.is_active
        assert {grant.permission_key: grant.scope for grant in role.permissions}["Time.Edit"] == "groups"
        assert [group.id for group in admin.groups] == [1]
        assert [group.id for group in member.groups] == [2]
        assert db.query(models.User).count() == 2
    with engine.begin() as connection:
        assert connection.execute(text("SELECT is_admin, can_edit_time_entries FROM groups ORDER BY id")).all() == [(0, 0), (0, 0)]
    engine.dispose()


def test_legacy_boolean_defaults_preserve_existing_rows(main, tmp_path):
    from app import db_migrations

    engine = create_engine(f"sqlite:///{tmp_path}/legacy-columns.db")
    with engine.begin() as connection:
        for name in ("users", "time_entries", "vacation_requests"):
            connection.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)"))
            connection.execute(text(f"INSERT INTO {name} (id) VALUES (7)"))
    for _ in range(2):
        db_migrations._add_user_auto_break_deduction(engine)
        db_migrations._add_remote_location_flags(engine)
        db_migrations._add_half_vacation_days(engine)
        db_migrations._add_user_deactivation(engine)
    with engine.begin() as connection:
        assert connection.execute(text("SELECT id, auto_break_deduction, remote_flag_enabled, is_active FROM users")).all() == [(7, 1, 0, 1)]
        assert connection.execute(text("SELECT id, is_remote FROM time_entries")).all() == [(7, 0)]
        assert connection.execute(text("SELECT id, half_day_start, half_day_end FROM vacation_requests")).all() == [(7, 0, 0)]
    engine.dispose()

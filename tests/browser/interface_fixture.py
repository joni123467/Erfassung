"""Create isolated UI regression actors; never open a developer database."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time, timedelta

import runtime  # noqa: F401 -- configures disposable E2E volumes before app imports
from app import crud, database, models, permissions, schemas


def create(prefix: str) -> dict:
    password = "Browser!12345"
    with database.SessionLocal() as db:
        group = models.Group(name=f"{prefix}-Montage-und-Service-Team")
        db.add(group)
        db.commit()
        own = {p.key: "self" for p in permissions.PERMISSIONS_BY_KEY.values() if p.self_service}
        member_role = crud.create_role(
            db, name=f"{prefix}-Mitglied", permissions={**own, "Company.Create": "all"}
        )
        restricted_role = crud.create_role(db, name=f"{prefix}-Ohne-Firmenanlage", permissions=own)
        lead_role = crud.create_role(
            db,
            name=f"{prefix}-Teamleitung",
            permissions={**own, "User.View": "groups", "Time.View": "groups", "Time.Approve": "groups"},
        )
        admin_role = crud.get_role_by_name(db, permissions.ROLE_SUPERADMINISTRATOR)
        assert admin_role is not None, "The test server must finish application startup first"
        result = {"password": password, "group_id": group.id, "actors": {}}
        for key, role, in_group in (
            ("admin", admin_role, False),
            ("member", member_role, True),
            ("lead", lead_role, True),
            ("outsider", restricted_role, False),
        ):
            username = f"{prefix}-{key}"
            name = (
                "Alexandra-Maria von Beispielhausen "
                "Montage-Service-Qualitätssicherung-International " + username
            )
            user = crud.create_user(
                db,
                schemas.UserCreate(
                    username=username,
                    full_name=name,
                    email=f"{username}@example.com",
                    password=password,
                    standard_weekly_hours=40,
                    time_account_enabled=True,
                    overtime_vacation_enabled=True,
                    employment_start_date=date(2024, 1, 1),
                    group_ids=[group.id] if in_group else [],
                    role_ids=[role.id],
                ),
            )
            user.must_change_password = False
            db.commit()
            result["actors"][key] = {"id": user.id, "username": username, "name": name}
        company = models.Company(
            name=f"{prefix}-Gebäudetechnik-und-Elektroinstallation-Musterkundenbetrieb",
            description="Langer Firmenname für responsive Originalformulare",
        )
        db.add(company)
        db.commit()
        result["company"] = {"id": company.id, "name": company.name}
        day = date.today() - timedelta(days=1)
        entry = models.TimeEntry(
            user_id=result["actors"]["lead"]["id"],
            company_id=company.id,
            work_date=day,
            start_time=time(8),
            end_time=time(16),
            break_minutes=30,
            status=models.TimeEntryStatus.APPROVED,
            source="browser-fixture",
            tz_name="Europe/Berlin",
        )
        db.add(entry)
        db.flush()
        interval = models.BreakInterval(
            entry_id=entry.id,
            started_at_utc=datetime.combine(day, time(10, 0, 23)),
            ended_at_utc=datetime.combine(day, time(10, 30, 23)),
            tz_name="Europe/Berlin",
            source="browser-fixture",
        )
        db.add(interval)
        db.commit()
        result["break_entry"] = {"id": entry.id, "break_id": interval.id}
        return result


def snapshot(username: str) -> dict:
    with database.SessionLocal() as db:
        user = db.query(models.User).filter_by(username=username).one()
        entries = db.query(models.TimeEntry).filter_by(user_id=user.id).order_by(models.TimeEntry.id).all()
        return {
            "user_id": user.id,
            "entries": [
                {
                    "id": entry.id,
                    "date": entry.work_date.isoformat(),
                    "start": entry.start_time.isoformat(),
                    "end": entry.end_time.isoformat() if entry.end_time else None,
                    "company": entry.company.name if entry.company else None,
                    "break_started": entry.break_started_at.isoformat() if entry.break_started_at else None,
                    "status": entry.status,
                    "break_minutes": entry.total_break_minutes,
                }
                for entry in entries
            ],
        }


if __name__ == "__main__":
    command, value = sys.argv[1:]
    print(json.dumps(create(value) if command == "create" else snapshot(value)))

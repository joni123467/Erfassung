"""Tests für 0.20.9 – doppelt gezählte Zeit nach einem überschreibenden Nachtrag.

Gemeldet wurde eine Tageszeile in „Woche im Blick", die zu einer Buchung von
08:00 bis 15:42 **10:46 Std** auswies. 7:42 wären richtig gewesen.

Die Ursache lag nicht in der Wochenansicht, sondern eine Ebene tiefer.
``app.worktime.entry_bounds`` – die einzige Dauerberechnung der Anwendung –
liest **bevorzugt** die Spalten ``started_at_utc``/``ended_at_utc`` und rechnet
nur ohne diese Stempel aus ``work_date``/``start_time``/``end_time``. Wer eine
Buchung kürzt oder teilt und dabei nur die Ortszeiten umsetzt, ändert damit die
Anzeige, nicht aber die gerechnete Dauer.

Genau das taten bis 0.20.8 drei Stellen in ``app.crud``:

* ``_split_closed_entry`` – Nachtrag innerhalb einer abgeschlossenen Buchung,
* ``_apply_overwrite`` – kürzen/teilen/verdrängen beim überschreibenden
  Bearbeiten,
* der Zweig für die laufende Buchung in ``create_manual_time_entry``.

Der gekürzte Rest zählte weiter seine ursprüngliche Länge; die ersetzte Zeit
stand ein zweites Mal in Tages-, Wochen- und Monatssumme. Aus 08:00–15:42 plus
einem Nachtrag ab 12:38 wurden exakt die gemeldeten 646 Minuten = 10:46 Std.

Behoben wird das dort, wo es nicht wieder auseinanderlaufen kann: Ein
Mapper-Ereignis (``models._sync_time_entry_stamps``) bindet die UTC-Stempel bei
**jedem** INSERT und UPDATE an die Ortszeiten – auch für Code, der erst noch
geschrieben wird. Migration 24 gleicht bereits gespeicherte Buchungen an.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import licensed_env

ROOT = Path(__file__).resolve().parent.parent
BERLIN = ZoneInfo("Europe/Berlin")

#: Der gemeldete Fall, Minute für Minute.
DAY = date(2026, 6, 10)
ORIGINAL_START = time(8, 0)
ORIGINAL_END = time(15, 42)
MANUAL_START = time(12, 38)
MANUAL_END = time(13, 38)
#: 08:00–15:42 sind 7:42 Std. Mehr kann an diesem Tag nicht gearbeitet worden
#: sein – gleich wie oft die Zeit nachträglich aufgeteilt wurde.
GROSS_MINUTES = 462


def _fresh_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("ERFASSUNG_TIMEZONE", "Europe/Berlin")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    for key in ("DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]
    import app.main as main

    licensed_env.activate()
    return main


@pytest.fixture()
def main(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    module = _fresh_app(tmp_path, monkeypatch)
    with TestClient(module.app):
        pass
    return module


@pytest.fixture()
def client(main):
    from fastapi.testclient import TestClient

    with TestClient(main.app) as test_client:
        from app import crud, database, security

        db = database.SessionLocal()
        try:
            admin = crud.get_user_by_username(db, "admin")
            admin.password_hash = security.hash_password("Admin!0000")
            admin.must_change_password = False
            db.commit()
        finally:
            db.close()
        yield test_client


_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(client, url: str) -> str:
    match = _CSRF_RE.search(client.get(url, follow_redirects=True).text)
    assert match, f"kein CSRF-Token auf {url}"
    return match.group(1)


def _login(client, username: str = "admin", password: str = "Admin!0000") -> None:
    response = client.post(
        "/login",
        data={"username": username, "password": password,
              "csrf_token": _csrf(client, "/login")},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _db():
    from app import database

    return database.SessionLocal()


def _admin_id() -> int:
    from app import crud

    with _db() as db:
        return int(crud.get_user_by_username(db, "admin").id)


def _utc(day: date, moment: time) -> datetime:
    """Ortszeit als naiven UTC-Wert – so, wie die Anwendung stempelt."""
    return datetime.combine(day, moment).replace(tzinfo=BERLIN).astimezone(
        timezone.utc
    ).replace(tzinfo=None)


def _stamped_entry(
    db,
    *,
    day: date = DAY,
    start: time = ORIGINAL_START,
    end: time = ORIGINAL_END,
    status: str | None = None,
    is_manual: bool = False,
):
    """Buchung **mit** UTC-Stempeln – so entstehen sie über Formular, Terminal
    und Stempeluhr. Ohne Stempel griffe die Rückfallebene und der Fehler bliebe
    unsichtbar; genau daran wäre der Test sonst vorbeigelaufen."""
    from app import models

    row = models.TimeEntry(
        user_id=_admin_id(),
        work_date=day,
        start_time=start,
        end_time=end,
        break_minutes=0,
        is_open=False,
        status=status or models.TimeEntryStatus.APPROVED,
        is_manual=is_manual,
        break_rule=models.BreakRule.ACTUAL,
        tz_name="Europe/Berlin",
        started_at_utc=_utc(day, start),
        ended_at_utc=_utc(day, end),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _counted_minutes(db, day: date) -> int:
    """Summe der Arbeitszeit eines Tages – wie sie jede Übersicht bildet."""
    from app import crud, models

    rows = crud.get_time_entries_for_user(db, _admin_id(), start=day, end=day)
    return sum(
        row.worked_minutes
        for row in rows
        if row.status not in (models.TimeEntryStatus.CANCELLED,
                              models.TimeEntryStatus.REJECTED)
    )


def _assert_stamps_match_local_times(db) -> None:
    """Kernzusicherung: Für **jede** abgeschlossene Buchung muss die gestempelte
    Dauer der Dauer aus ihren Ortszeiten entsprechen. Läuft das auseinander,
    zeigt die Anwendung andere Zeiten an, als sie rechnet."""
    from app import models, worktime

    deviations = []
    for entry in db.query(models.TimeEntry).all():
        if entry.is_open:
            continue
        start, end = worktime.entry_bounds(entry)
        stamped = int((end - start).total_seconds() // 60)
        local_start = datetime.combine(entry.work_date, entry.start_time)
        local_end = datetime.combine(entry.work_date, entry.end_time)
        if local_end < local_start:
            local_end += timedelta(days=1)
        local = int((local_end - local_start).total_seconds() // 60)
        if stamped != local:
            deviations.append(
                f"#{entry.id} {entry.start_time}–{entry.end_time}: "
                f"gerechnet {stamped} min, angezeigt {local} min"
            )
    assert not deviations, "Ortszeit und UTC-Stempel weichen ab: " + "; ".join(deviations)


# ---------------------------------------------------------------------------
# Der gemeldete Fall
# ---------------------------------------------------------------------------


def test_nachtrag_in_bestehende_buchung_zaehlt_die_zeit_nur_einmal(main):
    """08:00–15:42, Nachtrag ab 12:38 – die Meldung aus der Praxis."""
    from app import crud, models, schemas

    with _db() as db:
        _stamped_entry(db)
        entry, split = crud.create_manual_time_entry(db, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=DAY,
            start_time=MANUAL_START, end_time=MANUAL_END, break_minutes=0,
            status=models.TimeEntryStatus.PENDING, is_manual=True, is_open=False,
            started_at_utc=_utc(DAY, MANUAL_START),
            ended_at_utc=_utc(DAY, MANUAL_END),
            tz_name="Europe/Berlin",
        ))
        assert split is True
        assert entry.id is not None
        # Bis 0.20.8 kamen hier 646 Minuten heraus – 10:46 Std.
        assert _counted_minutes(db, DAY) == GROSS_MINUTES
        _assert_stamps_match_local_times(db)


def test_woche_im_blick_weist_den_geteilten_tag_richtig_aus(main):
    """Dieselbe Rechnung dort, wo sie gemeldet wurde."""
    from app import crud, database, models, schemas

    with _db() as db:
        _stamped_entry(db)
        crud.create_manual_time_entry(db, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=DAY,
            start_time=MANUAL_START, end_time=MANUAL_END, break_minutes=0,
            status=models.TimeEntryStatus.PENDING, is_manual=True, is_open=False,
            started_at_utc=_utc(DAY, MANUAL_START),
            ended_at_utc=_utc(DAY, MANUAL_END),
            tz_name="Europe/Berlin",
        ))

    with database.SessionLocal() as db:
        user = crud.get_user_by_username(db, "admin")
        overview = main._build_weekly_overview(db, user, DAY, today=DAY)
        day_row = next(row for row in overview["days"] if row["date"] == DAY)
        assert day_row["worked_minutes"] == GROSS_MINUTES
        assert overview["total_minutes"] == GROSS_MINUTES


def test_teilung_hinterlaesst_drei_luekenlose_abschnitte(main):
    """Die drei Abschnitte müssen bruchlos aneinander anschließen."""
    from app import crud, models, schemas

    with _db() as db:
        _stamped_entry(db)
        crud.create_manual_time_entry(db, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=DAY,
            start_time=MANUAL_START, end_time=MANUAL_END, break_minutes=0,
            status=models.TimeEntryStatus.PENDING, is_manual=True, is_open=False,
            started_at_utc=_utc(DAY, MANUAL_START),
            ended_at_utc=_utc(DAY, MANUAL_END),
            tz_name="Europe/Berlin",
        ))
        rows = sorted(
            (row for row in crud.get_time_entries_for_user(db, _admin_id(),
                                                           start=DAY, end=DAY)
             if row.status != models.TimeEntryStatus.CANCELLED),
            key=lambda row: row.start_time,
        )
        assert [(row.start_time, row.end_time) for row in rows] == [
            (ORIGINAL_START, MANUAL_START),
            (MANUAL_START, MANUAL_END),
            (MANUAL_END, ORIGINAL_END),
        ]
        # Und jeder Abschnitt rechnet genau seine angezeigte Länge.
        assert [row.worked_minutes for row in rows] == [278, 60, 124]


# ---------------------------------------------------------------------------
# Überschreibendes Bearbeiten (Verwaltung)
# ---------------------------------------------------------------------------


def test_ueberschreibendes_kuerzen_zieht_den_stempel_mit(main):
    from app import crud, models, schemas

    with _db() as db:
        kept = _stamped_entry(db, start=time(17, 0), end=time(19, 0))
        target = _stamped_entry(db, start=time(8, 0), end=time(16, 0))
        crud.update_time_entry(db, target.id, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=DAY,
            start_time=time(8, 0), end_time=time(18, 0), break_minutes=0,
            status=models.TimeEntryStatus.APPROVED, is_open=False,
        ), overwrite=True, reason="Korrektur")
        db.refresh(kept)
        assert (kept.start_time, kept.end_time) == (time(18, 0), time(19, 0))
        assert kept.worked_minutes == 60  # bis 0.20.8: 120
        # 08:00–18:00 und 18:00–19:00 – zusammen genau 08:00 bis 19:00.
        assert _counted_minutes(db, DAY) == 660
        _assert_stamps_match_local_times(db)


def test_ueberschreibendes_teilen_zieht_den_stempel_mit(main):
    from app import crud, models, schemas

    with _db() as db:
        long_entry = _stamped_entry(db, start=time(8, 0), end=time(18, 0))
        moved = _stamped_entry(db, start=time(20, 0), end=time(21, 0))
        crud.update_time_entry(db, moved.id, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=DAY,
            start_time=time(12, 0), end_time=time(13, 0), break_minutes=0,
            status=models.TimeEntryStatus.APPROVED, is_open=False,
        ), overwrite=True, reason="Korrektur")
        db.refresh(long_entry)
        assert (long_entry.start_time, long_entry.end_time) == (time(8, 0), time(12, 0))
        assert long_entry.worked_minutes == 240  # bis 0.20.8: 600
        assert _counted_minutes(db, DAY) == 600  # 08:00–18:00, unverändert lang
        _assert_stamps_match_local_times(db)


# ---------------------------------------------------------------------------
# Laufende Buchung
# ---------------------------------------------------------------------------


def test_nachtrag_in_die_laufende_buchung_setzt_ihren_beginn_neu(main):
    """Die laufende Buchung läuft nach dem Nachtrag weiter – ab dessen Ende.

    Geprüft wird der Stempel und nicht die verstrichene Zeit: Eine laufende
    Buchung endet „jetzt", das ließe sich nicht auf die Minute festnageln.
    """
    from app import crud, models, schemas

    with _db() as db:
        now = datetime.now().replace(microsecond=0)
        started = now - timedelta(hours=6)
        running = crud.start_running_entry(db, user_id=_admin_id(), started_at=started)
        original_stamp = running.started_at_utc
        gap_start = (started + timedelta(hours=2)).replace(second=0)
        gap_end = gap_start + timedelta(hours=1)
        crud.create_manual_time_entry(db, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=gap_start.date(),
            start_time=gap_start.time(), end_time=gap_end.time(), break_minutes=0,
            status=models.TimeEntryStatus.PENDING, is_manual=True, is_open=False,
        ))
        db.refresh(running)
        assert running.is_open is True
        assert running.start_time == gap_end.time()
        # Bis 0.20.8 blieb hier der ursprüngliche Stempel stehen; die laufende
        # Buchung zählte die nachgetragene Zeit ein zweites Mal mit.
        assert running.started_at_utc != original_stamp
        assert running.started_at_utc == _utc(gap_end.date(), gap_end.time())
        # Eine laufende Buchung hat kein Ende.
        assert running.ended_at_utc is None
        _assert_stamps_match_local_times(db)


def test_laufende_buchung_behaelt_beim_beenden_den_genauen_stempel(main):
    """Ein ausdrücklich gesetzter Stempel behält Vorrang.

    Beim Aus­stempeln kennt ``crud`` den Zeitpunkt sekundengenau – diese
    Angabe darf die Angleichung nicht durch eine gröbere ersetzen.
    """
    from app import crud

    with _db() as db:
        now = datetime.now().replace(microsecond=0)
        started = (now - timedelta(hours=3)).replace(second=17)
        finished = now.replace(second=41)
        running = crud.start_running_entry(db, user_id=_admin_id(), started_at=started)
        entry = crud.finish_running_entry(db, running, finished)
        assert entry.started_at_utc.second == 17
        assert entry.ended_at_utc.second == 41
        assert entry.ended_at_utc == _utc(finished.date(), finished.time())


# ---------------------------------------------------------------------------
# Die strukturelle Absicherung
# ---------------------------------------------------------------------------


def test_jede_ortszeitaenderung_zieht_den_stempel_nach(main):
    """Der eigentliche Schutz: Es genügt, die Ortszeit zu ändern.

    Kein Aufrufer muss an die UTC-Stempel denken – das Mapper-Ereignis
    erledigt es. Damit kann der Fehler auch in künftigem Code nicht wieder
    entstehen.
    """
    from app import models

    with _db() as db:
        entry = _stamped_entry(db)
        entry.end_time = time(12, 0)
        db.commit()
        db.refresh(entry)
        assert entry.ended_at_utc == _utc(DAY, time(12, 0))
        assert entry.worked_minutes == 240

        entry.work_date = DAY + timedelta(days=1)
        db.commit()
        db.refresh(entry)
        assert entry.started_at_utc == _utc(DAY + timedelta(days=1), ORIGINAL_START)

        # Wird eine Buchung wieder geöffnet, verschwindet ihr Ende.
        entry.is_open = True
        db.commit()
        db.refresh(entry)
        assert entry.ended_at_utc is None


def test_neue_buchung_ohne_stempel_wird_gestempelt(main):
    """Auch der Weg über das Formular (ohne eigene Stempel) hinterlässt eine
    vollständige Buchung – sonst wären die Stempel bei manchen Zeilen da und
    bei anderen nicht."""
    from app import crud, models, schemas

    with _db() as db:
        entry = crud.create_time_entry(db, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=DAY,
            start_time=time(9, 0), end_time=time(17, 0), break_minutes=0,
            status=models.TimeEntryStatus.PENDING, is_manual=True, is_open=False,
        ))
        assert entry.tz_name == "Europe/Berlin"
        assert entry.started_at_utc == _utc(DAY, time(9, 0))
        assert entry.ended_at_utc == _utc(DAY, time(17, 0))


def test_nachtarbeit_ueber_mitternacht_bleibt_richtig(main):
    """Endet eine Buchung vor ihrem Beginn, liegt das Ende am Folgetag – die
    Angleichung darf daraus keine negative Dauer machen."""
    from app import crud, models, schemas

    with _db() as db:
        entry = crud.create_time_entry(db, schemas.TimeEntryCreate(
            user_id=_admin_id(), work_date=DAY,
            start_time=time(22, 0), end_time=time(6, 0), break_minutes=0,
            status=models.TimeEntryStatus.APPROVED, is_open=False,
        ))
        assert entry.ended_at_utc == _utc(DAY + timedelta(days=1), time(6, 0))
        assert entry.worked_minutes == 480


def test_mapper_ereignisse_sind_registriert(main):
    """Wer die Angleichung entfernt, bringt den Fehler zurück."""
    from sqlalchemy import event

    from app import models

    for hook in ("before_insert", "before_update"):
        assert event.contains(models.TimeEntry, hook, models._sync_time_entry_stamps), (
            f"models.TimeEntry hat kein {hook}-Ereignis zur Stempelangleichung"
        )


# ---------------------------------------------------------------------------
# Migration 24 – bereits gespeicherte Buchungen
# ---------------------------------------------------------------------------


def _break_stamps(entry_id: int, *, ended: datetime, tz_name: str | None) -> None:
    """Den Zustand vor 0.20.8 herstellen: Ortszeit gekürzt, Stempel alt.

    Bewusst über rohes SQL – das Mapper-Ereignis würde die Buchung sonst sofort
    wieder in Ordnung bringen.
    """
    from sqlalchemy import text

    from app import database

    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE time_entries SET ended_at_utc = :ended, tz_name = :tz "
                 "WHERE id = :id"),
            {"ended": ended, "tz": tz_name, "id": entry_id},
        )


def test_migration_gleicht_bestandsbuchungen_an(main):
    from app import database, db_migrations, models

    with _db() as db:
        entry = _stamped_entry(db, start=ORIGINAL_START, end=MANUAL_START)
        entry_id = entry.id
    _break_stamps(entry_id, ended=_utc(DAY, ORIGINAL_END), tz_name="Europe/Berlin")

    with _db() as db:
        broken = db.get(models.TimeEntry, entry_id)
        assert broken.worked_minutes == GROSS_MINUTES  # falsch: zeigt 08:00–12:38

    db_migrations._repair_time_entry_utc_stamps(database.engine)

    with _db() as db:
        repaired = db.get(models.TimeEntry, entry_id)
        assert repaired.ended_at_utc == _utc(DAY, MANUAL_START)
        assert repaired.worked_minutes == 278
        _assert_stamps_match_local_times(db)


def test_migration_ist_wiederholbar(main):
    from app import database, db_migrations, models

    with _db() as db:
        entry_id = _stamped_entry(db).id
    db_migrations._repair_time_entry_utc_stamps(database.engine)
    db_migrations._repair_time_entry_utc_stamps(database.engine)
    with _db() as db:
        entry = db.get(models.TimeEntry, entry_id)
        assert entry.started_at_utc == _utc(DAY, ORIGINAL_START)
        assert entry.ended_at_utc == _utc(DAY, ORIGINAL_END)


def test_migration_laesst_buchungen_ohne_zeitzone_unberuehrt(main):
    """Ohne ``tz_name`` ist die damals gültige Zone nicht rekonstruierbar.

    Dann wird nichts angefasst – eine geratene Umrechnung wäre in einem
    Arbeitszeitnachweis schlechter als eine unveränderte Bestandszeile.
    """
    from app import database, db_migrations, models

    with _db() as db:
        entry_id = _stamped_entry(db).id
    stale = _utc(DAY, time(23, 0))
    _break_stamps(entry_id, ended=stale, tz_name=None)

    db_migrations._repair_time_entry_utc_stamps(database.engine)

    with _db() as db:
        entry = db.get(models.TimeEntry, entry_id)
        assert entry.ended_at_utc == stale


def test_migration_ist_versioniert(main):
    from app import db_migrations

    assert (24, db_migrations._repair_time_entry_utc_stamps) in db_migrations.MIGRATIONS
    # Bestehende Nummern bleiben, wo sie sind.
    assert [number for number, _ in db_migrations.MIGRATIONS] == list(range(1, 25))


# ---------------------------------------------------------------------------
# Über die Oberfläche
# ---------------------------------------------------------------------------


def test_nachtrag_ueber_das_formular_zaehlt_einmal(client):
    """Derselbe Vorgang, wie ihn ein Anwender auslöst."""
    from app import models

    _login(client)
    with _db() as db:
        _stamped_entry(db)

    response = client.post("/time", data={
        "work_date": DAY.isoformat(),
        "start_time": MANUAL_START.strftime("%H:%M"),
        "end_time": MANUAL_END.strftime("%H:%M"),
        "break_minutes": "0",
        "notes": "Nachtrag",
        "next_url": "/dashboard",
        "csrf_token": _csrf(client, "/dashboard"),
    }, follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "error=" not in response.headers.get("location", "")

    with _db() as db:
        assert _counted_minutes(db, DAY) == GROSS_MINUTES
        _assert_stamps_match_local_times(db)


def test_buchungsliste_und_summe_stimmen_ueberein(client):
    """Was in der Liste steht, muss die Summe hergeben – sonst rechnet die
    Anwendung mit anderen Zeiten, als sie zeigt."""
    from app import models

    _login(client)
    with _db() as db:
        _stamped_entry(db)
    client.post("/time", data={
        "work_date": DAY.isoformat(),
        "start_time": MANUAL_START.strftime("%H:%M"),
        "end_time": MANUAL_END.strftime("%H:%M"),
        "break_minutes": "0",
        "notes": "",
        "next_url": "/dashboard",
        "csrf_token": _csrf(client, "/dashboard"),
    }, follow_redirects=False)

    page = client.get(f"/records?month={DAY.strftime('%Y-%m')}").text
    assert "08:00" in page and "15:42" in page
    # 4:38 + 1:00 + 2:04 = 7:42 – und keine Zeile mit 7:42 als Einzelwert mehr.
    assert "4:38" in page and "2:04" in page


# ---------------------------------------------------------------------------
# Versionspflege
# ---------------------------------------------------------------------------


def test_version_ist_gepflegt(main):
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.20.9"
    assert main.APP_VERSION == "0.20.9"


def test_changelog_und_release_notes(main):
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.20.9]" in changelog
    notes = ROOT / "docs" / "RELEASE_NOTES_0.20.9.md"
    assert notes.exists()
    text_content = notes.read_text(encoding="utf-8")
    assert "0.20.9" in text_content
    # Keine Zusicherung, die die Anwendung nicht halten kann: Die Release Notes
    # sagen ausdrücklich, dass sie weder vollständige Rechtskonformität noch
    # eine Zertifizierung behaupten.
    lowered = text_content.lower()
    assert "weder eine aussage über die" in lowered
    assert "vollständige rechtskonformität" in lowered
    assert "noch eine zertifizierung" in lowered


def test_readme_nennt_die_version(main):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "0.20.9" in readme

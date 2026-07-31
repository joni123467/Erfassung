"""Regelprüfung nach ArbZG und ArbSchG – kennzeichnen statt verhindern.

Der Leitgedanke dieses Moduls steht in einem Satz:

    **Die tatsächlich geleistete Arbeitszeit wird immer gespeichert.**

Eine Überschreitung der Höchstarbeitszeit, eine zu kurze Ruhezeit oder eine
fehlende Pause sind Tatsachen. Sie zu verschweigen oder die Buchung abzulehnen
würde den Nachweis verfälschen – und genau den verlangen §16 Abs. 2 ArbZG,
§17 MiLoG und die Rechtsprechung zur Arbeitszeiterfassung. Deshalb wird hier
nichts blockiert, sondern gekennzeichnet, damit es auffällt und bearbeitet
werden kann.

Geprüft wird:

* **§3 ArbZG** – mehr als 8 Stunden werktäglich (zulässig bei Ausgleich, daher
  Hinweis) und mehr als 10 Stunden (absolute Grenze, daher kritisch).
* **§4 ArbZG** – fehlende Ruhepause. Grenzen und Mindestabschnitt stehen in
  :mod:`app.models`.
* **§5 ArbZG** – weniger als 11 Stunden Ruhezeit zwischen zwei Arbeitstagen.
* **§9 ArbZG** – Arbeit an Sonn- und Feiertagen.

Keine dieser Kennzeichnungen ist eine rechtliche Bewertung des Einzelfalls:
Ausnahmen (Tarifverträge, §7 ArbZG, §10 ArbZG, Bereitschaft) kann eine Software
nicht kennen. Sie zeigt, was auffällt; entscheiden müssen Menschen.

**Kunden sind keine Arbeitgeber.** ``Company`` und ``CompanyLocation`` sind in
dieser Anwendung Kunde und Auftragsort – sie dienen der Auftragszuordnung. Für
die arbeitsrechtliche Bewertung sind sie ohne Bedeutung:

* Die Feiertagsregion kommt ausschließlich aus der zentralen Konfiguration
  (Tabelle ``holidays``), nie aus dem Kundenstandort. Wer für einen Kunden in
  Bayern arbeitet, hat deswegen weder Fronleichnam frei noch verliert er einen
  Feiertag seiner eigenen Region.
* Höchstarbeitszeit, Ruhepause und Ruhezeit werden über **alle** Kunden und
  Aufträge hinweg gemeinsam bewertet. Ein Auftrags-, Kunden- oder
  Standortwechsel ist keine Pause und beginnt keinen neuen Arbeitstag.

Dieses Modul greift deshalb an keiner Stelle auf ``company`` oder ``location``
zu. Wer das ändert, hebelt die Trennung aus.
"""

from __future__ import annotations

import logging
import hashlib
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from . import models, worktime

LOGGER = logging.getLogger("erfassung.application")

#: Schweregrade – steuern ausschließlich die Darstellung.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

LABELS: dict[str, str] = {
    models.ComplianceCode.OVER_8H: "Mehr als 8 Stunden",
    models.ComplianceCode.OVER_10H: "Mehr als 10 Stunden",
    models.ComplianceCode.REST_UNDER_11H: "Ruhezeit unter 11 Stunden",
    models.ComplianceCode.BREAK_MISSING: "Ruhepause fehlt",
    models.ComplianceCode.SUNDAY_WORK: "Sonntagsarbeit",
    models.ComplianceCode.HOLIDAY_WORK: "Feiertagsarbeit",
    models.ComplianceCode.AVERAGE_OVER_8H: "Ausgleich fehlt (Ø über 8 Stunden)",
    models.ComplianceCode.COMPENSATION_DUE: "Ausgleichszeitraum läuft ab",
}

REFERENCES: dict[str, str] = {
    models.ComplianceCode.OVER_8H: "§3 ArbZG",
    models.ComplianceCode.OVER_10H: "§3 ArbZG",
    models.ComplianceCode.REST_UNDER_11H: "§5 ArbZG",
    models.ComplianceCode.BREAK_MISSING: "§4 ArbZG",
    models.ComplianceCode.SUNDAY_WORK: "§9 ArbZG",
    models.ComplianceCode.HOLIDAY_WORK: "§9 ArbZG",
    models.ComplianceCode.AVERAGE_OVER_8H: "§3 Satz 2 ArbZG",
    models.ComplianceCode.COMPENSATION_DUE: "§3 Satz 2 ArbZG",
}


def _naive_utc(moment: object) -> Optional[datetime]:
    """Zonenbehafteten UTC-Zeitpunkt als naiven Wert für die Spalte."""
    if not isinstance(moment, datetime):
        return None
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _format_minutes(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d} Std"


# Die Zeitrechnung liegt zentral in :mod:`app.worktime` – dieselbe Funktion,
# die auch ``TimeEntry.gross_minutes`` benutzt. Zwei Rechnungen für dieselbe
# Frage haben bis 0.15.0 über eine Zeitumstellung hinweg zwei verschiedene
# Antworten geliefert.
_timezone = worktime.zone
_from_local = worktime.from_local
_from_utc_column = worktime.from_utc_column
_entry_bounds = worktime.entry_bounds
_local_date = worktime.local_date


def _break_cuts(entry: models.TimeEntry) -> tuple[list[tuple[datetime, datetime]], int]:
    """Gebuchte Pausen einer Buchung als UTC-Intervalle.

    Rückgabe: die zeitlich verorteten Pausen und die Minuten, die sich
    **nicht** verorten lassen. Letztere stammen aus Bestandsbuchungen, die nur
    eine Pausensumme kennen – sie zählen für die Mindestpause mit, lassen sich
    aber nicht in die Schicht einsortieren.
    """
    tz = _timezone(getattr(entry, "tz_name", None))
    cuts: list[tuple[datetime, datetime]] = []
    placed = 0
    for interval in getattr(entry, "_break_intervals", []) or []:
        started = _from_utc_column(getattr(interval, "started_at_utc", None))
        ended = _from_utc_column(getattr(interval, "ended_at_utc", None))
        if started is None or ended is None or ended <= started:
            continue
        cuts.append((started, ended))
        placed += int((ended - started).total_seconds() // 60)
    unplaced = max(int(entry.total_break_minutes or 0) - placed, 0)
    return sorted(cuts), unplaced


def _subtract(
    span: tuple[datetime, datetime], cuts: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """Arbeitsintervalle einer Buchung: Zeitraum abzüglich der Pausen."""
    result: list[tuple[datetime, datetime]] = []
    cursor, end = span
    for cut_start, cut_end in cuts:
        if cut_end <= cursor or cut_start >= end:
            continue
        if cut_start > cursor:
            result.append((cursor, min(cut_start, end)))
        cursor = max(cursor, cut_end)
        if cursor >= end:
            break
    if cursor < end:
        result.append((cursor, end))
    return [(a, b) for a, b in result if b > a]


class Shift:
    """Eine zusammenhängende Arbeitsschicht über alle Kunden und Aufträge.

    Der Kern der Pausenprüfung: § 4 ArbZG kennt keine Aufträge. Wer von 8 bis
    12 für Kunde A und von 12 bis 17 für Kunde B arbeitet, hat neun Stunden am
    Stück gearbeitet und keine Pause gemacht – auch wenn das in zwei Buchungen
    steht. Ein Wechsel von Kunde, Auftrag oder Einsatzort ist **keine** Pause.
    """

    __slots__ = ("intervals", "entries", "unplaced_break_minutes")

    def __init__(self) -> None:
        self.intervals: list[tuple[datetime, datetime]] = []
        self.entries: list[models.TimeEntry] = []
        self.unplaced_break_minutes = 0

    @property
    def start(self) -> datetime:
        return self.intervals[0][0]

    @property
    def end(self) -> datetime:
        return self.intervals[-1][1]

    @property
    def work_minutes(self) -> int:
        """Tatsächliche Arbeitszeit der Schicht in Minuten.

        Nicht verortete Pausen aus Bestandsbuchungen werden abgezogen: Sie
        liegen irgendwo in der Schicht, nur wo genau, sagt die Altbuchung
        nicht.
        """
        gross = sum(
            int((end - start).total_seconds() // 60) for start, end in self.intervals
        )
        return max(gross - self.unplaced_break_minutes, 0)

    @property
    def break_minutes(self) -> int:
        """Anrechenbare Ruhepausen (§ 4 Abs. 1 Satz 2 ArbZG).

        Angerechnet werden nur Unterbrechungen von mindestens
        ``MIN_BREAK_SEGMENT_MINUTES``. Kürzere Lücken – etwa der Wechsel
        zwischen zwei Aufträgen – sind keine Ruhepause und wurden beim Bau der
        Schicht bereits zur Arbeitszeit geschlagen.
        """
        total = self.unplaced_break_minutes
        for index in range(1, len(self.intervals)):
            gap = int(
                (self.intervals[index][0] - self.intervals[index - 1][1]).total_seconds()
                // 60
            )
            if gap >= models.MIN_BREAK_SEGMENT_MINUTES:
                total += gap
        return total

    @property
    def required_break_minutes(self) -> int:
        """Mindestpause für die Arbeitszeit dieser Schicht."""
        duration = self.work_minutes
        if duration > 9 * 60:
            return 45
        if duration > 6 * 60:
            return 30
        return 0

    @property
    def break_shortfall_minutes(self) -> int:
        return max(self.required_break_minutes - self.break_minutes, 0)


def shift_break_minutes() -> int:
    """Ab welcher Unterbrechung gilt eine Schicht als beendet?

    Der Wert kommt aus der persistenten Systemkonfiguration im config-Volume
    (Administration → System → Einstellungen). Er ist eine **betriebliche
    Festlegung**, keine Zahl aus dem Gesetz – siehe
    :data:`app.app_config.SystemSettings.shift_break_minutes`.

    Bestandsinstallationen ohne Eintrag bekommen die bisherigen 360 Minuten,
    das Verhalten ändert sich also nicht von selbst.
    """
    try:
        from . import app_config

        return int(app_config.load_system_settings().shift_break_minutes)
    except Exception:  # pragma: no cover - Konfigurationsfehler darf nichts kippen
        return models.SHIFT_BREAK_MINUTES


def build_shifts(entries: Iterable[models.TimeEntry]) -> list[Shift]:
    """Buchungen zu chronologischen Schichten zusammenfassen.

    Vorgehen:

    1. Jede Buchung wird um ihre gebuchten Pausen bereinigt.
    2. Alle Arbeitsintervalle werden über **alle Kunden, Aufträge und
       Einsatzorte hinweg** chronologisch sortiert.
    3. Überlappende und unmittelbar aufeinanderfolgende Intervalle werden
       zusammengeführt; Lücken unter ``MIN_BREAK_SEGMENT_MINUTES`` gelten als
       Arbeitszeit, nicht als Pause.
    4. Eine Lücke von mindestens ``SHIFT_BREAK_MINUTES`` trennt zwei Schichten
       – alles darunter bleibt dieselbe Schicht mit einer Pause. Siehe dort:
       Der Wert ist eine fachliche Festlegung, keine Zahl aus dem Gesetz.

    Damit wird Nachtarbeit über Mitternacht automatisch richtig behandelt: Die
    Schicht endet dort, wo tatsächlich eine Ruhezeit liegt, nicht am
    Kalendertagwechsel.
    """
    shift_gap = shift_break_minutes()
    pieces: list[tuple[datetime, datetime, models.TimeEntry]] = []
    unplaced: dict[int, int] = {}
    for entry in entries:
        cuts, leftover = _break_cuts(entry)
        for start, end in _subtract(_entry_bounds(entry), cuts):
            pieces.append((start, end, entry))
        if leftover:
            unplaced[id(entry)] = unplaced.get(id(entry), 0) + leftover
    if not pieces:
        return []
    pieces.sort(key=lambda item: (item[0], item[1]))

    shifts: list[Shift] = []
    current = Shift()
    for start, end, entry in pieces:
        if not current.intervals:
            current.intervals.append((start, end))
            current.entries.append(entry)
            continue
        last_start, last_end = current.intervals[-1]
        gap = int((start - last_end).total_seconds() // 60)
        if gap >= shift_gap:
            shifts.append(current)
            current = Shift()
            current.intervals.append((start, end))
            current.entries.append(entry)
            continue
        if entry not in current.entries:
            current.entries.append(entry)
        if gap < models.MIN_BREAK_SEGMENT_MINUTES:
            # Überlappend oder direkt anschließend: zusammenführen. Der Wechsel
            # von Auftrag, Kunde oder Standort ist keine Ruhepause.
            current.intervals[-1] = (last_start, max(last_end, end))
        else:
            current.intervals.append((start, end))
    shifts.append(current)

    for shift in shifts:
        shift.unplaced_break_minutes = sum(
            unplaced.get(id(entry), 0) for entry in shift.entries
        )
    return shifts


def _countable(entries: Iterable[models.TimeEntry]) -> list[models.TimeEntry]:
    """Buchungen, die für die Bewertung zählen.

    Stornierte bleiben außen vor: Sie sind rückgängig gemacht und würden sonst
    einen Verstoß vortäuschen, den es nicht gab.
    """
    return [
        entry for entry in entries
        if entry.status != models.TimeEntryStatus.CANCELLED
    ]


def _entries_around(
    db: Session, user_id: int, work_date: date, *, days: int = 1
) -> list[models.TimeEntry]:
    """Buchungen des Tages samt Nachbartagen – für Schichten über Mitternacht."""
    return _countable(
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.work_date >= work_date - timedelta(days=days))
        .filter(models.TimeEntry.work_date <= work_date + timedelta(days=days))
        .order_by(models.TimeEntry.work_date, models.TimeEntry.start_time)
        .all()
    )


def evaluate_day(
    db: Session,
    user_id: int,
    work_date: date,
    *,
    holiday_dates: Optional[set[date]] = None,
) -> list[dict[str, object]]:
    """Alle Kennzeichnungen eines Arbeitstags ermitteln.

    Gibt einfache Wörterbücher zurück statt Datenbankobjekte – so lässt sich
    die Bewertung ohne Schreibzugriff prüfen und testen.
    """
    entries = _countable(
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.work_date == work_date)
        .order_by(models.TimeEntry.start_time)
        .all()
    )
    if not entries:
        return []

    findings: list[dict[str, object]] = []
    total = sum(entry.worked_minutes for entry in entries)

    if total > models.ABSOLUTE_MAX_DAILY_MINUTES:
        findings.append({
            "code": models.ComplianceCode.OVER_10H,
            "severity": SEVERITY_CRITICAL,
            "entry_id": entries[-1].id,
            "detail": (
                f"{_format_minutes(total)} gearbeitet – über der Höchstgrenze von "
                f"{_format_minutes(models.ABSOLUTE_MAX_DAILY_MINUTES)}."
            ),
        })
    elif total > models.MAX_DAILY_MINUTES:
        findings.append({
            "code": models.ComplianceCode.OVER_8H,
            "severity": SEVERITY_WARNING,
            "entry_id": entries[-1].id,
            "detail": (
                f"{_format_minutes(total)} gearbeitet. Über 8 Stunden ist nur zulässig, "
                "wenn innerhalb von 6 Monaten auf 8 Stunden ausgeglichen wird."
            ),
        })

    # Pausen werden über die **ganze Schicht** bewertet, nicht je Buchung.
    # Wer von 8 bis 12 für Kunde A und von 12 bis 17 für Kunde B arbeitet, hat
    # neun Stunden am Stück gearbeitet – der Kundenwechsel ist keine Pause.
    # Herangezogen werden auch die Nachbartage, damit eine Nachtschicht nicht
    # am Kalendertagwechsel zerfällt.
    for shift in build_shifts(_entries_around(db, user_id, work_date)):
        if _local_date(shift.start) != work_date:
            # Jede Schicht wird an ihrem Beginntag bewertet – sonst stünde
            # dieselbe Feststellung an zwei Tagen.
            continue
        shortfall = shift.break_shortfall_minutes
        if shortfall <= 0:
            continue
        findings.append({
            "code": models.ComplianceCode.BREAK_MISSING,
            "severity": SEVERITY_WARNING,
            "entry_id": shift.entries[-1].id,
            # Mehrere Schichten an einem Tag ergeben mehrere Feststellungen.
            "shift_start": shift.start,
            "detail": (
                f"{shortfall} Minuten Ruhepause fehlen: "
                f"{_format_minutes(shift.work_minutes)} Arbeitszeit in einer Schicht "
                f"über {len(shift.entries)} Buchung(en), "
                f"{shift.break_minutes} Minuten anrechenbare Pause, "
                f"erforderlich {shift.required_break_minutes} Minuten."
            ),
        })

    if work_date.weekday() == 6:
        findings.append({
            "code": models.ComplianceCode.SUNDAY_WORK,
            "severity": SEVERITY_INFO,
            "entry_id": entries[0].id,
            "detail": f"{_format_minutes(total)} an einem Sonntag.",
        })
    if holiday_dates is None:
        holiday_dates = _holiday_dates(db, work_date.year)
    if work_date in holiday_dates:
        findings.append({
            "code": models.ComplianceCode.HOLIDAY_WORK,
            "severity": SEVERITY_INFO,
            "entry_id": entries[0].id,
            "detail": f"{_format_minutes(total)} an einem Feiertag.",
        })

    rest = _rest_finding(db, user_id, work_date, entries)
    if rest:
        findings.append(rest)
    findings.extend(_compensation_findings(db, user_id, work_date, entries))
    return findings


class CompensationReport:
    """Auswertung des Ausgleichszeitraums nach § 3 Satz 2 ArbZG.

    Das Gesetz erlaubt bis zu zehn Stunden werktäglich, „wenn innerhalb von
    sechs Kalendermonaten oder innerhalb von 24 Wochen im Durchschnitt acht
    Stunden werktäglich nicht überschritten werden". Diese Auswertung macht
    genau das nachvollziehbar: Sie sagt, **welcher Zeitraum** betrachtet wurde,
    **welche Tage** eingeflossen sind und **wie viel Ausgleich** noch fehlt.
    """

    __slots__ = ("start", "end", "workdays", "total_minutes", "allowance_minutes")

    def __init__(
        self, start: date, end: date, workdays: int, total_minutes: int
    ) -> None:
        self.start = start
        self.end = end
        self.workdays = workdays
        self.total_minutes = total_minutes
        #: Zulässige Gesamtarbeitszeit: acht Stunden je **Werktag** mit Arbeit.
        self.allowance_minutes = workdays * models.MAX_DAILY_MINUTES

    @property
    def average_minutes(self) -> int:
        """Werktäglicher Durchschnitt im Zeitraum."""
        if self.workdays <= 0:
            return 0
        return int(round(self.total_minutes / self.workdays))

    @property
    def excess_minutes(self) -> int:
        """Noch auszugleichender Überhang; 0, wenn der Schnitt passt."""
        return max(self.total_minutes - self.allowance_minutes, 0)

    @property
    def is_compliant(self) -> bool:
        return self.excess_minutes <= 0


def compensation_report(
    db: Session, user_id: int, reference: date
) -> CompensationReport:
    """Rollierender Ausgleichszeitraum, der am ``reference``-Tag endet.

    Gezählt werden nur **Werktage mit Arbeit** (Montag bis Samstag im Sinne des
    ArbZG, das den Samstag als Werktag kennt). Tage ohne Buchung senken den
    Durchschnitt nicht künstlich – sonst ließe sich jede Überschreitung durch
    eine lange Abwesenheit wegrechnen.
    """
    start = reference - timedelta(days=models.COMPENSATION_DAYS - 1)
    entries = _countable(
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.work_date >= start)
        .filter(models.TimeEntry.work_date <= reference)
        .all()
    )
    per_day: dict[date, int] = {}
    for entry in entries:
        if entry.work_date.weekday() == 6:
            # Sonntag ist kein Werktag im Sinne des § 3 ArbZG. Die Arbeit wird
            # gespeichert und als Sonntagsarbeit gekennzeichnet, geht aber
            # nicht in den werktäglichen Durchschnitt ein.
            continue
        per_day[entry.work_date] = per_day.get(entry.work_date, 0) + entry.worked_minutes
    worked_days = {day: minutes for day, minutes in per_day.items() if minutes > 0}
    return CompensationReport(
        start=start,
        end=reference,
        workdays=len(worked_days),
        total_minutes=sum(worked_days.values()),
    )


def _compensation_findings(
    db: Session, user_id: int, work_date: date, entries: list[models.TimeEntry]
) -> list[dict[str, object]]:
    """Ausgleichsprüfung – nur an Tagen, an denen sie etwas aussagt.

    Ausgewertet wird an Tagen mit mehr als acht Stunden: Erst dann stellt sich
    die Frage nach dem Ausgleich überhaupt. Blockiert wird nichts.
    """
    if not entries:
        return []
    day_minutes = sum(entry.worked_minutes for entry in entries)
    if day_minutes <= models.MAX_DAILY_MINUTES:
        return []

    report = compensation_report(db, user_id, work_date)
    if report.workdays <= 0:
        return []

    span = (
        f"{report.start.strftime('%d.%m.%Y')}–{report.end.strftime('%d.%m.%Y')}, "
        f"{report.workdays} Arbeitstage, Ø {_format_minutes(report.average_minutes)}"
    )
    if not report.is_compliant:
        return [{
            "code": models.ComplianceCode.AVERAGE_OVER_8H,
            "severity": SEVERITY_WARNING,
            "entry_id": entries[-1].id,
            "detail": (
                f"Der werktägliche Durchschnitt liegt über 8 Stunden: {span}. "
                f"Auszugleichen sind {_format_minutes(report.excess_minutes)} "
                f"bis zum Ende des Ausgleichszeitraums."
            ),
        }]

    # Der Schnitt stimmt – aber läuft der Zeitraum bald ab und steht noch ein
    # Überhang aus den letzten Wochen im Raum? Dann früh warnen, solange
    # Ausgleich noch möglich ist.
    remaining = models.COMPENSATION_DAYS - (
        (report.end - report.start).days + 1
    )
    headroom = report.allowance_minutes - report.total_minutes
    if headroom < models.MAX_DAILY_MINUTES and remaining <= models.COMPENSATION_WARNING_DAYS:
        return [{
            "code": models.ComplianceCode.COMPENSATION_DUE,
            "severity": SEVERITY_INFO,
            "entry_id": entries[-1].id,
            "detail": (
                f"Der Ausgleichszeitraum ist fast ausgeschöpft: {span}. "
                f"Es bleiben {_format_minutes(max(headroom, 0))} Spielraum."
            ),
        }]
    return []


def _rest_finding(
    db: Session,
    user_id: int,
    work_date: date,
    entries: list[models.TimeEntry],
) -> Optional[dict[str, object]]:
    """Ruhezeit zur vorangegangenen Schicht prüfen (§ 5 ArbZG).

    Verglichen werden **Schichten**, nicht Kalendertage: Eine Nachtschicht
    endet am Folgetag, und ein Kundenwechsel innerhalb einer Schicht ist keine
    Ruhezeit. Gerechnet wird durchgehend in UTC, damit eine Zeitumstellung das
    Ergebnis nicht um eine Stunde verschiebt.
    """
    if not entries:
        return None
    # Drei Tage zurück und einen vor: genug, damit eine lange Nachtschicht und
    # die davorliegende Ruhezeit vollständig im Fenster liegen.
    shifts = build_shifts(_entries_around(db, user_id, work_date, days=3))
    today_shifts = [
        shift for shift in shifts if _local_date(shift.start) == work_date
    ]
    if not today_shifts:
        return None
    current = today_shifts[0]

    earlier = [shift for shift in shifts if shift.end <= current.start]
    if not earlier:
        return None
    previous = max(earlier, key=lambda shift: shift.end)
    rest_minutes = int((current.start - previous.end).total_seconds() // 60)
    if rest_minutes >= models.MIN_REST_MINUTES:
        return None
    local_end = previous.end.astimezone(_timezone(None))
    return {
        "code": models.ComplianceCode.REST_UNDER_11H,
        "severity": SEVERITY_CRITICAL,
        "entry_id": current.entries[0].id,
        "shift_start": current.start,
        "detail": (
            f"Nur {_format_minutes(max(rest_minutes, 0))} Ruhezeit seit "
            f"{local_end.strftime('%d.%m.%Y %H:%M')} – vorgeschrieben sind 11 Stunden."
        ),
    }


def _holiday_dates(db: Session, year: int) -> set[date]:
    from . import crud

    try:
        region = crud.get_default_holiday_region(db)
        return {holiday.date for holiday in crud.get_holidays_for_year(db, year, region)}
    except Exception:  # pragma: no cover - die Prüfung darf nie eine Buchung kippen
        return set()


def finding_key(user_id: int, work_date: date, finding: dict[str, object]) -> str:
    """Stabiler Schlüssel einer Feststellung (ab 0.16.0).

    Bis 0.15.0 wurde eine Feststellung nur über ``code`` wiedergefunden. Das
    genügt nicht: An einem Tag kann es mehrere getrennte Schichten geben, und
    jede kann denselben Verstoß erzeugen. Zwei fehlende Ruhepausen an einem Tag
    sind **zwei** Feststellungen – sie müssen sich getrennt bestätigen,
    erledigen und erneut öffnen lassen.

    Der Schlüssel bindet deshalb Benutzer, Tag, Code **und** den Schichtbeginn
    zusammen. Feststellungen ohne Schichtbezug (Sonntags-, Feiertagsarbeit,
    Tageshöchstarbeitszeit) gelten je Tag und bekommen einen leeren Anker – für
    sie ändert sich nichts.
    """
    anchor = finding.get("shift_start")
    anchor_text = anchor.isoformat() if hasattr(anchor, "isoformat") else ""
    payload = "|".join((str(user_id), work_date.isoformat(), str(finding.get("code", "")), anchor_text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


def fingerprint(finding: dict[str, object]) -> str:
    """Prüfsumme des bewerteten Datenstands einer Feststellung.

    Sie bindet die Bestätigung an genau **den** Stand, für den sie abgegeben
    wurde. Ändert sich Arbeitszeit, Pause oder Schweregrad, ändert sich die
    Prüfsumme – und die Feststellung wird wieder geöffnet. Eine Bestätigung
    von gestern soll einen Verstoß von heute nicht zudecken.

    Bewusst über Code, Schweregrad und Detailtext: Der Detailtext enthält die
    bewerteten Minuten und ist damit der kompakteste verfügbare Abdruck des
    Datenstands.
    """
    payload = "|".join(
        (
            str(finding.get("code", "")),
            str(finding.get("severity", "")),
            str(finding.get("detail", "")),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


def refresh_day(db: Session, user_id: int, work_date: date) -> list[models.ComplianceFlag]:
    """Kennzeichnungen eines Tages neu bewerten und **fortschreiben**.

    Bis 0.14.2 wurden offene Kennzeichnungen bei jeder Neuberechnung physisch
    gelöscht. Damit war hinterher nicht mehr erkennbar, dass es sie je gab –
    das Gegenteil dessen, was eine revisionssichere Erfassung leisten soll.

    Jetzt wird jede Feststellung fortgeschrieben:

    * **neu** → ``detected``
    * **weiterhin vorhanden, anderer Datenstand** → ``changed``
    * **weiterhin vorhanden, gleicher Datenstand** → bleibt, wie sie ist
    * **nicht mehr vorhanden** → ``resolved`` (nicht gelöscht)
    * **bestätigt, aber Datenstand geändert** → ``reopened``

    Fehler werden protokolliert und geschluckt – eine Stempelung darf nie an
    der Regelprüfung scheitern.
    """
    try:
        findings = evaluate_day(db, user_id, work_date)
        existing = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.user_id == user_id)
            .filter(models.ComplianceFlag.work_date == work_date)
            .all()
        )
        # Zuordnung über den Schlüssel, nicht über den Code: Sonst fielen
        # zwei gleichartige Verstöße aus verschiedenen Schichten desselben
        # Tages zu einer Feststellung zusammen.
        by_key: dict[str, models.ComplianceFlag] = {}
        for flag in existing:
            key = flag.finding_key or flag.code
            # Bestandsdaten ohne Schlüssel: der erste Treffer je Code gewinnt,
            # damit eine vorhandene Bestätigung nicht verlorengeht.
            by_key.setdefault(key, flag)
        now = datetime.utcnow()
        seen: set[str] = set()
        touched: list[models.ComplianceFlag] = []

        for finding in findings:
            code = str(finding["code"])
            key = finding_key(user_id, work_date, finding)
            seen.add(key)
            digest = fingerprint(finding)
            flag = by_key.get(key) or by_key.get(code)
            if flag is not None and flag.finding_key and flag.finding_key != key:
                flag = None
            if flag is None:
                flag = models.ComplianceFlag(
                    user_id=user_id,
                    entry_id=finding.get("entry_id"),
                    work_date=work_date,
                    code=code,
                    severity=str(finding["severity"]),
                    detail=str(finding["detail"])[:500],
                    state=models.ComplianceState.DETECTED,
                    fingerprint=digest,
                    finding_key=key,
                    shift_start_utc=_naive_utc(finding.get("shift_start")),
                    revision_no=1,
                    updated_at=now,
                )
                db.add(flag)
                touched.append(flag)
                continue

            unchanged = flag.fingerprint == digest
            # Bestandsfeststellungen bekommen ihren Schlüssel nachgereicht.
            flag.finding_key = key
            flag.shift_start_utc = _naive_utc(finding.get("shift_start"))
            flag.entry_id = finding.get("entry_id")
            flag.severity = str(finding["severity"])
            flag.detail = str(finding["detail"])[:500]
            flag.resolved_at = None
            if unchanged and flag.state != models.ComplianceState.RESOLVED:
                # Nichts hat sich geändert – Bestätigung und Zustand bleiben.
                continue
            flag.fingerprint = digest
            flag.revision_no = int(flag.revision_no or 1) + 1
            flag.updated_at = now
            if flag.acknowledged_at is not None:
                # Bestätigt, aber der bewertete Stand ist ein anderer: Die
                # Bestätigung gilt nicht mehr, die Feststellung wird wieder
                # geöffnet. Die alte Einordnung bleibt als Text erhalten.
                flag.state = models.ComplianceState.REOPENED
                flag.reopened_at = now
                flag.acknowledged_at = None
                flag.acknowledged_by_id = None
            else:
                flag.state = models.ComplianceState.CHANGED
            touched.append(flag)

        # Nicht mehr vorhandene Feststellungen werden erledigt, nicht gelöscht.
        for key, flag in by_key.items():
            if key in seen or flag.state == models.ComplianceState.RESOLVED:
                continue
            flag.state = models.ComplianceState.RESOLVED
            flag.resolved_at = now
            flag.updated_at = now
            touched.append(flag)

        db.commit()
        for flag in touched:
            db.refresh(flag)
        return touched
    except Exception as exc:  # pragma: no cover - defensiv
        db.rollback()
        LOGGER.warning("Regelprüfung für %s am %s fehlgeschlagen: %s", user_id, work_date, exc)
        return []


def refresh_for_entry(db: Session, entry: models.TimeEntry) -> None:
    """Nach jeder Änderung an einer Buchung deren Tag neu bewerten.

    Zusätzlich der Folgetag: Eine Buchung verändert die Ruhezeit *davor* – die
    steht aber am nächsten Arbeitstag.
    """
    if entry is None or entry.user_id is None or entry.work_date is None:
        return
    refresh_day(db, entry.user_id, entry.work_date)
    for offset in (1, 2):
        following = entry.work_date + timedelta(days=offset)
        has_entries = (
            db.query(models.TimeEntry.id)
            .filter(models.TimeEntry.user_id == entry.user_id)
            .filter(models.TimeEntry.work_date == following)
            .first()
        )
        if has_entries:
            refresh_day(db, entry.user_id, following)


def open_flags(
    db: Session,
    *,
    user_ids: Optional[Iterable[int]] = None,
    since: Optional[date] = None,
    limit: int = 200,
) -> list[models.ComplianceFlag]:
    """Offene Kennzeichnungen – für die Eskalation in der Administration."""
    # Offen heißt: braucht noch Aufmerksamkeit. Erledigte und bestätigte
    # Feststellungen bleiben erhalten, tauchen hier aber nicht mehr auf.
    query = db.query(models.ComplianceFlag).filter(
        models.ComplianceFlag.state.in_(
            (
                models.ComplianceState.DETECTED,
                models.ComplianceState.CHANGED,
                models.ComplianceState.REOPENED,
            )
        )
    )
    if user_ids is not None:
        ids = list(user_ids)
        if not ids:
            return []
        query = query.filter(models.ComplianceFlag.user_id.in_(ids))
    if since is not None:
        query = query.filter(models.ComplianceFlag.work_date >= since)
    return (
        query.order_by(
            models.ComplianceFlag.work_date.desc(), models.ComplianceFlag.id.desc()
        )
        .limit(limit)
        .all()
    )


def get_flag(db: Session, flag_id: int) -> Optional[models.ComplianceFlag]:
    """Einzelne Feststellung – für die Rechteprüfung vor dem Einordnen."""
    return (
        db.query(models.ComplianceFlag)
        .filter(models.ComplianceFlag.id == flag_id)
        .first()
    )


#: Bearbeitungsstand der Ausnahmedokumentation zu Sonn-/Feiertagsarbeit.
HANDLING_STATES = {
    "open": "Offen",
    "documented": "Begründet",
    "rest_granted": "Ersatzruhetag gewährt",
    "not_required": "Kein Ersatzruhetag nötig",
}


def document_exception(
    db: Session,
    flag_id: int,
    *,
    user: Optional[models.User],
    reason: str = "",
    legal_basis: str = "",
    replacement_rest_date: Optional[date] = None,
    handling_state: str = "documented",
) -> Optional[models.ComplianceFlag]:
    """Ausnahme zu Sonn-/Feiertagsarbeit dokumentieren (§§ 9–11 ArbZG).

    Sonntagsarbeit ist nicht verboten, sondern erlaubnispflichtig: § 10 ArbZG
    zählt Ausnahmen auf, § 11 Abs. 3 verlangt einen **Ersatzruhetag**. Ob eine
    Ausnahme greift, kann die Anwendung nicht entscheiden – sie hält fest,
    worauf sich der Betrieb beruft und ob der Ersatzruhetag gewährt wurde.

    Die tatsächlich geleistete Arbeit bleibt davon unberührt gespeichert und
    gekennzeichnet; hier kommt nur die Einordnung dazu.
    """
    flag = get_flag(db, flag_id)
    if flag is None:
        return None
    if handling_state not in HANDLING_STATES:
        raise ValueError("UNKNOWN_HANDLING_STATE")
    flag.exception_reason = (reason or "").strip()[:500] or None
    flag.legal_basis = (legal_basis or "").strip()[:255] or None
    flag.replacement_rest_date = replacement_rest_date
    flag.handling_state = handling_state
    flag.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(flag)
    return flag


def acknowledge(
    db: Session, flag_id: int, *, user: models.User, note: str
) -> Optional[models.ComplianceFlag]:
    """Eine Kennzeichnung einordnen. Die Begründung ist Pflicht.

    Bestätigen heißt nicht „erledigt", sondern „gesehen und bewertet" – der
    Verstoß selbst bleibt für die Prüfung erhalten.

    Die Bestätigung wird an den **geprüften Datenstand** gebunden
    (``acknowledged_fingerprint``). Ändert sich die Buchung später, öffnet
    :func:`refresh_day` die Feststellung wieder: Eine Einordnung gilt für das,
    was zum Zeitpunkt der Einordnung dastand – nicht für alles, was später
    daraus wird.
    """
    flag = get_flag(db, flag_id)
    if flag is None:
        return None
    cleaned = (note or "").strip()
    if not cleaned:
        raise ValueError("REASON_REQUIRED")
    now = datetime.utcnow()
    flag.acknowledged_at = now
    flag.acknowledged_by_id = user.id if user else None
    flag.acknowledgement = cleaned[:500]
    flag.state = models.ComplianceState.ACKNOWLEDGED
    flag.acknowledged_fingerprint = flag.fingerprint
    flag.updated_at = now
    db.commit()
    db.refresh(flag)
    return flag


def label(code: str) -> str:
    return LABELS.get(code, code)


def reference(code: str) -> str:
    return REFERENCES.get(code, "")


__all__ = [
    "LABELS",
    "REFERENCES",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "acknowledge",
    "evaluate_day",
    "label",
    "open_flags",
    "reference",
    "refresh_day",
    "refresh_for_entry",
]

"""Ausgleich der werktäglichen Arbeitszeit nach § 3 ArbZG (ab 0.17.0).

§ 3 Satz 2 ArbZG im Wortlaut:

    „Sie kann auf bis zu zehn Stunden nur verlängert werden, wenn innerhalb von
    sechs Kalendermonaten oder innerhalb von 24 Wochen im Durchschnitt acht
    Stunden werktäglich nicht überschritten werden."

Daraus folgen drei Dinge, die diese Umsetzung auseinanderhält:

1. **Der Nenner sind Werktage, nicht Arbeitstage.** Bis 0.16.0 zählte nur, an
   welchen Tagen tatsächlich gebucht wurde. Damit konnte der Durchschnitt gar
   nicht sinken: Wer an vier Tagen je zehn Stunden arbeitete, hatte einen
   Schnitt von zehn Stunden – der freie Freitag und der freie Samstag, über die
   der Ausgleich gerade läuft, kamen nicht vor. Genau über nicht gearbeitete
   Werktage funktioniert der Ausgleich aber.
2. **Werktage sind Montag bis Samstag.** Der Sonntag ist kein Werktag; Arbeit
   an ihm wird gespeichert und nach § 9 gekennzeichnet, geht aber nicht in den
   werktäglichen Durchschnitt ein.
3. **Acht Stunden sind eine Arbeitsschutzgrenze, keine Sollzeit.** Sie gilt für
   Vollzeit wie Teilzeit gleichermaßen. Eine Teilzeitkraft mit vier Stunden
   Tagessoll darf ebenso bis zu zehn Stunden arbeiten und muss ebenso auf
   durchschnittlich acht ausgleichen. Die individuelle Sollzeit spielt hier
   **keine** Rolle – sie gehört ins Zeitkonto, nicht in den Arbeitsschutz.

Was das Gesetz **nicht** regelt und diese Umsetzung deshalb ausdrücklich
festlegt statt stillschweigend anzunehmen, steht in
:class:`CompensationRules` – Behandlung von Feiertagen, Urlaub, Krankheit und
Ersatzruhetagen im Nenner. Alle Regeln sind über die Systemkonfiguration
einstellbar.

Kunden, Aufträge und Kundenstandorte beeinflussen hier nichts. Feiertage
kommen ausschließlich aus der zentral konfigurierten Region des eigenen
Unternehmens.

Keine dieser Auswertungen ist eine rechtliche Bewertung des Einzelfalls.
Tarifliche Verlängerungen nach § 7 ArbZG und Ausnahmen nach § 14 kann eine
Software nicht kennen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from . import models

LOGGER = logging.getLogger("erfassung.application")

#: Gründe, aus denen ein Werktag nicht in den Nenner eingeht.
EXCLUDED_SUNDAY = "sunday"
EXCLUDED_HOLIDAY = "holiday"
EXCLUDED_VACATION = "vacation"
EXCLUDED_REST_DAY = "rest_day"

EXCLUSION_LABELS = {
    EXCLUDED_SUNDAY: "Sonntag – kein Werktag (§ 3 ArbZG)",
    EXCLUDED_HOLIDAY: "Gesetzlicher Feiertag der eigenen Region",
    EXCLUDED_VACATION: "Genehmigter Urlaub",
    EXCLUDED_REST_DAY: "Ersatzruhetag (§ 11 Abs. 3 ArbZG)",
}


@dataclass(frozen=True)
class CompensationRules:
    """Fachliche Festlegungen zum Ausgleichszeitraum.

    **Das Gesetz lässt diese Fragen offen.** § 3 nennt nur den Zeitraum und den
    Durchschnitt; wie Ausfalltage im Nenner zu behandeln sind, ergibt sich
    daraus nicht. Deshalb sind sie hier ausdrücklich benannt und über die
    Systemkonfiguration einstellbar – eine stille Annahme wäre hier fehl am
    Platz, weil jede Variante das Ergebnis in eine Richtung verschiebt.

    Merkregel: **Ein größerer Nenner senkt den Durchschnitt** und ist damit für
    den Arbeitgeber günstiger; ein kleinerer Nenner ist für die Beschäftigten
    günstiger.
    """

    #: Länge des Ausgleichszeitraums in Wochen. Das Gesetz nennt „sechs
    #: Kalendermonate **oder** 24 Wochen" gleichrangig; die Wochenvariante ist
    #: tagesgenau rollierend auswertbar und nie länger als die Monatsvariante.
    weeks: int = 24

    #: Gesetzliche Feiertage aus dem Nenner nehmen (Vorgabe: ja).
    #:
    #: An einem Feiertag besteht keine Arbeitspflicht. Zählte er als Werktag
    #: mit null Stunden, würde er eine Überschreitung ausgleichen – der
    #: Feiertag „bezahlte" dann Mehrarbeit, obwohl er ein eigenständiger
    #: Anspruch ist.
    exclude_holidays: bool = True

    #: Genehmigten Urlaub aus dem Nenner nehmen (Vorgabe: ja).
    #:
    #: Derselbe Gedanke, und er ist hier besonders deutlich: Urlaub dient der
    #: Erholung, nicht dem Abbau von Mehrarbeit. Zählte ein Urlaubstag als
    #: Werktag mit null Stunden, ließe sich jede Überschreitung durch längeren
    #: Urlaub wegrechnen.
    exclude_vacation: bool = True

    #: Ersatzruhetage nach § 11 Abs. 3 aus dem Nenner nehmen (Vorgabe: ja).
    #:
    #: Ein Ersatzruhetag gleicht Sonn-/Feiertagsarbeit aus – er ist für diesen
    #: Zweck schon verbraucht und kann nicht zusätzlich Mehrarbeit ausgleichen.
    exclude_rest_days: bool = True

    #: Krankheitstage aus dem Nenner nehmen.
    #:
    #: **Offene Entscheidung, mangels Daten nicht wirksam.** Das Datenmodell
    #: kennt keine Krankmeldung – ein Krankheitstag ist von einem freien Tag
    #: nicht zu unterscheiden. Fachlich gehörte er wie Urlaub aus dem Nenner
    #: (Krankheit gleicht keine Mehrarbeit aus). Solange die Daten fehlen,
    #: zählt ein solcher Tag als Werktag ohne Arbeit und senkt damit den
    #: Durchschnitt. Wer das braucht, muss zuerst Abwesenheiten erfassen; der
    #: Schalter ist vorbereitet.
    exclude_sick_days: bool = True

    @property
    def days(self) -> int:
        return self.weeks * 7


def load_rules() -> CompensationRules:
    """Regeln aus der persistenten Systemkonfiguration (config-Volume)."""
    try:
        from . import app_config

        settings = app_config.load_system_settings()
        return CompensationRules(
            weeks=int(settings.compensation_weeks),
            exclude_holidays=bool(settings.compensation_exclude_holidays),
            exclude_vacation=bool(settings.compensation_exclude_vacation),
            exclude_rest_days=bool(settings.compensation_exclude_rest_days),
        )
    except Exception:  # pragma: no cover - Konfigurationsfehler darf nichts kippen
        return CompensationRules()


@dataclass
class WorkdayEntry:
    """Ein Tag des Ausgleichszeitraums mit seiner Einordnung."""

    day: date
    minutes: int = 0
    #: ``None`` heißt: zählt in den Nenner.
    excluded: Optional[str] = None

    @property
    def counts(self) -> bool:
        return self.excluded is None


@dataclass
class CompensationReport:
    """Nachvollziehbare Auswertung eines Ausgleichszeitraums.

    Der Bericht ist bewusst gesprächig: Er nennt nicht nur den Durchschnitt,
    sondern auch **welche Tage** ihn bilden und **welche warum nicht**. Eine
    Zahl ohne ihre Herleitung ist bei einer Arbeitsschutzgrenze wenig wert.
    """

    start: date
    end: date
    rules: CompensationRules
    days: list[WorkdayEntry] = field(default_factory=list)

    @property
    def counted_days(self) -> list[WorkdayEntry]:
        return [item for item in self.days if item.counts]

    @property
    def excluded_days(self) -> list[WorkdayEntry]:
        return [item for item in self.days if not item.counts]

    @property
    def denominator(self) -> int:
        """Werktage, über die gemittelt wird."""
        return len(self.counted_days)

    @property
    def total_minutes(self) -> int:
        """Tatsächliche Arbeitszeit; Sonntage erhöhen nur den Nenner nicht."""
        return sum(item.minutes for item in self.days)

    @property
    def allowance_minutes(self) -> int:
        """Zulässige Gesamtarbeitszeit: acht Stunden je gezähltem Werktag."""
        return self.denominator * models.MAX_DAILY_MINUTES

    @property
    def average_minutes(self) -> int:
        if self.denominator <= 0:
            return 0
        return int(round(self.total_minutes / self.denominator))

    @property
    def excess_minutes(self) -> int:
        """Überhang gegenüber dem Achtstundenschnitt; 0, wenn eingehalten."""
        return max(self.total_minutes - self.allowance_minutes, 0)

    @property
    def headroom_minutes(self) -> int:
        """Spielraum, bis der Schnitt reißt."""
        return max(self.allowance_minutes - self.total_minutes, 0)

    @property
    def is_compliant(self) -> bool:
        return self.excess_minutes <= 0

    def exclusion_summary(self) -> dict[str, int]:
        """Ausgeschlossene Tage je Grund – für die Anzeige."""
        summary: dict[str, int] = {}
        for item in self.excluded_days:
            summary[item.excluded] = summary.get(item.excluded, 0) + 1
        return summary

    def describe(self) -> str:
        """Einzeilige Herleitung für Kennzeichnungen und Berichte."""
        parts = [
            f"{self.start.strftime('%d.%m.%Y')}–{self.end.strftime('%d.%m.%Y')}",
            f"{self.denominator} Werktage",
            f"Ø {self.average_minutes // 60}:{self.average_minutes % 60:02d} Std",
        ]
        excluded = self.exclusion_summary()
        if excluded:
            details = ", ".join(
                f"{count}× {EXCLUSION_LABELS.get(reason, reason)}"
                for reason, count in sorted(excluded.items())
            )
            parts.append(f"ausgenommen: {details}")
        return "; ".join(parts)


def _excluded_dates(
    db: Session, user_id: int, start: date, end: date, rules: CompensationRules
) -> dict[date, str]:
    """Tage, die nach den geltenden Regeln nicht in den Nenner gehen."""
    from . import crud

    excluded: dict[date, str] = {}

    if rules.exclude_holidays:
        # Ausschließlich die zentral konfigurierte Region des eigenen
        # Unternehmens. Kundenfirma und Kundenstandort ändern daran nichts.
        for day in crud.get_holiday_dates_in_range(db, start, end):
            excluded.setdefault(day, EXCLUDED_HOLIDAY)

    if rules.exclude_vacation:
        vacations = crud.get_vacations_in_range(
            db, start, end, user_id=user_id,
            statuses=[models.VacationStatus.APPROVED],
        )
        for vacation in vacations:
            current = max(vacation.start_date, start)
            last = min(vacation.end_date, end)
            while current <= last:
                excluded.setdefault(current, EXCLUDED_VACATION)
                current += timedelta(days=1)

    if rules.exclude_rest_days:
        rest_days = (
            db.query(models.ComplianceFlag.replacement_rest_date)
            .filter(models.ComplianceFlag.user_id == user_id)
            .filter(models.ComplianceFlag.replacement_rest_date.isnot(None))
            .filter(models.ComplianceFlag.replacement_rest_date >= start)
            .filter(models.ComplianceFlag.replacement_rest_date <= end)
            .all()
        )
        for (rest_day,) in rest_days:
            if rest_day is not None:
                excluded.setdefault(rest_day, EXCLUDED_REST_DAY)

    return excluded


def build_report(
    db: Session,
    user_id: int,
    reference: date,
    *,
    rules: Optional[CompensationRules] = None,
) -> CompensationReport:
    """Ausgleichszeitraum, der am ``reference``-Tag endet.

    Jeder Kalendertag des Fensters wird eingeordnet: Sonntage und die nach den
    Regeln ausgenommenen Tage fallen aus dem Nenner, alle übrigen Werktage
    zählen – **auch die ohne Arbeit**. Genau über sie läuft der Ausgleich.
    """
    rules = rules or load_rules()
    start = reference - timedelta(days=rules.days - 1)

    from . import compliance

    entries = [
        entry
        for entry in db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.work_date >= start)
        .filter(models.TimeEntry.work_date <= reference)
        .all()
        if entry.status != models.TimeEntryStatus.CANCELLED
    ]
    per_day: dict[date, int] = {}
    for entry in entries:
        per_day[entry.work_date] = per_day.get(entry.work_date, 0) + entry.worked_minutes

    excluded = _excluded_dates(db, user_id, start, reference, rules)

    report = CompensationReport(start=start, end=reference, rules=rules)
    current = start
    while current <= reference:
        if current.weekday() == 6:
            reason = EXCLUDED_SUNDAY
        else:
            reason = excluded.get(current)
        minutes = per_day.get(current, 0)
        # An einem Ausfalltag tatsächlich geleistete Arbeit darf niemals aus
        # der Arbeitsschutzrechnung verschwinden. Feiertag, Urlaub oder ein
        # geplanter Ersatzruhetag neutralisieren nur einen *arbeitsfreien* Tag.
        # Sonntage bleiben als Nicht-Werktage aus dem §-3-Nenner; ihre Grenzen
        # werden gesondert über § 11 Abs. 2/§ 3 geprüft.
        if minutes > 0 and reason != EXCLUDED_SUNDAY:
            reason = None
        report.days.append(WorkdayEntry(day=current, minutes=minutes, excluded=reason))
        current += timedelta(days=1)
    return report


# ── Ausgleichsvorgänge je Überschreitungstag ──────────────────────────────


@dataclass
class CompensationCase:
    """Ein einzelner Tag über acht Stunden und sein Ausgleichsstand.

    § 3 knüpft die Verlängerung an **den einzelnen Tag**: Wer an einem Tag zehn
    Stunden arbeitet, muss diese zwei Stunden innerhalb des Ausgleichszeitraums
    abbauen. Bis 0.16.0 gab es nur eine Gesamtbetrachtung; welcher Tag wann
    fällig ist, ließ sich daraus nicht ablesen – und die Restlaufzeit war
    zwangsläufig null, weil das rollierende Fenster immer gleich lang ist.
    """

    work_date: date
    excess_minutes: int
    window_start: date
    deadline: date
    compensated_minutes: int = 0

    @property
    def open_minutes(self) -> int:
        return max(self.excess_minutes - self.compensated_minutes, 0)

    @property
    def is_resolved(self) -> bool:
        return self.open_minutes <= 0

    def remaining_days(self, reference: date) -> int:
        """Tage bis zum spätesten Ausgleichsdatum (negativ = überfällig)."""
        return (self.deadline - reference).days

    def state(self, reference: date, *, warning_days: int = 28) -> str:
        """Zustand nach § 3: erledigt, überfällig, fällig oder laufend."""
        if self.is_resolved:
            return models.CompensationState.RESOLVED
        if reference > self.deadline:
            return models.CompensationState.OVERDUE
        if self.remaining_days(reference) <= warning_days:
            return models.CompensationState.DUE
        return models.CompensationState.REQUIRED


def build_cases(
    db: Session,
    user_id: int,
    reference: date,
    *,
    rules: Optional[CompensationRules] = None,
) -> list[CompensationCase]:
    """Alle offenen und erledigten Ausgleichsvorgänge bis ``reference``.

    **Zuordnungsregel (FIFO, ausdrücklich festgelegt):** Freie Kapazität eines
    Werktags – also die Minuten, um die er unter acht Stunden bleibt – wird dem
    **ältesten** noch offenen Überschreitungstag zugeschlagen, dessen Fenster
    den Tag umfasst.

    Warum FIFO: Der älteste Vorgang hat die kürzeste Restlaufzeit. Würde
    zuerst der jüngste bedient (LIFO), liefe der älteste ab, obwohl Ausgleich
    stattgefunden hat – das Ergebnis wäre eine Überfälligkeit, die es der Sache
    nach nicht gibt. Das Gesetz schreibt keine Reihenfolge vor; diese ist die
    für die Beschäftigten günstigere und wird deshalb hier gewählt.

    Ausgleich zählt nur **innerhalb** des Fensters eines Vorgangs und nur an
    Werktagen, die auch im Nenner stehen: Ein Urlaubstag gleicht nichts aus.
    """
    rules = rules or load_rules()
    # Weit genug zurück, damit auch ein Vorgang am Rand seines Fensters noch
    # vollständig ausgewertet wird.
    lookback = reference - timedelta(days=rules.days * 2)
    report = build_report(db, user_id, reference, rules=rules)

    history = build_report(db, user_id, reference, rules=rules)
    ledger = {item.day: item for item in history.days}

    # Ältere Tage nachladen, damit ein Vorgang vom Fensteranfang seine
    # Ausgleichstage kennt.
    older = build_report(db, user_id, report.start - timedelta(days=1), rules=rules)
    for item in older.days:
        ledger.setdefault(item.day, item)

    cases: list[CompensationCase] = []
    for day in sorted(ledger):
        if day < lookback or day > reference:
            continue
        item = ledger[day]
        # § 11 Abs. 2 verweist für zulässige Sonntagsarbeit auf §§ 3–8:
        # Sonntag bleibt aus dem Werktagsnenner, seine Mehrarbeit eröffnet
        # dennoch einen Ausgleichsvorgang.
        if not item.counts and not (day.weekday() == 6 and item.minutes > 0):
            continue
        excess = item.minutes - models.MAX_DAILY_MINUTES
        if excess <= 0:
            continue
        cases.append(
            CompensationCase(
                work_date=day,
                excess_minutes=excess,
                window_start=day,
                # „innerhalb von 24 Wochen" – der Beschäftigungstag zählt mit.
                deadline=day + timedelta(days=rules.days - 1),
            )
        )

    if not cases:
        return []

    for day in sorted(ledger):
        item = ledger[day]
        if not item.counts:
            continue
        capacity = models.MAX_DAILY_MINUTES - item.minutes
        if capacity <= 0:
            continue
        for case in cases:               # FIFO: ältester Vorgang zuerst
            if case.is_resolved:
                continue
            if not (case.window_start <= day <= case.deadline):
                continue
            if day == case.work_date:
                continue
            take = min(capacity, case.open_minutes)
            case.compensated_minutes += take
            capacity -= take
            if capacity <= 0:
                break
    return cases


__all__ = [
    "CompensationCase",
    "CompensationReport",
    "CompensationRules",
    "EXCLUSION_LABELS",
    "WorkdayEntry",
    "build_cases",
    "build_report",
    "load_rules",
]

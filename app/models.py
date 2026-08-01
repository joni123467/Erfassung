from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from . import worktime
from .database import Base




class Company(Base):
    """Ein **Kunde** beziehungsweise Auftraggeber – nicht der eigene Betrieb.

    Wichtig für alle Auswertungen: Diese Daten dienen der Auftragszuordnung.
    Sie sind **keine** Quelle für arbeitsrechtliche Regeln. Feiertagsregion,
    Sollzeit, Pausenpflicht, Höchstarbeitszeit und Ruhezeit stammen
    ausschließlich aus der zentralen Konfiguration des eigenen Unternehmens
    beziehungsweise der Mitarbeiterstammdaten.
    """

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, default="")
    #: Der eigene Betrieb statt eines Kunden. Die Standorte einer solchen Firma
    #: stehen auch beim Stempeln **ohne** Auftrag zur Wahl, und Auswertungen
    #: können interne Zeit von Kundenzeit trennen.
    is_internal = Column(Boolean, default=False, nullable=False)

    time_entries = relationship("TimeEntry", back_populates="company")
    locations = relationship(
        "CompanyLocation",
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="CompanyLocation.name",
    )

    @property
    def active_locations(self) -> list["CompanyLocation"]:
        """Standorte, die noch zur Auswahl stehen – Hauptstandort zuerst."""
        return sorted(
            (location for location in self.locations if location.is_active),
            key=lambda location: (not location.is_primary, location.name.lower()),
        )

    @property
    def primary_location(self) -> Optional["CompanyLocation"]:
        """Vorauswahl beim Stempeln; ``None``, wenn nichts gepflegt ist."""
        active = self.active_locations
        return active[0] if active else None


class CompanyLocation(Base):
    """Ein **Kunden-/Auftragsstandort** – Niederlassung, Werk, Baustelle.

    Bewusst eine eigene Tabelle statt eines Adressfeldes an der Firma: Nur so
    lassen sich mehrere Standorte führen und an einer Buchung auswerten.

    Wie bei :class:`Company` gilt: Der Standort sagt, *wo für wen* gearbeitet
    wurde. Er bestimmt **nie** den Feiertagskalender oder eine andere
    arbeitsrechtliche Regel. Arbeit an einem Kundenstandort in einer anderen
    Feiertagsregion ändert die Bewertung nicht.
    """

    __tablename__ = "company_locations"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(255), nullable=False)
    street = Column(String(255), default="")
    postal_code = Column(String(32), default="")
    city = Column(String(255), default="")
    country = Column(String(128), default="")
    #: Vorauswahl beim Stempeln. Genau einer je Firma.
    is_primary = Column(Boolean, default=False, nullable=False)
    #: Geschlossene Standorte verschwinden aus der Auswahl, bleiben aber in
    #: Auswertungen und alten Buchungen erhalten.
    is_active = Column(Boolean, default=True, nullable=False)

    company = relationship("Company", back_populates="locations")
    time_entries = relationship("TimeEntry", back_populates="location")

    @property
    def address_line(self) -> str:
        """Einzeilige Anschrift; leer, wenn nichts hinterlegt ist."""
        parts = [
            (self.street or "").strip(),
            " ".join(
                value for value in ((self.postal_code or "").strip(), (self.city or "").strip())
                if value
            ),
            (self.country or "").strip(),
        ]
        return ", ".join(part for part in parts if part)

    @property
    def display_name(self) -> str:
        """Name mit Firma davor – für Listen über mehrere Firmen hinweg."""
        if self.company is None:
            return self.name
        return f"{self.company.name} – {self.name}"


#: Zuordnungstabellen des Rollenmodells (RBAC): Ein Benutzer gehört beliebig
#: vielen Gruppen (Organisation) und beliebig vielen Rollen (Berechtigungen) an.
user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Group(Base):
    """Organisationseinheit (Abteilung, Team, Standort) – ohne Berechtigungen.

    Rechte werden ausschließlich über Rollen vergeben; Gruppen dienen der
    Zuordnung und dem Geltungsbereich ``groups``.
    """

    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, default="")

    users = relationship("User", secondary=user_groups, back_populates="groups")


class Role(Base):
    """Bündel von Berechtigungen, unabhängig von der Organisation."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, default="")
    #: Systemrollen (Administrator/Superadministrator) sind nicht änderbar.
    is_system = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def permission_map(self) -> dict[str, str]:
        """Vergebene Rechte als ``{key: scope}``."""
        return {item.permission_key: item.scope for item in self.permissions}


class RolePermission(Base):
    """Einzelne Berechtigung einer Rolle samt Geltungsbereich."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_key", name="uq_role_permission"),
    )

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    permission_key = Column(String(64), nullable=False, index=True)
    scope = Column(String(16), nullable=False, default="all")

    role = relationship("Role", back_populates="permissions")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    standard_daily_minutes = Column(Integer, default=480)
    standard_weekly_hours = Column(Float, default=40.0)
    pin_code = Column(String(4), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    must_change_password = Column(Boolean, default=True)
    # Nur noch für Altbestände/Backups: die Zugehörigkeit steht in user_groups.
    group_id = Column(Integer, ForeignKey("groups.id"))
    time_account_enabled = Column(Boolean, default=False)
    overtime_vacation_enabled = Column(Boolean, default=False)
    annual_vacation_days = Column(Integer, default=30)
    vacation_carryover_enabled = Column(Boolean, default=False)
    vacation_carryover_days = Column(Integer, default=0)
    rfid_tag = Column(String(255), unique=True, nullable=True)
    monthly_overtime_limit_minutes = Column(Integer, nullable=True)
    auto_break_deduction = Column(Boolean, default=True)
    remote_flag_enabled = Column(Boolean, default=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    deactivated_at = Column(DateTime, nullable=True)
    deactivation_reason = Column(String(500), nullable=True)

    groups = relationship("Group", secondary=user_groups, back_populates="users", lazy="selectin")
    roles = relationship("Role", secondary=user_roles, back_populates="users", lazy="selectin")
    # ``foreign_keys`` ist nötig, seit ``time_entries`` einen zweiten Verweis
    # auf ``users`` trägt (``cancelled_by_id``); sonst bliebe die Zuordnung
    # mehrdeutig.
    time_entries = relationship(
        "TimeEntry",
        back_populates="user",
        foreign_keys="TimeEntry.user_id",
    )
    vacation_requests = relationship(
        "VacationRequest", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def group_names(self) -> list[str]:
        return sorted(group.name for group in self.groups)

    @property
    def group_ids(self) -> set[int]:
        return {group.id for group in self.groups}

    @property
    def role_names(self) -> list[str]:
        return sorted(role.name for role in self.roles)

    @property
    def weekly_target_minutes(self) -> int:
        if self.standard_weekly_hours is not None:
            weekly_hours = float(self.standard_weekly_hours)
        elif self.standard_daily_minutes:
            weekly_hours = (self.standard_daily_minutes or 0) * 5 / 60
        else:
            weekly_hours = 0.0
        return int(round(max(weekly_hours, 0) * 60))

    @property
    def daily_target_minutes(self) -> float:
        weekly_minutes = self.weekly_target_minutes
        if weekly_minutes <= 0:
            return 0.0
        return weekly_minutes / 5


class TimeEntryStatus:
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    #: Storniert. Die Buchung bleibt vollständig erhalten und sichtbar, zählt
    #: aber nicht mehr. Korrekturen laufen über Storno plus Ersatzbuchung –
    #: ein Originaldatensatz wird nie überschrieben oder gelöscht.
    CANCELLED = "cancelled"


class RevisionAction:
    """Was mit einer Buchung geschehen ist – Werte der Revisionshistorie."""

    CREATED = "created"
    #: Laufende Buchung beendet. Bewusst nicht ``UPDATED``: Das Beenden ist
    #: keine Korrektur, sondern der zweite Stempel derselben Buchung – und
    #: braucht deshalb auch keine Begründung.
    CLOSED = "closed"
    UPDATED = "updated"
    #: Pausenereignisse (ab 0.15.0). Beginn und Ende sind Stempelungen und
    #: brauchen keine Begründung; Korrektur und Storno einer Pause sind
    #: nachträgliche Eingriffe und deshalb begründungspflichtig.
    BREAK_STARTED = "break_started"
    BREAK_ENDED = "break_ended"
    BREAK_CORRECTED = "break_corrected"
    BREAK_CANCELLED = "break_cancelled"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REPLACED = "replaced"
    REOPENED = "reopened"


#: Bei diesen Vorgängen ist eine Begründung Pflicht. Anlegen und Freigeben
#: brauchen keine – der Vorgang selbst ist die Aussage.
#: Vorgänge, die eine Begründung erzwingen.
REVISION_REASON_REQUIRED = frozenset(
    {
        RevisionAction.UPDATED,
        RevisionAction.REJECTED,
        RevisionAction.CANCELLED,
        # Eine Pause nachträglich zu verschieben oder zu streichen verändert
        # die abgerechnete Arbeitszeit – das braucht einen Grund.
        RevisionAction.BREAK_CORRECTED,
        RevisionAction.BREAK_CANCELLED,
    }
)


#: Kürzeste Unterbrechung, die als Ruhepause im Sinne des §4 ArbZG zählt.
MIN_BREAK_SEGMENT_MINUTES = 15

#: Regelarbeitszeit und absolute Höchstgrenze je Werktag (§3 ArbZG).
MAX_DAILY_MINUTES = 8 * 60
ABSOLUTE_MAX_DAILY_MINUTES = 10 * 60

#: Ununterbrochene Ruhezeit zwischen zwei Arbeitstagen (§5 ArbZG).
MIN_REST_MINUTES = 11 * 60

#: Ausgleichszeitraum nach § 3 Satz 2 ArbZG: „innerhalb von sechs
#: Kalendermonaten oder innerhalb von 24 Wochen". Das Gesetz nennt beide
#: Varianten gleichrangig; diese Umsetzung rechnet mit **24 Wochen**, weil ein
#: Wochenraster zu einer werktäglichen Betrachtung passt und tagesgenau
#: rollierend auswertbar ist. Die Kalendermonatsvariante wäre bis zu zwei
#: Wochen länger und damit für den Beschäftigten ungünstiger.
COMPENSATION_WEEKS = 24
COMPENSATION_DAYS = COMPENSATION_WEEKS * 7

#: Ab wann vor Ablauf des Ausgleichszeitraums gewarnt wird.
COMPENSATION_WARNING_DAYS = 28

#: Ab dieser Unterbrechung gilt eine Schicht als beendet und eine neue als
#: begonnen (ab 0.15.0).
#:
#: Der Wert ist eine **fachliche Festlegung**, keine Zahl aus dem Gesetz. Das
#: ArbZG kennt den Begriff „Schicht" nicht; es kennt Ruhepausen (§ 4, höchstens
#: 45 Minuten gefordert) und die Ruhezeit zwischen zwei Arbeitstagen (§ 5,
#: 11 Stunden). Dazwischen klafft eine Lücke, die eine Software füllen muss:
#: Ist eine Unterbrechung von vier Stunden eine sehr lange Pause oder das Ende
#: des Arbeitstags?
#:
#: Sechs Stunden trennen beides brauchbar: Ein geteilter Dienst mit mehreren
#: Stunden Mittagspause bleibt **eine** Schicht (und muss die Pausenpflicht
#: erfüllen), während eine Unterbrechung von sechs Stunden oder mehr als Ende
#: des Arbeitstags gilt und damit die Ruhezeitprüfung nach § 5 auslöst.
#:
#: Wer das anders handhabt (Tarifvertrag, Betriebsvereinbarung), ändert diesen
#: Wert – die Auswirkung ist in den Release Notes zu 0.15.0 beschrieben.
SHIFT_BREAK_MINUTES = 6 * 60


class BreakRule:
    """Wie die Pause in die Arbeitszeit eingerechnet wird.

    Der Wert wird **je Buchung** festgehalten, nicht global ausgewertet. Nur so
    bleiben Bestandsauswertungen stabil, während neue Buchungen der korrigierten
    Regel folgen.
    """

    #: Seit 0.14.0 für neue Buchungen: Abgezogen wird ausschließlich die
    #: tatsächlich gestempelte Pause. Eine nicht genommene gesetzliche Pause
    #: wird als Verstoß gekennzeichnet, nicht stillschweigend verbucht.
    ACTUAL = "actual"
    #: Verhalten bis 0.13.x: Die gesetzliche Mindestpause wurde auch dann
    #: abgezogen, wenn sie nicht gestempelt war. Bestandsdaten behalten das,
    #: damit sich abgerechnete Monate nicht rückwirkend ändern.
    LEGACY_AUTO = "legacy_auto"


class ComplianceCode:
    """Kennzeichnungen aus ArbZG/ArbSchG. Sie sperren nichts, sie warnen."""

    OVER_8H = "over_8h"
    OVER_10H = "over_10h"
    REST_UNDER_11H = "rest_under_11h"
    BREAK_MISSING = "break_missing"
    SUNDAY_WORK = "sunday_work"
    HOLIDAY_WORK = "holiday_work"
    #: Der Ausgleich nach § 3 Satz 2 ArbZG fehlt (ab 0.16.0): Im
    #: Ausgleichszeitraum liegt der werktägliche Durchschnitt über acht
    #: Stunden.
    AVERAGE_OVER_8H = "average_over_8h"
    #: Ausgleich erforderlich, Frist läuft noch (ab 0.17.0).
    COMPENSATION_REQUIRED = "compensation_required"
    #: Der Ausgleichszeitraum läuft ab und der Überhang ist noch nicht
    #: abgebaut – eine Vorwarnung, solange Ausgleich noch möglich ist.
    COMPENSATION_DUE = "compensation_due"
    #: Die Frist ist abgelaufen, ohne dass ausgeglichen wurde (ab 0.17.0).
    COMPENSATION_OVERDUE = "compensation_overdue"


class CompensationState:
    """Zustand eines Ausgleichsvorgangs nach § 3 Satz 2 ArbZG (ab 0.17.0).

    Bewusst getrennt vom Lebenszyklus einer Feststellung
    (:class:`ComplianceState`): Der eine sagt, wie es um den **Ausgleich**
    steht, der andere, wie es um die **Bearbeitung der Kennzeichnung** steht.
    """

    #: Ausgleich nötig, Frist läuft.
    REQUIRED = "compensation_required"
    #: Frist läuft bald ab.
    DUE = "compensation_due"
    #: Frist abgelaufen, Ausgleich fehlt.
    OVERDUE = "compensation_overdue"
    #: Rechtzeitig ausgeglichen.
    RESOLVED = "compensation_resolved"


class PeriodStatus:
    """Zustände einer Abrechnungsperiode."""

    OPEN = "open"
    #: Mitarbeiter prüfen ihre Zeiten und bestätigen oder widersprechen.
    REVIEW = "review"
    #: Arbeitgeber hat freigegeben; Änderungen sind noch möglich.
    APPROVED = "approved"
    #: Gesperrt: keine Änderungen mehr an Buchungen dieses Zeitraums.
    LOCKED = "locked"


class ConfirmationStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    OBJECTED = "objected"


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        Index(
            "ix_time_entries_source_external",
            "source",
            "external_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    deleted_company_name = Column(String(255), nullable=True)
    work_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    break_minutes = Column(Integer, default=0)
    break_started_at = Column(Time, nullable=True)
    is_open = Column(Boolean, default=False)
    notes = Column(String(255), default="")
    status = Column(String(32), default=TimeEntryStatus.APPROVED)
    is_manual = Column(Boolean, default=False)
    is_remote = Column(Boolean, default=False)
    #: Gewählter Standort. ``NULL`` heißt: kein Standort gepflegt oder nicht
    #: gewählt – dann gilt weiterhin allein ``is_remote`` (Remote/Vor Ort).
    location_id = Column(
        Integer, ForeignKey("company_locations.id", ondelete="SET NULL"), nullable=True
    )
    #: Name des Standorts, falls dieser später gelöscht wird – damit eine alte
    #: Buchung ihre Aussage behält (wie ``deleted_company_name``).
    deleted_location_name = Column(String(255), nullable=True)
    source = Column(String(64), nullable=True)
    external_id = Column(String(191), nullable=True)
    #: Vollständiger Beginn/Ende in UTC. ``work_date``/``start_time``/
    #: ``end_time`` bleiben führend für Anzeige und Bestandsdaten; die
    #: UTC-Stempel machen Nachtarbeit, Zeitumstellung und Auswertungen über
    #: Zeitzonen hinweg eindeutig. Bei Bestandsbuchungen ``NULL``.
    started_at_utc = Column(DateTime, nullable=True)
    ended_at_utc = Column(DateTime, nullable=True)
    #: Zeitzone, in der gestempelt wurde (z. B. ``Europe/Berlin``). Ohne sie
    #: ließe sich ein UTC-Stempel nicht in die ursprüngliche Ortszeit
    #: zurückrechnen.
    tz_name = Column(String(64), nullable=True)
    #: Schnappschuss der Pausenregel – siehe :class:`BreakRule`.
    break_rule = Column(String(32), default=BreakRule.ACTUAL)
    #: Storno statt Löschen.
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancel_reason = Column(String(500), nullable=True)
    #: Ersatzbuchung, die diese Buchung ablöst, und die Gegenrichtung.
    replaced_by_id = Column(Integer, ForeignKey("time_entries.id"), nullable=True)
    replaces_id = Column(Integer, ForeignKey("time_entries.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="time_entries", foreign_keys=[user_id])
    company = relationship("Company", back_populates="time_entries")
    location = relationship("CompanyLocation", back_populates="time_entries")
    breaks = relationship(
        "BreakInterval",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="BreakInterval.started_at_utc",
    )
    # ``delete-orphan`` greift nur, wenn eine Buchung selbst verschwindet – und
    # das passiert seit 0.14.0 ausschließlich beim Löschen des ganzen Benutzers
    # (Art. 17 DSGVO). Dann soll auch dessen Änderungshistorie mitgehen; sie
    # ohne Bezugsbuchung stehen zu lassen wäre weder nützlich noch zulässig.
    revisions = relationship(
        "TimeEntryRevision",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="TimeEntryRevision.revision_no",
    )

    @property
    def gross_minutes(self) -> int:
        """Anwesenheit von Beginn bis Ende, ohne Pausenabzug.

        Gerechnet wird über :mod:`app.worktime` – dieselbe Funktion, die auch
        die Regelprüfung benutzt. Bis 0.15.0 gab es hier eine zweite Rechnung
        mit naiven Ortszeiten; über eine Zeitumstellung hinweg wichen
        Auswertung und Regelprüfung dadurch um eine Stunde voneinander ab.
        """
        return worktime.gross_minutes(self)

    @property
    def required_break_minutes(self) -> int:
        """Gesetzliche Mindestpause nach §4 ArbZG.

        **Mehr als** sechs Stunden: 30 Minuten. **Mehr als** neun Stunden:
        45 Minuten. Die Grenzen sind echte Überschreitungen – bei glatt sechs
        Stunden ist keine Pause vorgeschrieben. Bis 0.13.x rechnete die
        Anwendung hier mit „ab sechs Stunden" und verlangte eine Pause zu früh.
        """
        duration = self.gross_minutes
        if duration > 9 * 60:
            return 45
        if duration > 6 * 60:
            return 30
        return 0

    @property
    def countable_break_minutes(self) -> int:
        """Pausenminuten, die als Ruhepause im Sinne des §4 ArbZG zählen.

        Nur Abschnitte von **mindestens 15 Minuten** – kürzere Unterbrechungen
        sind keine Ruhepausen. Sie werden trotzdem gespeichert und von der
        Arbeitszeit abgezogen; sie erfüllen nur die Pausenpflicht nicht.
        """
        intervals = self._break_intervals
        if intervals:
            return sum(
                interval.minutes for interval in intervals
                if interval.minutes >= MIN_BREAK_SEGMENT_MINUTES
            )
        # Bestandsbuchung ohne Intervalle: Die Summe lässt sich nicht in
        # Abschnitte zerlegen, also wird sie als ein Abschnitt gewertet.
        total = self.total_break_minutes
        return total if total >= MIN_BREAK_SEGMENT_MINUTES else 0

    @property
    def break_shortfall_minutes(self) -> int:
        """Wie viel Pause fehlt zur gesetzlichen Mindestpause?

        Grundlage ist die *anrechenbare* Pause. Eine offene Buchung wird nicht
        bewertet – sie läuft ja noch.
        """
        if self.is_open:
            return 0
        return max(self.required_break_minutes - self.countable_break_minutes, 0)

    @property
    def auto_break_enabled(self) -> bool:
        """Rechnet diese Buchung noch nach der alten Regel?

        Nur Bestandsbuchungen (``break_rule = legacy_auto``) tun das. Neue
        Buchungen ziehen ausschließlich tatsächlich gestempelte Pausen ab; eine
        fehlende Pause wird gekennzeichnet, nicht verbucht.
        """
        if (self.break_rule or BreakRule.ACTUAL) != BreakRule.LEGACY_AUTO:
            return False
        from sqlalchemy import inspect as _inspect

        try:
            state = _inspect(self)
            # Nicht nachladen, wenn die Buchung von ihrer Sitzung gelöst ist –
            # dann gilt die alte Vorgabe (Abzug aktiv), wie vor 0.14.0.
            if "user" in state.unloaded and state.session is None:
                return True
        except Exception:  # pragma: no cover - nicht persistiertes Objekt
            pass
        if self.user is None:
            return True
        value = getattr(self.user, "auto_break_deduction", True)
        return True if value is None else bool(value)

    @property
    def applied_break_minutes(self) -> int:
        """Pausenminuten, die von der Arbeitszeit abgezogen werden.

        Für neue Buchungen ist das genau die gestempelte Pause. Eine nicht
        genommene Pause wird **nicht** abgezogen: Das würde die tatsächlich
        geleistete Arbeitszeit kleiner erscheinen lassen, als sie war.
        """
        if self.auto_break_enabled:
            return max(self.total_break_minutes, self.required_break_minutes)
        return self.total_break_minutes

    @property
    def worked_minutes(self) -> int:
        """Tatsächlich geleistete Arbeitszeit.

        Eine stornierte Buchung zählt nicht mehr; sie bleibt aber vollständig
        gespeichert und sichtbar.
        """
        if self.status == TimeEntryStatus.CANCELLED:
            return 0
        return max(self.gross_minutes - self.applied_break_minutes, 0)

    @property
    def overtime_minutes(self) -> int:
        if self.user:
            target = self.user.daily_target_minutes
            if target:
                return int(self.worked_minutes - target)
        return 0

    @property
    def _break_intervals(self) -> list["BreakInterval"]:
        """Pausenintervalle, ohne dafür nachzuladen.

        Ist die Beziehung nicht geladen und die Buchung von ihrer Sitzung
        gelöst (etwa in einem Export nach ``db.close()``), wird eine leere
        Liste geliefert statt eine Ausnahme ausgelöst. Es gilt dann die
        Summenspalte – also genau das Verhalten vor 0.14.0.
        """
        from sqlalchemy import inspect as _inspect

        try:
            state = _inspect(self)
        except Exception:  # pragma: no cover - nicht persistiertes Objekt
            return list(self.__dict__.get("breaks") or [])
        if "breaks" in state.unloaded and state.session is None:
            return []
        return list(self.breaks or [])

    @property
    def total_break_minutes(self) -> int:
        """Gestempelte Pause insgesamt.

        Gibt es Pausenintervalle, sind sie die Wahrheit – die Summenspalte
        ``break_minutes`` ist dann nur noch ein Bestandsfeld. Ohne Intervalle
        (Buchungen vor 0.14.0, Terminalimporte) wird wie bisher gerechnet.
        """
        intervals = self._break_intervals
        if intervals:
            return sum(interval.minutes for interval in intervals)
        minutes = self.break_minutes or 0
        if self.break_started_at:
            start_dt = datetime.combine(self.work_date, self.break_started_at)
            if self.is_open:
                now_dt = datetime.now()
                end_dt = datetime.combine(now_dt.date(), now_dt.time())
            else:
                end_dt = datetime.combine(self.work_date, self.end_time)
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            minutes += max(int((end_dt - start_dt).total_seconds() // 60), 0)
        return minutes

    @property
    def running_break(self) -> Optional["BreakInterval"]:
        """Die gerade laufende Pause, falls eine läuft."""
        for interval in self._break_intervals:
            if interval.is_running:
                return interval
        return None

    @property
    def is_cancelled(self) -> bool:
        return self.status == TimeEntryStatus.CANCELLED

    @property
    def company_display_name(self) -> str:
        if self.company:
            return self.company.name
        if self.deleted_company_name:
            return f"Gelöscht ({self.deleted_company_name})"
        return "Allgemeine Arbeitszeit"

    @property
    def location_label(self) -> str:
        """Einsatzort der Buchung.

        Der Standortname, sobald einer gewählt wurde – sonst wie seit 0.9.21
        „Remote" oder „Vor Ort". Bestandsbuchungen ohne Standort lesen sich
        damit unverändert.

        Die Abfrage von ``location_id`` steht bewusst vor dem Zugriff auf die
        Beziehung: Ohne Standort wird gar nicht erst nachgeladen. Das spart bei
        jeder Liste eine Abfrage je Zeile und macht die Eigenschaft auch an
        einer abgelösten Buchung benutzbar.
        """
        if self.location_id is not None and self.location is not None:
            return self.location.name
        if self.deleted_location_name:
            return f"Gelöscht ({self.deleted_location_name})"
        return "Remote" if self.is_remote else "Vor Ort"

    @property
    def location_address(self) -> str:
        """Anschrift des gewählten Standorts; leer, wenn keiner hinterlegt."""
        if self.location_id is None or self.location is None:
            return ""
        return self.location.address_line


class BreakInterval(Base):
    """Eine einzelne Pause mit Beginn und Ende.

    Bis 0.13.x hielt die Buchung nur eine Summe (``break_minutes``) und den
    Beginn der laufenden Pause. Damit ließ sich nicht mehr nachweisen, *wann*
    eine Pause lag – für §4 ArbZG (Lage und Dauer im Voraus feststehend) und
    für jede Prüfung ist genau das die Frage.

    Die Summenspalte bleibt als Bestandsfeld erhalten; für Buchungen mit
    Intervallen ist sie nur noch abgeleitet.
    """

    __tablename__ = "break_intervals"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer, ForeignKey("time_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at_utc = Column(DateTime, nullable=False)
    #: ``NULL`` heißt: Pause läuft noch.
    ended_at_utc = Column(DateTime, nullable=True)
    tz_name = Column(String(64), nullable=True)
    source = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    entry = relationship("TimeEntry", back_populates="breaks")

    @property
    def minutes(self) -> int:
        """Dauer in vollen Minuten; eine laufende Pause zählt bis jetzt."""
        end = self.ended_at_utc or datetime.utcnow()
        if self.started_at_utc is None or end <= self.started_at_utc:
            return 0
        return int((end - self.started_at_utc).total_seconds() // 60)

    @property
    def is_running(self) -> bool:
        return self.ended_at_utc is None


class TimeEntryRevision(Base):
    """Unveränderliche Historie einer Buchung.

    Jede Anlage, Änderung, Freigabe, Ablehnung und Stornierung landet hier mit
    Vorher- und Nachher-Stand, Zeitpunkt, Bearbeiter und – wo vorgeschrieben –
    Begründung. Einträge dieser Tabelle werden nie geändert oder gelöscht.
    """

    __tablename__ = "time_entry_revisions"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("time_entries.id"), nullable=False, index=True)
    #: Fortlaufend je Buchung, beginnend bei 1.
    revision_no = Column(Integer, nullable=False, default=1)
    action = Column(String(32), nullable=False)
    changed_at_utc = Column(DateTime, nullable=False, default=datetime.utcnow)
    tz_name = Column(String(64), nullable=True)
    #: Wer die Änderung ausgelöst hat. ``NULL`` nur bei Systemvorgängen
    #: (Terminalimport, Migration) – dann sagt ``actor_label`` wer.
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_label = Column(String(255), nullable=True)
    reason = Column(String(500), nullable=True)
    source = Column(String(64), nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)

    entry = relationship("TimeEntry", back_populates="revisions")


class ComplianceState:
    """Lebenszyklus einer Compliance-Feststellung (ab 0.15.0).

    Feststellungen werden nicht mehr gelöscht, sondern fortgeschrieben. Eine
    Bestätigung bezieht sich immer auf einen konkreten Datenstand; ändert er
    sich, wird die Feststellung wieder geöffnet.
    """

    #: Neu erkannt.
    DETECTED = "detected"
    #: Bestand schon, der bewertete Datenstand hat sich aber geändert.
    CHANGED = "changed"
    #: Verstoß besteht nicht mehr (Buchung korrigiert oder storniert).
    RESOLVED = "resolved"
    #: Gesehen und mit Begründung eingeordnet.
    ACKNOWLEDGED = "acknowledged"
    #: Nach einer Bestätigung erneut aufgetreten, weil sich die Daten änderten.
    REOPENED = "reopened"


class ComplianceFlag(Base):
    """Kennzeichnung eines Regelverstoßes zu einer Buchung oder einem Tag.

    Wichtig: Ein Verstoß verhindert nichts. Die tatsächlich geleistete Zeit
    wird immer gespeichert – gekennzeichnet wird sie zusätzlich, damit sie
    auffällt und bearbeitet werden kann.
    """

    __tablename__ = "compliance_flags"
    __table_args__ = (
        Index("ix_compliance_user_date", "user_id", "work_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entry_id = Column(
        Integer, ForeignKey("time_entries.id", ondelete="CASCADE"), nullable=True, index=True
    )
    work_date = Column(Date, nullable=False)
    code = Column(String(32), nullable=False)
    #: ``info``, ``warning`` oder ``critical`` – steuert nur die Darstellung.
    severity = Column(String(16), nullable=False, default="warning")
    detail = Column(String(500), default="")
    detected_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledgement = Column(String(500), nullable=True)

    #: Lebenszyklus der Feststellung (ab 0.15.0). Bis 0.14.2 wurden offene
    #: Kennzeichnungen bei jeder Neuberechnung physisch gelöscht – damit war
    #: nicht mehr nachvollziehbar, dass es sie je gab.
    state = Column(String(16), nullable=False, default="detected")
    #: Prüfsumme des bewerteten Datenstands. Ändert sich Arbeitszeit, Pause
    #: oder Schweregrad, passt die Bestätigung nicht mehr – die Feststellung
    #: wird dann wieder geöffnet. Eine Bestätigung gilt nur für **den**
    #: Datenstand, für den sie abgegeben wurde.
    fingerprint = Column(String(64), nullable=True)
    #: Fingerabdruck, für den die Bestätigung abgegeben wurde.
    acknowledged_fingerprint = Column(String(64), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    reopened_at = Column(DateTime, nullable=True)
    #: Wie oft der Verstoß nach einer Änderung erneut auftrat.
    revision_no = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow)
    #: Stabiler Schlüssel der Feststellung (ab 0.16.0).
    #:
    #: Bis 0.15.0 wurde eine Feststellung nur über ``code`` wiedergefunden.
    #: Das genügt nicht: An einem Tag kann es **mehrere getrennte Schichten**
    #: geben, und jede kann denselben Verstoß erzeugen – zwei fehlende
    #: Ruhepausen an einem Tag sind zwei Feststellungen, nicht eine. Der
    #: Schlüssel enthält deshalb zusätzlich den Schichtbeginn.
    finding_key = Column(String(64), nullable=True, index=True)
    #: Beginn der betroffenen Schicht in UTC – macht die Zuordnung lesbar.
    shift_start_utc = Column(DateTime, nullable=True)

    # ── Sonn- und Feiertagsarbeit (§§ 9 ff. ArbZG, ab 0.16.0) ────────────
    #
    # Sonntagsarbeit ist nicht verboten, sondern erlaubnispflichtig: § 10 ArbZG
    # zählt Ausnahmen auf, § 11 Abs. 3 verlangt einen **Ersatzruhetag**. Die
    # Anwendung kann nicht entscheiden, ob eine Ausnahme greift – sie kann aber
    # festhalten, worauf sich der Betrieb beruft und ob der Ersatzruhetag
    # gewährt wurde. Alle Felder sind optional; ohne Eintrag verhält sich die
    # Kennzeichnung wie bisher.
    #: Warum wurde an diesem Tag gearbeitet?
    exception_reason = Column(String(500), nullable=True)
    #: Worauf stützt sich die Ausnahme (Paragraf, Tarifvertrag,
    #: Betriebsvereinbarung, Genehmigung)?
    legal_basis = Column(String(255), nullable=True)
    #: Gewährter Ersatzruhetag (§ 11 Abs. 3 ArbZG).
    replacement_rest_date = Column(Date, nullable=True)
    #: Bearbeitungsstand der Ausnahmedokumentation.
    handling_state = Column(String(32), nullable=False, default="open")

    user = relationship("User", foreign_keys=[user_id])
    logs = relationship(
        "ComplianceLog",
        back_populates="flag",
        cascade="all, delete-orphan",
        order_by="ComplianceLog.id",
    )

    @property
    def is_open(self) -> bool:
        """Braucht diese Feststellung noch Aufmerksamkeit?

        Erledigt (``resolved``) heißt: Der Verstoß besteht nicht mehr.
        Bestätigt (``acknowledged``) heißt: gesehen und eingeordnet. Alles
        andere ist offen.
        """
        return self.state in (
            ComplianceState.DETECTED,
            ComplianceState.CHANGED,
            ComplianceState.REOPENED,
        )


class ComplianceAction:
    """Vorgänge an einer Compliance-Feststellung (ab 0.17.0)."""

    DETECTED = "detected"
    CHANGED = "changed"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    ACKNOWLEDGED = "acknowledged"
    EXCEPTION_DOCUMENTED = "exception_documented"
    REST_DAY_SET = "rest_day_set"
    COMPENSATION_ASSIGNED = "compensation_assigned"
    #: Bestandsvermerk bei der Migration – die Feststellung gab es schon,
    #: bevor die Historie eingeführt wurde.
    MIGRATED = "migrated"


class ComplianceLog(Base):
    """Append-only Historie einer Compliance-Feststellung (ab 0.17.0).

    Bis 0.16.0 wurden Ausnahmegrund, Rechtsgrundlage, Ersatzruhetag und
    Bearbeitungsstand **überschrieben**. Wer eine Begründung nachträglich
    änderte, hinterließ keine Spur – bei einer arbeitsrechtlichen Bewertung
    genau das falsche Verhalten.

    Diese Tabelle wird ausschließlich beschrieben. Es gibt in der Anwendung
    keinen Weg, einen Eintrag zu ändern oder zu löschen; die Feststellung
    selbst darf sich ändern, ihre Geschichte nicht.
    """

    __tablename__ = "compliance_logs"
    __table_args__ = (
        Index("ix_compliance_log_flag", "flag_id", "changed_at_utc"),
    )

    id = Column(Integer, primary_key=True, index=True)
    flag_id = Column(
        Integer, ForeignKey("compliance_flags.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    action = Column(String(32), nullable=False)
    changed_at_utc = Column(DateTime, nullable=False, default=datetime.utcnow)
    #: ``NULL`` heißt: kein angemeldeter Mensch (Migration, Regelprüfung).
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_label = Column(String(255), nullable=True)
    reason = Column(String(500), nullable=True)
    source = Column(String(64), nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)

    flag = relationship("ComplianceFlag", back_populates="logs")


class PayrollPeriod(Base):
    """Abrechnungsperiode mit Abschluss- und Sperrzustand."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        UniqueConstraint("period_start", "period_end", name="uq_payroll_period_range"),
    )

    id = Column(Integer, primary_key=True, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    label = Column(String(64), default="")
    status = Column(String(32), nullable=False, default=PeriodStatus.OPEN)
    opened_at = Column(DateTime, default=datetime.utcnow)
    review_started_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(String(500), default="")

    confirmations = relationship(
        "PeriodConfirmation", back_populates="period", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
        return self.status == PeriodStatus.LOCKED

    def covers(self, day: date) -> bool:
        return self.period_start <= day <= self.period_end


class PeriodConfirmation(Base):
    """Bestätigung oder Widerspruch einer Person zu einer Periode."""

    __tablename__ = "period_confirmations"
    __table_args__ = (
        UniqueConstraint("period_id", "user_id", name="uq_period_confirmation"),
    )

    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(
        Integer, ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default=ConfirmationStatus.PENDING)
    submitted_at = Column(DateTime, nullable=True)
    #: Bei Widerspruch Pflicht – sonst wüsste niemand, was zu prüfen ist.
    note = Column(String(500), default="")
    #: Antwort des Arbeitgebers auf einen Widerspruch.
    response = Column(String(500), default="")
    responded_at = Column(DateTime, nullable=True)
    responded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    period = relationship("PayrollPeriod", back_populates="confirmations")
    user = relationship("User", foreign_keys=[user_id])


class DataAccessLog(Base):
    """Wer hat wessen Zeitdaten angesehen oder exportiert?

    Art. 32 DSGVO verlangt nachvollziehbare Zugriffe auf personenbezogene
    Daten. Protokolliert wird der Zugriff auf **fremde** Daten – die eigenen
    einzusehen ist der Normalfall und erzeugt keinen Eintrag.

    Bewusst ohne IP-Adresse: Sie wäre für den Zweck nicht erforderlich und
    würde ihrerseits ein personenbezogenes Datum auf Vorrat speichern.
    """

    __tablename__ = "data_access_log"
    __table_args__ = (
        Index("ix_data_access_subject", "subject_user_id", "accessed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    accessed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_label = Column(String(255), nullable=True)
    subject_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    subject_label = Column(String(255), nullable=True)
    #: ``report``, ``export``, ``entry``, ``subject_export`` …
    scope = Column(String(64), nullable=False)
    detail = Column(String(500), default="")


class VacationStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAW_REQUESTED = "withdraw_requested"
    CANCELLED = "cancelled"


class VacationRequest(Base):
    __tablename__ = "vacation_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(32), default=VacationStatus.PENDING)
    comment = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    use_overtime = Column(Boolean, default=False)
    overtime_minutes = Column(Integer, default=0)
    previous_status = Column(String(32), nullable=True)
    # Halbe Urlaubstage: erster bzw. letzter Tag zaehlt nur zur Haelfte.
    # Bei einem eintaegigen Antrag genuegt eines der beiden Kennzeichen.
    half_day_start = Column(Boolean, default=False, nullable=False)
    half_day_end = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="vacation_requests")


class Holiday(Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("date", "region", name="uq_holidays_date_region"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
    region = Column(String(64), default="DE")
    # 'statutory' = automatisch geladene gesetzliche Feiertage,
    # 'custom' = vom Administrator manuell ergänzt (werden nie überschrieben).
    source = Column(String(20), default="custom")
    created_at = Column(DateTime, default=datetime.utcnow)


class MobileSyncAction(Base):
    __tablename__ = "mobile_sync_actions"
    __table_args__ = (
        UniqueConstraint("user_id", "client_action_id", name="uq_mobile_sync_actions_user_client"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    client_action_id = Column(String(191), nullable=False)
    action = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def default_work_end(start: time, minutes: int) -> time:
    start_dt = datetime.combine(date.today(), start)
    end_dt = start_dt + timedelta(minutes=minutes)
    return end_dt.time()


class BackupJob(Base):
    """A configured, job-based backup definition (§0.9.2)."""

    __tablename__ = "backup_jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True)
    # manual / daily / weekly / monthly (optional cron string for future use)
    schedule = Column(String(20), default="manual")
    cron = Column(String(120), default="")
    # comma separated subset of: database,config,logs
    contents = Column(String(64), default="database,config")
    # local / ftp / smb
    target_type = Column(String(10), default="local")

    local_path = Column(String(500), default="")

    ftp_host = Column(String(255), default="")
    ftp_port = Column(Integer, default=21)
    ftp_username = Column(String(255), default="")
    ftp_password = Column(String(255), default="")
    ftp_path = Column(String(500), default="/")
    ftp_use_tls = Column(Boolean, default=True)

    # SMB uses a single UNC path and a single username field
    # (\\server\share\sub, DOMAIN\user or user@domain).
    smb_path = Column(String(500), default="")
    smb_username = Column(String(255), default="")
    smb_password = Column(String(255), default="")

    retention_count = Column(Integer, default=10)
    retention_days = Column(Integer, default=30)

    last_run_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    runs = relationship(
        "BackupRun", back_populates="job", cascade="all, delete-orphan"
    )

    @property
    def content_list(self) -> list[str]:
        return [part for part in (self.contents or "").split(",") if part]


class BackupRun(Base):
    """A single execution of a backup job (history entry)."""

    __tablename__ = "backup_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("backup_jobs.id"), nullable=True)
    job_name = Column(String(255), default="")
    target_type = Column(String(10), default="local")
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    size_bytes = Column(Integer, default=0)
    status = Column(String(20), default="error")  # success / warning / error
    message = Column(Text, default="")
    filename = Column(String(500), nullable=True)  # local archive path (download)

    job = relationship("BackupJob", back_populates="runs")


class Terminal(Base):
    """A time-recording terminal managed through the generic terminal area (§0.9.8).

    The same row describes any terminal type via a driver key (``type``). Driver
    specific endpoints/options live in ``config_json`` so new terminal types can
    be added without schema changes. The password column holds either a device
    password or an API key. Credentials are persisted (unattended sync) but never
    written to a log file.
    """

    __tablename__ = "terminals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    # Driver key, e.g. "timemoto" (see app.integrations.terminals registry).
    type = Column(String(64), default="timemoto", nullable=False)
    active = Column(Boolean, default=True)

    host = Column(String(255), default="")
    port = Column(Integer, default=80)
    username = Column(String(255), default="")
    password = Column(String(255), default="")  # password or API key
    use_ssl = Column(Boolean, default=False)
    verify_ssl = Column(Boolean, default=True)
    timezone = Column(String(64), default="Europe/Berlin")
    sync_interval_minutes = Column(Integer, default=60)

    # Driver-specific extra configuration (endpoints, limits, …) as JSON text.
    config_json = Column(Text, default="")

    # Live status / history snapshot.
    status = Column(String(20), default="unknown")  # online/warning/offline/error/unknown
    last_connection_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_count = Column(Integer, default=0)
    last_sync_errors = Column(Integer, default=0)
    last_error = Column(String(500), default="")
    last_event_id = Column(Integer, nullable=True)  # incremental sync cursor

    created_at = Column(DateTime, default=datetime.utcnow)

    runs = relationship(
        "TerminalSyncRun", back_populates="terminal", cascade="all, delete-orphan"
    )


class TerminalSyncRun(Base):
    """History of a single terminal synchronisation (§0.9.8)."""

    __tablename__ = "terminal_sync_history"

    id = Column(Integer, primary_key=True, index=True)
    terminal_id = Column(Integer, ForeignKey("terminals.id"), nullable=True)
    terminal_name = Column(String(255), default="")
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="error")  # success / warning / error
    imported_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    message = Column(Text, default="")

    terminal = relationship("Terminal", back_populates="runs")


class RestoreRun(Base):
    """History of restore operations (§9)."""

    __tablename__ = "restore_runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    log_token = Column(String(40), default="")
    username = Column(String(255), default="")
    backup_file = Column(String(500), default="")
    backup_version = Column(String(40), default="")
    database_type = Column(String(20), default="")
    schema_version = Column(Integer, nullable=True)
    safety_backup = Column(String(500), nullable=True)
    migrations_applied = Column(String(255), default="")
    status = Column(String(20), default="error")  # success / warning / error
    message = Column(Text, default="")

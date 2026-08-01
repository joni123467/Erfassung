from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from . import models


class CompanyBase(BaseModel):
    name: str
    description: str = ""
    #: Der eigene Betrieb statt eines Kunden – ältere Clients, die das Feld
    #: nicht kennen, legen weiterhin Kunden an.
    is_internal: bool = False


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(CompanyBase):
    pass


class Company(CompanyBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class CompanyLocationBase(BaseModel):
    name: str
    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = ""
    is_primary: bool = False
    is_active: bool = True


class CompanyLocationCreate(CompanyLocationBase):
    pass


class CompanyLocationUpdate(CompanyLocationBase):
    pass


class CompanyLocation(CompanyLocationBase):
    id: int
    company_id: int
    model_config = ConfigDict(from_attributes=True)


class GroupBase(BaseModel):
    """Organisationsgruppe – ohne Berechtigungen (RBAC).

    Rechte-Felder älterer Clients werden von Pydantic ignoriert, damit
    bestehende API-Aufrufe weiterhin funktionieren.
    """

    name: str
    description: str = ""


class GroupCreate(GroupBase):
    pass


class Group(GroupBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RolePermissionEntry(BaseModel):
    permission_key: str
    scope: str = "all"
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    name: str
    description: str = ""
    is_active: bool = True


class RoleCreate(RoleBase):
    #: Berechtigungen als ``{key: scope}``.
    permissions: dict[str, str] = {}


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    permissions: Optional[dict[str, str]] = None


class Role(RoleBase):
    id: int
    is_system: bool = False
    permissions: List[RolePermissionEntry] = []
    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    standard_weekly_hours: float = 40.0
    group_id: Optional[int] = None
    time_account_enabled: bool = False
    overtime_vacation_enabled: bool = False
    annual_vacation_days: int = 30
    vacation_carryover_enabled: bool = False
    vacation_carryover_days: int = 0
    rfid_tag: Optional[str] = None
    monthly_overtime_limit_minutes: Optional[int] = None
    auto_break_deduction: bool = True
    remote_flag_enabled: bool = False
    #: Mehrfachzugehörigkeit (RBAC). ``group_id`` bleibt aus Kompatibilität
    #: erhalten und wird beim Anlegen als einzelne Mitgliedschaft übernommen.
    group_ids: Optional[List[int]] = None
    role_ids: Optional[List[int]] = None

    @field_validator("standard_weekly_hours")
    @classmethod
    def validate_weekly_hours(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Wochenarbeitszeit darf nicht negativ sein")
        return value

    @field_validator("annual_vacation_days", "vacation_carryover_days")
    @classmethod
    def validate_vacation_days(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Urlaubstage dürfen nicht negativ sein")
        return value

    @field_validator("monthly_overtime_limit_minutes")
    @classmethod
    def validate_overtime_limit(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if value < 0:
            raise ValueError("Überstundenlimit darf nicht negativ sein")
        return value


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError("Kennwort muss mindestens 10 Zeichen lang sein")
        return value


class UserUpdate(UserBase):
    password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value:
            return None
        if len(value) < 10:
            raise ValueError("Kennwort muss mindestens 10 Zeichen lang sein")
        return value


class User(UserBase):
    id: int
    groups: List[Group] = []
    roles: List[Role] = []
    model_config = ConfigDict(from_attributes=True)
    standard_daily_minutes: int = 0


class TimeEntryBase(BaseModel):
    user_id: int
    company_id: Optional[int] = None
    work_date: date
    start_time: time
    end_time: time
    break_minutes: int = 0
    break_started_at: Optional[time] = None
    is_open: bool = False
    notes: str = ""
    status: str = models.TimeEntryStatus.APPROVED
    is_manual: bool = False
    is_remote: bool = False
    #: Gewählter Standort; ``None`` heißt „kein Standort" und lässt allein
    #: ``is_remote`` entscheiden – wie vor 0.13.0.
    location_id: Optional[int] = None
    source: Optional[str] = None
    external_id: Optional[str] = None
    #: Vollständige Zeitstempel in UTC samt ursprünglicher Zeitzone. Optional,
    #: damit Bestandsaufrufe und Terminalimporte unverändert funktionieren.
    started_at_utc: Optional[datetime] = None
    ended_at_utc: Optional[datetime] = None
    tz_name: Optional[str] = None


class TimeEntryCreate(TimeEntryBase):
    """Vollständiges Eingabeschema – **nur für vertrauenswürdige Aufrufer**.

    Es erlaubt jedes Feld, auch ``status``, ``source``, ``external_id`` und die
    UTC-Stempel. Das ist für Administration, Terminalimport und interne
    Aufrufe richtig, für die Selbstbedienung aber viel zu weit: Ein
    Beschäftigter könnte sich damit eine freigegebene Buchung anlegen oder eine
    fremde Terminalquelle vortäuschen.

    Für die Selbstbedienung gibt es deshalb :class:`SelfServiceTimeEntryCreate`.
    """


class AdministrativeTimeEntryCreate(BaseModel):
    """Was eine Verwaltungskraft für **andere** setzen darf (ab 0.17.0).

    ``Time.Edit`` ist ein Korrekturrecht, kein Importrecht. Bis 0.16.0 lief die
    Verwaltung über dasselbe vollständige Schema wie der Terminalimport – wer
    fremde Buchungen korrigieren durfte, konnte damit auch ``source``,
    ``external_id`` und die UTC-Originalstempel frei setzen. Genau diese drei
    Angaben belegen aber, **woher** eine Buchung stammt: Eine von Hand
    angelegte Buchung ließe sich als Terminalstempelung ausgeben, und die
    Herkunft ist bei einer Prüfung das erste, worauf man schaut.

    **Nicht enthalten und damit nicht setzbar:** ``source``, ``external_id``,
    ``started_at_utc``, ``ended_at_utc``, ``tz_name``. Der Server setzt die
    Quelle auf ``manual`` und rechnet die UTC-Stempel aus den eingegebenen
    Ortszeiten und der zentralen Betriebszeitzone.

    Weiterhin enthalten – und das ist Absicht: ``status`` und ``is_manual``.
    Freigeben und einen Nachtrag kennzeichnen gehört zur Korrektur.

    Der Terminal- und Importpfad benutzt unverändert :class:`TimeEntryCreate`;
    er läuft nicht über diese HTTP-Schnittstelle.
    """

    user_id: int
    work_date: date
    start_time: time
    end_time: time
    break_minutes: int = 0
    break_started_at: Optional[time] = None
    company_id: Optional[int] = None
    location_id: Optional[int] = None
    is_remote: bool = False
    is_open: bool = False
    is_manual: bool = False
    notes: str = ""
    status: str = models.TimeEntryStatus.APPROVED

    @field_validator("break_minutes")
    @classmethod
    def validate_break(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Pausenminuten dürfen nicht negativ sein")
        if value > 24 * 60:
            raise ValueError("Pausenminuten sind unplausibel")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {
            models.TimeEntryStatus.APPROVED,
            models.TimeEntryStatus.PENDING,
            models.TimeEntryStatus.REJECTED,
        }
        if value not in allowed:
            raise ValueError("Unbekannter Status")
        return value

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str) -> str:
        return (value or "")[:255]


class SelfServiceTimeEntryCreate(BaseModel):
    """Was ein Beschäftigter für **sich selbst** nachtragen darf (ab 0.16.0).

    Bewusst ein eigenes, enges Schema statt eines beschnittenen
    :class:`TimeEntryCreate`. Ein Feld, das hier nicht steht, kann auch nicht
    versehentlich durchgereicht werden – ein Ausschluss per Positivliste hält
    länger als einer per Negativliste.

    **Nicht enthalten und damit nicht setzbar:** ``status``, ``is_manual``,
    ``is_open``, ``source``, ``external_id``, ``started_at_utc``,
    ``ended_at_utc``, ``tz_name``, ``break_rule`` sowie sämtliche Storno- und
    Revisionsfelder. Diese Werte setzt ausschließlich der Server.
    """

    work_date: date
    start_time: time
    end_time: time
    break_minutes: int = 0
    company_id: Optional[int] = None
    location_id: Optional[int] = None
    is_remote: bool = False
    notes: str = ""

    @field_validator("break_minutes")
    @classmethod
    def validate_break(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Pausenminuten dürfen nicht negativ sein")
        if value > 24 * 60:
            raise ValueError("Pausenminuten sind unplausibel")
        return value

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str) -> str:
        return (value or "")[:255]


class TimeEntry(TimeEntryBase):
    id: int
    company: Optional[Company]
    worked_minutes: int
    overtime_minutes: int
    total_break_minutes: int
    required_break_minutes: int
    model_config = ConfigDict(from_attributes=True)


class VacationRequestBase(BaseModel):
    user_id: int
    start_date: date
    end_date: date
    comment: str = ""
    use_overtime: bool = False
    #: Erster bzw. letzter Tag zählt nur halb. Bei einem eintägigen Antrag
    #: genügt eines der beiden Kennzeichen.
    half_day_start: bool = False
    half_day_end: bool = False


class VacationRequestCreate(VacationRequestBase):
    overtime_minutes: int = 0


class VacationRequest(VacationRequestBase):
    id: int
    status: str
    overtime_minutes: int
    previous_status: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class HolidayBase(BaseModel):
    name: str
    date: date
    region: str = "DE"
    source: str = "custom"


class HolidayCreate(HolidayBase):
    pass


class Holiday(HolidayBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class VacationSummary(BaseModel):
    total_days: float
    remaining_days: float
    used_days: float
    planned_days: float
    carryover_days: float = 0.0


class DashboardMetrics(BaseModel):
    total_work_minutes: int
    vacation_minutes: int
    #: Gutschrift für gesetzliche Feiertage an Werktagen (seit 0.14.2).
    #: Vorgabe 0, damit ältere Aufrufer und Offline-Snapshots gültig bleiben.
    holiday_minutes: int = 0
    total_overtime_minutes: int
    total_undertime_minutes: int
    target_minutes: int
    overtime_taken_minutes: int
    pending_vacations: int
    upcoming_holidays: List[Holiday]
    vacation_summary: VacationSummary
    overtime_limit_minutes: int = 0
    overtime_limit_remaining_minutes: int = 0
    overtime_limit_exceeded: bool = False
    overtime_limit_excess_minutes: int = 0

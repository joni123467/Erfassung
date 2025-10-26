from __future__ import annotations

from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from . import models


class CompanyBase(BaseModel):
    name: str
    description: str = ""


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(CompanyBase):
    pass


class Company(CompanyBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class GroupBase(BaseModel):
    name: str
    is_admin: bool = False
    can_manage_users: bool = False
    can_manage_vacations: bool = False
    can_approve_manual_entries: bool = False
    can_create_companies: bool = False
    can_view_time_reports: bool = False
    can_edit_time_entries: bool = False


class GroupCreate(GroupBase):
    pass


class Group(GroupBase):
    id: int
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
    pin_code: str

    @field_validator("pin_code")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if len(value) != 4 or not value.isdigit():
            raise ValueError("PIN muss aus genau 4 Ziffern bestehen")
        return value


class UserUpdate(UserBase):
    pin_code: str

    @field_validator("pin_code")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if len(value) != 4 or not value.isdigit():
            raise ValueError("PIN muss aus genau 4 Ziffern bestehen")
        return value


class User(UserBase):
    id: int
    pin_code: str
    group: Optional[Group]
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


class TimeEntryCreate(TimeEntryBase):
    pass


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

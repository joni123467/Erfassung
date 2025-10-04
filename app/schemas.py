from __future__ import annotations

from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, EmailStr, ConfigDict


class GroupBase(BaseModel):
    name: str
    is_admin: bool = False


class GroupCreate(GroupBase):
    pass


class Group(GroupBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    standard_daily_minutes: int = 480
    group_id: Optional[int] = None


class UserCreate(UserBase):
    pass


class User(UserBase):
    id: int
    group: Optional[Group]
    model_config = ConfigDict(from_attributes=True)


class TimeEntryBase(BaseModel):
    user_id: int
    work_date: date
    start_time: time
    end_time: time
    break_minutes: int = 0
    notes: str = ""


class TimeEntryCreate(TimeEntryBase):
    pass


class TimeEntry(TimeEntryBase):
    id: int
    worked_minutes: int
    overtime_minutes: int
    model_config = ConfigDict(from_attributes=True)


class VacationRequestBase(BaseModel):
    user_id: int
    start_date: date
    end_date: date
    comment: str = ""


class VacationRequestCreate(VacationRequestBase):
    pass


class VacationRequest(VacationRequestBase):
    id: int
    status: str
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


class DashboardMetrics(BaseModel):
    total_work_minutes: int
    total_overtime_minutes: int
    pending_vacations: int
    upcoming_holidays: List[Holiday]

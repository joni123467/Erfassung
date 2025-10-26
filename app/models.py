from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import relationship

from .database import Base




class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, default="")

    time_entries = relationship("TimeEntry", back_populates="company")


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    is_admin = Column(Boolean, default=False)
    can_manage_users = Column(Boolean, default=False)
    can_manage_vacations = Column(Boolean, default=False)
    can_approve_manual_entries = Column(Boolean, default=False)
    can_create_companies = Column(Boolean, default=False)

    users = relationship("User", back_populates="group")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    standard_daily_minutes = Column(Integer, default=480)
    standard_weekly_hours = Column(Float, default=40.0)
    pin_code = Column(String(4), unique=True, nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"))
    time_account_enabled = Column(Boolean, default=False)
    overtime_vacation_enabled = Column(Boolean, default=False)
    annual_vacation_days = Column(Integer, default=30)
    vacation_carryover_enabled = Column(Boolean, default=False)
    vacation_carryover_days = Column(Integer, default=0)
    rfid_tag = Column(String, unique=True, nullable=True)

    group = relationship("Group", back_populates="users")
    time_entries = relationship("TimeEntry", back_populates="user", cascade="all, delete-orphan")
    vacation_requests = relationship(
        "VacationRequest", back_populates="user", cascade="all, delete-orphan"
    )

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


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    work_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    break_minutes = Column(Integer, default=0)
    break_started_at = Column(Time, nullable=True)
    is_open = Column(Boolean, default=False)
    notes = Column(String, default="")
    status = Column(String, default=TimeEntryStatus.APPROVED)
    is_manual = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="time_entries")
    company = relationship("Company", back_populates="time_entries")

    @property
    def required_break_minutes(self) -> int:
        start_dt = datetime.combine(self.work_date, self.start_time)
        if self.is_open:
            now_dt = datetime.now()
            end_dt = datetime.combine(now_dt.date(), now_dt.time())
        else:
            end_dt = datetime.combine(self.work_date, self.end_time)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        duration = int((end_dt - start_dt).total_seconds() // 60)
        if duration < 6 * 60:
            return 0
        if duration < 9 * 60:
            return 30
        return 45

    @property
    def worked_minutes(self) -> int:
        start_dt = datetime.combine(self.work_date, self.start_time)
        if self.is_open:
            now_dt = datetime.now()
            end_dt = datetime.combine(now_dt.date(), now_dt.time())
        else:
            end_dt = datetime.combine(self.work_date, self.end_time)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        raw_minutes = int((end_dt - start_dt).total_seconds() // 60)
        applied_break = max(self.total_break_minutes, self.required_break_minutes)
        minutes = raw_minutes - applied_break
        return max(minutes, 0)

    @property
    def overtime_minutes(self) -> int:
        if self.user:
            target = self.user.daily_target_minutes
            if target:
                return int(self.worked_minutes - target)
        return 0

    @property
    def total_break_minutes(self) -> int:
        minutes = self.break_minutes
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


class VacationStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VacationRequest(Base):
    __tablename__ = "vacation_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String, default=VacationStatus.PENDING)
    comment = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    use_overtime = Column(Boolean, default=False)
    overtime_minutes = Column(Integer, default=0)

    user = relationship("User", back_populates="vacation_requests")


class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    date = Column(Date, unique=True, nullable=False)
    region = Column(String, default="DE")
    created_at = Column(DateTime, default=datetime.utcnow)


def default_work_end(start: time, minutes: int) -> time:
    start_dt = datetime.combine(date.today(), start)
    end_dt = start_dt + timedelta(minutes=minutes)
    return end_dt.time()

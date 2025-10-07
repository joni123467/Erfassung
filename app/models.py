from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, Time
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

    users = relationship("User", back_populates="group")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    standard_daily_minutes = Column(Integer, default=480)
    pin_code = Column(String(4), unique=True, nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"))

    group = relationship("Group", back_populates="users")
    time_entries = relationship("TimeEntry", back_populates="user", cascade="all, delete-orphan")
    vacation_requests = relationship(
        "VacationRequest", back_populates="user", cascade="all, delete-orphan"
    )


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    work_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    break_minutes = Column(Integer, default=0)
    notes = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="time_entries")
    company = relationship("Company", back_populates="time_entries")

    @property
    def worked_minutes(self) -> int:
        start_dt = datetime.combine(self.work_date, self.start_time)
        end_dt = datetime.combine(self.work_date, self.end_time)
        delta = end_dt - start_dt
        minutes = int(delta.total_seconds() // 60) - self.break_minutes
        return max(minutes, 0)

    @property
    def overtime_minutes(self) -> int:
        if self.user and self.user.standard_daily_minutes:
            return self.worked_minutes - self.user.standard_daily_minutes
        return 0


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

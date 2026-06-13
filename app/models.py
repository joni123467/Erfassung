from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from .database import Base




class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, default="")

    time_entries = relationship("TimeEntry", back_populates="company")


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    is_admin = Column(Boolean, default=False)
    can_manage_users = Column(Boolean, default=False)
    can_manage_vacations = Column(Boolean, default=False)
    can_approve_manual_entries = Column(Boolean, default=False)
    can_create_companies = Column(Boolean, default=False)
    can_view_time_reports = Column(Boolean, default=False)
    can_edit_time_entries = Column(Boolean, default=False)

    users = relationship("User", back_populates="group")


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
    group_id = Column(Integer, ForeignKey("groups.id"))
    time_account_enabled = Column(Boolean, default=False)
    overtime_vacation_enabled = Column(Boolean, default=False)
    annual_vacation_days = Column(Integer, default=30)
    vacation_carryover_enabled = Column(Boolean, default=False)
    vacation_carryover_days = Column(Integer, default=0)
    rfid_tag = Column(String(255), unique=True, nullable=True)
    monthly_overtime_limit_minutes = Column(Integer, nullable=True)
    auto_break_deduction = Column(Boolean, default=True)

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
    source = Column(String(64), nullable=True)
    external_id = Column(String(191), nullable=True)
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
    def auto_break_enabled(self) -> bool:
        """Whether statutory (ArbZG) breaks are deducted automatically."""
        if self.user is None:
            return True
        value = getattr(self.user, "auto_break_deduction", True)
        return True if value is None else bool(value)

    @property
    def applied_break_minutes(self) -> int:
        """Break minutes actually deducted from the working time."""
        if self.auto_break_enabled:
            return max(self.total_break_minutes, self.required_break_minutes)
        return self.total_break_minutes

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
        minutes = raw_minutes - self.applied_break_minutes
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

    @property
    def company_display_name(self) -> str:
        if self.company:
            return self.company.name
        if self.deleted_company_name:
            return f"Gelöscht ({self.deleted_company_name})"
        return "Allgemeine Arbeitszeit"


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


class RestoreRun(Base):
    """History of restore operations (§9)."""

    __tablename__ = "restore_runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    username = Column(String(255), default="")
    backup_file = Column(String(500), default="")
    backup_version = Column(String(40), default="")
    database_type = Column(String(20), default="")
    schema_version = Column(Integer, nullable=True)
    safety_backup = Column(String(500), nullable=True)
    migrations_applied = Column(String(255), default="")
    status = Column(String(20), default="error")  # success / warning / error
    message = Column(Text, default="")

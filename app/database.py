import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./erfassung.db")

_url = make_url(SQLALCHEMY_DATABASE_URL)
DB_BACKEND = _url.get_backend_name()  # e.g. "sqlite", "mysql"
IS_SQLITE = DB_BACKEND == "sqlite"

# SQLite stores the database in a file that lives in the data volume; make sure
# its parent directory exists before SQLAlchemy opens it.
if SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
    raw_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1)
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

if IS_SQLITE:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    # MySQL 8+ / MariaDB via PyMySQL. pool_pre_ping recycles stale connections
    # (important behind connection-dropping proxies / long idle periods).
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=int(os.environ.get("DB_POOL_RECYCLE", "1800")),
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

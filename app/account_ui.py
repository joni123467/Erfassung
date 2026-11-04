"""Kontobezogene Darstellung und portable Ergänzung der Startansicht."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import db_schema


class AccountPreferences(BaseModel):
    """Nur eigene Darstellung; eine Zielbenutzer-ID ist nicht zulässig."""

    model_config = ConfigDict(extra="forbid")
    overview_preference: Literal["day", "week"]
    # Optionaler Abgleich mit der PWA-Zuordnung, niemals ein frei wählbares Ziel.
    user_id: int | None = Field(default=None, gt=0, strict=True)


def overview_preference(user: object) -> str:
    value = getattr(user, "overview_preference", None)
    return value if value in {"day", "week"} else "day"


def ensure_overview_preference(engine: Engine) -> None:
    """Bestandskonten behalten die Tagesansicht; gespeicherte Wochen bleiben."""

    if not db_schema.has_table(engine, "users"):
        return
    db_schema.add_column(
        engine, "users", "overview_preference", "VARCHAR(8) NOT NULL",
        default="'day'", backfill_null_to="'day'",
    )
    # Auch eine schon vorhandene, noch NULL-fähige Spalte aus einem Import
    # reparieren. add_column allein überspringt bereits existierende Spalten.
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE users SET overview_preference = 'day' "
            "WHERE overview_preference IS NULL"
        ))

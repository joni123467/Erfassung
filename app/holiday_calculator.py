from __future__ import annotations

from typing import Iterable

import holidays

from . import schemas


def calculate_german_holidays(year: int, state: str = "BY") -> Iterable[schemas.HolidayCreate]:
    """Return German public holidays for a given year and federal state."""
    holiday_set = holidays.Germany(years=year, subdiv=state)
    for holiday_date, name in sorted(holiday_set.items()):
        yield schemas.HolidayCreate(name=name, date=holiday_date, region=state)


def ensure_holidays(db, year: int, state: str = "BY"):
    from . import crud

    holiday_models = list(calculate_german_holidays(year, state))
    return crud.upsert_holidays(db, holiday_models)

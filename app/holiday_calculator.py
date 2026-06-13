from __future__ import annotations

from typing import Iterable

import holidays

from . import crud, schemas


GERMAN_STATES = {
    "DE": "Deutschland (gesamt)",
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}


def calculate_german_holidays(year: int, state: str = "BY") -> Iterable[schemas.HolidayCreate]:
    """Return German public holidays for a given year and federal state."""
    state = (state or "DE").upper()
    subdiv = state if state != "DE" else None
    holiday_set = holidays.Germany(years=year, subdiv=subdiv, language="de")
    for holiday_date, name in sorted(holiday_set.items()):
        yield schemas.HolidayCreate(
            name=name, date=holiday_date, region=state or "DE", source="statutory"
        )


def ensure_holidays(db, year: int, state: str = "BY"):
    """Load and persist statutory holidays for a year/state.

    Custom (administrator-defined) holidays are preserved; only statutory
    entries are refreshed.
    """
    normalized_state = (state or "DE").upper()
    holiday_models = list(calculate_german_holidays(year, normalized_state))
    region = normalized_state or "DE"
    crud.apply_statutory_holidays(db, region, year, holiday_models)
    return crud.get_holidays_for_year(db, year, region)

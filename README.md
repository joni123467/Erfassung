# Erfassung

"Erfassung" ist eine moderne Zeiterfassungssoftware mit Überstundenermittlung, Urlaubsplanung, Feiertagssynchronisation und Excel-Export. Die Anwendung ist als Web-App mit FastAPI umgesetzt und kann später um RFID-Terminals erweitert werden.

## Features

- Benutzer- und Gruppenverwaltung (inkl. Admin-Gruppen für Anpassungen)
- Erfassung von Arbeitszeiten mit automatischer Überstundenberechnung
- Verwaltung von Urlaubsanträgen
- Feiertagssynchronisation für deutsche Bundesländer (via `python-holidays`)
- Export von Arbeitszeiten als Excel-Datei (`.xlsx`)
- Responsives Dashboard mit den wichtigsten Kennzahlen

## Installation

### Voraussetzungen

- Python 3.10+
- [Poetry](https://python-poetry.org/) oder `pip`

### Installation mit pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Installation mit Poetry

```bash
poetry install
```

## Entwicklung starten

```bash
uvicorn app.main:app --reload
```

Die Anwendung ist dann unter <http://127.0.0.1:8000> erreichbar.

## Feiertage synchronisieren

Um Feiertage für ein Bundesland zu laden, kann folgender API-Call abgesetzt werden:

```bash
curl -X POST "http://127.0.0.1:8000/api/holidays/sync?year=2024&state=BY"
```

## RFID-Integration (Ausblick)

Die Architektur ist so aufgebaut, dass später eine RFID-Erweiterung realisiert werden kann. Die Zeiterfassung kann über zusätzliche Endpoints oder Hintergrundprozesse ergänzt werden, die Stempelzeiten verarbeiten.

## Tests

Zurzeit sind keine automatisierten Tests hinterlegt. Es wird empfohlen, für produktive Szenarien API- und Integrationstests zu ergänzen.

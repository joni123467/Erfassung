# Erfassung

"Erfassung" ist eine moderne Zeiterfassungssoftware mit Überstundenermittlung, Urlaubsplanung, Feiertagssynchronisation und Excel-Export. Die Anwendung ist als Web-App mit FastAPI umgesetzt und kann später um RFID-Terminals erweitert werden.

## Features

- Anmeldung über einen persönlichen 4-stelligen PIN.
- Umfangreiche Administrationsoberfläche für Benutzer- und Gruppenverwaltung inklusive PIN-, Rollen- und Arbeitszeitkontingenten.
- Firmenverwaltung, damit Arbeitszeiten eindeutig Projekten oder Unternehmen zugeordnet werden können.
- Direktes Stempeln vom Dashboard mit Firmenauswahl und Kommentarfeld für jede Buchung.
- Administratoren können bestehende Zeitbuchungen filtern, anpassen oder löschen.
- Verwaltung von Urlaubsanträgen und Feiertagssynchronisation für deutsche Bundesländer (via `python-holidays`).
- Export von Arbeitszeiten als Excel-Datei (`.xlsx`).

## Installation

### Automatische Installation (wget & install.sh)

Das Projekt enthält ein Installationsskript, das Systempakete prüft, Abhängigkeiten installiert und eine virtuelle Umgebung vorbereitet. Es kann per `wget` bezogen werden und funktioniert ohne lokal vorhandenes Git.

```bash
wget https://<IHRE-DOMÄNE>/install.sh -O install.sh
bash install.sh --source-url https://<IHRE-DOMÄNE>/erfassung.tar.gz
```

Ersetzen Sie die Platzhalter-URLs durch den Speicherort Ihres Installationsskripts bzw. Archivs (z. B. ein GitHub Release). Wird das Skript erneut ausgeführt, erkennt es bestehende Installationen, entfernt sie und richtet die Anwendung frisch ein. So bleiben Aktualisierungen reproduzierbar.

Das Skript kann zusätzlich über `--install-dir` ein Zielverzeichnis angeben. Nach erfolgreicher Installation finden Sie die Anwendung im gewählten Ordner; Aktivierung und Start erfolgen wie gewohnt mit `source .venv/bin/activate` und `uvicorn app.main:app --reload`.

### Manuelle Installation

Wenn Sie das Installationsskript nicht verwenden möchten, kann die Installation weiterhin klassisch erfolgen:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

oder

```bash
poetry install
```

## Entwicklung starten

```bash
uvicorn app.main:app --reload
```

Die Anwendung ist dann unter <http://127.0.0.1:8000> erreichbar.

## Anmeldung und Rollen

Beim ersten Start wird automatisch eine Administratorgruppe sowie ein Benutzer `admin` angelegt. Dieser kann sich mit dem PIN `0000` anmelden und anschließend weitere Nutzer oder Gruppen in der Administrationsansicht verwalten.

## Feiertage synchronisieren

Um Feiertage für ein Bundesland zu laden, kann folgender API-Call abgesetzt werden:

```bash
curl -X POST "http://127.0.0.1:8000/api/holidays/sync?year=2024&state=BY"
```

## RFID-Integration (Ausblick)

Die Architektur ist so aufgebaut, dass später eine RFID-Erweiterung realisiert werden kann. Die Zeiterfassung kann über zusätzliche Endpoints oder Hintergrundprozesse ergänzt werden, die Stempelzeiten verarbeiten.

## Tests

Zurzeit sind keine automatisierten Tests hinterlegt. Es wird empfohlen, für produktive Szenarien API- und Integrationstests zu ergänzen.

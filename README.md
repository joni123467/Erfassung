# Erfassung

"Erfassung" ist eine moderne Zeiterfassungssoftware mit Überstundenermittlung, Urlaubsplanung, Feiertagssynchronisation und Excel-Export. Die Anwendung ist als Web-App mit FastAPI umgesetzt und kann später um RFID-Terminals erweitert werden.

## Features

- Anmeldung über einen persönlichen 4-stelligen PIN.
- Umfangreiche Administrationsoberfläche für Benutzer- und Gruppenverwaltung inklusive PIN-, Rollen- und Arbeitszeitkontingenten.
- Firmenverwaltung, damit Arbeitszeiten eindeutig Projekten oder Unternehmen zugeordnet werden können.
- Direktes Stempeln vom Dashboard mit Firmenauswahl und Kommentarfeld für jede Buchung.
- Komfortable Echtzeit-Stempelung im TopZeit-Stil: Arbeitsbeginn/-ende, Auftragsstart auf eine Firma sowie Pausenstart/-ende auf einen Klick.
- Administratoren können bestehende Zeitbuchungen filtern, anpassen oder löschen.
- Verwaltung von Urlaubsanträgen und Feiertagssynchronisation für deutsche Bundesländer (via `python-holidays`).
- Export von Arbeitszeiten als Excel-Datei (`.xlsx`).

## Installation

### Automatische Installation (wget & install.sh)

Das Projekt enthält ein Installationsskript, das Systempakete prüft, Abhängigkeiten installiert und eine virtuelle Umgebung vorbereitet. Es kann per `wget` bezogen werden und funktioniert ohne lokal vorhandenes Git.

```bash
wget https://raw.githubusercontent.com/joni123467/Erfassung/version-0.0.4/install.sh -O install.sh
bash install.sh --source-url https://github.com/joni123467/Erfassung/archive/refs/heads/version-0.0.4.tar.gz
```

Das Installationsskript und der Quellcode liegen im öffentlichen Repository <https://github.com/joni123467/Erfassung>. Wird das Skript erneut ausgeführt, erkennt es bestehende Installationen im Zielverzeichnis (`/opt/erfassung` als Standard), entfernt sie und richtet die Anwendung frisch ein. So bleiben Aktualisierungen reproduzierbar.

Alle Python-Abhängigkeiten werden direkt als vorgefertigte Wheels über `pip` eingespielt – zusätzliche Rust- oder Compiler-Werkzeuge sind nicht länger erforderlich. Auf Wunsch kann über `--install-dir` ein alternatives Zielverzeichnis angegeben werden. Nach erfolgreicher Installation finden Sie die Anwendung unter dem gewählten Pfad; Aktivierung und Start erfolgen wie gewohnt mit `source .venv/bin/activate` und `uvicorn app.main:app --reload`. Systeme mit `systemd` erhalten automatisch den Dienst `erfassung.service`, der die Anwendung als Hintergrundprozess auf Port `8000` betreibt.

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

## Aktualisierung

Für installierte Instanzen steht mit `update.sh` ein zweistufiger Updater zur Verfügung. Beim Start lädt das Skript automatisch die aktuellste Version des Repository-Archivs, führt daraus die jüngste Update-Routine aus und übernimmt anschließend den Quellcode in das Installationsverzeichnis. Dabei bleiben lokale Datenordner (`data`, `logs`), Konfigurationsdateien (`config`, `config.yml`, `config.yaml`, `.env`) sowie vorhandene virtuelle Umgebungen (`.venv`) erhalten. Die SQLite-Datenbank (`erfassung.db`) wird beibehalten; nach dem Kopiervorgang werden Tabellen erzeugt und Migrationen angewendet, sodass neue Felder ohne manuelle Eingriffe zur Verfügung stehen. Abschließend startet das Skript – sofern vorhanden – den Dienst `erfassung.service` neu.

Der Updater kann – ähnlich wie die Installation – ohne lokale Git-Kopie genutzt werden:

```bash
wget https://raw.githubusercontent.com/joni123467/Erfassung/version-0.0.4/update.sh -O update.sh
bash update.sh --app-dir /opt/erfassung --repo-url https://github.com/joni123467/Erfassung --ref version-0.0.4
```

Über `--repo-url` lässt sich bei Bedarf ein eigener Fork bzw. eine alternative Quelle angeben, `--ref` steuert den Branch oder Tag. Vorhandene Abhängigkeiten werden nach dem Kopiervorgang automatisch aktualisiert.

### Update über die Administrationsoberfläche

Administratoren finden im Bereich **Administration → System & Updates** eine Oberfläche zum Auslösen von Aktualisierungen. Die Seite listet verfügbare Branches (einschließlich `version-x.x.x`), erlaubt eigene Referenzen und zeigt das Protokoll aus `logs/update.log` an. Während der Vorgang läuft, bleibt die Seite geöffnet; nach erfolgreichem Abschluss wird die Anwendung neu gestartet und der Benutzer landet automatisch wieder auf dem Dashboard.

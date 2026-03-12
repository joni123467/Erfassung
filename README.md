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
uvicorn app.main:app --host 0.0.0.0 --reload
```

Die Anwendung lauscht damit auf allen verfügbaren Netzwerk-Interfaces und ist im lokalen Netz unter der jeweiligen IP-Adresse des Hosts erreichbar (z. B. <http://127.0.0.1:8000> auf dem gleichen Rechner).

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

## Offline-First / PWA

Die mobile Oberfläche (`/mobile`) arbeitet jetzt mit einer Offline-First-Sync-Architektur:

- **PWA-Installierbarkeit** über Manifest (`/static/manifest.webmanifest`) und Service Worker (`/static/sw.js`).
- **App-Shell-Caching** für mobile Kernansichten und statische Assets.
- **IndexedDB-Outbox** für Offline-Stempelungen und Urlaubsaktionen (`static/mobile.js`).
- **Robuste Synchronisation** über `POST /api/mobile/sync` mit idempotenten `operation_id`s.
- **Bootstrap-Endpunkt** `GET /api/mobile/bootstrap` für lokale Stammdaten, Zeitbuchungen und Offline-Auth-Verifier.
- **Konfliktbehandlung**: serverseitig werden widersprüchliche Offline-Operationen als `conflict` markiert und nicht still überschrieben.

### Offline-Authentifizierung (bekannte Benutzer)

Für bereits online bekannte Benutzer liefert der Bootstrap-Endpunkt einen lokalen PIN-Verifier (PBKDF2-SHA256, Salt + Iterationen). Die PIN wird **nicht im Klartext** lokal gespeichert.

> Sicherheitsgrenze: Da Web-PWAs keinen sicheren Hardware-Keystore wie native Apps garantieren, ist dies eine bestmögliche Web-Variante, aber kein vollwertiger Ersatz für natives Secure Enclave Handling.

### Sync-Ablauf

1. Offline erzeugte Aktionen landen in der lokalen Outbox.
2. Bei App-Start, Reconnect oder manuellem „Jetzt synchronisieren“ wird die Outbox gepusht.
3. Der Server verarbeitet idempotent über `operation_id`.
4. Ergebnisstatus pro Operation: `synced`, `conflict`, `failed`.
5. Die UI zeigt Pending-Count, Sync-Lauf und Fehlerzustände.

### iPhone / Safari QA-Checkliste

- [ ] App zu Home-Bildschirm hinzufügen.
- [ ] App im Flugmodus starten.
- [ ] Arbeitsbeginn/-ende sowie Pause offline ausführen.
- [ ] App schließen, neu öffnen, lokale Daten prüfen.
- [ ] Online gehen und Sync auslösen.
- [ ] Konfliktfall prüfen (z. B. parallel serverseitig beendet).
- [ ] Sync-Retry bei kurzzeitigem Serverausfall prüfen.

### Tests

Neue automatisierte Tests liegen unter `tests/test_mobile_sync.py` und decken u. a. ab:

- lokale Sync-/Konfliktlogik,
- idempotente Wiederholung identischer Sync-Requests.

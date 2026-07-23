# Erfassung

Erfassung ist eine FastAPI-basierte Zeiterfassungsanwendung (Web-App) mit Benutzer-/Gruppenverwaltung, Arbeitszeitbuchungen, Urlaubsverwaltung, Feiertagssynchronisation und Exportfunktionen.

**Version:** `0.9.16`

> Seit 0.9.16: **Bearbeiten trotz bestehender Überschneidung** – eine Buchung
> lässt sich jetzt auch dann korrigieren (z. B. verkürzen), wenn eine bereits
> vorhandene Überlappung (etwa eine noch laufende Buchung) den Zeitraum
> berührt; nur *neu* entstehende Konflikte werden abgelehnt.

> Seit 0.9.15: **Nachtrag zwischen bestehenden Buchungen & Bearbeiten aus den
> Berichten** – eine manuelle Buchung, die in eine abgeschlossene Buchung
> fällt, teilt diese automatisch (wie bei der laufenden Buchung); die
> Einzelbuchungs-Tabelle der Zeitübersichten bietet Berechtigten einen
> Bearbeiten-Link.

> Seit 0.9.14: **Nachtrag bei laufender Arbeitszeit** – eine manuelle Buchung
> (z. B. ein Telefonat), die in die laufende Buchung fällt, teilt diese
> automatisch: bisheriger Teil wird abgeschlossen, der Nachtrag eingefügt,
> die Arbeitszeit läuft ab dem Nachtragsende unverändert weiter.

> Seit 0.9.13: **Zuverlässige PWA-Updates** – installierte PWAs (insbesondere
> iOS) erkennen neue Versionen jetzt automatisch bei App-Start/-Resume und
> nach jedem Sync und laden sich einmalig selbst neu; zusätzlich wird beim
> Zurückholen in den Vordergrund synchronisiert. Details unter
> [„Updates & Service-Worker-Versionierung"](#updates--service-worker-versionierung).

> Seit 0.9.12: **Geltungsbereich für Team-Rechte** – Freigaben, Berichte und
> Buchungsbearbeitung lassen sich je Gruppe auf das **eigene Team (Gruppe)**
> oder **alle Benutzer** eingrenzen. Details unter
> [„Gruppen & Berechtigungen"](#gruppen--berechtigungen).

> Seit 0.9.11: **Überarbeitete Gruppenberechtigungen** – kategorisierte
> Berechtigungsmatrix in der Gruppenverwaltung mit neuen Rechten für
> Selbstbedienung (manuelle Buchungen, Kommentare nachträglich bearbeiten,
> Urlaubsanträge stellen) und Firmenverwaltung. Details unter
> [„Gruppen & Berechtigungen"](#gruppen--berechtigungen).

> Seit 0.9.10: **Mobile Stempel-Fixes & Kommentar-Nachbearbeitung** – die
> Firmensuche der mobilen App übernimmt gewählte Vorschläge zuverlässig in die
> Buchung, und nach dem Beenden eines Auftrags bzw. der Arbeitszeit kann der
> Kommentar der Buchung optional nachbearbeitet werden.

> Seit 0.9.9: **Docker-Erstinitialisierung** der Datenbank über `DB_*`-ENV-
> Variablen, **datenbankunabhängige (logische) Backups** und **Cross-Database
> Restore** (z. B. SQLite-Backup → PostgreSQL). Details unter
> [„Docker Deployment"](#docker-deployment).

> Die mobile Oberfläche (`/mobile`) ist eine installierbare, offline-fähige PWA.
> Details siehe Abschnitt [„Mobile Offline-Funktion"](#mobile-offline-funktion-mobile) und [`CHANGELOG.md`](CHANGELOG.md).

## Deployment-Standard (neu)

Der Standardweg ist jetzt vollständig image-basiert:

1. Code nach GitHub pushen
2. GitHub Actions baut das Docker-Image
3. Image wird in die GitHub Container Registry (GHCR) veröffentlicht
4. Portainer deployt dieses GHCR-Image per Stack/Compose

> Portainer baut **nicht** lokal, sondern zieht ein bereits gebautes Image.

## Einstiegspunkt und Laufzeit

- FastAPI-App: `app.main:app`
- Standardport: `8000`
- Container-Startkommando:
  `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Lokale Entwicklung

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker (lokal)

```bash
docker build -t erfassung:0.9.16 .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=sqlite:////app/data/erfassung.db \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  erfassung:0.9.16
```

## GHCR & GitHub Actions

Der Workflow liegt unter `.github/workflows/container-publish.yml` und veröffentlicht nach GHCR.

### Trigger

- Push auf `main`
- Push von Tags `v*` (z. B. `v0.9.16`)
- Manuell über `workflow_dispatch`

### Tags

- Versions-Tag aus `VERSION` (hier `0.9.16`)
- `latest` auf `main`
- Git-Tag (`v0.9.16`)

### Erwartetes Image

Beispiel:

`ghcr.io/OWNER/erfassung:0.9.16`

`OWNER` ist der GitHub-Owner (User oder Organisation) des Repositories.

## Deployment mit Portainer

Für Portainer ist die bereitgestellte `compose.yaml` gedacht. Sie referenziert ein GHCR-Image (ohne lokalen Build).

### Beispiel

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.9.16
    container_name: erfassung
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: sqlite:////app/data/erfassung.db
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
```

## Benutzerverwaltung über die Konsole (CLI)

Für Notfälle und Administration ohne Web-Oberfläche gibt es ein Konsolen-Werkzeug
(`app/manage.py`). Es nutzt dieselbe Datenbank wie die Web-App (Umgebungsvariable
`DATABASE_URL`) sowie dieselbe Passwort-Prüfung (mind. 10 Zeichen, Groß-/Klein­buchstabe,
Zahl, Sonderzeichen).

### Aufruf

Im laufenden Docker-Container (empfohlen im Produktivbetrieb – nutzt automatisch das
gemountete `/app/data`):

```bash
docker exec -it erfassung python -m app.manage <befehl> [optionen]
```

> `erfassung` ist der Container-Name aus der `compose.yaml`. Bei abweichendem Namen
> entsprechend anpassen (`docker ps`).

Lokal (Entwicklung):

```bash
python -m app.manage <befehl> [optionen]
```

### Benutzer auflisten

```bash
docker exec -it erfassung python -m app.manage list-users
```

Zeigt ID, Benutzername, Name, E-Mail, Gruppe, Admin-Kennzeichen und ob beim nächsten
Login ein Passwortwechsel erzwungen wird.

### Gruppen auflisten

```bash
docker exec -it erfassung python -m app.manage list-groups
```

Hilfreich, um die Gruppen-ID/den -Namen für `--group` zu finden (Admin-Rechte hängen
an der Gruppe).

### Benutzer anlegen

```bash
docker exec -it erfassung python -m app.manage create-user \
  --username mmustermann \
  --full-name "Max Mustermann" \
  --email max@example.com \
  --group Administration \
  --weekly-hours 40
```

- Ohne `--password` wird das Passwort interaktiv (verdeckt) abgefragt.
- `--password "Geheim!2345"` setzt es direkt (Vorsicht: erscheint in der Shell-History).
- `--random` erzeugt ein sicheres Zufallspasswort und gibt es einmalig aus.
- `--group` akzeptiert Gruppen-**ID oder -Name**; für Admin-Rechte die Admin-Gruppe
  (Standard: `Administration`) angeben.
- Standardmäßig muss der Benutzer das Passwort bei der ersten Anmeldung ändern.
  Mit `--no-force-change` wird das deaktiviert.

### Passwort zurücksetzen

```bash
# per Benutzername, mit interaktiver Abfrage
docker exec -it erfassung python -m app.manage reset-password --username mmustermann

# per ID, mit Zufallspasswort
docker exec -it erfassung python -m app.manage reset-password --id 1 --random

# direkt gesetztes Passwort, ohne erzwungenen Wechsel
docker exec -it erfassung python -m app.manage reset-password \
  --username admin --password "NeuesPasswort!1" --no-force-change
```

Standardmäßig wird nach dem Zurücksetzen ein Passwortwechsel bei der nächsten
Anmeldung verlangt (`--no-force-change` deaktiviert das).

### Hinweise

- Das voreingestellte Administratorkonto lautet `admin` (Erst-PIN/-Passwort `0000`).
  Über `reset-password --username admin --random` lässt sich ein sicheres Passwort
  vergeben, falls der Zugang verloren ging.
- Alle Befehle geben bei Fehlern (unbekannter Benutzer, doppelter Benutzername/E-Mail,
  zu schwaches Passwort) eine verständliche Meldung und den Exit-Code `1` zurück.

## Gruppen & Berechtigungen

Berechtigungen werden über Gruppen vergeben (**Administration → Benutzer →
Gruppen**). Seit 0.9.11 sind sie – wie in bekannten Rollen-/Rechteverwaltungen –
in Kategorien gegliedert und im Gruppenformular als Berechtigungsmatrix mit
Beschreibung je Recht dargestellt:

| Kategorie | Berechtigung | Standard |
|-----------|--------------|----------|
| Eigene Zeiterfassung | Manuelle Zeitbuchungen nachtragen | ✅ erlaubt |
| Eigene Zeiterfassung | Eigene Kommentare nachträglich bearbeiten | ✅ erlaubt |
| Eigene Zeiterfassung | Urlaubsanträge stellen | ✅ erlaubt |
| Aufträge & Firmen | Firmen beim Stempeln anlegen | ❌ |
| Aufträge & Firmen | Firmen verwalten (Administration) | ❌ |
| Team & Freigaben | Manuelle Buchungen freigeben | ❌ (Bereich wählbar) |
| Team & Freigaben | Urlaubsanträge verwalten | ❌ (Bereich wählbar) |
| Team & Freigaben | Zeitübersichten einsehen | ❌ (Bereich wählbar) |
| Team & Freigaben | Zeitbuchungen bearbeiten | ❌ (Bereich wählbar) |
| Verwaltung | Benutzer verwalten | ❌ |

- **Geltungsbereich der Team-Rechte (seit 0.9.12)**: Jedes Recht unter
  „Team & Freigaben" wird dreistufig vergeben – **Nicht erlaubt**,
  **Eigenes Team (Gruppe)** oder **Alle Benutzer**. „Eigenes Team" beschränkt
  Freigabelisten, Berichte/Exporte und die Buchungsbearbeitung auf Benutzer
  derselben Gruppe; der Server prüft das zusätzlich bei jeder Aktion.
  Bestandsgruppen behalten beim Update automatisch „Alle Benutzer".
- **Administratorrechte** umfassen automatisch alle Berechtigungen (inklusive
  System, Backups, Terminals und Gruppenverwaltung) mit Geltungsbereich
  „Alle Benutzer"; die Einzelrechte sind im Formular dann gesperrt sichtbar.
- **Selbstbedienungsrechte** (Kategorie „Eigene Zeiterfassung") sind
  standardmäßig aktiv; Benutzer ohne Gruppe behalten sie. Entzogene Rechte
  blenden die zugehörigen Funktionen in Web und mobiler App aus und werden
  serverseitig durchgesetzt (auch für Offline-Aktionen).
- Die Gruppenübersicht zeigt vergebene Rechte kompakt je Kategorie
  (z. B. „Team & Freigaben: 2/4", Zusatz „(eigenes Team)" bei Team-Bereich).

## Datenbank (SQLite, MySQL, MariaDB, PostgreSQL)

Standard ist SQLite. Unterstützt werden außerdem **MySQL 8+, MariaDB 10.6+ und
PostgreSQL 14+** (Treiber `PyMySQL` und `psycopg2-binary` sind enthalten).
MariaDB und PostgreSQL sind die empfohlenen Produktivdatenbanken, SQLite eignet
sich für Einzelplatz-, Test- und Entwicklungsumgebungen.

Das aktive Datenbanksystem kann seit 0.9.7 direkt über die Oberfläche unter
**Administration → System → Datenbank** verwaltet und gewechselt werden. Vor
jedem Wechsel wird automatisch ein Sicherheitsbackup erstellt, anschließend
werden alle Daten verlustfrei übertragen und auf Integrität geprüft; schlägt
etwas fehl, bleibt die bisherige Datenbank aktiv (kein Datenverlust, keine
Downtime). Die Auswahl wird persistent in `config/database.json` gespeichert und
hat Vorrang vor `DATABASE_URL`.

Alternativ lässt sich das Backend weiterhin per Umgebungsvariable vorgeben:

```
DATABASE_URL: mysql+pymysql://benutzer:passwort@db-host:3306/erfassung
DATABASE_URL: postgresql+psycopg2://benutzer:passwort@db-host:5432/erfassung
```

Schemaänderungen werden beim Start automatisch und dialektübergreifend
angewandt (Versionsstand in der Tabelle `schema_migrations`). Upgrades von
älteren Versionen (0.6.x/0.7.x/0.8.x) sind ohne Datenverlust möglich.

## Docker Deployment

### Unterstützte Datenbanken

| Datenbank | Eignung |
|-----------|---------|
| ⭐ **PostgreSQL** | Empfohlene Referenzinstallation für den Produktivbetrieb |
| ⭐ **MariaDB** | Empfohlen für den Produktivbetrieb |
| MySQL | Produktiv geeignet |
| SQLite | Entwicklung, Tests, kleine Installationen |

### Erstinitialisierung über Docker ENV (seit 0.9.9)

Bei einer **Neuinstallation** (noch keine `config/database.json` vorhanden) kann
die Datenbank vollständig über ENV-Variablen vorkonfiguriert werden. Beim ersten
Start wird daraus die Konfiguration erzeugt, persistiert, getestet und migriert.

| Variable | Beschreibung | Beispiel |
|----------|--------------|----------|
| `DB_TYPE` | `sqlite` / `mysql` / `mariadb` / `postgresql` | `postgresql` |
| `DB_HOST` | Host (Servertypen) | `postgres` |
| `DB_PORT` | Port (Servertypen) | `5432` |
| `DB_NAME` | Datenbankname | `timetracking` |
| `DB_USER` | Benutzer | `timetracking` |
| `DB_PASSWORD` | Passwort | `secret` |
| `DB_SSL` | TLS aktivieren | `false` |
| `DB_PATH` | Pfad der SQLite-Datei (nur SQLite) | `/data/app.db` |

> **Wichtig:** ENV-Variablen dienen **ausschließlich der Erstinitialisierung**.
> Existiert bereits eine `config/database.json`, werden die ENV-Variablen
> ignoriert und niemals überschrieben. Die Datenbank bleibt danach vollständig
> über **Administration → System → Datenbank** verwaltbar; dort wird auch
> angezeigt, ob die Konfiguration aus Docker ENV oder über das Webinterface
> erstellt wurde.

### PostgreSQL (empfohlene Referenzinstallation) ⭐

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.9.16
    container_name: erfassung
    restart: unless-stopped
    depends_on: [postgres]
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: postgresql
      DB_HOST: postgres
      DB_PORT: "5432"
      DB_NAME: timetracking
      DB_USER: timetracking
      DB_PASSWORD: changeme
      DB_SSL: "false"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
  postgres:
    image: postgres:16
    container_name: erfassung-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: timetracking
      POSTGRES_USER: timetracking
      POSTGRES_PASSWORD: changeme
    volumes:
      - ./pgdata:/var/lib/postgresql/data
```

### MariaDB ⭐

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.9.16
    container_name: erfassung
    restart: unless-stopped
    depends_on: [mariadb]
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: mariadb
      DB_HOST: mariadb
      DB_PORT: "3306"
      DB_NAME: timetracking
      DB_USER: timetracking
      DB_PASSWORD: changeme
      DB_SSL: "false"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
  mariadb:
    image: mariadb:11
    container_name: erfassung-mariadb
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: timetracking
      MARIADB_USER: timetracking
      MARIADB_PASSWORD: changeme
      MARIADB_ROOT_PASSWORD: changeme-root
    volumes:
      - ./mariadb:/var/lib/mysql
```

### MySQL

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.9.16
    container_name: erfassung
    restart: unless-stopped
    depends_on: [mysql]
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: mysql
      DB_HOST: mysql
      DB_PORT: "3306"
      DB_NAME: timetracking
      DB_USER: timetracking
      DB_PASSWORD: changeme
      DB_SSL: "false"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
  mysql:
    image: mysql:8
    container_name: erfassung-mysql
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: timetracking
      MYSQL_USER: timetracking
      MYSQL_PASSWORD: changeme
      MYSQL_ROOT_PASSWORD: changeme-root
    volumes:
      - ./mysql:/var/lib/mysql
```

### SQLite (Entwicklung / Tests / kleine Installationen)

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.9.16
    container_name: erfassung
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: sqlite
      DB_PATH: /app/data/erfassung.db
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
```

> In **allen** Beispielen sind die drei persistenten Volumes `config`, `data`
> und `logs` eingebunden – diese müssen erhalten bleiben, damit Konfiguration,
> Geschäftsdaten und Protokolle Neustarts überleben.

## Backups (datenbankunabhängig, seit 0.9.9)

Unter **Administration → Backups** lassen sich Sicherungen (Datenbank +
Konfiguration, optional Logs) lokal sowie auf **FTP/FTPS** oder **SMB3**
ablegen. Zugangsdaten werden persistent im `config`-Volume gespeichert und nie
im Klartext protokolliert. Es gibt einen Verbindungstest, konfigurierbare
Aufbewahrung, eine Integritätsprüfung nach jeder Sicherung und eine Historie.

Backups sind seit 0.9.9 **datenbankunabhängig (logisch)**: Die Daten werden als
JSON je Tabelle exportiert (`data/database.json`) statt als rohe Datenbankdatei.
Jedes Archiv enthält Metadaten (`app_version`, `backup_format_version`,
`database_type`, `schema_version`, `created_at`, Datensatzanzahlen) – diese
dienen ausschließlich der Analyse/Information und lösen niemals einen
automatischen Datenbankwechsel aus.

### Cross-Database Restore (seit 0.9.9)

Ein logisches Backup kann **unabhängig vom ursprünglichen Datenbanktyp** in die
aktuell konfigurierte Datenbank wiederhergestellt werden (z. B. SQLite-Backup →
PostgreSQL, MariaDB-Backup → PostgreSQL, PostgreSQL-Backup → SQLite). Ablauf:
Backup analysieren → Daten extrahieren → in die **aktive** Datenbank importieren
(ORM, eine Transaktion) → Migrationen ausführen → Integritätsprüfung. Vor jeder
Wiederherstellung wird automatisch ein Sicherheitsbackup (`pre_restore_*.zip`)
erstellt. Eine Vorschau zeigt vorab Backup- und Systeminformationen.

> **Restore importiert ausschließlich Daten.** Der aktive Datenbanktyp, die
> Datenbankkonfiguration sowie die ENV-/Docker-Einstellungen werden dabei
> niemals verändert.

## Terminalverwaltung (Zeiterfassungsterminals)

Unter **Administration → Zeiterfassung → Terminals** werden Zeiterfassungs-
terminals zentral verwaltet (seit 0.9.8). Die Ansicht ist analog zu den
Backup-Jobs aufgebaut: eine Tabelle mit Name, Typ, Status, letzter Verbindung
und letzter Synchronisation sowie den Aktionen Bearbeiten, Verbindung testen,
Synchronisieren, Aktivieren/Deaktivieren und Löschen. Über **„Neues Terminal“**
öffnet sich ein kompaktes Modal.

Die Verwaltung basiert auf einer **Treiber-/Plugin-Architektur**
(`app/integrations/terminals/`): Jeder Terminaltyp ist ein eigener Treiber, der
sich in einer Registry registriert. Es gibt **keine hartkodierte TimeMoto-Logik**
in der Oberfläche – weitere Typen (z. B. ZKTeco, Suprema, generische REST-/CSV-
Terminals) lassen sich ohne Umbauten ergänzen. Aktuell wird der Typ **TimeMoto**
ausgeliefert.

Der frühere eigene Menüpunkt „TimeMoto TM-616“ wurde durch diese
Terminalverwaltung ersetzt; eine vorhandene `config/timemoto.json` wird beim
Upgrade automatisch und verlustfrei als Terminal übernommen. Terminalaktionen
werden im Logkanal `terminal` (`logs/terminal.log`) protokolliert; der
Systemstatus zeigt Anzahl, Online-/Offline-Terminals sowie die letzte
Synchronisation und den letzten Synchronisationsfehler.

## Persistenz (wichtig)

Für produktiven Betrieb sollten folgende Pfade persistent gemountet werden:

- `/app/data` (inkl. SQLite-DB `erfassung.db` und `data/backups`)
- `/app/logs` (strukturierte Logdateien)
- `/app/config` (Konfigurationen: System, Logging, Backup-Ziele, Datenbank)

Optional zusätzlich:

- `.env`-Datei im Stack/Host, falls eigene Umgebungsvariablen genutzt werden

## Was du selbst anpassen musst

- `OWNER` im Image-Namen (`ghcr.io/OWNER/erfassung:0.9.16`)
- optional Image-Name/Tag (`erfassung`, `0.9.16`, `latest`)
- Volume-Hostpfade (`./data`, `./logs`, `./config`)
- ggf. zusätzliche Umgebungsvariablen (z. B. für DB/Integrationen)

## Hinweise zu privaten Repositories

GHCR funktioniert auch mit privaten Repositories. In Portainer muss dann ein Registry-Zugang (PAT mit `read:packages`) hinterlegt werden, damit das private Image gezogen werden kann.

## Mobile Offline-Funktion (`/mobile`)

Die mobile Oberfläche ist als pragmatische **Offline-first-PWA** umgesetzt.

### Was offline funktioniert

- Laden der mobilen Seite `/mobile` inklusive zentraler Assets per Service Worker.
- Start/Stop von Arbeitszeitbuchungen.
- Pausenstart/Pausenende.
- Firmen-/Auftragsstart und -ende.
- Firmensuche mit Vorschlagsliste: ein gewählter Vorschlag wird automatisch in
  die Firmenauswahl übernommen (ab 0.9.10); zusätzlich löst der Server den
  Suchtext als Fallback über den Firmennamen auf.
- Kommentar-/Notizfelder in mobilen Aktionen.
- Kommentar nachbearbeiten (ab 0.9.10): Nach „Auftrag beenden" bzw.
  „Arbeitszeit beenden" öffnet sich optional ein Dialog, um den Kommentar der
  beendeten Buchung anzupassen; zusätzlich gibt es unter den Stempel-Aktionen
  den Button „Kommentar der letzten Buchung bearbeiten" (Buchungen des
  aktuellen Tages).
- Offline erstellte Urlaubsanträge.

### Lokale Datenhaltung (letzte 6 Monate)

Die App speichert mobilrelevante Serverdaten für ca. 6 Monate (183 Tage) lokal im Browser (IndexedDB):

- Zeitbuchungen/Stempelhistorie.
- Firmenliste.
- Urlaubsanträge.
- Aktiven Buchungszustand und mobile Kennzahlen.
- Metadaten wie `lastSyncAt`.

### Synchronisation

- Automatische Synchronisation beim Start der mobilen Seite.
- Automatische Synchronisation beim Wechsel von Offline zu Online.
- Offline-Aktionen bleiben persistent in einer lokalen Queue gespeichert (auch nach Browser-Neustart).
- **Queue-and-forward (ab 0.5.0):** Jedes Ereignis wird zuerst unconditional in
  IndexedDB gespeichert und dann in Erstellungsreihenfolge an den Server gesendet.
  Eine Aktion wird nur entfernt, wenn der Server sie eindeutig bestätigt – der
  Server (mit `client_action_id`-Idempotenz) ist die alleinige Wahrheitsquelle.
  Dadurch keine verlorenen Stempelungen und keine Dubletten.
- Die Sync-Endpunkte (`/punch`, `/vacations`) antworten bei `Accept: application/json`
  mit `{ok, duplicate, retryable, message}`, sodass der Client zuverlässig
  entscheidet, ob eine Aktion erledigt ist oder erneut gesendet werden muss.
- **Echte Ereigniszeit (ab 0.5.0):** Der Client sendet die lokale Zeit der Aktion
  (`event_time`); offline erfasste Zeiten bleiben korrekt, auch wenn erst Stunden
  später synchronisiert wird.

### Service Worker / Offline-Start

- Der Service Worker wird von der Wurzel ausgeliefert (`GET /sw.js`) mit dem
  Header `Service-Worker-Allowed: /`, damit sein Scope die `/mobile`-`start_url`
  abdeckt. (Ein unter `/static/` ausgelieferter Worker kann nicht für `/`
  registriert werden – das verhinderte früher den Offline-Start auf iOS/Safari.)
- Beim ersten Online-Aufruf installiert der Worker und legt App-Shell, CSS, JS und
  Icons in den Cache. Danach startet `/mobile` vollständig ohne Netzwerk.

### Statusmeldungen in der mobilen App

Die mobile Seite zeigt nutzerfreundlich an:

- Online/Offline-Serverstatus.
- Ob lokale Daten verfügbar sind.
- Anzahl ausstehender Offline-Aktionen.
- Zeitstempel der letzten erfolgreichen Synchronisation.

### Einschränkungen

- Eine **neue Anmeldung** benötigt weiterhin Serververbindung.
- Eine bereits aktive Sitzung mit lokal gespeicherten Mobil-Daten kann offline weiterarbeiten.
- Fokus liegt bewusst auf der mobilen Kernfunktion (Stempeln/Synchronisation), nicht auf vollständiger Offline-Abdeckung aller Admin-/Desktop-Seiten.

### Browser-Unterstützung

- Moderne Browser mit Service Worker + IndexedDB (aktuelles Chrome/Edge/Safari/Firefox mobile).
- Bei deaktiviertem IndexedDB fällt die App auf reduzierte Browser-Speicherung zurück.

### Updates & Service-Worker-Versionierung

- Die Route `GET /sw.js` **brennt die Version in den Skriptinhalt ein**
  (`self.__ERFASSUNG_VERSION`, Quelle: Datei `VERSION`) und liefert mit
  `Cache-Control: no-cache` aus. Jedes Release ändert damit die Skript-Bytes –
  der Update-Check des Browsers erkennt die neue Version auch dann, wenn eine
  installierte PWA noch eine alte gecachte Seite (mit alter
  Registrierungs-URL) ausführt. Vorher blieb die PWA in diesem Fall dauerhaft
  auf dem alten Stand hängen (Update kam erst nach Neuinstallation an).
- Der Cache-Name (`erfassung-mobile-v<VERSION>`) folgt der eingebrannten
  Version; der alte Cache wird beim `activate`-Event gelöscht (`skipWaiting()`
  + `clients.claim()`). Beim Installieren lädt der Worker die Assets mit
  `cache: 'no-cache'`, damit kein staler HTTP-Cache in die neue Cache-Version
  gelangt.
- **Aktive Update-Prüfung (ab 0.9.13):** Die Registrierung nutzt
  `updateViaCache: 'none'`; zusätzlich stößt die App `registration.update()`
  bei jedem Start, beim Zurückholen in den Vordergrund (App-Resume, wichtig
  für iOS) und nach jedem Sync mit geänderter Server-Version an. Übernimmt
  ein neuer Worker die Kontrolle, lädt sich die Seite **einmalig automatisch
  neu**, sodass sofort die frischen Assets aktiv sind (Offline-Queue bleibt
  erhalten – sie liegt persistent in IndexedDB).
- **Sync bei App-Resume (ab 0.9.13):** Beim Wechsel der PWA in den Vordergrund
  wird automatisch synchronisiert – zuvor geschah das nur beim Seitenstart
  und beim `online`-Ereignis.
- Es ist **kein** manuelles Editieren von `static/sw.js` oder `static/app.js` pro
  Release mehr nötig.

### PWA am Desktop/PC verwenden

Ja – die mobile Oberfläche ist nicht auf Smartphones beschränkt:

- **Ohne Installation:** `/mobile` einfach im Desktop-Browser öffnen; alle
  Funktionen (Stempeln, Offline-Queue, Synchronisation) stehen zur Verfügung.
- **Als installierte App:** Chrome/Edge am PC bieten über das Symbol in der
  Adressleiste (bzw. Menü → „App installieren") die Installation an
  (`display: standalone`). Die App startet dann in einem eigenen Fenster mit
  `/mobile` als Startseite und funktioniert offline wie am Smartphone.
- Die Oberfläche ist für schmale Bildschirme gestaltet, läuft im
  Desktop-Fenster aber uneingeschränkt; für die volle Desktop-Oberfläche
  (Administration, Berichte) bleibt die normale Web-Ansicht (`/dashboard`)
  die bessere Wahl.

### Installierbarkeit

Installierbar auf Android, iOS, Windows, macOS und Linux über das Manifest
(`static/manifest.webmanifest`) mit `id`, `start_url`, `scope`, `display: standalone`
sowie Icons in 192px, 512px und SVG (maskable).

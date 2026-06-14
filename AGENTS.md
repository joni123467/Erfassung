# AGENTS.md – Leitfaden für Entwicklungsagenten

Dieser Leitfaden gilt für alle automatisierten Änderungen an diesem
Repository. Er ergänzt `README.md` und `CHANGELOG.md`.

## Projektüberblick

- FastAPI-Anwendung (`app/`), Jinja2-Templates (`templates/`),
  statische Assets inkl. Offline-PWA (`static/`).
- SQLite-Datenbank (`erfassung.db`), SQLAlchemy-Modelle in `app/models.py`.
- Versionsquelle ist ausschließlich die Datei `VERSION` im Repo-Root;
  `app/__init__.py` liest sie und versorgt FastAPI (`version=`), Footer,
  Health-API und Asset-Cache-Busting (`?v=`). Bei Releases nur `VERSION`
  und `CHANGELOG.md` pflegen – nirgendwo Versionsnummern hartkodieren.

## Datenbankschema prüfen (verpflichtend)

Bei **jeder** Änderung analysieren, ob sie das Datenbankschema berührt:

- neue Felder (Spalten)
- neue Tabellen
- geänderte Datentypen
- neue Beziehungen (Foreign Keys)
- neue Indizes (inkl. Unique-Indizes)

Berührt eine Änderung `app/models.py`, ist IMMER ein Migrationspfad
erforderlich (siehe unten). `Base.metadata.create_all()` legt nur fehlende
Tabellen an – **keine** fehlenden Spalten in bestehenden Tabellen.

## Datenbank-Backends (SQLite & MySQL)

- Standard ist SQLite; MySQL 8+/MariaDB wird über `DATABASE_URL`
  (`mysql+pymysql://…`) unterstützt. `app/database.py` erkennt das Backend
  (`DB_BACKEND`, `IS_SQLITE`).
- **String-Spalten immer mit Länge** definieren (`String(255)`), sonst
  scheitert `create_all` auf MySQL.
- Migrations-DDL muss portabel sein (Typen wie `INTEGER`, `BOOLEAN`, `FLOAT`,
  `VARCHAR(n)`, `TEXT`, `DATE`, `TIME`, `DATETIME`). SQLite-spezifische Schritte
  (PRAGMA, Tabellen-Rebuild) mit `if database.IS_SQLITE:` kapseln.

## Migrationen

Es gibt zwei Mechanismen, die beide gepflegt werden müssen:

1. **`app/main.py` → `ensure_schema()`**
   Läuft bei jedem Anwendungsstart. Ergänzt fehlende Spalten/Indizes
   idempotent. SQLite-spezifische Teile sind mit `database.IS_SQLITE`
   gekapselt.

2. **`app/db_migrations.py` → `MIGRATIONS`** (dialect-aware)
   Versionierter Runner; der Versionsstand wird in der portablen Tabelle
   `schema_migrations` geführt (`app/db_schema.py`). Bestehende SQLite-
   Installationen werden aus `PRAGMA user_version` einmalig übernommen.
   Migrationen laufen automatisch beim Start (`_apply_versioned_migrations`)
   **und** via CLI (`python -m app.db_migrations`). Für jede Schemaänderung
   einen neuen Eintrag `(n, funktion)` anhängen; Spalten über
   `db_schema.add_column(...)` ergänzen (dialect-sicher, mit `default` und
   `backfill_null_to`). Bestehende Einträge nie ändern/umnummerieren;
   Downgrades werden nicht unterstützt.

### Anforderungen an jede Migration

- **idempotent**: mehrfaches Ausführen darf nichts beschädigen
  (Spalten-/Tabellen-/Index-Existenz vorher prüfen).
- **datenerhaltend**: bestehende Daten dürfen nie verloren gehen.
- **fehlende Spalten automatisch ergänzen** (`ALTER TABLE … ADD COLUMN`
  mit Default + `UPDATE … WHERE … IS NULL` als Absicherung).
- **fehlende Tabellen automatisch anlegen** (über `create_all` bzw.
  explizites `CREATE TABLE IF NOT EXISTS`).
- **Verhalten erhalten**: Defaults so wählen, dass sich das Verhalten für
  Bestandsdaten nicht ändert (Beispiel: `auto_break_deduction DEFAULT 1`,
  damit gesetzliche Pausen weiterhin angewendet werden).

### Versionsübergreifende Updates

Benutzer aktualisieren von **beliebigen** älteren Versionen
(z. B. 0.6.x → 0.8.1, 0.7.x → 0.8.1, 0.8.0 → 0.8.1). Deshalb:

- Migrationen bauen aufeinander auf und laufen lückenlos von jedem Stand.
- Keine Migration darf voraussetzen, dass eine bestimmte App-Version
  vorher lief; nur der tatsächliche Schemazustand zählt.
- `ensure_schema()` fängt zusätzlich Installationen ab, deren
  `user_version` nicht gepflegt wurde.

## Pflichtprüfung vor jedem Abschluss/Deployment

1. Sind Datenbankänderungen enthalten? (`git diff app/models.py`)
2. Existiert dafür eine Migration (beide Mechanismen aktualisiert)?
3. Funktioniert das Upgrade einer bestehenden Installation?
   Test: Datenbank mit altem Schema erzeugen → App starten bzw.
   `python -m app.db_migrations --database <pfad>` ausführen →
   Spalten/Daten prüfen.
4. Bleiben vorhandene Daten erhalten? (Stichproben vor/nach Migration)
5. Werden Logs geschrieben und liegen sie im `logs`-Volume?
6. Bleiben Konfigurationsänderungen über Neustarts erhalten (`config`-Volume)?
7. Werden config/data/logs jeweils korrekt verwendet?

## Logging prüfen (verpflichtend)

Seit 0.9.0 existiert ein dateibasiertes Logging-System
(`app/logging_setup.py`) mit sechs rotierenden Kanälen im `logs`-Volume:
`application`, `api`, `sync`, `security`, `error`, `audit`.

- **Neue Logs registrieren**: zusätzliche Kanäle ausschließlich über
  `logging_setup.CHANNELS` einführen; keine eigenen Dateipfade hartkodieren.
- **Persistenz geprüft**: Logdateien liegen unter `paths.LOGS_DIR`. Keine
  Logs ins data- oder config-Volume schreiben.
- **Audit-Pflicht**: administrative Aktionen (Login/Logout, Passwort-,
  Benutzer-, Rollenänderungen, Urlaubsfreigaben, Feiertags- und
  Systemeinstellungsänderungen, Log-Level-Änderungen) müssen
  `logging_setup.log_audit` auslösen – möglichst bevor eine neue
  Logging-Policy aktiv wird.

## Konfiguration prüfen (verpflichtend)

Persistente Einstellungen liegen als JSON im `config`-Volume
(`app/app_config.py`: `logging.json`, `system.json`).

- **Einstellungen persistent**: neue konfigurierbare Werte über `app_config`
  (Dataclass + `from_dict`/`to_dict`) ergänzen, nie nur im Speicher halten.
- Validierung für Importe in `app_config.validate_import` ergänzen.

## Volumes prüfen (verpflichtend)

`app/paths.py` löst die drei Volumes zentral auf:

- **config**: nur Konfiguration (System, Logging, UI, Mail, Sync, PWA).
- **data**: nur Geschäftsdaten (Datenbank, Benutzer, Urlaub, Zeiterfassung,
  Aufträge, Feiertage, Backups).
- **logs**: nur Protokolle.
- Pfade immer über `paths.*` beziehen, nichts relativ zum Arbeitsverzeichnis
  ablegen und keine Datei im falschen Volume speichern.

## Backups (Job-basiert, ab 0.9.2)

- Backups laufen über **Backup-Jobs** (`models.BackupJob`) mit Historie
  (`models.BackupRun`). Engine/Transfer/Retention/Integritätsprüfung liegen in
  `app/backup_manager.py`, die Zeitplanung in `app/backup_scheduler.py`.
- SMB nutzt **ein** UNC-Pfadfeld und **ein** Benutzerfeld – keine separaten
  Felder für Freigabe/Share/Unterordner/Domain. UNC wird über
  `backup_manager._parse_unc` zerlegt; `DOMAIN\\user` und `user@domain` gehen
  direkt an `smbclient`.
- Passwörter nie im Klartext loggen. Nach jeder Sicherung Integrität prüfen
  (Datei vorhanden, plausible Größe, Archiv lesbar). DB-Snapshots müssen
  konsistent sein (SQLite Online-Backup-API, MySQL `mysqldump`).

## Backup-/Restore-Kompatibilität (verpflichtend, ab 0.9.4)

Restore liegt in `app/restore_manager.py`, das dedizierte Backup-Log in
`logs/backup.log` (Kanal `backup` in `logging_setup`). Jedes Archiv enthält
`backup_meta.json` (App-Version, DB-Typ, Schema-Version, Backup-Typ).

Bei Änderungen an Backup-, Restore-, Upload-, Datenbank-, Migrations- oder
Konfigurationscode ist zu prüfen: **Sind bestehende Backups weiterhin
wiederherstellbar?**

### Pflichtprüfungen vor jedem Release

1. Können aktuelle Backups wiederhergestellt werden?
2. Können ältere Backups (0.6.x–vorherige) wiederhergestellt werden?
3. Können hochgeladene Backups wiederhergestellt werden?
4. Werden Migrationen nach dem Restore automatisch ausgeführt?
5. Bleiben Daten erhalten?
6. Wird automatisch ein Sicherheitsbackup (`pre_restore_*.zip`) erzeugt?
7. Wird `backup.log` korrekt geschrieben (ohne Passwörter)?

### Release-Blocker

Kein Release, wenn: Restore fehlschlägt, Migration nach Restore fehlschlägt,
Datenverlust möglich ist oder das Backup-Logging fehlerhaft ist.

### Asynchrones Restore (ab 0.9.5, verpflichtend)

Restore läuft **niemals** synchron im HTTP-Request (sonst 500 durch DB-Tausch /
`engine.dispose()`). Der Request validiert und queued nur; der Hintergrund-Worker
(`app/restore_jobs.py`) führt den Restore aus, Status über die Datei
`data/restore_status.json` und `GET /api/restore/status` (ohne DB-Zugriff).

Vor jedem Release zusätzlich prüfen:
- Restore aktueller Backups (asynchron, ohne 500)
- Restore älterer Backups (Auto-Migration)
- Restore während laufendem Betrieb
- Wiederverbindung/Statusanzeige nach (simuliertem) Neustart
- Status-API liefert korrekte Zustände; Sicherheitsbackup wird erzeugt

- **Restore-Regeln**: Nach dem DB-Swap immer `Base.metadata.create_all` (fehlende
  Tabellen) + `db_migrations.run()` ausführen, damit ältere Backups vollständig
  aufschließen. Uploads nur isoliert speichern, auf Dateityp/Integrität/Path-
  Traversal prüfen und erst danach übernehmen. Niemals Zugangsdaten loggen.

## Administration-Navigation

- Die Admin-Navigation (`templates/admin/_nav.html`) ist in einklappbare
  Gruppen (`<details>`) organisiert. Neue Admin-Seiten in die passende Gruppe
  einsortieren (Benutzer / Zeitverwaltung / Sicherung / System / Einstellungen)
  und einen eindeutigen `admin_active`-Key setzen; die Gruppe der aktiven Seite
  öffnet automatisch.

## Weitere Konventionen

- **Offline-PWA**: `static/sw.js` cached Assets versioniert über `?v=`;
  neue statische Dateien in `CORE_ASSETS` aufnehmen. Funktionsänderungen
  an `static/mobile.js`/Service Worker immer gegen den Offline-Modus
  testen.
- **Design-System**: Farben/Radien/Abstände ausschließlich über die
  CSS-Tokens in `static/styles.css` (`:root` / `:root[data-theme="dark"]`).
  Keine hartkodierten Hex-Werte in Komponenten; Dark Mode muss ohne
  komponentenspezifische Overrides funktionieren.
- **Reports**: PDF-Layouts über das gemeinsame Stilsystem in
  `app/pdf_export.py` (`_data_table`, `_kv_table`, …) – Zellen immer als
  umbruchfähige Paragraphs mit Escaping.
- **Changelog**: jede nutzersichtbare Änderung in `CHANGELOG.md`
  dokumentieren (Keep-a-Changelog-Format, deutsch).

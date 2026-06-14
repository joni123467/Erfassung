# AGENTS.md – Leitfaden für Entwicklungsagenten

Dieser Leitfaden gilt für alle automatisierten Änderungen an diesem
Repository. Er ergänzt `README.md` und `CHANGELOG.md`.

## Projektüberblick

- FastAPI-Anwendung (`app/`), Jinja2-Templates (`templates/`),
  statische Assets inkl. Offline-PWA (`static/`).
- SQLite-Datenbank (`erfassung.db`), SQLAlchemy-Modelle in `app/models.py`.
- Versionsquelle ist ausschließlich die Datei `VERSION` im Repo-Root;
  `app/__init__.py` liest sie und versorgt FastAPI (`version=`), Footer,
  Loginseite, Systemstatus, Health-/API-Version, Release- und Build-
  informationen sowie Asset-Cache-Busting (`?v=`). Nirgendwo Versionsnummern
  hartkodieren.
- Bei **jedem** Release verpflichtend gemeinsam pflegen: `VERSION`,
  `CHANGELOG.md`, `README.md` und – sofern vorhanden – die Release Notes unter
  `docs/RELEASE_NOTES_<version>.md`. Siehe Abschnitt „Dokumentation &
  Versionspflege“.

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
(`app/logging_setup.py`) mit rotierenden Kanälen im `logs`-Volume:
`application`, `api`, `sync`, `security`, `error`, `audit`, `backup`
(ab 0.9.4), `database` (ab 0.9.7) und `terminal` (ab 0.9.8).

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

## Datenbankverwaltung & -migration (ab 0.9.7, verpflichtend)

Das aktive Datenbanksystem ist über die Oberfläche umstellbar
(Administration → System → Datenbank). Unterstützt: SQLite, MySQL, MariaDB,
PostgreSQL. **MariaDB und PostgreSQL** sind die empfohlenen Produktivdatenbanken
(⭐ im UI), SQLite bleibt für Einzelplatz-/Test-/Entwicklungsumgebungen.

- Die aktive Auswahl liegt persistent als `config/database.json` im
  config-Volume und hat Vorrang vor `DATABASE_URL`. `app/database.py` baut die
  URL über `build_url(...)` (einzige Quelle der Wahrheit), kann die Engine zur
  Laufzeit über `reconfigure(...)` neu binden. Keine datenbankspezifische Logik
  in Fachfunktionen – ausschließlich über die abstrahierte SQLAlchemy-Schicht.
- Die Migration (`app/db_migrator.py`) ist ORM/metadaten-getrieben und damit
  dialektunabhängig: Zielschema über `Base.metadata.create_all`, Datenkopie über
  die typisierten `sorted_tables` (FK-Reihenfolge), `schema_migrations` wird
  übernommen, PostgreSQL-Sequenzen werden nachgezogen.
- Der Wechsel läuft **asynchron** (`app/db_migration_jobs.py`,
  `GET /api/database/migration/status`), nie synchron im Request.
- Neue Datenbanken müssen einfach ergänzbar bleiben: Treiber in `_DRIVERS`,
  Optionen in `_engine_options`, UI-Eintrag in `DATABASE_OPTIONS`.

### Datenbankwechsel – Pflichtprüfungen vor jedem Release

Jede Richtung muss ohne Datenverlust funktionieren:

- SQLite → MySQL / MariaDB / PostgreSQL
- MySQL → SQLite / MariaDB / PostgreSQL
- MariaDB → SQLite / MySQL / PostgreSQL
- PostgreSQL → SQLite / MySQL / MariaDB

### Integritätsprüfung nach jeder Migration

Prüfen (in `db_migrator.integrity_check`): Datensätze vollständig, Tabellen-
anzahl, Referenzen/Foreign Keys (über gleiche Zeilenzahlen je Tabelle),
Benutzer, Rollen, Historien vollständig. Einstellungen liegen im config-Volume
und bleiben unberührt.

### Ablauf & Sicherheit

1. Zielverbindung prüfen, 2. Sicherheitsbackup `pre_db_migration_*.zip` erstellen,
3. Zielschema erzeugen (leere Zieldatenbank erzwingen), 4./5. Daten exportieren/
importieren, 6. Integrität prüfen, 7. erst dann Engine umstellen + Auswahl
persistieren, 8. `post_db_migration_*.zip` als Wiederherstellungspunkt erzeugen.
Alles in `logs/database.log` (Kanal `database`) protokollieren, nie Zugangsdaten.

### Release-Blocker

Kein Release, wenn: ein Datenbankwechsel fehlschlägt, der Rollback fehlschlägt
(bisherige Datenbank muss aktiv bleiben) oder Datenverlust möglich ist.

## Administration-Navigation

- Die Admin-Navigation (`templates/admin/_nav.html`) ist im Reiter-Design
  (wie „Buchungen“/„Urlaub“) gehalten: Hauptgruppen sind Reiter, die auf dem
  Desktop beim Hover ein Dropdown öffnen und auf Mobil als Accordion klappen.
  Es ist immer nur **eine** Hauptgruppe geöffnet. Neue Admin-Seiten in die
  passende Gruppe einsortieren (Benutzer / Zeiterfassung / Sicherung / System /
  Einstellungen) und einen eindeutigen `admin_active`-Key setzen; die Gruppe der
  aktiven Seite öffnet automatisch.
- Auf Bearbeitungs-/Formularseiten `{% set admin_nav_collapse = true %}` vor dem
  Include setzen, damit keine Navigationsgruppe dauerhaft geöffnet bleibt.
  Beim Öffnen eines Modals wird die Navigation automatisch geschlossen
  (Beobachtung der `body.modal-open`-Klasse bzw. Event `adminnav:close`).

### Pflichtprüfung bei Änderungen an der Administration (ab 0.9.6)

Bei jeder Änderung an der Administration (Navigation, Formulare, Tabellen,
Modals, Karten) prüfen:

1. **Navigation konsistent** – Reiter-Optik wie „Buchungen“/„Urlaub“; gleiche
   Höhe, Schriftgröße, Hover-/Active-/Focus-States und Abstände.
2. **Responsive Darstellung geprüft** – Desktop (Hover-Dropdown), Tablet und
   Mobile (Accordion) durchgespielt; keine Überlappungen/Scrollprobleme.
3. **Dropdowns schließen korrekt** – nur eine Gruppe offen; Navigation schließt
   beim Öffnen von Dialogen/Modals und auf Formularseiten.
4. **Formulare sauber ausgerichtet** – einheitliche Feldhöhen, gleich breite
   Dropdowns/Eingaben, ausgerichtete Labels, konsistente Buttons.
5. **Design konsistent** – keine Bootstrap-Standardoptik; Karten/Sektionen,
   Tokens aus `static/styles.css`, Dark Mode ohne Sonderfälle.

## Terminalverwaltung (ab 0.9.8, verpflichtend)

Zeiterfassungsterminals werden zentral über **Administration → Zeiterfassung →
Terminals** (`/admin/terminals`) verwaltet. Der frühere TimeMoto-
Konfigurationspunkt entfällt; `/admin/integrations/timemoto` leitet auf
`/admin/terminals` um.

- **Treiber-/Plugin-Architektur** (`app/integrations/terminals/`): Jeder
  Terminaltyp ist ein `TerminalDriver` (Methoden `test_connection`,
  `synchronize`), der sich in der Registry (`register(...)`) anmeldet. **Keine
  hartkodierte terminaltyp-spezifische Logik in der UI oder im Routing** – die
  Oberfläche kennt nur das Treiber-Interface. Neue Typen (ZKTeco, Suprema,
  generische REST-/CSV-Terminals) werden als zusätzlicher Treiber ergänzt und
  registriert; das genügt, damit sie im Modal-Dropdown erscheinen.
- Terminaldaten liegen in `models.Terminal`; treiber­spezifische Endpunkte/
  Optionen gehören in `Terminal.config_json` (kein Schemaänderung pro Typ).
  Synchronisationsläufe werden in `models.TerminalSyncRun` historisiert.
- Aktionen über `logging_setup.log_terminal` im Kanal `terminal`
  (`logs/terminal.log`) protokollieren: erstellt/geändert/gelöscht,
  Verbindungstest, Synchronisation gestartet/erfolgreich/fehlgeschlagen,
  aktiviert/deaktiviert. Niemals Passwörter/API-Keys loggen.

### Pflichtprüfungen vor jedem Release

1. Neues Terminal anlegen, bearbeiten und löschen funktioniert.
2. Verbindung testen liefert ein verständliches Ergebnis (kein 500 bei
   unerreichbarem Host).
3. Synchronisation läuft, Ergebnis (importierte Buchungen/Fehler) und Status
   (online/warning/offline/error) werden gespeichert und angezeigt.
4. Aktivieren/Deaktivieren wirkt.
5. `terminal.log` wird geschrieben; der Systemstatus zeigt Terminalkennzahlen.
6. Eine vorhandene `config/timemoto.json` wird beim Upgrade automatisch als
   Terminal übernommen (Migration 9, idempotent, ohne Datenverlust).

### Release-Blocker

Kein Release, wenn: TimeMoto nicht migriert wurde, die Terminalverwaltung
(Anlegen/Bearbeiten/Löschen/Test/Synchronisation) nicht funktioniert oder
terminaltyp-spezifische Logik hartkodiert in die UI gelangt ist.

## Datenbank-Konfiguration (UI) prüfen (ab 0.9.8, verpflichtend)

Im Modal unter Administration → System → Datenbank gilt:

1. **Felder wechseln korrekt**: SQLite zeigt nur den Datenbankpfad;
   MySQL/MariaDB/PostgreSQL zeigen Host, Port, Datenbankname, Benutzer,
   Passwort und SSL.
2. **Standardports korrekt**: beim Wechsel automatisch MySQL/MariaDB 3306,
   PostgreSQL 5432; der Platzhalter folgt dem Typ.
3. **Gespeicherte/eigene Werte bleiben erhalten**: ein selbst eingetragener
   Port und bereits gesetzte Werte (z. B. Host) dürfen beim Typwechsel nicht
   überschrieben werden (nur ein automatisch gesetzter Standardport wird auf den
   neuen Standard angepasst).
4. **Validierung & Verbindungstest** beziehen sich immer auf die aktuell
   eingestellte Konfiguration, nie auf eine alte.

## Dokumentation & Versionspflege (verpflichtend)

Bei **jeder** Versionsänderung automatisch prüfen und pflegen:

- Wurde die `README.md` aktualisiert und entspricht sie dem tatsächlichen
  Funktionsumfang (neue/entfernte Funktionen, geänderte Menüpunkte, neue
  Konfigurations-, Datenbank-, Backup-/Restore- und Terminalfunktionen)?
- Stimmen die Versionsnummern in `VERSION`, `README.md`, `CHANGELOG.md`,
  Anwendung, API, Footer, Build- und Releaseinformationen überein?
- Existiert ein `CHANGELOG.md`-Eintrag für die neue Version mit mindestens:
  neue Funktionen, Änderungen, Fehlerbehebungen, Datenbankänderungen,
  Migrationshinweise?

### Release-Blocker

Kein Release, wenn: die README nicht aktualisiert wurde, Versionsnummern nicht
übereinstimmen, neue Funktionen nicht dokumentiert sind oder ein Changelog-
Eintrag fehlt.

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

# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.9.7] – 2026-06-14

### Added – Datenbankverwaltung & -migration über die Oberfläche

- **Neuer Bereich Administration → System → Datenbank** (`/admin/system/database`):
  Das aktive Datenbanksystem lässt sich jetzt direkt über die Weboberfläche
  verwalten. Unterstützt werden **SQLite, MySQL, MariaDB und PostgreSQL**.
  MariaDB und PostgreSQL sind als empfohlene Produktivdatenbanken
  gekennzeichnet (⭐ Empfohlen); SQLite bleibt für Einzelplatz-, Test- und
  Entwicklungsumgebungen verfügbar.
- **Datenbankauswahl & -konfiguration**: Dropdown „Aktive Datenbank“ mit
  Empfehlungskarten (Einsatzzwecke, Hinweise) sowie ein kompaktes Modal
  („Datenbank konfigurieren“). SQLite zeigt den Datenbankpfad, die Server-
  backends Host, Port, Datenbankname, Benutzer, Passwort, SSL und Verbindungs-
  Timeout. Ein Info-Symbol (ⓘ) zeigt empfohlene und unterstützte Versionen.
  Konfiguration wird persistent als `config/database.json` im config-Volume
  gespeichert und hat Vorrang vor `DATABASE_URL`.
- **Verlustfreie Datenbankmigration** (`app/db_migrator.py`): Wechsel zwischen
  allen vier Systemen ohne Datenverlust. Ablauf: Zielverbindung prüfen →
  automatisches Sicherheitsbackup (`pre_db_migration_*.zip`) → Zielschema
  erzeugen → Daten exportieren/importieren → Integritätsprüfung →
  Anwendung umstellen → `post_db_migration_*.zip` als sofortiger
  Wiederherstellungspunkt. Übernommen werden Benutzer, Rollen, Arbeitszeiten,
  Stempelungen, Urlaub, Feiertage, Logs, Backup-/Restore-Historie,
  Offline-Synchronisationsdaten und alle weiteren Tabellen. Einstellungen liegen
  im config-Volume und bleiben unberührt.
- **Integritätsprüfung** nach jeder Migration: Tabellenanzahl, Datensatzanzahl
  je Tabelle, Schlüsselentitäten (Benutzer, Rollen, Historien). Bei Abweichung
  schlägt die Migration fehl.
- **Rollback ohne Downtime**: Da nur in die Zieldatenbank geschrieben wird,
  bleibt die bisherige Datenbank bei jedem Fehler unverändert aktiv. Eine nicht
  leere Zieldatenbank bricht die Migration ab (Datenverlust-Schutz).
- **Asynchroner Migrations-Worker** (`app/db_migration_jobs.py`) analog zum
  Restore: Der Request validiert und queued nur, der Hintergrund-Thread führt
  die Migration aus; Fortschritt über `data/db_migration_status.json` und
  `GET /api/database/migration/status` mit eigener Fortschrittsseite.
- **Neuer Logkanal `database`** → `logs/database.log` (in Administration → Logs
  filter-/such-/downloadbar). Erfasst Migration gestartet/erfolgreich/
  fehlgeschlagen, Rollback und Verbindungstests (Zeitpunkt, Benutzer, Quelle,
  Ziel, Datensatzanzahl, Dauer, Ergebnis) – nie Zugangsdaten. Über das neue
  Logging-Setting „Datenbank-Logging“ steuerbar.

### Changed

- **Systemstatus erweitert**: zeigt aktive Datenbank, Datenbankversion, Host,
  Datenbankname, Tabellenanzahl, letzte Migration, letzte erfolgreiche Migration
  und letzten Fehler.
- **PostgreSQL-Treiber** (`psycopg2-binary`) ergänzt; `app/database.py` erkennt
  und bedient SQLite, MySQL/MariaDB (PyMySQL) und PostgreSQL über eine
  abstrahierte URL-/Engine-Schicht mit Laufzeit-Reconfigure.
- Version auf **0.9.7** angehoben (Frontend, Backend, Footer, Loginseite,
  Systemstatus, API-Version, Release- und Buildinformationen).

## [0.9.6] – 2026-06-14

### Changed – Administration UI/UX überarbeitet

- **Navigation im Reiter-Design**: Die Administrationsnavigation
  (`templates/admin/_nav.html`) entspricht jetzt optisch den Reitern unter
  „Buchungen“/„Urlaub“ (`.timetac-subnav`): flache, kantige Reiter mit gemeinsamer
  Unterkante, gleicher Höhe, Schriftgröße, Hover-/Active-/Focus-States und
  Abständen – keine klassischen Dropdown-Menüs/Bootstrap-Optik mehr.
  Verhalten unverändert: Desktop öffnet beim Hover ein Dropdown und schließt
  beim Verlassen, Mobile klappt als Accordion, es ist immer nur **eine**
  Hauptgruppe geöffnet.
- **Systemeinstellungen aufgeräumt**: `admin/system_settings.html` ist in klare
  Sektionen mit Kartenlayout gegliedert (Allgemein, Logging, Log-Rotation,
  Synchronisation, Import) mit einheitlichen Feldbreiten, -höhen und Abständen.

### Added – QR-Code im Benutzerdialog

- „Benutzer bearbeiten“ zeigt den Anmelde-QR-Code jetzt direkt im Dialog
  (rechte Seitenspalte auf dem Desktop, unterhalb der Benutzerdaten auf Mobil)
  mit Kurzbeschreibung, Download und „Neu generieren“.

### Fixed – Backup-Historie als eigene Ansicht

- Die Backup-Historie hatte bisher dieselbe Seite wie die Backup-Jobs
  (`/admin/system/backups#history`). Sie besitzt nun eine **eigene Route**
  (`GET /admin/system/backups/history`), ein eigenes Template
  (`admin/system_backups_history.html`) und eine eigene Datenabfrage. Spalten:
  Backup, Start, Ende, Dauer, Größe, Ziel, Status sowie Aktionen (Download,
  Details, Wiederherstellen). Die Backup-Jobs-Seite zeigt nur noch geplante Jobs.

### Fixed – Navigation schließt bei Dialogen

- Beim Öffnen eines Bearbeitungs-/Erstellungsdialogs (Benutzer, Rollen, Firmen,
  Systemeinstellungen, Backup-/Restore-Dialoge u. a.) bleibt keine
  Navigationsgruppe mehr dauerhaft geöffnet: Formularseiten setzen
  `admin_nav_collapse`, Modals lösen ein automatisches Schließen aus
  (Beobachtung der `body.modal-open`-Klasse).

### Docs

- `AGENTS.md`: neue Pflichtprüfung für Administrationsänderungen (Navigation,
  Responsive, Dropdown-Verhalten, Formularausrichtung, Design-Konsistenz).

## [0.9.5] – 2026-06-14

### Fixed – „Internal Server Error" bei der Wiederherstellung

- **Ursache**: Die Wiederherstellung lief synchron im HTTP-Request und tauschte
  die SQLite-Datei aus bzw. verwarf den Engine-Pool (`engine.dispose()`) –
  dadurch wurde genau die Verbindung zerstört, die der laufende Request nutzte,
  und die Antwort endete als 500, obwohl der Restore teils/ganz erfolgreich war.
- **Lösung**: Restore läuft jetzt **asynchron** in einem Hintergrund-Worker. Der
  Request validiert nur (Berechtigung, Datei, Integrität, Kompatibilität),
  erzeugt einen Restore-Job und antwortet sofort mit Weiterleitung auf eine
  Fortschrittsseite.

### Added – Asynchrones Restore mit Statusüberwachung

- Hintergrund-Worker (`app/restore_jobs.py`) mit persistenter Status-Datei im
  `data`-Volume (übersteht DB-Tausch und Neustarts).
- **Status-API** `GET /api/restore/status` (nur Session-basiert, ohne
  Datenbankzugriff) mit Zuständen `queued`, `creating_backup`, `restoring`,
  `restarting`, `running_migrations`, `completed`, `failed` inkl. Fortschritt,
  Meldung, Start-/Endzeit.
- **Fortschrittsseite** mit Fortschrittsbalken, Statusschritten,
  **Neustarterkennung** (bei kurzzeitig nicht erreichbarem Backend wird „Anwendung
  wird neu gestartet, Verbindung wird wiederhergestellt …" angezeigt und weiter
  gepollt) sowie **Countdown (5→1)** und automatischer Weiterleitung zu `/login`.
- **Fehleranzeige** mit Ursache, Zeitpunkt und Log-ID statt nacktem 500.
- Sauberes Schließen/Neuinitialisieren der DB-Verbindungen vor/nach dem Restore
  (SQLite & MySQL).

### Added – Logging, Historie & Systemstatus

- `backup.log` um detaillierte Restore-Schritte erweitert (Restore gestartet,
  Sicherheitsbackup erstellt, Migration gestartet/erfolgreich/fehlgeschlagen,
  Anwendung wird neu gestartet/wieder verfügbar, Restore erfolgreich/fehlgeschlagen).
- Restore-Historie um **Dauer** und **Log-ID** erweitert.
- Systemstatus zeigt zusätzlich letzte erfolgreiche/fehlgeschlagene
  Wiederherstellung, aktiven Restore-Job und letzte Migrationsausführung.

### Notes

- Schemaänderung: `restore_runs.duration_seconds` und `restore_runs.log_token`
  (Migration 8, idempotent, dialect-aware). Upgradepfade 0.6.x–0.9.4 → 0.9.5
  (SQLite & MySQL) verifiziert; keine Datenverluste.

## [0.9.4] – 2026-06-13

### Added – Enterprise Backup & Restore

- **Wiederherstellung** (`Administration → Sicherung → Wiederherstellung`):
  Backups prüfen, herunterladen, hochladen und wiederherstellen. Listet lokale
  und hochgeladene Backups mit Dateiname, Größe, Datum, Anwendungsversion,
  Datenbanktyp, Schema-Version und Quelle.
- **Restore-Dialog** mit Pflicht-Bestätigung („WIEDERHERSTELLEN" eingeben) und
  deutlicher Warnung. Vor jeder Wiederherstellung wird automatisch ein
  **Sicherheitsbackup** (`pre_restore_*.zip`) erzeugt.
- **Versionsübergreifender Restore**: Ältere Backups (0.6.x–0.9.3) werden
  unterstützt; nach dem Einspielen werden fehlende Tabellen angelegt und alle
  ausstehenden Migrationen automatisch ausgeführt (SQLite & MySQL). Kein
  manueller Eingriff nötig.
- **Backup-Download** als Streaming/Chunked-Transfer (auch große Dateien, nicht
  komplett im RAM). **Upload** großer Backups in 1-MiB-Chunks, isoliert
  gespeichert, erst nach Integritätsprüfung übernommen.
- **Backup-Prüfung** (verify) mit Ampel: grün (verwendbar), gelb (verwendbar
  mit Hinweisen), rot (nicht verwendbar).
- **Backup-Metadaten** in jedem Archiv (`backup_meta.json`): Anwendungsversion,
  Datenbanktyp, Schema-Version, Erstellungsdatum, Backup-Typ – für
  Kompatibilitätsprüfungen.
- **Restore-Historie** (`restore_runs`): Zeitpunkt, Benutzer, Datei, Version,
  DB-Typ, Sicherheitsbackup, ausgeführte Migrationen, Ergebnis.

### Added – Eigenes Backup-Logging

- Neuer Logkanal **`logs/backup.log`** für alle Backup-/Restore-/Upload-/
  Verbindungstest-/Aufbewahrungs-/Integritätsvorgänge (Zeitpunkt, Benutzer,
  Jobname, Ziel, Dateiname, Größe, Dauer, Ergebnis). Passwörter/Zugangsdaten
  werden niemals protokolliert. In `Administration → Logs` filter-, such- und
  herunterladbar.
- Logging-Konfiguration um **Backup-Logging** und **Restore-Logging** erweitert
  (persistent im config-Volume).
- Audit-Log um Backup-Ereignisse erweitert (manuell gestartet, gelöscht,
  hochgeladen, wiederhergestellt, Job erstellt/geändert, Ziel geändert).

### Changed

- Systemstatus zeigt zusätzlich letztes erfolgreiches Backup, letzten
  Backupfehler, letzte Wiederherstellung und letzte Backupprüfung.
- Navigation „Sicherung" um **Wiederherstellung** und **Restore-Historie**
  erweitert.

### Notes

- Schemaänderung: neue Tabelle `restore_runs` (Migration 7, idempotent,
  dialect-aware). Upgradepfade 0.6.x–0.9.3 → 0.9.4 (SQLite & MySQL) verifiziert;
  keine Datenverluste. Uploads werden auf Dateityp, Archiv-Integrität und
  Path-Traversal geprüft und isoliert gespeichert.

## [0.9.3] – 2026-06-13

### Fixed – Backup-Job-Modal vollständig bedienbar

- Das Modal „Neuer Backup-Job" wird nie höher als der Viewport (`max-height:
  90vh`). Kopfzeile (Titel) und Fußzeile (Abbrechen, Verbindung testen,
  Speichern) bleiben immer sichtbar; nur der Inhaltsbereich scrollt. Damit
  werden die unteren Buttons auf Notebook-/Tablet-Auflösungen nicht mehr
  abgeschnitten.
- Kompakteres Layout (geringere Abstände, gruppierte Felder); dynamische Felder
  je Typ (Lokal/FTP/SMB) ohne Leerflächen. Zusätzlicher „Abbrechen"-Button.

### Changed – Administration-Navigation als echtes Akkordeon

- Es ist immer **maximal eine** Hauptgruppe geöffnet: Beim Öffnen einer Gruppe
  schließen sich die übrigen automatisch.
- **Desktop**: Gruppen öffnen per Hover und schließen automatisch, wenn der
  Mauszeiger die Navigation verlässt; Klick funktioniert weiterhin.
- **Mobile/Touch**: Accordion per Klick (kein Hover); das Öffnen einer Gruppe
  schließt die vorherige.
- Überarbeitete Hover-, Fokus- und Active-States; Dropdown-Panels ohne Lücke
  (kein Flackern beim Hover).

## [0.9.2] – 2026-06-13

### Added – Job-basierte Backup-Verwaltung

- Backups laufen jetzt als verwaltete **Backup-Jobs** (Tabelle `backup_jobs`):
  Liste aller Jobs mit Name, Typ, Aktiv, Zeitplan, Aufbewahrung, letzter
  Ausführung und letztem Ergebnis; Aktionen Bearbeiten, Sofort ausführen,
  Aktivieren/Deaktivieren, Löschen.
- **Neuer Backup-Job** öffnet ein Modal mit dynamischen Feldern je Typ:
  - Lokal: Zielpfad
  - FTP/FTPS: Server, Port, Benutzer, Passwort (maskiert), Zielpfad
  - SMB3: **ein** UNC-Pfad-Feld (`\\\\server\\share\\sub`) und **ein**
    Benutzerfeld (`benutzer`, `DOMAIN\\benutzer` oder `benutzer@domain.local`).
- **Verbindung testen** direkt im Modal (lokal/FTP/SMB), mit Ergebnis-/Fehlertext.
- **Backup-Inhalt** wählbar (Datenbank, Konfiguration, Logs – Mehrfachauswahl).
- **Zeitplan** je Job: manuell, täglich, wöchentlich, monatlich; ein
  In-Process-Scheduler führt fällige Jobs automatisch aus.
- **Aufbewahrung** je Job (Anzahl und/oder Tage), alte Backups werden
  automatisch entfernt (lokal vollständig, FTP/SMB best-effort).
- **Backup-Historie** (Tabelle `backup_runs`): Start, Ende, Dauer, Größe, Ziel,
  Status (Erfolg/Warnung/Fehler); Download lokaler Sicherungen.
- **Engine**: konsistente Datenbank-Sicherung (SQLite Online-Backup-API,
  MySQL via `mysqldump`), Integritätsprüfung nach jeder Sicherung
  (Datei vorhanden, plausible Größe, Archiv lesbar). Passwörter werden nie
  im Klartext geloggt. Eine vorhandene 0.9.0/0.9.1-Backup-Konfiguration wird
  beim Start in einen (inaktiven) Job übernommen.

### Changed – Administration-Navigation gruppiert

- Neue, gruppierte und einklappbare Navigation (`<details>`-Accordion) mit den
  Gruppen **Benutzer**, **Zeitverwaltung**, **Sicherung**, **System** und
  **Einstellungen**. Desktop als Dropdown-Panels, Mobile als Accordion; der
  offene/geschlossene Zustand wird pro Gruppe gemerkt (localStorage). Die Gruppe
  der aktiven Seite öffnet automatisch.

### Notes

- Schemaänderung: neue Tabellen `backup_jobs` und `backup_runs`
  (Migration 6, idempotent, dialect-aware via `create_all`). Upgradepfade
  0.6.x–0.9.1 → 0.9.2 für SQLite und MySQL verifiziert; keine Datenverluste.

## [0.9.1] – 2026-06-13

### Fixed

- „Schnell stempeln": Das Info-Symbol zeigte fälschlich den Freigabe-Hinweis
  der manuellen Buchung. Es wird wieder der Arbeitsschutz-Hinweis nach ArbZG
  angezeigt (Pausen: nach 6 Std mind. 30 Min, nach 9 Std mind. 45 Min) – bei
  aktiver automatischer Pausenkorrektur ergänzt um den Abzugs-Hinweis. Gilt für
  Web und Mobile.

## [0.9.0] – 2026-06-13

### Added – Professionelles Logging-System

- Dateibasiertes Logging (`app/logging_setup.py`) mit sechs rotierenden
  Kanälen im `logs`-Volume: `application.log`, `api.log`, `sync.log`,
  `security.log`, `error.log`, `audit.log`. Strukturiertes Format mit
  Zeitstempel, Log-Level, Kanal und Benutzerbezug.
- Größenbasierte Log-Rotation (max. Dateigröße + Generationen),
  konfigurierbar und persistent im `config`-Volume (`logging.json`).
- Optionale automatische Bereinigung rotierter Logs nach Alter.

### Added – Administration → System

- **Logs** (`/admin/system/logs`): Anzeige aller Kanäle mit Filter
  (Suchtext, Log-Level, Zeitraum), Einzel-Download, ZIP-Download mehrerer
  Logs, Leeren einzelner/aller Logs (mit Sicherheitsabfrage, nur Admins)
  sowie optionalem Auto-Refresh.
- **Systemstatus** (`/admin/system/status`): Version, Datenbankstatus/-typ,
  Benutzer-/Urlaubs-/Auftrags-Zahlen, Speicherinformationen (DB-, config-,
  logs-Größe, freier Speicher), Synchronisation, PWA-Status und Volume-Übersicht
  (Pfad, Größe, Dateianzahl, letzte Änderung).
- **Fehlerübersicht** (`/admin/system/errors`): Fehler 24 h / 7 Tage,
  häufigste Fehler, Fehler nach Kategorie, Direktsprung zu den Logs.
- **Systemeinstellungen** (`/admin/system/settings`): Log-Level, Logging-Toggles,
  Rotation und Synchronisationsparameter; persistent im `config`-Volume.
- **Backups** (`/admin/system/backups`): Übersicht (letzte Sicherung, Datum,
  Größe, Speicherort) und manuelles Erstellen einer ZIP-Sicherung von
  Datenbank + Konfiguration.

### Added – Audit-Logging, Health, Import/Export

- Audit-Protokollierung für Login/Logout, Passwort-, Benutzer-, Rollen-,
  Urlaubs-, Feiertags- und Systemeinstellungsänderungen sowie Log-Aktionen.
- `/health` liefert nun einen detaillierten Statusbericht (Datenbank,
  Konfiguration, Volumes, Schreibrechte) inkl. korrektem HTTP-Status.
- Export/Import der Systemeinstellungen und der Feiertagskonfiguration als JSON
  (mit Validierung vor der Übernahme).

### Added – Persistente Volumes & Start-up-Prüfung

- Zentrale Volume-Auflösung (`app/paths.py`) für `config`, `data`, `logs`
  inkl. Umgebungsvariablen-Overrides. Beim Start werden fehlende Verzeichnisse
  angelegt und das Ergebnis im `application.log` dokumentiert.

### Changed – Dashboard & Arbeitsschutz-Hinweis

- Dashboard-Reihenfolge: Mein Soll-/Ist-Stunden → Urlaubsübersicht →
  Feiertagsübersicht. Die doppelte Feiertagsanzeige im unteren Bereich
  wurde entfernt – Feiertage erscheinen nur noch einmal.
- Arbeitsschutz-Hinweis ist nun kontextabhängig: Der Freigabe-Hinweis wird
  immer angezeigt; der Hinweis zu automatischen gesetzlichen Pausen nur, wenn
  `auto_break_deduction` aktiv ist (Web und Mobile, inkl. Info-Tooltip).

### Added – Feiertagsverwaltung überarbeitet (§22)

- Jahres-Dropdown entfernt; es gilt automatisch das aktuelle Kalenderjahr.
- Einzige Auswahl ist das Bundesland; Aktion „**Feiertage übernehmen**" lädt,
  speichert und übernimmt die gesetzlichen Feiertage des aktuellen Jahres.
- Neues Feld `Holiday.source` (`statutory`/`custom`): Eigene Feiertage werden
  beim Übernehmen nie überschrieben, es entstehen keine Duplikate. Bestehende
  Einträge gelten als `custom` (Default), bleiben also erhalten.

### Added – Optionale MySQL-Unterstützung (§23)

- Datenbankwahl über `DATABASE_URL` (Standard bleibt SQLite); MySQL 8+/MariaDB
  via PyMySQL. Engine dialect-aware (Pool-Pre-Ping für MySQL).
- Alle `String`-Spalten haben jetzt explizite Längen (MySQL-kompatibel).
- Migrationen sind dialect-aware: Versionsstand wird in der portablen Tabelle
  `schema_migrations` geführt (statt SQLite-`PRAGMA user_version`), bestehende
  SQLite-Installationen werden transparent übernommen. Migrationen laufen
  automatisch beim Start, sind idempotent und datenerhaltend.

### Fixed – Offline-Aktionszähler (§24)

- „Offene Offline-Aktionen" im Systemstatus zählte fälschlich den
  Idempotenz-/Dedup-Log bereits verarbeiteter Aktionen (`mobile_sync_actions`).
  Der Server verarbeitet Offline-Aktionen synchron und hat keine serverseitige
  Warteschlange – der Wert ist nun korrekt 0. Verarbeitete Aktionen werden
  separat als Gesamtzahl ausgewiesen.

### Added – Synchronisationsdiagnose & Systemstatus (§24/§26)

- Neuer Bereich **Administration → Synchronisation** (`/admin/system/sync`):
  offene Aktionen, laufende/fehlerhafte Synchronisationen, Retry-Versuche,
  letzte erfolgreiche Synchronisation, verarbeitete Offline-Aktionen.
- Systemstatus zeigt Datenbanktyp, DB-Version, letzte und ausstehende
  Migrationen.

### Added – Backup-Ziele & -Verwaltung (§25/§26)

- Backup-Ziele **lokal**, **FTP/FTPS** und **SMB3** (Windows-kompatible Pfade,
  Auth mit Benutzer/Passwort/Domäne). Konfiguration persistent im
  config-Volume; Passwörter werden nie im Klartext geloggt.
- „Verbindung testen", konfigurierbare Aufbewahrung (Anzahl/Dauer),
  Integritätsprüfung nach jeder Sicherung (Datei/Größe/Archiv lesbar),
  Backup-Historie mit Ergebnis, optionales Einschließen der Logs.

### Notes

- Schemaänderung in dieser Version: `holidays.source` (Migration 5,
  idempotent, dialect-aware, Default `custom`). Upgradepfade
  0.6.x/0.7.x/0.8.x → 0.9.0 für SQLite und MySQL über `schema_migrations`
  verifiziert (Daten bleiben erhalten). Neue Abhängigkeiten: `PyMySQL`,
  `smbprotocol`.

## [0.8.1] – 2026-06-13

### Added – Benutzerauswertung (Zeitübersicht je Benutzer)

- Neue Auswertung unter **Administration → Benutzerauswertung**
  (`/admin/reports/users`): frei wählbarer Zeitraum, Auswahl einzelner
  oder mehrerer Benutzer (ohne Auswahl: alle). Je Benutzer werden
  Buchungen, Arbeitszeit, Pausen, Soll, Urlaub, Überstundenabbau und
  Über-/Minusstunden ausgewiesen, inkl. Summenzeile.
  (Krankheit ist im Datenmodell nicht vorhanden und daher nicht enthalten.)
- **PDF-Export** im bestehenden Report-Layout
  (`/admin/reports/users/pdf`).
- **Excel-Export** (`/admin/reports/users/excel`): ein Benutzer pro
  Zeile, Dezimalstunden mit Zahlenformat, fixierte Kopfzeile – geeignet
  für Weiterverarbeitung.

### Added – Konfigurierbare gesetzliche Pausen

- Neues Benutzerfeld `auto_break_deduction` (Standard: aktiviert).
  Checkbox „Automatische gesetzliche Pausen anwenden (ArbZG)" unter
  Benutzer bearbeiten → Zeitkonto & Buchungen.
- Deaktiviert: keine automatische Pausenkorrektur mehr – es zählen nur
  tatsächlich gestempelte Pausen. Aktiviert: bisheriges Verhalten.
- Migrationssicher: `ensure_schema()` ergänzt die Spalte mit Default 1
  beim Start, zusätzlich versionierte Migration 4 in
  `app/db_migrations.py`. Bestehende Benutzer behalten das bisherige
  Verhalten.

### Changed – Feiertagsverwaltung vereinfacht

- „Jahr synchronisieren"-Formular und „Feiertage laden"-Button entfernt;
  die Endpunkte `POST /admin/holidays/sync` und `POST /api/holidays/sync`
  wurden ersatzlos gestrichen.
- Feiertage werden jetzt automatisch verwaltet: beim Anwendungsstart
  werden aktuelles und nächstes Jahr für die konfigurierte Region
  sichergestellt; die Verwaltungsseite lädt fehlende Jahre weiterhin
  automatisch beim Aufruf. Manuelles Anlegen/Löschen bleibt erhalten.

### Added – Feiertage im Dashboard

- Neue kompakte Sektion „Nächste Feiertage" in der Dashboard-Seitenleiste
  direkt unter „Meine Soll-/Ist-Stunden" (bis zu 5 kommende Feiertage,
  token-basiert und damit Dark-Mode-kompatibel).

### Added – AGENTS.md

- Neuer Leitfaden für Entwicklungsagenten mit verpflichtenden Regeln für
  Datenbankschema-Prüfung, idempotente Migrationen, versionsübergreifende
  Upgrades (0.6.x/0.7.x/0.8.0 → 0.8.1) und Vor-Deployment-Checks.

### Grund der Versionsanhebung

Patch-/Minor-Mischung bewusst als 0.8.1 gemäß Vorgabe: neue Auswertung und
Benutzereinstellung, vereinfachte Feiertagsverwaltung, keine Breaking
Changes; Migrationen halten alle Bestandsdaten.

## [0.8.0] – 2026-06-13

### Changed – PDF-Reports grundlegend überarbeitet (`app/pdf_export.py`)

- **Keine Überlappungen mehr:** jede Tabellenzelle wird als umbruchfähiger
  `Paragraph` gerendert (inkl. XML-Escaping von Nutzereingaben). Lange
  Firmennamen, Kommentare oder Status brechen sauber innerhalb ihrer Spalte
  um, statt in Nachbarspalten zu laufen oder abgeschnitten zu werden.
- **Bessere Seitennutzung:** kompakter Kopf (Titel 15pt linksbündig + eine
  Metazeile statt großem zentriertem Titel mit Doppel-Spacern), Ränder
  20mm → 14mm seitlich / 12mm oben, kompakte Zellenpaddings und 8pt-Schrift
  in Tabellen, Kennzahlen + Urlaubskonto bzw. Zusammenfassung +
  Statusverteilung nebeneinander statt untereinander.
- **Einheitliches Tabellen-Stilsystem** für beide Reports (Kopfzeile,
  Zebra-Streifen, Gitter, rechtsbündige Zahlenspalten, wiederholte
  Kopfzeile bei Seitenumbruch, Summenzeile) statt sechsfach kopierter
  Einzel-Styles.
- **Fußzeile mit Seitenzahl** auf jeder Seite (auch im Team-Report, der
  zuvor gar keine Fußzeile hatte).
- **Fix:** Im Team-Report stand die Summe der Einzelbuchungen in der
  Spalte „Ende" statt „Arbeitszeit".

### Added – Urlaubsübersicht im PDF

- Beide Reports enthalten eine Tabelle „Urlaubsübersicht" mit Zeitraum,
  Typ (Urlaub/Überstundenabbau), Status (Genehmigt, Offen, Abgelehnt,
  Storniert, Rücknahme angefragt), Arbeitstagen, Stunden-Anrechnung (nur
  bei genehmigten Anträgen) und Kommentar – für dieselbe Periode wie der
  Report. Die Kennzahlen-Berechnung nutzt unverändert nur genehmigte
  Anträge.

### Changed – Arbeitsschutz-Hinweis als Info-Tooltip

- Der dauerhaft sichtbare ArbZG-Hinweis (Desktop-Dashboard, Mobile-App,
  Offline-Shell) ist jetzt ein kleines (i)-Symbol neben „Schnell stempeln":
  Hover/Fokus zeigt den Tooltip (Desktop), Tippen öffnet/schließt ihn
  (Mobile), Escape schließt. Token-basiert, Dark-Mode-kompatibel, absolut
  positioniert (keine Layoutverschiebung).

### Grund der Versionsanhebung

Minor (`0.7.0` → `0.8.0`): neue Reportinhalte (Urlaubsübersicht) plus
Layout-/Usability-Überarbeitung ohne Änderung bestehender Geschäftslogik.

## [0.7.0] – 2026-06-13

### Added – Dark Mode (vollständig, umschaltbar)

- **Umschalter Hell/Dunkel** im Desktop-Header und im Mobile-Footer
  (auch in der Offline-Shell der PWA). Die Wahl wird in `localStorage`
  (`erfassung-theme`) gespeichert und bleibt beim Neuladen erhalten; ohne
  gespeicherte Wahl folgt die App der Systemeinstellung
  (`prefers-color-scheme`).
- **Kein Flackern:** ein Inline-Snippet im `<head>` wendet das gespeicherte
  Theme vor dem ersten Paint an; `static/theme.js` (neu, im Service-Worker-
  Precache) verdrahtet die Toggle-Buttons und hält `theme-color` synchron.
- **Dunkle Palette** (kein reines Schwarz): Hintergrund `#0f172a`, Flächen
  `#111827`, Karten `#1e293b`, Rahmen `#334155`, Text `#f8fafc`, gedämpfter
  Text `#94a3b8`, Primärfarbe `#3b82f6`. Umgesetzt ausschließlich als
  Token-Overrides unter `:root[data-theme="dark"]` – keine komponentenweisen
  Sonderfälle.

### Changed – Design-System konsequent durchgezogen

- **Radius-Skala als einzige Quelle:** `--radius-xs` 3px (Tabs, Badges,
  Chips), `--radius-sm` 5px (Buttons, Inputs, Selects), `--radius-md` 6px,
  `--radius-lg` 8px (Karten, Dialoge). Alle fest codierten `border-radius`-
  Werte (inkl. `50%` beim Mobile-Einstellungsbutton) entfernt; nichts ist
  mehr runder als 8px.
- **Einheitliche Control-Höhen:** `--control-h` (2.5rem) für Inputs, Selects
  und Buttons; `--control-h-sm` (2rem) nur für kompakte Tabellen-Buttons.
  Filterleisten (u. a. „Feiertage verwalten", Buchungen, Zeitübersichten)
  haben jetzt durchgehend gleiche Höhen in einer Zeile.
- **Navigation modernisiert:** kompakter Sticky-Header (3.5rem), SVG-Icons
  statt Emojis, ruhige Hover-Zustände (neutraler Wash), klarer aktiver
  Zustand; Bereichs-Tabs (Admin, Buchungen/Urlaub) als Underline-Tabs statt
  Pill-Container; Footer als dezente Trennlinie statt blauem Balken.
- **Alle Farben tokenisiert:** sämtliche hartcodierten Hex-/RGBA-Werte in
  `styles.css` (Modals, Login, Alerts, Formulare, Tabellen-Streifen,
  Status-Badges, Mobile-Listen …) durch Design-Tokens ersetzt – Voraussetzung
  dafür, dass der Dark Mode überall greift. Einzige Ausnahme: der QR-Code
  behält bewusst einen weißen Hintergrund (Scanbarkeit).
- **Manifest/Theme-Color** auf die aktuelle Palette aktualisiert
  (`#2563eb`, Hintergrund `#f8fafc`).

### Grund der Versionsanhebung

Minor (`0.6.0` → `0.7.0`): neues Feature (umschaltbarer Dark Mode) plus
sichtbares, aber rein darstellungsbezogenes Design-Refactoring.

## [0.6.0] – 2026-06-12

### Changed – UI-Redesign (modernes SaaS-/Business-Erscheinungsbild)

Reines Design-/UX-Update – **keine** Änderung an Funktionen, APIs, Datenmodell,
Synchronisation, Offline-Funktion oder Geschäftslogik. Betroffen ist
ausschließlich `static/styles.css`.

- **Design-System / Tokens:** zentrale `:root`-Token-Ebene (Farben, Radien,
  Schatten, Status, Focus-Ring). Alle Komponenten konsumieren diese Tokens, wodurch
  Desktop und Mobile durchgängig wie ein Produkt wirken.
- **Farbpalette:** tiefes Blau als Primärfarbe (`#2563eb` / Hover `#1d4ed8`),
  Slate-Neutraltöne, ruhiger Hintergrund (`#f8fafc`), weiße Karten. Statusfarben
  vereinheitlicht: Grün (aktiv), Amber (Pause), Blau (Urlaub/Info), Rot (Fehler).
- **Kanten statt Pillen:** kleine Border-Radien (Buttons/Inputs/Badges 6px, Karten
  /Dialoge 8px); alle `999px`-Pillen entfernt.
- **Buttons:** Primary (klare Fläche, dezenter Schatten, Hover, Focus-Ring),
  Secondary (zurückhaltender Neutral-Outline), Danger (klar rot).
- **Karten:** 1px-Rahmen + dezente Schatten statt starker Schlagschatten; mehr
  Ruhe, klare Trennung. KPI-Karten vereinheitlicht.
- **Tabellen:** ruhige Kopfzeile (Uppercase, gedämpft), Zeilen-Hover, bessere
  Lesbarkeit.
- **Mobile (`/mobile`):** Header, Tabs, Stempelbuttons, Auftrags- und
  Urlaubsansicht auf dasselbe Token-System umgestellt – wirkt wie eine
  installierbare Business-App, nicht wie eine Website.
- **Dark Mode:** vorbereitet (Token-Overrides unter `html[data-theme="dark"]`),
  bewusst **nicht** automatisch aktiv – Standard bleibt Hell.

### Grund der Versionsanhebung

Minor (`0.5.2` → `0.6.0`): umfassendes, sichtbares Redesign (nur Darstellung),
ohne funktionale Änderungen.

## [0.5.2] – 2026-06-12

### Fixed – Mobile-/PWA-Funktionen

- **Auftragsstart-Dialog blieb geöffnet:** `handleOfflineSubmission` setzte das
  Formular zwar zurück, schloss aber das Modal nicht. Nach erfolgreichem Start
  (queue-first, also immer erfolgreich) wird das umgebende Modal jetzt
  automatisch geschlossen; der Nutzer sieht wieder die normale Ansicht.
- **Urlaubsanträge verschwanden nach der Synchronisation:** Die mobile Urlaubsliste
  wurde nur serverseitig (beim Online-Laden) bzw. für Offline-Entwürfe befüllt –
  es gab **keine** clientseitige Darstellung aus dem gecachten Snapshot. Nach
  Sync/Reload waren synchronisierte Anträge daher nicht mehr sichtbar. Neu:
  `renderVacations()` zeigt **alle Anträge des laufenden Jahres** (offen,
  genehmigt, abgelehnt, storniert, Rücknahme angefragt sowie noch nicht
  synchronisierte Offline-Anträge) mit Zeitraum, Typ und Status. Backend:
  `/mobile/sync-data` liefert Urlaubsanträge nun für das **gesamte laufende Jahr**
  (zuvor nur das `days`-Fenster).
- **Synchronisationsanzeige zeigte Phantom-Aktionen („4 Offline-Aktionen warten"
  trotz Sync):** In der Queue konnten Aktionen dauerhaft hängen bleiben – etwa
  ein verwaister Stempel-Stopp (`end_*`), dessen Buchung serverseitig längst
  geschlossen ist und der mit `retryable` beantwortet wurde (das blockierte zudem
  die übrige Queue). `flushOfflineQueue` entfernt eine Aktion jetzt bei **jeder
  eindeutigen Server-Antwort** (Erfolg, Duplikat oder definitive Ablehnung);
  nur bei echten Transport-/Auth-Fehlern bleibt sie erhalten. Echte
  Reihenfolge-Abhängigkeiten bleiben über den Transientfehler-Pfad gewahrt.
  Ergebnis: Der Zähler entspricht exakt dem Queue-Zustand – keine Phantom-Einträge.

### Nicht verändert (Offline-Architektur erhalten)

- Offline-Start, Service Worker, IndexedDB-Speicherung, Offline-Stempelungen,
  Sync-Queue, Wiederanlauf, Idempotenz/Duplikatvermeidung und automatische
  Synchronisation bleiben unverändert (per Regressionstest bestätigt).

### Grund der Versionsanhebung

Patch (`0.5.1` → `0.5.2`): gezielte Korrekturen dreier Mobile-Funktionen ohne
Eingriff in die Offline-Architektur, Datenmodell oder Geschäftslogik.

## [0.5.1] – 2026-06-11

### Fixed – Regressionen nach dem 0.5.0-Offline-Refactoring

- **Navigation reagierte erst beim zweiten Klick & Administration nicht
  erreichbar (gleiche Ursache):** Mit 0.5.0 wurde der Service Worker erstmals im
  Scope `/` aktiv. Sein `offlineFirstNavigation` bediente daraufhin **jede**
  Navigation cache-first aus dem einen `/mobile`-Cache-Eintrag. Folge: andere
  Seiten (`/dashboard`, `/admin`, `/records/*`) zeigten beim ersten Klick den
  zuvor gecachten Inhalt und erst der zweite Klick die richtige Seite; der
  legitime `303`-Redirect von `/admin` → `/admin/users` wurde nie befolgt
  („Administration nicht erreichbar"). Der Worker bedient nun **ausschließlich
  die `/mobile`-Route** offline-first; alle übrigen Navigationen gehen direkt
  ans Netzwerk und funktionieren beim ersten Klick. Offline-Verhalten von
  `/mobile`, Caching statischer Assets und die Sync-Logik bleiben unverändert.
- **Arbeitszeitverlauf falsch sortiert:** Zwei Ansichten sortierten aufsteigend
  (ältester Eintrag oben). Sie zeigen jetzt **neueste Einträge zuerst**:
  - Desktop-Dashboard „Heute" (`_build_daily_overview`).
  - Administration → Zeitberichte inkl. PDF-/Excel-Export (`entries_sorted`;
    Datum/Startzeit absteigend, Name aufsteigend als Tiebreaker).
  Geändert wurde ausschließlich die Anzeige-/Export-Reihenfolge – Zeitstempel,
  Arbeits-/Pausenzeiten, Summen, Datenbank und Synchronisation bleiben unberührt.
  (Mobile Tages-/Wochenansicht, Buchungsliste und Freigaben waren bereits
  absteigend bzw. Kalenderraster und blieben unverändert.)

### Grund der Versionsanhebung

Patch (`0.5.0` → `0.5.1`): gezielte Regressionsbehebung, keine Änderung an den
Offline-Komponenten (Start, Service-Worker-Caching, IndexedDB, Queue, Sync,
Duplikatvermeidung).

## [0.5.0] – 2026-06-11

### Fixed – Offline-PWA zuverlässig gemacht

- **Offline-Start scheiterte (Safari/iOS: „Seite nicht gefunden"):**
  Der Service Worker wurde unter `/static/sw.js` ausgeliefert, aber mit
  `{scope: '/'}` registriert. Der maximal erlaubte Scope eines Workers ist sein
  eigener Pfad (`/static/`); ein breiterer Scope erfordert den Header
  `Service-Worker-Allowed`, den `StaticFiles` nicht sendet. Dadurch wurde die
  **Registrierung vom Browser abgelehnt**, das `install`-Event lief nie, nichts
  wurde vorab gecacht – die App konnte offline nicht starten. Der Worker wird nun
  von der Wurzel (`GET /sw.js`) mit `Service-Worker-Allowed: /` ausgeliefert und
  als `/sw.js` registriert, sodass Scope `/` gültig ist und `/mobile` offline
  bedient wird.
- **Offline-Stempelungen wurden nicht vollständig synchronisiert (v. a.
  Arbeitsende):** Mehrere zusammenwirkende Ursachen behoben:
  1. `postQueuedAction` nutzte `redirect: 'manual'` und wertete **jede**
     303-Antwort als „Sitzung abgelaufen". Da `/punch` bei Erfolg immer per 303
     antwortete, schlug jede erfolgreiche Buchung clientseitig fehl. Die
     Endpunkte liefern bei `Accept: application/json` nun eine **maschinenlesbare
     JSON-Antwort** (`{ok, duplicate, retryable, message}`).
  2. `processPunchSubmission` **verwarf** Ereignisse vor dem Speichern anhand
     einer clientseitigen Zustandsprüfung. In Kombination mit einem eingefrorenen
     Lade-Zustand führte das dazu, dass das **Arbeitsende verworfen** wurde. Jede
     Buchung wird jetzt **immer** zuerst in IndexedDB gespeichert.
  3. `flushOfflineQueue` löschte nicht gesendete Aktionen aufgrund clientseitiger
     Vermutung (Datenverlust). Es wird nun **jede** Aktion in Erstellungsreihenfolge
     an den Server gesendet; entfernt wird sie nur bei eindeutiger Server-Antwort
     (Erfolg/duplikat). Server-Idempotenz (`client_action_id`) verhindert Dubletten.
  4. Der effektive Zustand wird nach jeder Synchronisation aus dem frischen
     Server-Snapshot aktualisiert (statt am eingefrorenen Lade-Zustand zu hängen).
- **Offline-Zeiten waren falsch (Sync-Zeit statt Ereigniszeit):** Der Server
  stempelte jede Buchung mit `datetime.now()`. Offline erfasste Ereignisse
  bekamen damit die (spätere) Synchronisationszeit – ein um 8 h versetzter
  Arbeitstag wurde z. B. mit Dauer 0 erfasst. Der Client sendet nun die echte
  lokale Ereigniszeit (`event_time`), die der Server verwendet (mit Plausibilitäts-
  Grenzen). Online-Buchungen verhalten sich unverändert.
- **Robustheit:** Eine `start_work`-Buchung, deren Intervall sich mit einer
  vorhandenen Buchung überschneidet, liefert jetzt eine saubere, endgültige
  Fehlerantwort statt eines HTTP 500 (das ein Offline-Client endlos wiederholt
  hätte).

### Unverändert / kompatibel

- Normale Browser-Formular-POSTs (`Accept: text/html`) erhalten weiterhin die
  klassische 303-Weiterleitung – die Desktop-Web-Oberfläche ist nicht betroffen.
- CSRF-Schutz, Datenmodell und Geschäftslogik bleiben unverändert.

### Grund der Versionsanhebung

Minor (`0.4.0` → `0.5.0`): überarbeitete Offline-Synchronisations-Engine inkl.
neuem JSON-Sync-Vertrag und client-seitigen Ereigniszeitstempeln.

## [0.4.0] – 2026-06-11

### Added

- **Konsolen-Benutzerverwaltung (`app/manage.py`):** Neues CLI-Werkzeug zur
  Administration ohne Web-Oberfläche – ideal für Notfälle (z. B. verlorener
  Admin-Zugang) und Erstinbetriebnahme.
  - `list-users` – alle Benutzer auflisten (ID, Benutzername, Name, E-Mail,
    Gruppe, Admin, Passwortwechsel-Flag).
  - `list-groups` – Gruppen inkl. Admin-Kennzeichen auflisten.
  - `create-user` – Benutzer anlegen (Passwort interaktiv, per `--password`
    oder `--random`; Gruppenzuordnung per ID/Name; `--weekly-hours`;
    `--no-force-change`).
  - `reset-password` – Passwort per `--username` oder `--id` zurücksetzen
    (interaktiv, `--password` oder `--random`; `--force-change/--no-force-change`).
  - Aufruf im Container: `docker exec -it erfassung python -m app.manage <befehl>`.
  - Nutzt dieselbe DB (`DATABASE_URL`), Passwort-Hashing (PBKDF2) und
    Stärke-Prüfung wie die Web-App; PIN-Vergabe erfolgt automatisch.
- **README:** Abschnitt „Benutzerverwaltung über die Konsole (CLI)" mit Anleitung
  und Beispielen ergänzt.

### Grund der Versionsanhebung

Minor (`0.3.8` → `0.4.0`): additive neue Funktionalität (Administrations-CLI). Keine
Änderung an bestehender Web-/Geschäftslogik, am Datenmodell oder an Endpunkten.

## [0.3.8] – 2026-06-11

### Fixed

- **Anmeldung mit „403 – Ungültige Sitzung" repariert (zwei zusammenhängende
  Fehler in der CSRF-Absicherung):**
  1. **Middleware-Reihenfolge:** Starlette wendet Middleware in umgekehrter
     Registrierungsreihenfolge an – die zuletzt registrierte läuft *außen*. Die
     `CSRFMiddleware` war nach der `SessionMiddleware` registriert und lief damit
     *vor* ihr. Beim CSRF-Check war die Session daher noch nicht geladen
     (`scope["session"]` fehlte), sodass **jeder** POST – inklusive `/login` –
     mit `403` abgewiesen wurde. Reihenfolge korrigiert (CSRF zuerst, Session
     zuletzt registriert ⇒ Session läuft außen).
  2. **Request-Body wurde verbraucht:** Die `CSRFMiddleware` (vormals
     `BaseHTTPMiddleware`) las das Formular per `await request.form()`, wodurch
     der Body-Stream geleert wurde und der `/login`-Handler keine Felder mehr
     erhielt (`422 Field required`). Die Middleware ist nun eine **reine
     ASGI-Middleware**, die den Body puffert und über ein frisches
     `receive`-Callable an die Anwendung **weiterreicht**.
  Ergebnis: Anmeldung funktioniert wieder; falsche Zugangsdaten liefern wieder
  die reguläre Fehlermeldung (HTTP 400) statt eines 403, und fehlende/ungültige
  CSRF-Token werden weiterhin korrekt mit 403 abgelehnt.

### Grund der Versionsanhebung

Patch (`0.3.7` → `0.3.8`): Behebung eines kritischen Fehlers, der die Anmeldung
vollständig blockierte. Keine Änderung an Datenmodell oder Geschäftslogik.

## [0.3.7] – 2026-06-11

### Fixed

- **Docker-Image in Portainer deploybar (behebt „error 500" beim Deploy):**
  Der Build (`docker/build-push-action@v6`) hängte standardmäßig
  Provenance-/SBOM-Attestations an das Image. Dadurch wurde das Image als
  **OCI Image Index** veröffentlicht, der zusätzlich ein Attestation-Manifest mit
  `platform: unknown/unknown` enthält. Dieser Zusatz-Eintrag bringt Portainer und
  ältere Docker-/Registry-Tooling beim Deploy zum Fehler („no matching manifest" /
  HTTP 500). Der Workflow erzeugt nun mit `provenance: false`, `sbom: false` und
  explizitem `platforms: linux/amd64` ein **schlankes Single-Platform-Manifest**
  (identisch zu `docker build && docker push`). Das Image `:0.3.7` ist damit ohne
  Sonderbehandlung deploybar.

### Grund der Versionsanhebung

Patch (`0.3.6` → `0.3.7`): reiner Build-/Auslieferungs-Fix. Es wurde kein
Anwendungscode geändert. Eigene Version (statt Überschreiben von `0.3.6`), damit
Portainer/Docker garantiert ein frisches, sauberes Manifest ziehen und kein zuvor
gecachter `0.3.6`-Index verwendet wird.

## [0.3.6] – 2026-06-11

### Hintergrund

Die mobile Oberfläche (`/mobile`) ist bereits seit `0.3.5` eine offline-first PWA
(Service Worker, IndexedDB-Datenhaltung, Offline-Aktionsqueue mit Idempotenz und
Reconnect-Synchronisation). Mit `0.3.6` wird diese PWA produktionshärtend
vervollständigt – minimal-invasiv, ohne Eingriff in die Business-Logik.

### Changed / Fixed

- **Automatische Service-Worker-Versionierung (behebt Stale-Cache-Risiko):**
  Der Cache-Name in `static/sw.js` war fest auf `erfassung-mobile-v0.3.5`
  verdrahtet. Wurde `VERSION` erhöht, ohne die Datei manuell anzupassen, blieb der
  alte Cache aktiv und Clients konnten auf veralteten Assets „hängen bleiben".
  Der Cache-Name wird nun zur Laufzeit aus dem `?v=`-Parameter der
  SW-Registrierung abgeleitet (`new URLSearchParams(self.location.search)`), der
  wiederum aus `app_version` / `VERSION` stammt. Damit erzeugt jede Versionsanhebung
  automatisch einen neuen Cache; der alte wird beim `activate`-Event entfernt.
- **`static/app.js`** registriert den Service Worker jetzt mit der aus
  `import.meta.url` (`?v=…`) ermittelten Version statt mit einer hartcodierten
  Versionsnummer (`?v=0.3.5`).

### Added

- **Manifest vervollständigt** (`static/manifest.webmanifest`): Felder `id`
  (`"/mobile"`), `dir` (`"ltr"`) und `categories` (`["business", "productivity"]`)
  ergänzt. Das verbessert die eindeutige App-Identität (Installierbarkeit/Updates)
  und die Einordnung bei App-Store-/Launcher-Integrationen.
- **Dokumentation:** README um Abschnitte „Updates & Service-Worker-Versionierung"
  und „Installierbarkeit" erweitert; Versionsangabe von `0.1.7` auf `0.3.6`
  korrigiert. Diese Changelog-Datei sowie Release Notes
  (`docs/RELEASE_NOTES_0.3.6.md`) neu angelegt.

### Grund der Versionsanhebung

Patch-Release (`0.3.5` → `0.3.6`): Es handelt sich um Härtung und Vervollständigung
einer bestehenden Funktion (PWA/Offline), nicht um eine neue, brechende oder
umfangreiche Feature-Erweiterung. Es wurden keine bestehenden Endpunkte, Datenmodelle
oder die Business-Logik verändert.

## [0.3.5]

- Offline-first-PWA-Architektur der mobilen Oberfläche (Service Worker,
  IndexedDB, Offline-Queue mit `client_action_id`-Idempotenz,
  Reconnect-Synchronisation, Konfliktbehandlung per State-Replay).

## [0.3.4]

- Fix: HTTP-500 bei `/mobile/sync-data` behoben.

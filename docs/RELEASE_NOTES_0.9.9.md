# Release Notes – 0.9.9

Docker-/Container-/Datenbank-freundlich: **Erstinitialisierung über Docker ENV**,
**datenbankunabhängige (logische) Backups** und **Cross-Database Restore**.

## Docker-Erstinitialisierung über ENV (§1–§7)
- Bei einer Neuinstallation (noch keine `config/database.json`) wird die
  Datenbankkonfiguration aus `DB_*`-ENV-Variablen erzeugt, **persistiert**,
  getestet und migriert:
  `DB_TYPE`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSL`
  sowie `DB_PATH` (SQLite). Unterstützt: SQLite, MySQL, MariaDB, PostgreSQL.
- **ENV nur zur Erstinitialisierung**: Eine vorhandene Konfiguration wird
  verwendet und niemals überschrieben (`INIT_SOURCE = "file"`).
- Die Datenbank bleibt vollständig über **Administration → System → Datenbank**
  verwaltbar (wechseln, konfigurieren, testen, migrieren, Daten übernehmen).
- Die Seite zeigt die **Herkunft** der Konfiguration an (Docker ENV vs.
  Webinterface, `created_by`).
- `database.log` erfasst: ENV-Initialisierung erkannt, Konfiguration erstellt,
  Verbindung erfolgreich/fehlgeschlagen, Migration gestartet/erfolgreich/
  fehlgeschlagen. **Passwörter/Tokens/Secrets werden nie protokolliert.**

## Datenbankunabhängige Backups (§8–§9)
- Backups speichern die Daten **logisch** als JSON je Tabelle
  (`data/database.json`) – keine rohe SQLite-Datei und kein vendor-spezifischer
  Dump als primäre Methode.
- Jedes Archiv enthält Metadaten: `app_version`, `backup_format_version`,
  `database_type`, `schema_version`, `created_at` und Datensatzanzahlen –
  ausschließlich für Analyse, Kompatibilität und Vorschau (nie für automatische
  Datenbankwechsel).

## Cross-Database Restore (§10–§16)
- Ein Backup kann **unabhängig vom ursprünglichen Datenbanktyp** in die aktuell
  konfigurierte Datenbank wiederhergestellt werden
  (SQLite → PostgreSQL, MariaDB → PostgreSQL, PostgreSQL → SQLite, …).
- Ablauf: Backup analysieren → Daten extrahieren → ORM-Import in **einer
  Transaktion** (keine Teilimporte) → Migrationen → Integritätsprüfung.
- **Restore importiert ausschließlich Daten.** Der aktive Datenbanktyp, die
  Datenbankkonfiguration und die ENV-/Docker-Einstellungen bleiben unverändert.
- Vor jedem Restore wird automatisch ein Sicherheitsbackup (`pre_restore_*.zip`)
  erstellt (Rollback).
- **Restore-Vorschau** zeigt Backup- und Systeminformationen sowie den Hinweis,
  dass die Datenbankkonfiguration unverändert bleibt.
- Ältere Datei-Backups (vor 0.9.9) werden weiterhin typgleich wiederhergestellt
  (Abwärtskompatibilität) und beim Restore automatisch migriert (0.8.x → 0.9.9).

## Dokumentation
- README um **Docker Deployment** mit Stack-Vorlagen erweitert: PostgreSQL
  (empfohlene Referenz) ⭐, MariaDB ⭐, MySQL und SQLite – jeweils mit den
  Volumes `config`, `data`, `logs`.
- SQLite ist als Datenbank für Entwicklung/Tests/kleine Installationen
  gekennzeichnet, PostgreSQL/MariaDB als Produktivempfehlung.

## Regressionstests
`tests/test_v099.py` (10): Versions-Bump, ENV-Erstinitialisierung (Konfiguration
erzeugt + persistiert + Logeinträge), ENV überschreibt vorhandene Konfiguration
nicht, keine Secrets in Logs, Init-Herkunft auf der Datenbankseite, logisches
Backupformat + Metadaten, Export/Import-Roundtrip, Cross-Database Restore
(logisches Backup eines anderen DB-Typs ohne Konfigurationsänderung),
Cross-Database-Logging und die Restore-Vorschau.

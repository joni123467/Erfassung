# Release Notes – 0.9.4

Ausbau zur Enterprise-Backup-/Restore-Lösung, vollständig über das Webinterface
administrierbar.

## Wiederherstellung (neu)
- **Administration → Sicherung → Wiederherstellung**: lokale und hochgeladene
  Backups mit Dateiname, Größe, Datum, Anwendungsversion, Datenbanktyp,
  Schema-Version und Quelle.
- **Download** (Streaming/Chunked, auch große Dateien), **Prüfen** (Ampel
  grün/gelb/rot), **Details**, **Wiederherstellen**, **Löschen**.
- **Restore-Dialog** mit Pflichtbestätigung „WIEDERHERSTELLEN" und Warnung;
  automatisches **Sicherheitsbackup** vor jeder Wiederherstellung.

## Upload (neu)
- Backups hochladen (1-MiB-Chunks, nicht komplett im RAM), isolierte
  Zwischenspeicherung, Integritätsprüfung, dann Übernahme in die Verwaltung.
- Sicherheit: Dateityp-/Archivprüfung, Path-Traversal-Schutz, keine Ausführung.

## Versionsübergreifender Restore
- Ältere Backups (0.6.x–0.9.3) werden unterstützt. Nach dem Einspielen werden
  fehlende Tabellen angelegt und alle ausstehenden Migrationen automatisch
  ausgeführt (SQLite & MySQL) – ohne manuellen Eingriff.

## Backup-Logging (neu)
- Dedizierte Datei **`logs/backup.log`** für Backups, Restores, Uploads,
  Verbindungstests, Aufbewahrung und Integritätsprüfungen. Zugangsdaten werden
  nie protokolliert. In Administration → Logs filter-/such-/herunterladbar.
- Neue Logging-Optionen: Backup-Logging und Restore-Logging (persistent).

## Sonstiges
- Systemstatus: letztes erfolgreiches Backup, letzter Backupfehler, letzte
  Wiederherstellung, letzte Backupprüfung.
- Restore-Historie (`restore_runs`, Migration 7), Audit-Log um Backup-Ereignisse
  erweitert.
- Version durchgängig 0.9.4. Upgradepfade 0.6.x–0.9.3 → 0.9.4 verifiziert.

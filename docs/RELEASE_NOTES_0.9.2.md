# Release Notes – 0.9.2

Schwerpunkt: professionelle, **job-basierte Backup-Verwaltung** und eine
gruppierte, übersichtliche Administration-Navigation.

## Backup-Jobs

- **Administration → Sicherung → Backup-Jobs**: Liste aller Jobs mit Name, Typ,
  Aktiv-Status, Zeitplan, Aufbewahrung, letzter Ausführung und letztem Ergebnis.
- Aktionen je Job: Bearbeiten, Sofort ausführen, Aktivieren/Deaktivieren,
  Löschen.
- **Neuer Backup-Job** öffnet ein Modal mit dynamischen Feldern je Typ:
  - **Lokal**: Zielpfad
  - **FTP/FTPS**: Server, Port, Benutzer, Passwort, Zielpfad
  - **SMB3**: ein UNC-Pfad-Feld (`\\server\share\sub`) und ein Benutzerfeld
    (`benutzer`, `DOMAIN\benutzer` oder `benutzer@domain.local`)
- **Verbindung testen** direkt im Modal.
- **Inhalt** wählbar: Datenbank, Konfiguration, Logs (Mehrfachauswahl).
- **Zeitplan**: manuell, täglich, wöchentlich, monatlich – fällige Jobs werden
  automatisch ausgeführt.
- **Aufbewahrung** je Job (Anzahl und/oder Tage), automatische Bereinigung.

## Backup-Historie & Engine

- Historie mit Start, Ende, Dauer, Größe, Ziel, Status; Download lokaler
  Sicherungen.
- Konsistente Datenbank-Sicherung (SQLite Online-Backup-API, MySQL via
  `mysqldump`) und Integritätsprüfung nach jeder Sicherung.
- Passwörter werden nie im Klartext protokolliert.

## Navigation

- Gruppierte, einklappbare Administration-Navigation: **Benutzer**,
  **Zeitverwaltung**, **Sicherung**, **System**, **Einstellungen**. Desktop als
  Dropdown, Mobile als Accordion; Zustand wird gemerkt.

## Datenbank / Upgrade

- Neue Tabellen `backup_jobs` und `backup_runs` (Migration 6, idempotent,
  dialect-aware). Upgradepfade 0.6.x–0.9.1 → 0.9.2 für SQLite und MySQL
  verifiziert; bestehende Daten bleiben erhalten. Eine vorhandene
  0.9.0/0.9.1-Backup-Konfiguration wird automatisch in einen (inaktiven)
  Backup-Job übernommen.

# Release Notes – 0.9.0

Diese Version erweitert Erfassung funktional, administrativ und betrieblich.
Schwerpunkte: ein professionelles, dateibasiertes Logging-System, ein neuer
Administrationsbereich „System", konsequente Nutzung der persistenten Volumes
sowie ein bereinigtes Dashboard mit kontextabhängigem Arbeitsschutz-Hinweis.

## Highlights

### Logging-System
- Sechs rotierende Kanäle im `logs`-Volume: `application`, `api`, `sync`,
  `security`, `error`, `audit`.
- Strukturiertes Format: Zeitstempel | Level | Kanal | Benutzer | Meldung.
- Größenbasierte Rotation mit konfigurierbarer Dateigröße und Anzahl
  Generationen, persistent gespeichert.
- Optionale automatische Bereinigung alter rotierter Logs.

### Administration → System
- **Logs**: Filter (Suchtext, Level, Zeitraum), Einzel- und ZIP-Download,
  Leeren (mit Sicherheitsabfrage), optionaler Auto-Refresh.
- **Systemstatus**: Version, Datenbank, Kennzahlen, Speicher- und
  Volume-Informationen, Synchronisation, PWA.
- **Fehlerübersicht**: 24 h / 7 Tage, häufigste Fehler, Kategorien.
- **Systemeinstellungen**: Log-Level, Logging-Toggles, Rotation,
  Synchronisationsparameter (persistent im `config`-Volume) inkl.
  JSON-Export/-Import mit Validierung.
- **Backups**: Übersicht + manuelles Erstellen (Datenbank + Konfiguration).

### Audit & Betrieb
- Audit-Logging für sicherheits- und administrationsrelevante Aktionen.
- `/health` mit detailliertem Statusbericht (Datenbank, Konfiguration,
  Volumes, Schreibrechte) und korrektem HTTP-Status.
- Export/Import der Feiertagskonfiguration als JSON.

### Dashboard & Arbeitsschutz
- Neue Reihenfolge: Soll-/Ist-Stunden → Urlaub → Feiertage; doppelte
  Feiertagsanzeige entfernt.
- Arbeitsschutz-Hinweis kontextabhängig: Pausen-Hinweis nur bei aktiven
  automatischen gesetzlichen Pausen (Web und Mobile).

## Persistente Volumes
- `config`: Konfiguration (Systemeinstellungen, Logging, Sync, …)
- `data`: Geschäftsdaten (Datenbank, Backups, …)
- `logs`: Protokolle

Fehlende Volumes werden beim Start automatisch angelegt und im
`application.log` dokumentiert. Pfade lassen sich über
`ERFASSUNG_CONFIG_DIR`, `ERFASSUNG_DATA_DIR` und `ERFASSUNG_LOGS_DIR`
überschreiben.

## Datenbank / Upgrade
- Keine Schemaänderungen in 0.9.0 (Logging und Konfiguration sind
  dateibasiert).
- Upgradepfade 0.6.x / 0.7.x / 0.8.x → 0.9.0 über die bestehenden
  Migrationen verifiziert; vorhandene Daten bleiben erhalten.

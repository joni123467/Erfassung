# Release Notes – 0.9.5

Robustes, asynchrones Restore-System – behebt den „Internal Server Error" bei
der Wiederherstellung.

## Ursache
Der Restore lief synchron im HTTP-Request und tauschte die SQLite-Datei aus
bzw. verwarf den Datenbank-Pool (`engine.dispose()`). Damit wurde die
Verbindung des laufenden Requests zerstört → 500, obwohl die Wiederherstellung
oft bereits erfolgreich war.

## Lösung: asynchrones Restore
- Der Request **validiert** nur (Berechtigung, Datei, Integrität,
  Kompatibilität), erstellt einen **Restore-Job** und antwortet sofort.
- Ein **Hintergrund-Worker** führt den Restore aus (Sicherheitsbackup → DB-Swap
  → Migrationen) und meldet Fortschritt über eine **persistente Status-Datei**
  im `data`-Volume (übersteht DB-Tausch und Neustarts).

## Status-API & Fortschrittsseite
- `GET /api/restore/status` (Session-basiert, ohne DB-Zugriff) mit Zuständen
  `queued`, `creating_backup`, `restoring`, `restarting`, `running_migrations`,
  `completed`, `failed` inkl. Fortschritt, Meldung, Start-/Endzeit.
- Fortschrittsseite mit Balken und Schritten:
  Sicherheitsbackup → Wiederherstellung → Migrationen → Neustart → Abschluss.
- **Neustarterkennung**: Bei kurzzeitig nicht erreichbarem Backend wird nicht
  sofort ein Fehler angezeigt, sondern „Anwendung wird neu gestartet, Verbindung
  wird wiederhergestellt …" und weiter gepollt (alle 2,5 s).
- Nach Erfolg: **Countdown 5→1** und automatische Weiterleitung zu `/login`.
- Bei Fehler: Ursache, Zeitpunkt und Log-ID – kein nackter 500.

## Weiteres
- `backup.log` um alle Restore-/Migrationsschritte erweitert.
- Restore-Historie um Dauer und Log-ID erweitert (Migration 8).
- Systemstatus: letzte erfolgreiche/fehlgeschlagene Wiederherstellung, aktiver
  Restore-Job, letzte Migrationsausführung.
- Saubere DB-Verbindungsbehandlung (SQLite & MySQL).
- Version durchgängig 0.9.5. Upgradepfade 0.6.x–0.9.4 → 0.9.5 verifiziert.

## Regressionstests
`tests/test_v095.py` (11): async Restore ohne 500, Status-API (inkl. 401 ohne
Session), Fortschrittsseite, Sicherheitsbackup + vollständiges backup.log,
Fehlerfälle (ohne Bestätigung, defektes/fehlendes Backup), Migration 8,
Systemstatus-Felder. Gesamt: 66 Tests grün.

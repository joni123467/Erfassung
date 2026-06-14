# Release Notes – 0.9.8

Generische **Terminalverwaltung** ersetzt die bisherige TimeMoto-Konfiguration,
eine **korrigierte Datenbank-Konfiguration** und eine **verpflichtende
Dokumentations-/Versionspflege**.

## Neuer Bereich: Administration → Zeiterfassung → Terminals
- Zentrale Verwaltung aller Zeiterfassungsterminals – optisch und funktional
  analog zu den Backup-Jobs und der Benutzerverwaltung (Kartenlayout, Tabelle,
  kompaktes Modal, Dark-Mode-kompatibel, responsiv).
- Tabellenansicht mit **Name, Typ, Status, letzter Verbindung, letzter
  Synchronisation** und Aktionen: **Bearbeiten, Verbindung testen,
  Synchronisieren, Aktivieren/Deaktivieren, Löschen**.
- Button **„Neues Terminal“** (oben rechts) öffnet ein Modal analog zu „Neuer
  Backup-Job“ mit Terminaltyp-Auswahl.
- Statusanzeige je Terminal: **Online** (erreichbar), **Warnung** (instabil),
  **Offline** (nicht erreichbar), **Fehler** (Authentifizierung fehlgeschlagen).
- Synchronisationsergebnis je Lauf: letzte Synchronisation, Anzahl importierter
  Buchungen und Anzahl Fehler (Historie in `terminal_sync_history`).

## Treiber-/Plugin-Architektur
- `app/integrations/terminals/`: Jeder Terminaltyp ist ein `TerminalDriver`
  (`test_connection`, `synchronize`), der sich in einer Registry registriert.
- **Keine hartkodierte terminaltyp-spezifische Logik** in der Oberfläche – die
  UI kennt nur das Treiber-Interface. Weitere Typen (ZKTeco, Suprema, generische
  REST-/CSV-Terminals) lassen sich ohne Umbauten ergänzen.
- Treiber­spezifische Endpunkte/Optionen liegen in `Terminal.config_json`, sodass
  neue Typen ohne Schemaänderung auskommen.
- Mitgeliefert: Terminaltyp **TimeMoto** (Anlegen, Bearbeiten, Verbindung testen,
  Synchronisieren, Aktivieren/Deaktivieren).

## Migration der bisherigen TimeMoto-Integration
- Der eigene Menüpunkt „TimeMoto TM-616“ entfällt; `/admin/integrations/timemoto`
  leitet dauerhaft auf `/admin/terminals` um.
- Eine vorhandene `config/timemoto.json` wird beim Upgrade **automatisch und
  verlustfrei** als Terminal übernommen (Migration 9, idempotent).

## Datenbank-Konfiguration korrigiert
- Beim Wechsel des Datenbanktyps werden die Eingabefelder jetzt korrekt
  aktualisiert: SQLite zeigt nur den Datenbankpfad; MySQL/MariaDB/PostgreSQL
  zeigen Host, Port, Datenbankname, Benutzer, Passwort und SSL.
- Der **Standardport** wird beim Wechsel automatisch gesetzt (MySQL/MariaDB
  3306, PostgreSQL 5432) und der Platzhalter aktualisiert. Ein selbst
  eingetragener Port sowie bereits gespeicherte Werte (z. B. der Host) bleiben
  erhalten.
- Der Verbindungstest läuft stets gegen die aktuell eingestellte Konfiguration.

## Logging & Systemstatus
- Neuer Kanal **`terminal`** → `logs/terminal.log` (in Administration → Logs
  filter-/such-/downloadbar). Erfasst Terminal erstellt/geändert/gelöscht,
  Verbindungstest, Synchronisation gestartet/erfolgreich/fehlgeschlagen sowie
  Aktivierung/Deaktivierung – niemals Zugangsdaten.
- Neues Logging-Setting **„Terminal-Logging“**.
- Systemstatus erweitert um **Anzahl Terminals, Online-/Offline-Terminals,
  letzte Synchronisation und letzten Synchronisationsfehler**.

## Datenbankänderungen
- Neue Tabellen `terminals` und `terminal_sync_history` (Migration 9,
  automatisch, idempotent, ohne Datenverlust).
- Unterstützte Upgradepfade: `0.9.5 → 0.9.8`, `0.9.6 → 0.9.8`, `0.9.7 → 0.9.8`.

## Dokumentationspflicht
- README, Changelog und Versionsnummern müssen bei jedem Release übereinstimmen
  und gepflegt werden (siehe `AGENTS.md` → „Dokumentation & Versionspflege“).
  Abweichende Versionsnummern oder eine nicht aktualisierte README gelten als
  Release-Blocker.

## Weiteres
- Version durchgängig **0.9.8**.

## Regressionstests
`tests/test_v098.py` (12): Versions-Bump, Navigation (TimeMoto entfernt,
Terminals ergänzt, Redirect), Terminalseite, Treiber-Registry, kompletter
Terminal-Lebenszyklus (anlegen/bearbeiten/aktivieren/löschen, Passwort bleibt
erhalten), Verbindungstest gegen unerreichbaren Host, `terminal`-Logkanal und
-Setting, Terminalkennzahlen im Systemstatus, Datenbank-Port-Logik im Modal und
die automatische Übernahme einer Legacy-`timemoto.json`.

# Release Notes – 0.9.7

Vollständige **Datenbankverwaltung mit verlustfreier Migration** direkt über die
Weboberfläche. Das verwendete Datenbanksystem lässt sich nun zwischen SQLite,
MySQL, MariaDB und PostgreSQL umstellen – bestehende Daten werden automatisch
übernommen.

## Neuer Bereich: Administration → System → Datenbank
- Übersicht der aktiven Datenbank: Typ, Version, Host, Datenbankname,
  Tabellenanzahl, Größe, letzte/letzte erfolgreiche Migration, letzter Fehler.
- **Aktive Datenbank** als Dropdown mit Empfehlungskarten. **MariaDB** und
  **PostgreSQL** sind als empfohlene Produktivdatenbanken gekennzeichnet
  (⭐ Empfohlen). SQLite bleibt für Einzelplatz-/Test-/Entwicklungsumgebungen.
- **Datenbank konfigurieren** (Modal): SQLite zeigt den Datenbankpfad; MySQL/
  MariaDB/PostgreSQL zeigen Host, Port, Datenbankname, Benutzer, Passwort, SSL
  und Verbindungs-Timeout. Ein Info-Symbol (ⓘ) zeigt empfohlene und unterstützte
  Versionen je System. Funktionen: Verbindung testen, Speichern, Abbrechen.
- Konfiguration persistent im **config-Volume** (`config/database.json`).

## Unterstützte Versionen
- **SQLite**: 3.x
- **MySQL**: empfohlen 8.0+, unterstützt 8.x (ältere nicht unterstützt)
- **MariaDB** ⭐: empfohlen 10.11 LTS / 11.x, unterstützt 10.6+/10.11+/11.x
- **PostgreSQL** ⭐: empfohlen 16/17, unterstützt 14+/15+/16+/17+

## Verlustfreie Migration
Ablauf (`app/db_migrator.py`):
1. Zielverbindung prüfen
2. Sicherheitsbackup erstellen (`pre_db_migration_YYYYMMDD_HHMMSS.zip`)
3. Zielschema erzeugen (leere Zieldatenbank wird erzwungen)
4. Daten exportieren
5. Daten importieren
6. Integrität prüfen (Tabellen-/Datensatzanzahl, Benutzer, Rollen, Historien)
7. Anwendung umstellen (Engine-Reconfigure + Auswahl persistieren)
8. Migration protokollieren + `post_db_migration_*.zip` als Wiederherstellungspunkt

Übernommen werden Benutzer, Rollen, Arbeitszeiten, Stempelungen, Urlaub,
Feiertage, Logs, Backup-/Restore-Historie, Offline-Synchronisationsdaten und
alle weiteren Tabellen. Einstellungen liegen im config-Volume und bleiben
unberührt. Der Datentransfer ist ORM-/metadaten-getrieben und damit
dialektunabhängig (keine datenbankspezifische Logik in Fachfunktionen).

## Rollback ohne Downtime
Es wird ausschließlich in die Zieldatenbank geschrieben – schlägt irgendein
Schritt fehl, bleibt die bisherige Datenbank unverändert **aktiv**. Eine nicht
leere Zieldatenbank bricht die Migration ab (Schutz vor Datenverlust).

## Asynchroner Ablauf
Wie beim Restore läuft die Migration **nie** synchron im HTTP-Request: der
Request validiert und queued nur, ein Hintergrund-Worker
(`app/db_migration_jobs.py`) führt die Migration aus. Fortschritt über
`data/db_migration_status.json` und `GET /api/database/migration/status` mit
eigener Fortschrittsseite (Schritte + Balken).

## Logging
- Neuer Kanal **`database`** → `logs/database.log`, in Administration → Logs
  filter-/such-/downloadbar. Erfasst Migration gestartet/erfolgreich/
  fehlgeschlagen, Rollback und Verbindungstests (Zeitpunkt, Benutzer, Quelle,
  Ziel, Datensatzanzahl, Dauer, Ergebnis) – niemals Zugangsdaten.
- Neues Logging-Setting **„Datenbank-Logging"**.

## Weiteres
- **PostgreSQL-Treiber** (`psycopg2-binary`) ergänzt. `app/database.py` bedient
  SQLite, MySQL/MariaDB (PyMySQL) und PostgreSQL über eine abstrahierte URL-/
  Engine-Schicht mit Laufzeit-`reconfigure`.
- Systemstatus um aktive Datenbank, Datenbankversion, letzte (erfolgreiche)
  Migration und letzten Fehler erweitert.
- Version durchgängig **0.9.7**.

## Regressionstests
`tests/test_v097.py` (10): Versions-Bump, Datenbankseite (Empfehlungskarten +
⭐ Badges + Konfigurationsmodal), `database`-Logkanal und -Setting,
Verbindungstest (gültig/ungültig) sowie die vollständige Migrations-Pipeline
SQLite → SQLite (Datenkopie, Integritätsprüfung, automatisches Sicherheitsbackup,
`database.log`) und der Rollback bei nicht leerer Zieldatenbank.

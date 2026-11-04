# Prüfprotokoll 0.22.0

Prüfdatum: 2026-11-04. Grundlage: `main` nach dem Merge der
Synchronisationskorrekturen aus 0.21.0. Geprüft wird die produktive Anwendung
mit echten HTTP-Routen und isolierten Testdatenbanken.

## Funktionsumfang erhalten

Die Oberfläche verwendet weiterhin die vorhandenen Formulare, Berechtigungen,
Lizenzprüfungen und Fachfunktionen. Der Abgleich der 42 ursprünglichen Admin-
und Buchungstemplates bestätigt den Erhalt von 63 Formularen, 54 CSRF-Helfern
und 621 Formular-/Navigations-/JavaScript-Verträgen (`action`, `href`, `name`,
`id`, `data-*`). Neue Pausenkorrekturformulare kommen hinzu.

Erhaltene Bereiche: Schnellstempeln, Aufträge und optionale Firmenanlage,
Firmenstandorte und Remote, Kommentare, Nachträge und Freigaben, Storno und
Änderungshistorie, Zeitkonten, Urlaub/Abwesenheiten, Kalender, Arbeitszeitpläne,
PDF-/Excel-Auswertungen, Benutzer/Gruppen/Rollen, Terminals, Lizenz,
Systemeinstellungen, Protokolle, Sicherung/Wiederherstellung,
Datenbankverwaltung und Synchronisationskonflikte.

## Zeiterfassung

Die neuen Regressionen prüfen gespeicherte UTC-Stempel, Minuten, Metadaten,
Pausenintervalle und Vorher-/Nachher-Historie:

- Beginn, Pause, Fortsetzen und Ende einschließlich Beenden während einer Pause.
- 08:00–16:00 mit 30 Minuten tatsächlicher Pause ergibt 7:30 Stunden;
  ein eingeschobener Auftrag darf die Tageszeit nicht doppelt zählen.
- Pausen bleiben nach dem Teilen in dem zeitlich passenden Restabschnitt.
  Abschnittsübergreifende Pausen werden aufgeteilt; Altbestände mit bloßer
  Minutensumme behalten eine nachvollziehbare Verteilung.
- Zwischenstempelungen in laufende und abgeschlossene Arbeit, am Rand und
  mitten in der Buchung, einschließlich Nachtbuchungen und Folgetag.
- Nachträgliche Änderungen bewahren Firma, Standort, Quelle, Zeitzone,
  Pausenregel und Historie. Laufende Arbeit läuft nach dem Nachtrag weiter.
- Storno und Ersatz sind atomar: Scheitert die Ersatzbuchung, bleibt das
  Original gültig. Abgerechnete Perioden und fremde Zuständigkeiten bleiben gesperrt.
- Pausenintervalle lassen sich mit Begründung korrigieren; fremde Intervalle,
  Überschneidungen und Zeiten außerhalb der Buchung werden abgewiesen.
- Europe/Berlin, 22:00–06:00: normalerweise 8 Stunden, in der Frühlingsnacht
  7 und in der Herbstnacht 9 Stunden. Die zweite 02-Uhr-Stunde behält ihren
  eindeutigen UTC-Zeitpunkt beim Beenden und Bearbeiten. Eine Korrektur von
  02:10–02:40 auf 02:20–02:40 in der zweiten Stunde ergibt 20 Minuten,
  eine Endkorrektur auf 02:50 ergibt 40 Minuten. Eine getrennte Buchung in
  der ersten Stunde blockiert diese Änderung nicht; Vorschau und Speicherung
  verwenden dieselbe UTC-Zuordnung.
- Online-Stempelungen ohne brauchbare Gerätezeit verwenden auf einem
  UTC-Server die Betriebszeitzone, im Winter wie im Sommer.
- Neue Buchungen ziehen ausschließlich tatsächliche Pausen ab. Gesetzliche
  Schwellen beziehen sich auf Nettoarbeit; 9:30 Anwesenheit mit 30 Minuten
  Pause ergibt 9 Stunden Arbeit und keine zusätzliche 15-Minuten-Warnung.
  `legacy_auto` behält seine historische Berechnung.

## Oberfläche und Offline-PWA

Browserprüfungen verwenden Chromium und WebKit mit iPhone-Viewport.
Geprüft werden Navigation, eigenes Konto/QR, rollen- und gruppenbezogener
Zugriff, individuelle Tages-/Wochenvorgabe, vorübergehender Ansichtswechsel,
Firmenanlage und echte Stempelungen in Web und PWA sowie Pausenkorrekturen.

Die Layoutprüfung misst auch innere Karten und Dialoge, damit verdeckte
Überbreiten nicht allein durch `overflow` kaschiert werden. Schmale Ansichten
mit 320 und 390 Pixeln sowie Querformat mit 844 × 390 Pixeln werden geprüft,
einschließlich langer Benutzer-/Gruppennamen, Adminnavigation und Dialogen.
Weitere Sichtprüfungen umfassen Tablet/Desktop und Hell-/Dunkeldarstellung.

Die bisherigen Synchronisationsprüfungen bleiben erhalten: sieben Tage
offline mit 14 Stempelungen, Neustart, Wiederverbindung, fehlende/ungültige
Quittungen, Kontowechsel, IndexedDB-Upgrade, Backoff, kontrolliertes Update
und additive Sicherungswiederherstellung. Zusätzlich wird der Wechsel aus
der offline neu geladenen Ansicht „Mehr“ zurück zu bedienbaren Stempelknöpfen
geprüft. Persönliche QR-Codes werden nicht offline gespeichert.

Neustarttests warten gezielt auf den Ablauf einer noch gültigen 30-Sekunden-
Synchronisationssperre und den bestehenden 15-Sekunden-Wiederholungszyklus.
Danach müssen weiterhin genau eine Buchung und der passende Beleg vorhanden
sein. Der Online-Test wartet auf die gespeicherte Serverbuchung, bevor er die
leere Warteschlange bewertet. Globale Testwiederholungen wurden nicht eingeführt.

## Datenbank und Betrieb

Migration 26 ergänzt ausschließlich `users.overview_preference` mit dem
Standard `day`. Sowohl der versionierte Runner als auch `ensure_schema()`
ergänzen die Spalte idempotent. Vorhandene Benutzer und Buchungen bleiben
erhalten; gespeicherte Wochenvorgaben bleiben bei erneuter Ausführung bestehen.

Die Prüfung auf echten Datenbankservern umfasst SQLite, PostgreSQL 17,
MariaDB 11.4 und MySQL 8.4: Upgrade 25→26, jede gerichtete Kombination von
Datenbankwechsel und logischer Wiederherstellung sowie ein älteres Archiv
ohne die neue Einstellung. Kontrolliert werden Zeilenzahlen, Stundenwerte,
Benutzervorgabe, Sicherheitsbackups, unveränderte Datenbankkonfiguration und
passwortfreie Backup-/Datenbankprotokolle.

Die Containerprüfung baut das Release-Abbild und startet es ohne Netzwerk
mit getrennten `config`-/`data`-/`logs`-Volumes. Nach Login, Stempelung,
Dublettenerkennung und Speichern der Wochenvorgabe wird der Container neu
gestartet; Daten, Konfiguration, Schema und Protokolle werden erneut geprüft.

## Ergebnisse und Grenzen

| Prüfung | Ergebnis |
|---|---|
| Python | 1.032 unterschiedliche Testfälle bestanden; Gesamtlauf und gezielte Nachprüfungen der zuletzt angepassten Fälle |
| JavaScript / IndexedDB | 21 bestanden |
| Browser | 50 unterschiedliche Fälle bestanden: 25 Chromium, 25 WebKit; Gesamtlauf und gezielte Nachprüfung der zuletzt korrigierten Fälle |
| Datenbank-Upgrades 25→26 | 4 bestanden, jeweils wiederholt und datenerhaltend |
| Datenbankwechsel | 12 von 12 gerichteten Kombinationen bestanden |
| Cross-Database Restore | 12 von 12 gerichteten Kombinationen bestanden |
| Älteres logisches Archiv ohne Startansicht | Wiederherstellung auf allen 4 Backends bestanden |
| Container | Build, Healthcheck, Login, Stempelung, QR/Konto/Assets, Dublettenerkennung und Neustart mit Daten-/Konfigerhalt bestanden |
| Versions-/Dateiprüfung | Releaseversion, Migration 26 und `git diff --check` geprüft |

Die Python-Suite enthält 82 neue Zeitregressionen, 11 Konto-/Migrationsfälle,
18 Pausenkorrektur-/Nachtformularfälle, 4 Betriebszonenfälle, 4 portable
Migrationsfälle und 3 Konfigurationsschutzfälle beim Restore. Die bestehenden
910 Tests bleiben enthalten. Bestehende Tests wurden bei Bedarf an die
Releaseversion, Schema 26, korrekte UI-Hinweise und Betriebszeit angepasst.
Es wurden keine Prüfungen übersprungen oder Berechtigungsprüfungen entfernt.

WebKit-Automatisierung ersetzt keinen Test einer auf einem echten iPhone
installierten PWA. Insbesondere Betriebssystem-Speicherbereinigung und eine
geschlossene App lassen sich damit nicht garantieren. Die vorhandenen
[iOS-Grenzen](PWA_SYNCHRONISATION.md) gelten weiterhin. Es wurde keine
Produktivdatenbank verändert und kein Deployment durchgeführt.

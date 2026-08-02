# Release Notes 0.20.1

Eine Pflegeversion: gemeldete Fehler in der Bedienung, durchgängig deutsche
Ausgabe und Kommentierung, entfernter toter Code. An der arbeitsrechtlichen
Bewertung aus 0.18.0–0.20.0 ändert sich nichts.

> **Keine rechtliche Garantie.** Es gilt unverändert, was in
> [`RELEASE_NOTES_0.14.0.md`](RELEASE_NOTES_0.14.0.md) steht: Die Umsetzung
> erfüllt technische Anforderungen, ist nicht zertifiziert und ersetzt keine
> Rechtsberatung.

## 1. „Remote" war aus der Einsatzortauswahl verschwunden

Der auffälligste Punkt und zugleich der mit der längsten Vorgeschichte.

`users.remote_flag_enabled` stammt aus 0.9.21. Damals **war** „Remote" die
gesamte Einsatzorterfassung: ein Haken, den man je Person freischaltete. Seit
0.13.0 ist der Einsatzort eine Liste von Arbeitsorten, und seit 0.14.1 wird
diese Liste immer angezeigt. Das Kennzeichen entfernte damit nur noch **einen
Eintrag** aus der Liste – während seine Beschriftung weiterhin „Einsatzort
erfassen" versprach.

Wer das las, sah ein bereits erfülltes Versprechen und ließ den Haken weg.
„Remote" verschwand daraufhin unbemerkt aus der Auswahl, und der Server verwarf
sogar eine ausdrücklich gesendete Remote-Angabe stillschweigend.

**Ab 0.20.1 ist „Remote" ein Arbeitsort wie jeder andere und steht allen
offen.** Ob jemand remote arbeiten darf, steht im Arbeitsvertrag; eine
Zeiterfassung soll festhalten, wo gearbeitet wurde, und die Antwort nicht
verstecken.

Entfallen sind damit der Haken in der Benutzerverwaltung, die Verzweigungen in
den Vorlagen und die Auswertung im Server. Die Spalte
`users.remote_flag_enabled` bleibt in der Datenbank: Sie zu entfernen wäre über
SQLite, MySQL/MariaDB und PostgreSQL hinweg nicht datenerhaltend-portabel, und
der gespeicherte Wert bliebe für eine spätere echte Berechtigung auswertbar.

**Offene Entscheidung, bewusst dokumentiert:** Soll es eine personenbezogene
Erlaubnis für Remote-Arbeit geben, gehört sie als `Own.Time.Remote` ins
Rollenmodell und nicht als stiller Haken in die Stammdaten. Diese Umsetzung
greift der Entscheidung nicht vor.

**Nebenbei repariert:** Formulare tragen jetzt den Vermerk `location_field`.
Damit unterscheidet der Server „Haken nicht gesetzt" von „das Formular kennt
das Feld gar nicht". Ein reiner Kommentar-Nachtrag – etwa aus einer älteren
Offline-Warteschlange – überschreibt den gespeicherten Einsatzort deshalb nicht
mehr.

## 2. Wochentage erschienen auf Englisch

Drei Stellen benutzten `strftime('%A')` beziehungsweise `%a`. Diese Formate
richten sich nach der Locale des Betriebssystems – und `de_DE` ist in den
schlanken Container-Abbildern gar nicht vorhanden. Im Betrieb stand dort
„Tuesday" statt „Dienstag".

Neu sind die Jinja-Filter `weekday`, `weekday_short`, `month_name` und
`german_date` mit einer eigenen Namenstabelle. Sie können nicht fehlschlagen und
machen die Ausgabe unabhängig davon, wie der Host eingerichtet ist. Die
Mobilansicht formatierte über JavaScript ohnehin schon mit `de-DE`.

## 3. Anmeldeseite: Sperrsatz entfernt

`.login-form input` trug `letter-spacing: 0.3rem` – fast fünf Pixel je Zeichen,
gedacht für eine PIN-Eingabe. Im Benutzernamen sah das zerrissen aus. Der
Abstand steht jetzt auf `normal`.

## 4. „Anzurechnung" ist kein deutsches Wort

Ersetzt durch **„Angerechnete Zeit"** in der Urlaubsübersicht der
Administration, im PDF-Export (Einzel- und Sammelbericht) und im Excel-Export.

## 5. App: Einsatzort und „Arbeitszeit starten" klebten aneinander

`.mobile-action-grid` verteilt seinen Abstand zwischen den Kacheln. Ein
Formular ist **eine** Kachel – der Abstand wirkte deshalb nur außen, und der
Einsatzort saß direkt auf der Schaltfläche darunter. Das Formular ist jetzt
selbst ein Flex-Container mit demselben Abstand.

## 6. Erfülltes Sonntagsminimum ist grün

In der Jahresprüfung zu Sonn- und Nachtarbeit trug „Sonntagsminimum erfüllt"
die Grundklasse `.license-state` und war damit gelb hinterlegt. Gelb heißt
„aufpassen"; hier ist aber alles in Ordnung. Jetzt grün
(`.license-state--valid`).

## 7. Kommentare durchgängig auf Deutsch

Rund 200 Kommentare und Docstrings in `app/`, `static/` und den Vorlagen lagen
noch auf Englisch – gewachsen aus der Frühzeit des Projekts. Sie sind
übersetzt; inhaltlich wurde dabei nichts verändert, wohl aber manches genauer
gefasst, wo der englische Text ungenau war.

## 8. Toter Code entfernt

Gefunden über `vulture` und einen Abgleich der CSS-Klassen gegen Vorlagen und
Skripte. Entfernt wurden:

| Ort | Was | Warum |
|---|---|---|
| `app/main.py` | Import `BackgroundTasks` samt Rückfallzweig | nie benutzt |
| `app/pdf_export.py` | `TA_LEFT` | importiert, nie benutzt |
| `app/app_config.py` | `DatabaseConfig.to_url()` | ohne Aufrufer |
| `app/database.py` | `DB_TYPES` | ohne Leser |
| `app/db_migration_jobs.py` | `TERMINAL_STATES`, `clear_status()` | ohne Aufrufer |
| `app/crud.py` | `get_group_by_name`, `get_holiday_regions`, `get_internal_locations`, `get_active_terminals`, `get_terminal_sync_runs` | ohne Aufrufer |
| `app/crud.py` | **`replace_holidays_for_region`** | löschte *alle* Feiertage einer Region, auch die von Hand angelegten; `apply_statutory_holidays` erledigt dasselbe, ohne fremde Einträge mitzureißen |
| `app/backup_manager.py` | Parameter `original_name` | im Rumpf ungenutzt – der Ablagename entsteht bewusst serverseitig |
| `static/styles.css` | 34 Regelblöcke, rund 220 Zeilen | Klassen, die in keiner Vorlage und keinem Skript vorkommen |
| `static/styles.css` | doppelte Regel `.punch-start-quick` | wurde von der späteren vollständig überschrieben |
| `static/mobile.js` | Zweig `perms.flag_remote === false` | der Schlüssel wird nicht mehr gesendet |

Dynamisch zusammengesetzte Klassen (`log-level--…`, `status-…`,
`mobile-vacation__status--…`) wurden **nicht** angetastet.

## 9. Systemeinstellungen setzten sich beim Speichern zurück

Das Formular baute die Konfiguration aus den Vorgaben neu auf. Jeder Wert, den
es nicht selbst mitschickte – Betriebszeitzone, Ausgleichszeitraum, Behandlung
der Ausfalltage – ging dabei verloren. Jetzt setzt das Speichern auf dem
bisherigen Stand auf.

## Upgrade

Keine Schemaänderung, keine neue Migration. Konfiguration, Volumes, Sicherung
und Rücksicherung, Offline-PWA und Terminalimport bleiben unverändert.

Nach dem Upgrade steht „Remote" für alle Personen in der Einsatzortauswahl.
Wer das nicht möchte, sollte die unter Punkt 1 genannte offene Entscheidung
treffen, bevor er die Anwendung ausrollt.

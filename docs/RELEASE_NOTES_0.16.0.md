# Release Notes 0.16.0

Schließt die nach 0.15.0 verbliebenen Berechtigungs-, Integritäts- und
Arbeitszeitlücken: Selbstbedienungsrechte werden durchgesetzt, die
Eingabeschemas der Schnittstelle getrennt, die Dauerberechnung vereinheitlicht
und der Ausgleich nach § 3 ArbZG ergänzt.

> **Keine rechtliche Garantie.** Es gilt unverändert, was in
> [`RELEASE_NOTES_0.14.0.md`](RELEASE_NOTES_0.14.0.md) steht: Die Umsetzung
> erfüllt technische Anforderungen, ist nicht zertifiziert und ersetzt keine
> Rechtsberatung. In Betrieben mit Betriebsrat ist die Einführung nach
> § 87 Abs. 1 Nr. 6 BetrVG mitbestimmungspflichtig.

## 1. Selbstbedienung kannte keine Rechte

0.15.0 hat die Schnittstelle gegen **Fremdzugriffe** abgesichert – für die
**eigene** Person blieb sie offen: Wer angemeldet war, konnte sich über
`POST /api/time-entries` eine Buchung anlegen, auch ohne `Own.Time.Edit`, und
über `POST /api/vacations` Urlaub beantragen, auch ohne
`Own.Vacation.Request`. Die Oberfläche prüfte diese Rechte, die Schnittstelle
nicht – ein Recht, das sich umgehen lässt, ist keines.

Jetzt gilt für jeden Weg dasselbe:

| Vorgang | eigene Person | fremde Person |
|---|---|---|
| Buchung anlegen | `Own.Time.Edit` | `Time.Edit` + Scope |
| Buchung stornieren | **`Own.Time.Cancel`** | `Time.Edit` + Scope |
| Urlaub beantragen | `Own.Vacation.Request` | `Vacation.Manage` + Scope |

**Neues Recht `Own.Time.Cancel`.** `Own.Time.Edit` wäre dafür zu weit:
Nachtragen und Zurücknehmen sind verschiedene Dinge. Ein Nachtrag geht in die
Freigabe und wird geprüft; eine Stornierung nimmt bereits erfasste – womöglich
schon freigegebene – Zeit zurück. Wie alle `Own.*`-Rechte gilt es ohne
zugewiesene Rolle als erlaubt, sodass Bestandsinstallationen sich nicht ändern;
sobald eine Rolle zugewiesen ist, entscheidet ausschließlich sie.

Anonyme Aufrufe liefern weiterhin **401**, fehlendes Recht oder falscher Scope
**403**, und jede Abweisung geht ohne Geheimnisse ins Sicherheitsprotokoll.

## 2. Die Schnittstelle nahm zu viel entgegen

`schemas.TimeEntryCreate` war das öffentliche Eingabeschema – für alle. Es
erlaubt jedes Feld. Ein Beschäftigter konnte damit:

* sich eine **freigegebene** Buchung anlegen (`status=approved`), an der
  Freigabe vorbei,
* eine Buchung als **Terminalstempelung** ausgeben (`source`, `external_id`)
  und damit eine Herkunft vortäuschen,
* **UTC-Stempel und Zeitzone** frei setzen und so die Regelprüfung in die Irre
  führen,
* `is_manual=false` setzen und den Nachtrag als gestempelt ausgeben.

Jetzt sind drei Ebenen getrennt:

| Schema | Für wen | Umfang |
|---|---|---|
| `SelfServiceTimeEntryCreate` | Beschäftigte für sich selbst | Datum, Zeiten, Pause, Kunde, Standort, Einsatzort, Kommentar |
| `TimeEntryCreate` | Verwaltung (`Time.Edit`) | vollständig |
| `TimeEntryCreate` intern | Terminaltreiber, Import, Migration | vollständig, inkl. Quelle und Originalzeitstempel |

Bewusst ein **eigenes, enges Schema** statt eines beschnittenen
`TimeEntryCreate`: Ein Feld, das dort nicht steht, kann auch nicht versehentlich
durchgereicht werden. Eine Positivliste hält länger als eine Negativliste.

Für eigene Nachträge erzwingt der Server:

* `status = pending` – ein Nachtrag geht immer in die Freigabe,
* `is_manual = true`, `is_open = false`,
* `source` und `external_id` bleiben **leer**,
* UTC-Stempel und `tz_name` entstehen aus den eingegebenen Ortszeiten und der
  **zentralen Betriebszeitzone**, nicht aus einer Client-Angabe,
* der Standort wird nur übernommen, wenn er zur gebuchten Firma gehört.

Terminaltreiber und Importpfade rufen `crud.create_time_entry` weiterhin direkt
mit dem vollen Schema auf – sie sind vertrauenswürdig und bleiben unverändert.

## 3. Die Dauer wurde zweimal gerechnet

`compliance._entry_bounds()` rechnete seit 0.15.0 korrekt in UTC.
`TimeEntry.gross_minutes` und `worked_minutes` dagegen weiter mit **naiven
Ortszeiten** – zwei Wege für dieselbe Frage, und über eine Zeitumstellung
hinweg zwei verschiedene Antworten. Die Regelprüfung sah eine Stunde mehr oder
weniger als Auswertung, Zeitkonto und Export.

Neu ist `app/worktime.py` als **einzige** Quelle:

* Gepflegte `started_at_utc`/`ended_at_utc` haben Vorrang.
* Bestandsbuchungen fallen auf `work_date` + Ortszeit + `tz_name` zurück.
* Ein naiver Wert aus einer `*_at_utc`-Spalte wird als **UTC** gelesen.
* Gerechnet wird durchgehend zonenbehaftet; naive und zonenbehaftete Werte
  werden nie gemischt.

Benutzt wird es von `models.TimeEntry.gross_minutes` und damit von allem, was
darauf aufbaut: Regelprüfung, Tages-, Wochen- und Monatssummen, Überstunden,
Zeitkonto, Berichte, PDF, Excel, Offline-Snapshot und Backup-Prüfung. Ein Test
hält fest, dass Regelprüfung und Tagesübersicht dieselbe Zahl liefern.

Beispiel Nachtschicht 22:00–06:00 in `Europe/Berlin`:

| Nacht | Ortszeit | tatsächlich |
|---|---|---|
| 28./29.03.2026 (Beginn Sommerzeit) | 8 Std | **7 Std** |
| 24./25.10.2026 (Ende Sommerzeit) | 8 Std | **9 Std** |

Gestempelte Pausen werden abgezogen; fehlende gesetzliche Pausen werden nur
gekennzeichnet, nie abgezogen.

## 4. Feststellungen waren nur über den Code zugeordnet

Zwei getrennte Schichten an einem Tag können denselben Verstoß erzeugen – zwei
fehlende Ruhepausen sind **zwei** Feststellungen. Bis 0.15.0 fielen sie zu
einer zusammen: Wer die eine einordnete, deckte die andere gleich mit zu.

Neu ist ein stabiler Schlüssel (`finding_key`) aus Benutzer, Tag, Code und
**Schichtbeginn**, dazu `shift_start_utc` als lesbarer Anker. Feststellungen
ohne Schichtbezug (Sonntags-, Feiertagsarbeit, Tageshöchstarbeitszeit) gelten
weiter je Tag und bekommen einen leeren Anker – für sie ändert sich nichts.

Damit lassen sich mehrere gleichartige Verstöße eines Tages getrennt speichern,
anzeigen, bestätigen, erledigen und erneut öffnen. Bestandsfeststellungen
bekommen ihren Schlüssel bei der nächsten Neuberechnung nachgereicht und werden
dabei über den Code zugeordnet, damit keine Bestätigung verlorengeht.
Physisch gelöscht wird nach wie vor nichts.

## 5. Die Schichtgrenze ist jetzt einstellbar

`SHIFT_BREAK_MINUTES = 360` war eine im Code festgeschriebene **betriebliche**
Festlegung. Sie steht jetzt in der persistenten Systemkonfiguration
(config-Volume, `system.json`) und ist unter *Administration → System →
Einstellungen* änderbar.

* **Voreinstellung 360 Minuten** – Bestandsinstallationen verhalten sich
  unverändert.
* **Zulässig 60 bis 720 Minuten.** Unter einer Stunde wäre jede längere
  Mittagspause ein Feierabend; über zwölf Stunden bliebe von der
  Ruhezeitprüfung nichts übrig.
* Beim Import wird der Wert **validiert** – ein unsinniger Wert würde die
  Regelprüfung still verfälschen, und das fiele erst in einer Auswertung auf.
* Jede Änderung löst einen **Audit-Eintrag** mit altem und neuem Wert aus: Sie
  verändert die Bewertung von Pausen und Ruhezeiten rückwirkend.

Warum es diesen Wert überhaupt braucht, steht unverändert in den Release Notes
zu 0.15.0: Das ArbZG kennt den Begriff „Schicht" nicht.

## 6. Ausgleich nach § 3 Satz 2 ArbZG

Mehr als acht Stunden werktäglich sind zulässig, „wenn innerhalb von sechs
Kalendermonaten oder innerhalb von 24 Wochen im Durchschnitt acht Stunden
werktäglich nicht überschritten werden". Bisher wurde die Überschreitung
gekennzeichnet, der Ausgleich aber nie geprüft.

Neu ist eine **rollierende Auswertung** (`compliance.compensation_report`):

* Zeitraum: die **24 Wochen**, die am Bewertungstag enden.
* Gezählt werden nur **Werktage mit Arbeit**. Sonntage bleiben außen vor –
  § 3 spricht von werktäglicher Arbeitszeit. Tage ohne Buchung senken den
  Durchschnitt nicht künstlich; sonst ließe sich jede Überschreitung durch eine
  lange Abwesenheit wegrechnen.
* Ausgewiesen werden **Zeitraum, Anzahl der einbezogenen Tage und Durchschnitt**
  im Klartext der Kennzeichnung.

Zwei neue Kennzeichnungen:

| Code | Bedeutung |
|---|---|
| `average_over_8h` | Der Durchschnitt liegt über acht Stunden; der Ausgleich fehlt. |
| `compensation_due` | Der Zeitraum ist fast ausgeschöpft – Vorwarnung, solange Ausgleich noch möglich ist. |

Geprüft wird nur an Tagen mit mehr als acht Stunden: Erst dann stellt sich die
Frage. Blockiert wird nichts – die tatsächliche Zeit steht wie immer in der
Datenbank.

### Offene fachliche Entscheidung: 24 Wochen oder sechs Kalendermonate?

Das Gesetz nennt beide Varianten **gleichrangig**. Diese Umsetzung rechnet mit
**24 Wochen**, weil ein Wochenraster zur werktäglichen Betrachtung passt und
sich tagesgenau rollierend auswerten lässt. Die Kalendermonatsvariante wäre je
nach Monatslängen bis zu zwei Wochen länger und damit für Beschäftigte
ungünstiger.

**Wer die Monatsvariante braucht (Tarifvertrag, Betriebsvereinbarung), muss das
festlegen** – die Anwendung nimmt es nicht stillschweigend an.
`models.COMPENSATION_WEEKS` ist der Schalter. Ebenso wenig bewertet die
Anwendung tarifliche Verlängerungen nach § 7 ArbZG.

## 7. Sonn- und Feiertagsarbeit lässt sich dokumentieren

Sonntagsarbeit ist nicht verboten, sondern **erlaubnispflichtig**: § 10 ArbZG
zählt Ausnahmen auf, § 11 Abs. 3 verlangt einen Ersatzruhetag. Ob eine Ausnahme
greift, kann die Anwendung nicht entscheiden – sie kann aber festhalten, worauf
sich der Betrieb beruft.

Zu einer Sonn-/Feiertagskennzeichnung lassen sich jetzt erfassen:

* **Ausnahmegrund** (z. B. Notdienst, Instandhaltung),
* **Rechts-/Betriebsgrundlage** (Paragraf, Tarifvertrag, Betriebsvereinbarung,
  Genehmigung),
* **Ersatzruhetag** nach § 11 Abs. 3,
* **Bearbeitungsstand**: offen, begründet, Ersatzruhetag gewährt, kein
  Ersatzruhetag nötig.

Alle Felder sind optional; ohne Eintrag verhält sich die Kennzeichnung wie
bisher. Die tatsächlich geleistete Arbeit bleibt unberührt gespeichert und
gekennzeichnet – hier kommt nur die Einordnung dazu. Der Zugriff ist an
denselben Geltungsbereich gebunden wie das Einordnen; jede Dokumentation löst
einen Audit-Eintrag aus.

**Kunden ändern daran nichts.** Feiertage kommen ausschließlich aus der zentral
konfigurierten Region. Arbeit an einem Kundenstandort in Bayern löst keine
bayerische Feiertagsbewertung aus, und ein Feiertag der eigenen Region gilt auch
während eines Kundenauftrags. Drei Tests halten das fest.

## Datenbank

**Migration 19** (`_add_finding_keys_and_holiday_notes`) – in beiden
Mechanismen (`ensure_schema()` und `MIGRATIONS`).

Sechs neue Spalten an `compliance_flags`: `finding_key`, `shift_start_utc`,
`exception_reason`, `legal_basis`, `replacement_rest_date`, `handling_state`.
Portables DDL für SQLite, MySQL, MariaDB und PostgreSQL.

**Idempotent und datenerhaltend.** Vorhandene Feststellungen behalten Inhalt,
Zustand und Bestätigung; `finding_key` bleibt zunächst `NULL` und wird bei der
nächsten Neuberechnung nachgetragen. Geprüft für Aufstiege aus **0.14.2** und
**0.15.0**. Die neuen Spalten wandern automatisch in das logische Backup und
damit auch über Datenbankgrenzen hinweg.

Bestehende Migrationen sind unverändert; die Nummerierung bleibt fortlaufend.

## Was sich für den Betrieb ändert

* **`Own.Time.Cancel` ist neu.** Rollen, die bereits Rechte vergeben, bekommen
  es **nicht** automatisch – ohne Zuweisung können diese Personen eigene
  Buchungen nicht mehr über die API stornieren. Wer keine Rolle zugewiesen hat,
  behält das bisherige Verhalten.
* **API-Clients, die `status`, `source` oder UTC-Stempel für eigene Buchungen
  gesetzt haben**, bekommen diese Werte jetzt vom Server überschrieben. Das ist
  beabsichtigt.
* **Mehr Kennzeichnungen**: zwei getrennte Schichten an einem Tag ergeben zwei
  Feststellungen statt einer, und der fehlende Ausgleich nach § 3 kommt als
  neue Warnung dazu.
* Die Dauerberechnung ändert Werte nur dort, wo sie vorher falsch war – bei
  Buchungen über eine Zeitumstellung.
* Offline-Aktionen, Terminalimporte, Backup und Restore laufen unverändert.

## Tests

`tests/test_v0160.py` – 46 Tests:

* **Selbstbedienung:** anonym 401; eigene Buchung ohne `Own.Time.Edit` 403, mit
  Recht 200; eigenes Storno ohne `Own.Time.Cancel` 403, mit Recht 200; eigener
  Urlaub ohne `Own.Vacation.Request` 403; fremde Buchung braucht `Time.Edit`.
* **Eingabeschemas:** Beschäftigter kann sich nicht selbst freigeben, keine
  Terminalquelle vortäuschen, keine UTC-Stempel einschleusen, `is_manual=false`
  nicht setzen; firmenfremder Standort wird verworfen; der Terminalimport
  behält Quelle und externe ID.
* **Dauer:** UTC-Vorrang, beide Zeitumstellungen, Mitternacht, Gleichstand von
  Regelprüfung und Tagesübersicht, Pausenabzug.
* **Feststellungen:** zwei Schichten ergeben zwei Befunde mit verschiedenen
  Schlüsseln, getrennt gespeichert und einzeln bestätigbar.
* **Schichtgrenze:** kommt aus der Konfiguration, liegt im config-Volume, wird
  im Wertebereich validiert, und ein niedrigerer Wert teilt die Schicht.
* **Ausgleich:** Zeitraum wird benannt, ein einzelner langer Tag schlägt an,
  genügend normale Tage gleichen aus, Sonntag zählt nicht mit, Arbeit wird nie
  blockiert.
* **Sonn-/Feiertag:** Ausnahme dokumentierbar, unbekannter Stand abgewiesen,
  Kundenfeiertag wirkt nicht, zentraler Feiertag gilt auch beim Kunden,
  Kundenwechsel ändert keine Regel.
* **Migration:** 19 registriert und fortlaufend, Spalten vorhanden, Aufstieg
  aus 0.15.0 ohne Verlust von Bestätigung und Revisionsstand, doppelte
  Ausführung unschädlich, Buchungen/Pausen/Revisionen überleben, neue Spalten
  im logischen Backup.

## Bekannte Grenzen

* **24 Wochen statt sechs Kalendermonate** – bewusste Wahl, siehe Abschnitt 6.
* Die Schichtgrenze bleibt eine betriebliche Festlegung, jetzt immerhin
  einstellbar und dokumentiert.
* Ausnahmen nach §§ 7, 10 ArbZG, Tariföffnungen, Bereitschaftsdienst und
  Rufbereitschaft kann die Anwendung nicht bewerten. Sie hält fest, worauf sich
  der Betrieb beruft; entscheiden müssen Menschen.
* Bestandsbuchungen ohne UTC-Stempel werden über die Anlagenzeitzone
  umgerechnet. Wurde die Zeitzone seit der Erfassung geändert, ist das eine
  Annäherung – geraten wird nichts, nachträglich umgeschrieben ebenfalls nichts.
* Revisionssicherheit endet an der Anwendungsgrenze: Wer direkten Datenbank-
  oder Dateizugriff hat, kann Einträge verändern.

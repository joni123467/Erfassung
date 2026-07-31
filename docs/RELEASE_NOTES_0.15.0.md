# Release Notes 0.15.0

Sicherheits- und Compliance-Release. Es schließt eine offene JSON-Schnittstelle,
korrigiert die Pausenprüfung fachlich und macht Compliance-Feststellungen
nachvollziehbar statt löschbar.

> **Keine rechtliche Garantie.** Es gilt unverändert, was in
> [`RELEASE_NOTES_0.14.0.md`](RELEASE_NOTES_0.14.0.md) steht: Diese Umsetzung
> erfüllt technische Anforderungen, sie ist nicht zertifiziert und ersetzt
> keine Rechtsberatung. In Betrieben mit Betriebsrat ist die Einführung nach
> § 87 Abs. 1 Nr. 6 BetrVG mitbestimmungspflichtig.

## 1. Die JSON-Schnittstelle war offen

**Der schwerwiegendste Befund.** Neun Endpunkte hatten bis 0.14.2 **keinerlei**
Prüfung – weder Anmeldung noch Berechtigung:

| Endpunkt | Was ohne Anmeldung möglich war |
|---|---|
| `GET /api/users` | Stammdaten **aller** Personen auslesen |
| `POST /api/users` | ein Benutzerkonto anlegen |
| `GET /api/groups` | Organisationsstruktur auslesen |
| `POST /api/groups` | Gruppen anlegen |
| `GET /api/users/{id}/excel` | **vollständige Arbeitszeit** jeder Person herunterladen |
| `POST /api/time-entries` | beliebiger Person Arbeitszeit unterschieben |
| `DELETE /api/time-entries/{id}` | jede Buchung stornieren – ohne Urheber, ohne Grund |
| `POST /api/vacations` | Urlaub für beliebige Personen beantragen |
| `POST /api/vacations/{id}/status` | jeden Antrag genehmigen oder ablehnen |

Der CSRF-Schutz war dabei **keine** Hürde: `GET /api/csrf` liefert Sitzung und
Token auch ohne Anmeldung, damit die Offline-App sich vor dem Abgleich ein
frisches Token holen kann. Ein Angreifer musste denselben Weg gehen.

Besonders schwer wiegt der Excel-Export: Er gibt die vollständige Arbeitszeit
einer namentlich genannten Person heraus – ein personenbezogenes Datum im Sinne
von Art. 4 DSGVO, ohne jede Zugriffskontrolle.

### Was jetzt gilt

Drei Helfer sind der einzige Weg in die Schnittstelle:

* `_api_user` klärt **wer** – ohne Anmeldung **401**, nicht 403. Der
  Unterschied zwischen „nicht angemeldet" und „angemeldet, aber nicht
  berechtigt" gehört in die Antwort.
* `_api_require` klärt **darf überhaupt** – sonst **403**.
* `_api_require_scope` klärt **darf für diese Person** – sonst **403**.

Der Geltungsbereich ist der eigentliche Schutz: Ohne ihn genügte die Kenntnis
einer fremden Benutzer-ID. Für die **eigene** Person bleibt alles ohne
Sonderrecht möglich; für fremde greifen `User.View`, `User.Create`,
`Time.Edit`, `Time.View`, `Vacation.Manage` bzw. `System.Groups` samt Scope.

**Stornieren über die API** braucht jetzt zwingend einen angemeldeten Akteur
**und** eine Begründung (`?reason=…`). Beides landet in der Revisionshistorie –
eine Stornierung ohne Urheber wäre für die Nachvollziehbarkeit wertlos. Fehlt
die Begründung, antwortet der Server mit 400.

**Protokollierung:** Jede Abweisung geht in den Kanal `security`, jede
erfolgreiche administrative Aktion zusätzlich in `audit`. Bewusst **ohne**
IP-Adresse – sie wäre ein personenbezogenes Datum, das die Anwendung sonst
nirgends dauerhaft festhält (Art. 5 Abs. 1 lit. c DSGVO). Passwörter, PINs und
Tokens erscheinen nirgends.

## 2. Compliance-Bestätigung war ungeschützt

Beim Einordnen eines Regelverstoßes genügte die Kenntnis einer `flag_id`. Wer
`Time.View` für das *eigene* Team hatte, konnte damit eine fremde Feststellung
bestätigen – und der Verstoß selbst verrät Arbeitszeit, Datum und Schweregrad
einer anderen Person.

Der Server prüft jetzt, ob die betroffene Person im Geltungsbereich von
`Time.View` liegt. Sonst: **403**, Eintrag im Sicherheits- **und**
Audit-Protokoll.

## 3. Pausen wurden je Buchung geprüft – jetzt je Schicht

**Der fachlich gravierendste Fehler.** Wer von 8 bis 12 für Kunde A und von 12
bis 17 für Kunde B arbeitete, hatte nach alter Rechnung zwei Buchungen von vier
bzw. fünf Stunden – beide unter der Sechs-Stunden-Grenze, also **keine**
Pausenpflicht. Tatsächlich sind das neun Stunden am Stück ohne Pause.

§ 4 ArbZG kennt keine Aufträge. Die Prüfung bildet deshalb jetzt die
**chronologische Schicht** über alle Kunden, Aufträge und Einsatzorte hinweg:

1. Jede Buchung wird um ihre gebuchten Pausen bereinigt.
2. Alle Arbeitsintervalle werden zusammengeführt – überlappende und
   unmittelbar aufeinanderfolgende ebenso.
3. Lücken **unter 15 Minuten** sind keine Ruhepause, sondern Arbeitszeit. Ein
   Auftrags-, Kunden- oder Standortwechsel täuscht damit keine Pause mehr vor.
4. Nur tatsächliche Unterbrechungen **ab 15 Minuten** werden angerechnet
   (§ 4 Abs. 1 Satz 2 ArbZG).
5. Grenzen unverändert: **mehr als** 6 Stunden → 30 Minuten, **mehr als**
   9 Stunden → 45 Minuten.

Nachtarbeit über Mitternacht bleibt **eine** Schicht: Die Bewertung endet dort,
wo tatsächlich eine Ruhezeit liegt, nicht am Kalendertagwechsel. Die
Ruhezeitprüfung nach § 5 vergleicht ebenfalls Schichten statt Kalendertage.

Die tatsächlich geleistete Arbeitszeit wird wie bisher **immer** gespeichert.
Verstöße werden gekennzeichnet, nicht blockiert und nicht gekürzt.

### Offene fachliche Entscheidung: Wann endet eine Schicht?

Das ArbZG kennt den Begriff „Schicht" nicht. Es kennt Ruhepausen (§ 4,
höchstens 45 Minuten gefordert) und die Ruhezeit zwischen zwei Arbeitstagen
(§ 5, 11 Stunden). Dazwischen klafft eine Lücke, die eine Software füllen muss:
**Ist eine Unterbrechung von vier Stunden eine sehr lange Pause oder das Ende
des Arbeitstags?**

Diese Umsetzung legt die Grenze bei **sechs Stunden**
(`models.SHIFT_BREAK_MINUTES`):

* Ein geteilter Dienst mit mehreren Stunden Mittagspause bleibt **eine**
  Schicht und muss die Pausenpflicht erfüllen.
* Eine Unterbrechung ab sechs Stunden gilt als Ende des Arbeitstags und löst
  die Ruhezeitprüfung nach § 5 aus.

**Das ist eine Festlegung, keine Zahl aus dem Gesetz.** Wer sie anders handhabt
(Tarifvertrag, Betriebsvereinbarung), ändert die Konstante. Auswirkung: Ein
niedrigerer Wert erzeugt mehr Ruhezeitwarnungen und weniger Pausenwarnungen,
ein höherer das Gegenteil. Die Entscheidung gehört – wie die Einführung der
Erfassung selbst – in die Mitbestimmung.

## 4. Pausen sind jetzt revisionssicher

Bis 0.14.2 wurde das Anlegen und Beenden einer Buchung historisiert, das
**Pausenereignis** dagegen nicht. Wann eine Pause begann und endete, ist aber
genau die Angabe, an der § 4 ArbZG gemessen wird.

Neue Vorgänge in der Historie:

| Vorgang | Begründung nötig? |
|---|---|
| `break_started` – Pause begonnen | nein (der Stempel ist die Aussage) |
| `break_ended` – Pause beendet | nein |
| `break_corrected` – Pause nachträglich verschoben | **ja** |
| `break_cancelled` – Pause zurückgenommen | **ja** |

Alle vier speichern Akteur, Quelle, UTC-Zeitpunkt, ursprüngliche Zeitzone und
Vorher-/Nachher-Snapshot. Eine stornierte Pause wird auf die Länge null gesetzt
statt gelöscht – auch eine zurückgenommene Pause bleibt nachvollziehbar.

Web, Mobil/Offline, Terminalimport und API laufen über **denselben** Pfad
(`crud.start_break` / `crud.end_break`), es gibt keinen zweiten.

## 5. UTC-Stempel werden jetzt tatsächlich benutzt

`compliance._entry_bounds()` behauptete in seinem eigenen Docstring, die
UTC-Stempel hätten Vorrang – benutzte aber ausschließlich `work_date` plus
Ortszeit. Über eine Zeitumstellung hinweg lag die Ruhezeit dadurch um eine
Stunde daneben.

Jetzt gilt:

* `started_at_utc` / `ended_at_utc` haben Vorrang, wenn gepflegt.
* Ortszeit ist **Rückfallebene** für Bestandsbuchungen vor 0.14.0.
* Ein naiver Wert aus einer `*_at_utc`-Spalte wird als **UTC** gelesen, nicht
  als Ortszeit – die Spalte heißt nicht umsonst so. (Genau hier wäre die
  Korrektur um den Zonenversatz danebengegangen.)
* Gerechnet wird durchgehend mit zonenbehafteten Zeitpunkten; naive und
  zonenbehaftete Werte werden nie gemischt.

Abgesichert durch Tests für Mitternacht, Nachtarbeit und **beide**
Zeitumstellungen in `Europe/Berlin`: Am 29.03.2026 fällt eine Stunde aus – wer
um 22:00 aufhört und um 8:00 anfängt, hat nur neun Stunden Ruhe, nicht zehn.
Am 25.10.2026 ist es umgekehrt.

## 6. Feststellungen werden fortgeschrieben statt gelöscht

Bis 0.14.2 löschte jede Neuberechnung die offenen `ComplianceFlag`-Datensätze
physisch. Hinterher war nicht mehr erkennbar, dass es sie je gab – das
Gegenteil dessen, was eine revisionssichere Erfassung leisten soll.

Neuer Lebenszyklus (`models.ComplianceState`):

| Zustand | Bedeutung |
|---|---|
| `detected` | neu erkannt |
| `changed` | besteht weiter, der bewertete Datenstand hat sich geändert |
| `resolved` | besteht nicht mehr (Buchung korrigiert oder storniert) – **nicht gelöscht** |
| `acknowledged` | gesehen und mit Begründung eingeordnet |
| `reopened` | nach einer Bestätigung erneut aufgetreten |

**Eine Bestätigung gilt nur für den geprüften Datenstand.** Sie wird an eine
Prüfsumme gebunden (`fingerprint`, SHA-256 über Code, Schweregrad und
Detailtext mit den bewerteten Minuten). Ändert sich Arbeitszeit, Pause oder
Schweregrad, passt die Prüfsumme nicht mehr und die Feststellung wird
**automatisch wieder geöffnet**. Eine Einordnung von gestern deckt keinen
Verstoß von heute zu.

Ohne Änderung bleibt die Bestätigung bestehen – niemand soll dieselbe Sache
zweimal einordnen müssen.

## 7. Kunden sind keine Arbeitgeber

`Company` ist in dieser Anwendung ein **Kunde**, `CompanyLocation` ein
**Kunden-/Auftragsstandort**. Diese Daten dienen der Auftragszuordnung und sind
**keine** Quelle für arbeitsrechtliche Regeln.

Die Prüfung ergab: `app/compliance.py` und `app/services.py` greifen an keiner
Stelle auf `company` oder `location` zu – die Trennung hielt bereits. Sie ist
jetzt in beiden Modulen und an beiden Modellklassen ausdrücklich dokumentiert
und durch Tests abgesichert, damit sie nicht unbemerkt aufweicht:

* Feiertagsregion, Sollzeit, Pausenpflicht, Höchstarbeitszeit und Ruhezeit
  stammen ausschließlich aus der zentralen Konfiguration (Tabelle `holidays`
  bzw. Mitarbeiterstammdaten).
* Ein Wechsel von Kunde, Auftrag oder Kundenstandort ändert **keine** dieser
  Regeln.
* Arbeitszeiten aller Kunden werden für Tages- und Ruhezeitprüfung gemeinsam
  betrachtet.
* Arbeit an einem Kundenstandort außerhalb der eigenen Feiertagsregion löst
  weder eine Feiertagsgutschrift noch eine Feiertagswarnung aus.
* Umgekehrt gilt ein Feiertag der eigenen Region auch dann, wenn die Buchung
  einem Kunden in einer anderen Region zugeordnet ist.

## Datenbank

**Migration 18** (`_add_compliance_lifecycle`) – in beiden Mechanismen
(`ensure_schema()` und `MIGRATIONS`), wie vorgeschrieben.

Sieben neue Spalten an `compliance_flags`: `state`, `fingerprint`,
`acknowledged_fingerprint`, `resolved_at`, `reopened_at`, `revision_no`,
`updated_at`. Portables DDL für SQLite, MySQL, MariaDB und PostgreSQL.

**Idempotent und datenerhaltend.** Vorhandene Kennzeichnungen behalten ihren
Inhalt und bekommen einen passenden Zustand: bereits bestätigte
`acknowledged`, alle übrigen `detected`. Die Prüfsumme bleibt zunächst `NULL`
und wird bei der nächsten Neuberechnung gesetzt – bis dahin gilt eine
Bestätigung weiter, denn eine leere Prüfsumme wird nicht als Änderung gewertet.

Die neuen Spalten wandern automatisch in das logische Backup und damit auch
über Datenbankgrenzen hinweg (`Base.metadata.sorted_tables`).

**Keine Änderung** an bestehenden Migrationen; Nummerierung fortlaufend.

## Was sich für den Betrieb ändert

* **Bestehende API-Integrationen brechen**, wenn sie sich bisher ohne Anmeldung
  bedient haben. Das ist beabsichtigt. Sie brauchen jetzt eine Sitzung und das
  passende Recht.
* **`DELETE /api/time-entries/{id}` verlangt `?reason=…`** – ohne Begründung
  antwortet der Server mit 400.
* **Mehr Pausenwarnungen.** Die schichtbasierte Prüfung findet Fälle, die
  vorher durchgefallen sind – vor allem bei Beschäftigten, die an einem Tag für
  mehrere Kunden arbeiten. Die gespeicherte Arbeitszeit ändert sich dadurch
  **nicht**.
* Offline-Aktionen, Terminalimporte, Backups und Restore laufen unverändert.

## Tests

`tests/test_v0150.py` – 42 Tests:

* **Schnittstelle:** anonyme Lese- und Schreibzugriffe (401), fehlendes Recht
  (403), Scope-Umgehung über eine fremde Benutzer-ID (403), Buchung für Dritte,
  Stornierung mit Akteur und Begründung in der Historie, Stornierung ohne
  Begründung (400), Protokollierung ohne Geheimnisse.
* **Compliance-Rechte:** Einordnen einer fremden Kennzeichnung wird abgewiesen.
* **Pausen:** zwei Buchungen ohne echte Pause ergeben zusammen eine Warnung;
  Kunden- und Standortwechsel täuschen keine Pause vor; 14 Minuten zählen
  nicht, ab 15 Minuten schon; die Grenzen 6:00 / 6:01 / 9:00 / 9:01 exakt;
  Nachtschicht über Mitternacht als eine Schicht.
* **Pausenhistorie:** Beginn und Ende protokolliert, Korrektur ohne Begründung
  abgewiesen, stornierte Pause bleibt sichtbar.
* **Zeitzonen:** UTC-Stempel werden benutzt, Bestandsbuchungen fallen auf
  Ortszeit zurück, beide Zeitumstellungen in `Europe/Berlin`.
* **Feststellungen:** erledigte bleiben erhalten, Änderung nach Bestätigung
  öffnet erneut, unveränderte behalten ihre Bestätigung.
* **Kunden/Arbeitgeber:** zwei Kunden ergeben einen Arbeitstag, Feiertag am
  Kundenstandort wirkt nicht, Feiertag der eigenen Region wirkt auch bei
  Kundenarbeit.
* **Migration:** Nummer 18 registriert und fortlaufend, Spalten vorhanden,
  Aufstieg von einem 0.14.x-Bestand ohne Datenverlust, doppelte Ausführung
  unschädlich, neue Spalten im logischen Backup.

## Bekannte Grenzen

* Die Schichtgrenze von sechs Stunden ist eine Festlegung, keine
  Gesetzesvorgabe – siehe Abschnitt 3.
* Ausnahmen nach §§ 7, 10 ArbZG, Tariföffnungen, Bereitschaftsdienst und
  Rufbereitschaft kann die Anwendung nicht bewerten. Sie kennzeichnet, was
  auffällt; entscheiden müssen Menschen.
* Bestandsbuchungen ohne UTC-Stempel werden über die Anlagenzeitzone
  umgerechnet. Wurde die Zeitzone der Installation seit der Erfassung
  geändert, ist diese Umrechnung eine Annäherung – geraten wird nichts,
  nachträglich umgeschrieben ebenfalls nichts.
* Revisionssicherheit endet an der Anwendungsgrenze: Wer direkten Datenbank-
  oder Dateizugriff hat, kann Einträge verändern. Dafür braucht es Rechte-,
  Backup- und Betriebsmaßnahmen außerhalb der Anwendung.

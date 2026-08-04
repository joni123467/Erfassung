# Release Notes 0.20.8

**Datum:** 2026-08-03
**Art:** Funktionserweiterung (Patch)

Tätigkeitsbeschreibungen lassen sich jetzt nachtragen – unter **Buchungen** an
jeder eigenen Buchung und unter **Urlaub** an jedem eigenen Antrag.

---

## Was vorher fehlte

Ein Kommentar ließ sich nur an **einer** Stelle ändern: an der zuletzt
beendeten Buchung des **laufenden Tages**, über das Dashboard oder die App.
Wer die Tätigkeit später beschreiben wollte, hatte keinen Weg:

- am Monatsende, wenn der Nachweis zusammengestellt wird,
- bei einer Buchung, die vom Terminal kam und nie einen Kommentar hatte,
- oder schlicht, weil man beim Ausstempeln in Eile war.

Übrig blieb der Umweg über die Administration – jemand mit `Time.Edit` musste
die fremde Buchung anfassen, obwohl es nur um die Beschreibung der eigenen
Arbeit ging.

## Was jetzt geht

**Unter Buchungen** trägt die Spalte *Kommentar* ein Eingabefeld mit
Schaltfläche *Speichern* – für jede eigene Buchung des gewählten Monats, in
jedem Status. Nach dem Speichern bleibt die Monatsauswahl erhalten.

**Unter Urlaub** dasselbe in der Spalte *Kommentar* der eigenen Anträge, auch
für bereits genehmigte: Der Kommentar beschreibt, er entscheidet nicht.

Das Recht dafür gibt es seit Langem – `Own.Comment.Edit`, „Eigene Kommentare
nachträglich bearbeiten". Es steuerte bisher nur den Dashboard-Weg und steuert
jetzt beide.

## Was ausdrücklich **nicht** geht

| | |
| --- | --- |
| Zeiten, Firma, Einsatzort, Status einer Buchung | unberührt – dafür gibt es `Time.Edit` und den Freigabeweg |
| Zeitraum, Art, Status eines Antrags | unberührt – wer den Zeitraum ändern will, zieht zurück und stellt neu |
| Fremde Buchungen und Anträge | abgewiesen, auch bei direkt geratener ID |
| Abgerechnete (gesperrte) Perioden | abgewiesen; dort erscheint erst gar kein Feld, sondern der Hinweis „Zeitraum abgerechnet" |
| Ohne `Own.Comment.Edit` | kein Feld, nur der Text |

## Nachvollziehbarkeit

Ein Nachtrag ist eine Änderung und wird als solche festgehalten:

- **Buchungen** laufen über `crud.update_time_entry_notes` und landen damit in
  der Revisionshistorie – mit Vorher/Nachher, sichtbar unter
  *Administration → Zeiterfassung → Historie* der Buchung und im zentralen
  Änderungsprotokoll.
- **Anträge** haben keine Revisionstabelle; die Änderung geht deshalb ins
  Auditlog (`logs/audit.log`) – mit Antragsnummer sowie altem und neuem Text.
  Ein Antrag ist ein Nachweis, und eine stille Änderung daran wäre keiner.

---

## Umsetzung

- `POST /records/entries/{entry_id}/note` – Kommentar einer eigenen Buchung.
- `POST /vacations/{vacation_id}/comment` – Kommentar eines eigenen Antrags.
- Beide Formulare stehen leer im Tabellenraster und hängen ihre Felder über
  das HTML-Attribut `form="…"` an. So bleibt die Tabellenzeile gültiges HTML –
  dasselbe Muster wie bei den Standorten im Firmenformular.
- Die Sperre abgerechneter Perioden steht ohnehin im Schreibpfad
  (`crud.ensure_period_open`); die Buchungsseite nimmt sie zusätzlich vorweg,
  damit gar kein Feld erscheint, das beim Absenden abgewiesen würde.
- Der bisherige Weg über `/punch` (Dashboard, App, Offline-Warteschlange)
  bleibt unverändert bestehen.

## Tests

`tests/test_v0208.py` (34 Tests, davon sechs zum Nebenbefund weiter unten):

- Das Feld erscheint, trägt den aktuellen Text und hat ein CSRF-Token.
- Nachtragen, Ersetzen und Leeren wirken; die Monatsauswahl überlebt.
- Zeiten, Firma, Status, Zeitraum und Art bleiben nachweislich unverändert.
- Die Änderung steht in der Revisionshistorie bzw. im Auditlog.
- Fremde Vorgänge, gesperrte Perioden und fehlendes Recht werden abgewiesen –
  jeweils mit der Gegenprobe, dass der alte Text **stehen bleibt**.
- Text über 255 Zeichen wird auf die Spaltenbreite gekürzt.
- Der Dashboard-Weg über `/punch` funktioniert weiterhin.
- Erneut: **jedes** POST-Formular aller Vorlagen trägt ein CSRF-Token.

Im Browser (Chromium/Playwright) nachgemessen:

```
Kommentarfelder unter Buchungen: ['', 'Wartung Halle 2', '', 'Aufmaß beim Kunden']
Nach dem Speichern:              ['Nachtraeglich beschrieben', 'Wartung Halle 2', '', 'Aufmaß beim Kunden']
Rueckmeldung: Kommentar gespeichert.
URL danach:   /records?month=2026-08&msg=Kommentar+gespeichert.

Kommentarfelder unter Urlaub:    ['Herbstferien', '']
Nach dem Speichern:              ['Herbstferien', 'Umzug']
```

Keine Konsolen- oder Netzwerkfehler; kein waagerechter Überlauf bei 390 px.

---

## Nebenbefund: Eine Nullminuten-Buchung sperrte 24 Stunden

Beim vollen Testlauf zu dieser Version fiel ein Test aus, der mit den
Kommentaren nichts zu tun hat:
`test_v0121.py::test_a_running_order_can_still_be_ended`, mit der Meldung
*„Zeitraum überschneidet sich mit einer vorhandenen Buchung."* Dahinter stand
kein Zufall, sondern ein Rechenfehler.

`crud._entry_bounds` – die Grundlage der Überschneidungsprüfung – behandelte
ein Ende **gleich** dem Beginn wie eine Schicht über Mitternacht:

```python
if end_dt <= start_dt:      # bis 0.20.7
    end_dt += timedelta(days=1)
```

Eine Buchung von 15:42 bis 15:42 – null Minuten – belegte damit **24 Stunden**,
von 15:42 des einen bis 15:42 des nächsten Tages. Nachgemessen:

```
start_time == end_time == 15:42  ->  15:42:00 bis 15:42:00 des Folgetags (1 Tag)
später am selben Tag  17:00-18:00  ->  blockiert
am Folgetag           08:00-09:00  ->  blockiert
```

**Was das im Betrieb bedeutet.** Wer einen Auftrag startet und ihn in derselben
Minute wieder beendet – ein Fehlklick, eine schnelle Korrektur –, konnte danach
den ganzen Tag und den folgenden Vormittag nichts mehr buchen. Schlimmer noch:
„Auftrag beenden" schließt die Auftragsbuchung und startet unmittelbar die
normale Arbeitszeit weiter. Genau dieser Anschluss scheiterte an der eben
geschlossenen Buchung – **die Arbeitszeit lief nicht weiter**, und die Person
bekam nur eine Überschneidungsmeldung zu sehen.

Behoben durch den strikten Vergleich:

```python
if end_dt < start_dt:       # ab 0.20.8
    end_dt += timedelta(days=1)
```

Ein Ende **vor** dem Beginn heißt weiterhin: Schicht über Mitternacht, Ende am
Folgetag. Ein Ende **gleich** dem Beginn heißt jetzt das, was dasteht.

`worktime.entry_bounds` – die einzige Quelle aller Dauern – rechnete an
derselben Stelle schon immer mit `<`. Die beiden Rechnungen stimmen damit
wieder überein; genau dieses Auseinanderlaufen hatte 0.16.0 für die
Dauerberechnung bereits beseitigt.

Sechs Tests sichern das ab: die Rechnung selbst, die unverändert erkannte
Nachtschicht, dass eine Nullminuten-Buchung nichts blockiert (davor, danach und
am Folgetag), dass eine echte Überschneidung weiterhin erkannt wird, dass
aneinandergrenzende Buchungen sich nicht überschneiden, und der vollständige
Vorgang „Auftrag in derselben Minute beenden – die Arbeitszeit läuft weiter".
Die beiden Kernprüfungen wurden gegen den alten Stand gegengeprüft und
schlagen dort fehl.

---

## Migration

Keine. 0.20.8 ändert weder Datenbankschema noch gespeicherte Daten; die
Schemaversion bleibt bei 23. Es kommt kein neues Recht hinzu – `Own.Comment.Edit`
gibt es bereits, und wer es hat, bekommt die neuen Felder ohne Zutun.

Bereits gespeicherte Nullminuten-Buchungen blockieren ab sofort nichts mehr;
sie bleiben unverändert stehen und zählen wie bisher null Minuten.

---

## Hinweis

Diese Fassung erweitert eine Bedienmöglichkeit. Sie ist weder eine Aussage über
die vollständige Rechtskonformität der Anwendung noch eine Zertifizierung.

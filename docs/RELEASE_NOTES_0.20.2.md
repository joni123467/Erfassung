# Release Notes 0.20.2

Korrigiert drei Grenzfälle der Jahresprüfung für Sonn- und Nachtarbeit aus
0.20.0. Alle drei führten dazu, dass die Anwendung eine Aussage traf, die die
Daten nicht hergaben.

> **Keine rechtliche Garantie.** Es gilt unverändert, was in
> [`RELEASE_NOTES_0.14.0.md`](RELEASE_NOTES_0.14.0.md) steht: Die Umsetzung
> erfüllt technische Anforderungen, ist **nicht zertifiziert** und ersetzt
> keine Rechtsberatung. In Betrieben mit Betriebsrat ist die Einführung nach
> § 87 Abs. 1 Nr. 6 BetrVG mitbestimmungspflichtig.

## 1. Die Nachtarbeitsgrenze war um eine Minute zu großzügig

§ 2 Abs. 4 ArbZG definiert Nachtarbeit als Arbeit, die **mehr als** zwei
Stunden der Nachtzeit umfasst. Der Vergleich stand auf `>=`:

| Nachtminuten | bis 0.20.1 | ab 0.20.2 |
|---|---|---|
| 119 | keine Nachtarbeit | keine Nachtarbeit |
| **120** | **Nachtarbeit** | **keine Nachtarbeit** |
| 121 | Nachtarbeit | Nachtarbeit |

Eine punktgenaue Schicht von 23:00 bis 01:00 Uhr galt damit als Nachtarbeit,
obwohl das Gesetz sie ausnimmt. Betroffen waren beide Auswertungen: die
Tagesfeststellung nach § 6 Abs. 2 ArbZG und die Jahreszählung der 48 Tage nach
§ 2 Abs. 5 ArbZG.

Die Schwelle wird jetzt an **genau einer** Stelle ausgewertet
(`compliance.is_night_work`). Tages- und Jahresprüfung können dadurch nicht
mehr auseinanderlaufen; ein Test hält fest, dass es keinen zweiten Vergleich
gibt.

Unverändert: Nachtzeit 23:00–06:00 Uhr, Pausen werden anhand der tatsächlichen
Intervalle herausgerechnet, gerechnet wird über UTC und die bei der Buchung
gespeicherte Zeitzone – auch über eine Zeitumstellung hinweg.

## 2. Die Sonntagsprüfung kannte den Beschäftigungszeitraum nicht

Die Zählung der freien Sonntage nach § 11 Abs. 1 ArbZG lief über das **ganze**
Kalenderjahr. Wer im November eintrat, bekam die Sonntage von Januar bis
Oktober als „beschäftigungsfrei" gutgeschrieben – Sonntage, an denen es
überhaupt kein Beschäftigungsverhältnis gab. Das Ergebnis war ein „Minimum
erfüllt", das auf einer Zeit beruhte, in der die Person gar nicht beschäftigt
war.

**Neue Felder am Benutzer** (Administration → Benutzer → *Person* →
**Arbeitszeit**):

- `employment_start_date` – Beschäftigungsbeginn
- `employment_end_date` – Beschäftigungsende (optional)

**Prüfzeitraum** ist der Schnitt aus Kalenderjahr und Beschäftigungsverhältnis:

```
period_start = max(Beschäftigungsbeginn, 1. Januar)
period_end   = min(Beschäftigungsende,  31. Dezember)
```

`required_free_sundays` ist `min(15, Sonntage im Zeitraum)`. In einem Teiljahr
mit neun Sonntagen sind fünfzehn freie nicht erreichbar; ein unerfüllbares Soll
wäre keine brauchbare Aussage.

**Ohne Beschäftigungsbeginn kein positives Prüfurteil.** Fehlt das Datum, ist
`employment_period_known = false`, und weder `sunday_rule_met` noch
`sunday_rule_impossible` können `true` werden. Die Übersicht weist dann
„Beschäftigungsbeginn fehlt" aus. Ohne Eintritt lässt sich schlicht nicht
sagen, welche Sonntage überhaupt in das Beschäftigungsverhältnis fallen –
weder eine Bestätigung noch ein Verstoß wäre gedeckt.

**Bestandskonten bekommen kein erfundenes Eintrittsdatum.** Beide Felder
bleiben nach der Migration `NULL`. Ein geratenes Datum wäre in einem
gesetzlichen Nachweis schlimmer als eine ehrliche Lücke.

**Validierung:** Beide Felder sind optional; sind beide gesetzt, muss das Ende
am oder nach dem Beginn liegen. Geprüft wird **serverseitig** im Pydantic-Modell
und zusätzlich beim Auswerten des Formulars – nicht nur über HTML-Attribute,
denn dieselben Daten kommen auch über die Schnittstelle.

## 3. Der Jahreswechsel fiel durch

Eine am 31. Dezember um 23:00 Uhr begonnene Schicht reicht in den 1. Januar.
Ist der 1. Januar ein Sonntag, muss er im **neuen** Kalenderjahr als gearbeitet
gelten. Die Prüfung lud die Buchungen aber über `work_date` – und die
Silvesterschicht trägt das Datum des Vorjahres.

Geladen wird jetzt ab dem **Vortag** des Zeitraumbeginns; zugeordnet wird über
die tatsächlichen lokalen Arbeitsintervalle. Der mitgeladene Vortag zählt dabei
nicht als Nachtarbeitstag des neuen Jahres – er gehört zum Vorjahr.

Beispiel (durch einen Test abgedeckt):

| Buchung | Ergebnis für 2023 |
|---|---|
| 31.12.2022, 23:00–02:00 Uhr | ein gearbeiteter Sonntag (01.01.2023 ist ein Sonntag) |

## Datenbank und Migration

**Migration 22** (`_add_employment_period`) ergänzt beide Spalten als
`DATE NULL`.

- portabel über SQLite, MySQL/MariaDB und PostgreSQL (`db_schema.add_column`),
- beliebig oft ausführbar, ohne etwas zu beschädigen,
- datenerhaltend: vorhandene Zeilen werden nicht angefasst,
- **ohne** Vorgabewert und **ohne** Nachbefüllung – `NULL` ist hier die
  richtige Antwort und bleibt `NULL`,
- bestehende Migrationen bleiben unverändert und behalten ihre Nummern.

Denselben idempotenten Reparaturpfad gibt es in `ensure_schema()`
(`app/main.py`), damit auch Installationen aufschließen, deren Migrationsstand
nicht gepflegt wurde.

Geprüft an einer eigens erzeugten Alt-Datenbank ohne die beiden Spalten: Nach
dem Migrationslauf existieren beide Spalten, der Bestandsbenutzer ist
unverändert vorhanden, beide neuen Werte sind `NULL`, und ein wiederholter Lauf
ändert daran nichts.

## Neue Werte im Bericht

`annual_compliance_report(...)` liefert zusätzlich:

| Feld | Bedeutung |
|---|---|
| `employment_period_known` | Ist ein Beschäftigungsbeginn hinterlegt? |
| `employment_start_date` | Eintritt (oder `None`) |
| `employment_end_date` | Austritt (oder `None`) |
| `period_start` / `period_end` | tatsächlich geprüfter Zeitraum |

`required_free_sundays` ist nicht mehr fest 15, sondern das erreichbare
Minimum. Die Feststellung nennt im Text das tatsächlich geforderte Minimum und
– sofern hinterlegt – den Beschäftigungszeitraum.

## Unverändert

- Tatsächlich geleistete Arbeitszeit wird nie blockiert, gekürzt oder
  automatisch verändert. Verstöße werden **gekennzeichnet**.
- Pausen zählen anhand ihrer tatsächlichen Intervalle.
- Zeitberechnungen laufen über die zentrale UTC-/Zeitzonenlogik.
- Compliance-Feststellungen bleiben revisionssicher (`detected`, `changed`,
  `reopened`, `resolved`, `acknowledged`), die Historie bleibt append-only.
- Deaktivierte Konten bleiben Teil der Jahresprüfung.
- Rechte unverändert: `Time.View` bestimmt die sichtbaren Personen,
  `Time.Compliance.Manage` ist zum Einordnen erforderlich.
- Kunden, Aufträge und Kundenstandorte beeinflussen die arbeitsrechtliche
  Bewertung nicht.
- Kein neuer Regelcode-Typ und keine neue Tabelle: Die Jahresfeststellung nutzt
  weiterhin die vorhandene Spalte `compliance_flags.code`.

## Weiterhin nicht maschinell entscheidbar

Diese Punkte bleiben ausdrücklich eine menschliche Einordnung; die Anwendung
macht die technisch feststellbaren Sachverhalte sichtbar und mehr nicht:

- **Wechselschicht** als alternative Einordnung der
  Nachtarbeitnehmereigenschaft (§ 2 Abs. 5 ArbZG) – ohne Dienstplan- und
  Vertragsdaten nicht entscheidbar.
- **Branchenausnahmen**, insbesondere die abweichende Nachtzeit für Bäckereien
  und Konditoreien (§ 2 Abs. 4 ArbZG) – setzt ein Branchenmerkmal voraus, das
  die Anwendung nicht führt.
- **Tarifverträge und Betriebsvereinbarungen** (§ 7 ArbZG) sowie behördliche
  Bewilligungen (§ 15).
- **Arbeitsmedizinische Vorsorge** nach § 6 Abs. 3 ArbZG.
- **Zuschlags- oder Freizeitausgleich** nach § 6 Abs. 5 ArbZG – die
  angemessene Höhe ist eine Vertrags- und Tariffrage.
- **Ausnahmen nach § 14 ArbZG** (vorübergehende Arbeiten in Notfällen).

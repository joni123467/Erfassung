# Release Notes 0.9.15

## Überblick

Zwei ergänzende Funktionen rund um manuelle Zeitbuchungen: Nachträge lassen
sich jetzt auch **zwischen bereits abgeschlossene Buchungen** einfügen, und
Berechtigte (insbesondere Administratoren) können Zeitbuchungen direkt aus den
**Zeitübersichten** bearbeiten.

## Neue Funktionen

### Nachtrag in eine abgeschlossene Buchung

Seit 0.9.14 wird die *laufende* Buchung geteilt, wenn ein Nachtrag in sie
fällt. Das gilt jetzt genauso für **abgeschlossene** Buchungen: Fällt eine
manuelle Buchung (z. B. ein Telefonat) vollständig in eine bestehende Buchung,
wird diese in bis zu zwei Abschnitte zerlegt und der Nachtrag dazwischen
eingefügt.

| Vorher | Nachher |
|--------|---------|
| 08:00–12:00 (Büro, freigegeben) | 08:00–10:00 (Büro, freigegeben, Pausen) |
| | 10:00–10:20 Nachtrag „Telefonat" (wartet auf Freigabe) |
| | 10:20–12:00 (Büro, freigegeben) |

Eigenschaften:

- Abschnitt davor und danach behalten **Firma, Kommentar, Status und Quelle**
  der Bestandsbuchung.
- Die erfassten **Pausenminuten** bleiben beim führenden Abschnitt (oder –
  falls es keinen gibt – beim nachfolgenden).
- Randfälle werden korrekt behandelt: Beginnt der Nachtrag am Start der
  Bestandsbuchung, entfällt der erste Abschnitt; endet er am Ende, entfällt
  der zweite; deckt er sie exakt ab, wird die Bestandsbuchung ersetzt.
- Nur teilweise Überlappungen (nicht vollständig umschlossen) und Kollisionen
  mit anderen Buchungen werden weiterhin abgelehnt. Mehrtägige/über
  Mitternacht laufende Bestandsbuchungen werden nicht geteilt.

Damit lassen sich neue Stempelungen zwischen bestehende manuelle Buchungen
einfügen, ohne dass Zeiten doppelt zählen.

### Zeitbuchungen aus den Berichten bearbeiten

Die Einzelbuchungs-Tabelle unter **Administration → Zeiterfassung →
Zeitübersichten** hat für Berechtigte eine neue Spalte „Aktionen" mit einem
**Bearbeiten**-Link, der das bestehende Bearbeitungsformular öffnet (Rücksprung
in den gefilterten Bericht inklusive).

- Sichtbar für Administratoren sowie Gruppen mit dem Recht „Zeitbuchungen
  bearbeiten".
- Bisher war das Bearbeitungsformular nur aus den Freigaben (offene manuelle
  Buchungen) erreichbar; jetzt lassen sich auch freigegebene und automatische
  Buchungen direkt aus der Übersicht korrigieren.
- Der **Geltungsbereich** (eigenes Team / alle Benutzer) aus 0.9.12 gilt
  unverändert – Bearbeiten fremder Buchungen außerhalb des Geltungsbereichs
  bleibt gesperrt.
- Laufende Buchungen werden in der Tabelle als „läuft" markiert und nicht zur
  Bearbeitung angeboten.

## Datenbank

Keine Schemaänderungen; keine Migration erforderlich.

## Upgrade-Hinweise

Standard-Update genügt.

# Release Notes 0.9.14

## Überblick

Manuelle Zeitbuchungen können jetzt auch **bei laufender Arbeitszeit**
nachgetragen werden. Fällt der Nachtrag (z. B. ein Telefonat) in die aktuell
laufende Buchung, wird diese automatisch geteilt.

## Neue Funktionen

### Nachtrag bei laufender Arbeitszeit

Bisher lehnte die Überschneidungsprüfung jeden Nachtrag ab, der in die
laufende Buchung fiel („Zeit überschneidet sich mit einer bestehenden
Buchung") – die laufende Buchung gilt intern als Zeitraum „Start bis jetzt".

Jetzt wird die laufende Buchung geteilt. Das Ergebnis entspricht dem, was
beim Live-Stempeln entstanden wäre:

| Vorher | Nachher |
|--------|---------|
| 08:00 – läuft (Arbeitszeit) | 08:00–10:00 abgeschlossen (Arbeitszeit, bisherige Pausen) |
| | 10:00–10:15 Nachtrag „Telefonat" (wartet auf Freigabe) |
| | 10:15 – läuft weiter (Arbeitszeit, Firma/Kommentar unverändert) |

Eigenschaften:

- **Keine doppelten Zeiten**: Der Nachtrag ersetzt den entsprechenden
  Abschnitt der laufenden Buchung, statt parallel zu ihr zu existieren.
- **Pausen**: Bereits erfasste Pausenminuten bleiben beim abgeschlossenen
  ersten Teil; die weiterlaufende Buchung startet ohne Pausen. Beginnt der
  Nachtrag exakt mit der laufenden Buchung, entfällt der erste Teil und die
  Pausenminuten bleiben an der weiterlaufenden Buchung.
- **Freigabe unverändert**: Der Nachtrag wartet wie jede manuelle Buchung
  auf Freigabe; die geteilten Arbeitszeit-Abschnitte bleiben freigegeben.
- **Klare Fehlermeldungen**: Bei laufender Pause muss diese zuerst beendet
  werden. Nachträge, die vor der laufenden Buchung beginnen, in der Zukunft
  enden oder mit anderen Buchungen kollidieren, werden weiterhin abgelehnt.
- Nachträge außerhalb der laufenden Buchung (z. B. für gestern) verhalten
  sich unverändert.

## Datenbank

Keine Schemaänderungen; keine Migration erforderlich.

## Upgrade-Hinweise

Standard-Update genügt.

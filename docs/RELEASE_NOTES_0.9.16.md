# Release Notes 0.9.16

## Überblick

Fehlerbehebung: Eine bestehende Buchung ließ sich nicht korrigieren, wenn sie
sich mit einer anderen Buchung überschnitt – selbst dann nicht, wenn der
Zeitraum durch die Korrektur *kleiner* wird.

## Fehlerbehebung

### Bearbeiten scheiterte an bereits bestehenden Überschneidungen

**Symptom:** Eine (z. B. automatisch erfasste) Buchung „14:18–19:20" sollte auf
„16:00" verkürzt werden. Beim Speichern erschien „Zeiten überschneiden sich mit
einer bestehenden Buchung", obwohl der neue Zeitraum kleiner ist als der alte.

**Ursache:** Die Überschneidungsprüfung beim Bearbeiten verglich den neuen
Zeitraum mit allen anderen Buchungen und lehnte jede Überlappung ab – auch
solche, die bereits mit dem *bisherigen* Zeitraum bestanden. Typische Auslöser:

- eine noch **laufende (offene) Buchung**, deren Zeitfenster bis „jetzt" reicht
  und damit den ganzen Tag überspannt, oder
- eine bereits vorhandene **Doppelbuchung** (z. B. durch überlappende Importe).

Da jede Buchung, die den verkürzten Bereich überlappt, auch den ursprünglichen
(größeren) Bereich überlappte, war eine Korrektur schlicht unmöglich – die
fehlerhafte Buchung ließ sich nicht einmal verkürzen.

**Behebung:** Beim Bearbeiten werden nur noch **neu entstehende**
Überschneidungen abgelehnt. Eine Überschneidung, die schon mit dem
ursprünglichen Zeitraum der Buchung bestand, blockiert die Korrektur nicht mehr.

- Verkürzen/Anpassen einer Buchung, die in eine bestehende Überlappung
  verwickelt ist, ist jetzt möglich.
- Das **Verschieben** einer Buchung auf einen bisher freien, aber von einer
  anderen Buchung belegten Zeitraum wird weiterhin abgelehnt (echter neuer
  Konflikt).
- Das **Anlegen** neuer Buchungen sowie Nachträge/Teilen bleiben unverändert
  streng geprüft.

## Datenbank

Keine Schemaänderungen; keine Migration erforderlich.

## Upgrade-Hinweise

Standard-Update genügt. Bestehende Doppelbuchungen lassen sich nach dem Update
korrigieren; um eine Überlappung ganz aufzulösen, ggf. beide beteiligten
Buchungen anpassen oder eine löschen.

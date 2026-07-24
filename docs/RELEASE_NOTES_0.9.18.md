# Release Notes 0.9.18

## Überblick

Fehlerbehebung für die eigentliche Ursache der wiederkehrenden Meldung „Zeiten
überschneiden sich mit einer bestehenden Buchung" beim Bearbeiten: Sekunden an
der Grenze zwischen direkt angrenzenden Buchungen.

## Fehlerbehebung

### Falsche Überschneidung zwischen angrenzenden Buchungen (Sekunden)

**Symptom:** Zwei automatische Buchungen liegen nahtlos hintereinander, z. B.

| Zeitraum | Firma |
|----------|-------|
| 11:08–14:18 | Allgemeine Arbeitszeit |
| 14:18–19:20 | Intensivpflegedienst … (Notiz „Bis 16:00") |

Beim Versuch, die zweite Buchung auf 16:00 zu **verkürzen**, erschien „Zeiten
überschneiden sich mit einer bestehenden Buchung: 22.07.2026 11:08–14:18" –
obwohl der Zeitraum kleiner wird und die erste Buchung genau am Startzeitpunkt
endet.

**Ursache:** Terminal-Importe (TimeMoto) speichern die Zeiten **inklusive
Sekunden**. Direkt aneinandergrenzende Buchungen teilen sich denselben
Stempel-Zeitpunkt bis auf die Sekunde – im Beispiel endet die erste Buchung um
`14:18:45` und die zweite beginnt um `14:18:45`. Das Bearbeiten-Formular
arbeitet aber nur mit Minuten (`HH:MM`). Beim Speichern der zweiten Buchung
wurde deren Start von `14:18:45` auf `14:18:00` abgerundet – wodurch sie die
erste Buchung plötzlich um 45 Sekunden „überlappte" und als (vermeintlich
neuer) Konflikt abgelehnt wurde.

**Behebung:** Die Überschneidungsprüfung vergleicht Zeiträume jetzt
**minutengenau** (Anlegen, Bearbeiten und Nachtrag/Teilen). Damit gelten
Sekunden-Grenzfälle direkt angrenzender Buchungen korrekt als *nicht*
überlappend, während echte Überschneidungen von mindestens einer Minute
weiterhin erkannt und abgelehnt werden.

## Datenbank

Keine Schemaänderungen; keine Migration erforderlich.

## Upgrade-Hinweise

Standard-Update genügt. Nach dem Ausrollen lassen sich betroffene Buchungen
(direkt an eine andere angrenzend) wieder normal bearbeiten und verkürzen.

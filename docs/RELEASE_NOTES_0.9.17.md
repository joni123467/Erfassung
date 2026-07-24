# Release Notes 0.9.17

## Überblick

Ergänzung zur Fehlerbehebung aus 0.9.16: Wird das Bearbeiten einer Buchung
tatsächlich durch eine neu entstehende Überschneidung blockiert, nennt die
Meldung jetzt die konkret kollidierende Buchung. Das erleichtert die Diagnose,
falls die Meldung „Zeiten überschneiden sich …" weiterhin auftritt.

## Änderungen

### Aussagekräftige Überschneidungs-Meldung

Beim Speichern einer bearbeiteten Buchung nennt die Fehlermeldung im Konfliktfall
die blockierende Buchung mit Datum und Zeitraum:

> Zeiten überschneiden sich mit einer bestehenden Buchung: 22.07.2026 16:00–19:20

Damit ist sofort ersichtlich, welche andere Buchung im Weg ist – und sie kann
gezielt angepasst oder gelöscht werden.

### Zusammenhang mit 0.9.16

Der eigentliche Fix bleibt unverändert: Eine Buchung, die sich bereits mit dem
**ursprünglichen** Zeitraum überschnitt (z. B. eine noch laufende Buchung, deren
Fenster bis „jetzt" reicht, oder eine bereits vorhandene Doppelbuchung),
blockiert eine Korrektur **nicht** – ein reines Verkürzen ist immer möglich.
Nur ein **neu** entstehender Konflikt (Verschieben auf einen bislang freien,
aber belegten Zeitraum) wird abgelehnt – und dann mit Detailangabe.

## Hinweis zur ausgerollten Version

Sollte die Meldung „Zeiten überschneiden sich …" beim reinen **Verkürzen** einer
Buchung weiterhin **ohne** Detailangabe erscheinen, läuft die Instanz noch nicht
auf 0.9.16/0.9.17. Die aktuell laufende Version steht im Footer jeder Seite bzw.
unter **Administration → System**; alternativ liefert `GET /health` die Version.
In dem Fall bitte das aktuelle Docker-Image ausrollen (GHCR-Tag `0.9.17` bzw.
`latest`) und den Container neu starten.

## Datenbank

Keine Schemaänderungen; keine Migration erforderlich.

## Upgrade-Hinweise

Standard-Update genügt.

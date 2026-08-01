# Release Notes 0.18.0

## Schwerpunkt

Version 0.18.0 schließt Logiklücken in der ArbZG-Ausgleichskontrolle und bei
Ersatzruhetagen. Sie ist eine fachliche Korrektur ohne Schemaänderung.

## Ausgleichsfeststellungen

Ausgleichsvorgänge werden nicht mehr nur am ursprünglichen Buchungstag
bewertet. Ein idempotenter Lauf aktualisiert relevante Überschreitungstage:

- beim Anwendungsstart,
- vor dem Öffnen der Compliance-Übersicht,
- nach Änderungen an Zeitbuchungen.

Dadurch werden spätere Ausgleichstage, Fristnähe und Fristablauf auch in den
gespeicherten Feststellungen und ihrer Historie sichtbar.

## Arbeit an Ausfalltagen

Feiertag, Urlaub oder Ersatzruhetag neutralisieren in der konfigurierten
§-3-Auswertung nur einen arbeitsfreien Tag. Existiert tatsächliche Arbeitszeit,
bleiben Tag und Minuten in der Rechnung. Kunden und Kundenstandorte haben
weiterhin keinen Einfluss auf den Feiertagskalender.

## Ersatzruhetage

Ein Ersatzruhetag:

- muss nach dem betroffenen Sonn-/Feiertag liegen,
- muss innerhalb der bestehenden gesetzlichen Frist liegen,
- darf kein Sonntag oder Feiertag der eigenen zentralen Region sein,
- darf nicht bereits einer anderen Beschäftigung zugeordnet sein,
- darf keine nicht stornierte Arbeitszeit enthalten.

## Konfiguration

Die Wochenvariante des Ausgleichs lässt höchstens 24 Wochen zu. Eine Regelung
über sechs Kalendermonate ist keine pauschale 26-Wochen-Frist und wird deshalb
nicht auf diesem Weg angeboten.

## Datenbank und Update

Es gibt keine Schemaänderung. Migration 20 bleibt der aktuelle Schema-Stand.
Das Update ist datenerhaltend; bestehende Feststellungen werden bei der
nächsten Neubewertung fortgeschrieben, nicht gelöscht.

## Bekannte fachliche Grenze

Die Zuordnung arbeitet weiterhin konservativ FIFO in einem vorwärts
gerichteten Zeitraum je Überschreitungstag. Tarifliche Abweichungen und
Krankheitstage können ohne eigene, belastbare Stammdaten nicht automatisch
bewertet werden. Die Anwendung liefert eine technische Warn- und
Dokumentationshilfe, keine juristische Einzelfallentscheidung.

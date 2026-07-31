# Release Notes 0.13.1 – Standorte gehören zu ihrer Firma

0.13.0 hat die Standorte eingeführt, sie aber bewusst **nicht** an die gewählte
Firma gebunden. Der Gedanke war: Wer für Kunde A arbeitet, kann im eigenen Büro
sitzen – eine Kopplung wäre eine falsche Einschränkung.

In der Praxis war das Ergebnis falsch:

- Beim **Schnellstempeln** – ganz ohne Auftrag – standen Firmenstandorte zur
  Wahl, obwohl es dort keine Firma gibt.
- Im **Auftragsdialog** blieb „Vor Ort" vorausgewählt, statt des Standorts der
  gewählten Firma.
- Und man sah **firmenfremde Standorte**: Bei Kunde A ließ sich ein Standort
  von Kunde B buchen.

Ein Standort gehört zu genau einer Firma. Ab 0.13.1 gilt das überall.

## Was jetzt gilt

| Stelle | Auswahl |
|---|---|
| Schnell stempeln (ohne Auftrag) | nur **Vor Ort** und **Remote** |
| Auftragsdialog, keine Firma gewählt | nur **Vor Ort** und **Remote** |
| Auftragsdialog mit Firma | Vor Ort, Remote **und die Standorte dieser Firma** |
| Nachtrag mit Firma | dieselbe Liste |
| Buchung bearbeiten | Standorte der Firma dieser Buchung |

**Beim Wechsel der Firma tauscht die Liste** und der **Hauptstandort** ist
vorausgewählt – nicht „Vor Ort". Wer eine Firma mit Standort wählt, meint fast
immer deren Standort.

Die Standorte liegen als JSON in der Seite; der Wechsel läuft ohne Nachladen
und funktioniert damit auch offline. In der Stempel-App kommt dieselbe Liste
aus dem Offline-Speicher.

## Serverseitig geprüft

Das Skript ist Bedienkomfort, keine Absicherung. Der Server nimmt einen
Standort nur an, wenn er zur gebuchten Firma gehört – ein veraltetes oder
manipuliertes Formular kann keinen fremden Standort unterschieben.

Verworfen statt abgewiesen: Ein unbekannter, geschlossener, firmenfremder oder
nicht lizenzierter Standort gilt als „vor Ort". Eine Stempelung darf nie an
einer Stammdatenfrage scheitern.

Weil die Firma bei `/punch` erst feststeht, wenn die Aktion ausgewertet ist
(bei `start_company` etwa nach dem Anlegen einer neuen Firma), wird der
Einsatzort jetzt **dort** aufgelöst und nicht mehr vorab.

## Auch der eigene Betrieb

Die Standorte des eigenen Betriebs standen bisher überall zur Wahl. Das war
bequem, aber inkonsequent. Sie hängen jetzt genauso an ihrer Firma: Wer im
eigenen Büro arbeitet, startet einen Auftrag auf den eigenen Betrieb.

Die Markierung „eigener Betrieb" behält ihren Zweck – interne Zeit bleibt in
Auswertungen von Kundenzeit unterscheidbar.

## Was sich nicht ändert

- Ohne gepflegte Standorte bleibt es beim Umschalter „Remote / Vor Ort".
- Bestandsbuchungen (`location_id = NULL`) lesen sich unverändert.
- Keine Schemaänderung, keine Migration.

## Tests

`tests/test_v0130.py` – 27 Tests. Neu bzw. umgeschrieben:

- Schnellstempeln bietet nur Vor Ort und Remote; ein mitgeschickter Standort
  wird dort ignoriert.
- Der Auftragsdialog zeigt die Liste in derselben Pille, der Katalog ist nach
  Firma gruppiert und nennt den Hauptstandort.
- Ein Standort einer anderen Firma wird verworfen – auch der des eigenen
  Betriebs, solange nicht auf ihn gebucht wird.
- Unbekannter und geschlossener Standort fallen auf „vor Ort" zurück.

# Release Notes 0.9.20

## Überblick

Der PDF-Export der **Benutzerauswertung** kann jetzt optional auch die
**Stempelzeiten** – also die einzelnen Buchungen je Benutzer – enthalten.
Bisher gab es diese Detailtiefe nur in der persönlichen Arbeitszeitübersicht,
die Benutzer sich selbst erzeugen.

## Neue Funktion

### Option „Stempelzeiten" beim PDF-Export

Unter **Administration → Benutzerauswertung** steht neben dem PDF-Export ein
Schalter **„Stempelzeiten"**. Ist er gesetzt, hängt das PDF hinter die
Summenübersicht je Benutzer eine Tabelle mit allen freigegebenen Buchungen des
gewählten Zeitraums an:

| Datum | Firma | Start | Ende | Arbeitszeit | Status | Kommentar |
|-------|-------|-------|------|-------------|--------|-----------|

Am Ende jeder Benutzertabelle steht die Summe der Arbeitszeit. Benutzer ohne
Buchungen im Zeitraum erscheinen mit dem Hinweis „Keine freigegebenen Buchungen
im Zeitraum.", damit die Auswertung vollständig bleibt.

Layout und Spalten entsprechen exakt der persönlichen Arbeitszeitübersicht
(`/records` → PDF-Export) – beide nutzen dieselbe Tabellenfunktion.

### Bedienung

- Zeitraum und Benutzerauswahl wie gewohnt über den Filter setzen.
- Schalter „Stempelzeiten" aktivieren und auf **PDF-Export** klicken; der Filter
  wird dabei übernommen.
- Ohne den Schalter bleibt der Export wie bisher die reine Summenauswertung.
- Direkter Aufruf ist ebenfalls möglich:
  `/admin/reports/users/pdf?start=…&end=…&entries=1`
- Dateiname mit Stempelzeiten: `benutzer_zeit_<von>_<bis>_stempelzeiten.pdf`.

## Berechtigungen

Unverändert gilt das Recht **„Zeitübersichten einsehen"** samt Geltungsbereich
aus 0.9.12/0.9.19: Ein Abteilungsadministrator mit Bereich „Eigenes Team"
exportiert ausschließlich Buchungen der eigenen Gruppe – auch die Stempelzeiten.

## Nicht betroffen

- Der **Excel-Export** der Benutzerauswertung bleibt die Summenauswertung.
- Die persönliche Arbeitszeitübersicht ist unverändert.

## Datenbank

Keine Migration; Standard-Update genügt.

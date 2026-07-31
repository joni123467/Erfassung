# Release Notes 0.13.0 – Standorte statt „Vor Ort“

Der Einsatzort einer Buchung war bisher ein Ja/Nein: **Remote** oder **Vor
Ort**. Wer bei drei Kundenstandorten arbeitet, sah in der Auswertung dreimal
dasselbe. Ab 0.13.0 hat jede Firma beliebig viele Standorte mit Anschrift, und
eine Buchung zeigt auf genau einen davon.

## Standorte an der Firma

Unter Administration → Firmen → *Firma bearbeiten* steht jetzt eine
Standortliste: Bezeichnung, Straße, PLZ, Ort, Land. Eine Niederlassung, ein
Werk, eine Baustelle, ein eigenes Büro – beliebig viele je Firma.

Zwei Kleinigkeiten, die den Alltag entscheiden:

- Der **erste Standort** einer Firma wird automatisch zum **Hauptstandort** und
  ist beim Stempeln vorausgewählt. Wer nur eine Adresse hat, merkt vom ganzen
  Umbau nichts.
- Ein Standort lässt sich **schließen** (Haken „aktiv“ entfernen), statt ihn zu
  löschen. Geschlossene Standorte verschwinden aus der Auswahl, bleiben in
  Auswertungen aber vollständig erhalten. Das ist dem Löschen vorzuziehen.

## Der eigene Betrieb

Eine Firma lässt sich als **eigener Betrieb** markieren. Ihre Standorte stehen
dann auch beim Stempeln **ohne Auftrag** zur Wahl – für die eigenen Büros. In
der Firmenübersicht ist sie als solche gekennzeichnet, damit sie sich in
Auswertungen von Kundenzeit trennen lässt.

Damit braucht es keinen zweiten Katalog für eigene Adressen: ein Modell, eine
Oberfläche, eine Migration.

## Beim Stempeln

Das gewohnte Bild bleibt. Ohne gepflegte Standorte ist der Einsatzort
weiterhin der bekannte Umschalter:

```
● Einsatzort  Vor Ort        (Klick →)        ● Einsatzort  Remote
```

Sobald Standorte hinterlegt sind, wird daraus eine **Auswahlliste in derselben
Pille** – gleicher Punkt, gleiche Beschriftung, gleiche Farben:

```
● Einsatzort  [ Vor Ort ▾ ]
                Vor Ort
                Remote
                ── Wir GmbH ──────
                Büro Hamburg · Hamburg
                Büro Berlin · Berlin
                ── Müller GmbH ───
                Werk Nord · Kiel
```

Bewusst **ein** Bedienelement statt Schalter *und* Liste: Auf dem Handy ist
jeder zusätzliche Griff einer zu viel.

> ⚠️ **Gilt nur für 0.13.0.** Die Auswahl hing hier noch nicht an der
> gewählten Firma – auch das Schnellstempeln zeigte Standorte, und
> firmenfremde Standorte waren wählbar. Seit 0.13.1 gehört ein Standort zu
> genau einer Firma; siehe
> [`RELEASE_NOTES_0.13.1.md`](RELEASE_NOTES_0.13.1.md).

Der laufende Zustand zeigt den Standort samt Anschrift, Listen und Exporte
zeigen statt „Vor Ort“ den Standortnamen. Die Spalte „Ort“ in PDF und Excel
erscheint jetzt auch dann, wenn nur Standorte und kein Remote genutzt werden.

## Aufgeräumt: die Stempelkarte

Die Aktionsknöpfe lagen in einer einzigen umbrechenden Reihe – bei schmalem
Fenster stand „Arbeitszeit beenden“ dann irgendwo zwischen den Pausenknöpfen.
Jetzt sind sie gruppiert:

| Gruppe | Knöpfe |
|---|---|
| Pause | Pause starten · Pause beenden |
| Auftrag | Auftrag starten/wechseln · Auftrag beenden |
| Abschluss | **Arbeitszeit beenden** – abgesetzt am rechten Rand |

Auf schmalen Schirmen stapeln die Gruppen mit einer feinen Trennlinie
untereinander, die abschließende Aktion zuletzt. Im Startzustand steht der
Einsatzort in einer eigenen Zeile über den Knöpfen – er gilt für die Buchung,
nicht für einen einzelnen Knopf.

## Offline

Die Standorte kommen über `GET /mobile/sync-data` mit in den Offline-Speicher
und werden beim Start in die Auswahllisten geschrieben. Ohne das stünde man
auf der Baustelle ohne Netz vor einer Liste mit nur zwei Einträgen. Eine
offline erfasste Buchung nimmt den Standort in die Warteschlange mit.

## Was sich für Bestandsdaten ändert: nichts

- `time_entries.location_id` bleibt bei allen vorhandenen Buchungen `NULL`.
  Der Einsatzort ergibt sich dann weiterhin allein aus `is_remote`, die
  Anzeige liest sich unverändert als „Remote“ oder „Vor Ort“.
- Jede vorhandene Firma ist ein Kunde (`is_internal = 0`).
- Wer den Einsatzort nie genutzt hat, sieht die Auswahl gar nicht erst.

Ein unbekannter oder geschlossener Standort wird beim Stempeln **verworfen**
und gilt als „vor Ort“ – abgewiesen wird nichts. Eine Stempelung darf nie an
einer Stammdatenfrage scheitern.

## Historie

Ein gelöschter Standort nimmt seinen Namen nicht mit: Wie bei Firmen wandert er
als `deleted_location_name` an die betroffenen Buchungen, die ihn dann als
„Gelöscht (Werk Nord)“ zeigen. Auch beim Löschen einer ganzen Firma. War der
gelöschte Standort der Hauptstandort, rückt der nächste nach.

## Lizenz

Standorte hängen an Firmen und gehören damit zum Baustein **`orders`**. Ohne
ihn gibt es keine Standortauswahl, und es bleibt beim Umschalter „Remote /
Vor Ort“ wie vor 0.13.0.

## Datenbank

Migration **16** (`_add_company_locations`), in beiden Mechanismen gepflegt:

- neue Tabelle `company_locations`
- `companies.is_internal` (Default `0`)
- `time_entries.location_id` und `time_entries.deleted_location_name`

Geprüft gegen eine 0.12.x-Datenbank: Spalten ergänzt, Tabelle angelegt, alle
Buchungen unverändert.

## Tests

`tests/test_v0130.py` – 24 Tests: mehrere Standorte je Firma, automatischer
Hauptstandort, nur ein Hauptstandort, Schließen statt Löschen, einzeilige
Anschrift; Umschalter ohne Standorte, Liste mit Standorten in derselben Pille,
eigener Betrieb zuerst, Stempeln auf einen Standort, Remote und Vor Ort
unverändert, alte Offline-Aktion ohne das Feld, unbekannter und geschlossener
Standort werden verworfen, Standort unabhängig vom Auftrag; Name überlebt das
Löschen von Standort und Firma, Hauptstandort rückt nach; Pflege über die
Oberfläche samt Fremdzugriff-Schutz; Standorte in der Synchronisation,
Exportspalte, Standortname in der Buchungsliste; ohne `orders` keine Auswahl.

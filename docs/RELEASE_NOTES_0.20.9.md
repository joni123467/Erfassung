# Release Notes 0.20.9

**Ein überschreibender Nachtrag wird nicht mehr doppelt gezählt.**

---

## Die Meldung

> „Woche im Blick scheint teilweise doppelt zu rechnen (von 8 bis 15:42
> 10:46 Std kann nicht passen). Tritt auf, wenn manuell Stempelungen
> hinzugefügt werden, die andere überschreiben."

Der Befund stimmt, und die Zahl war der Schlüssel. Von 08:00 bis 15:42 sind es
7:42 Std = 462 Minuten. Ausgewiesen wurden 10:46 Std = 646 Minuten. Die
Differenz von 3:04 ist kein Rundungsfehler, sondern genau die Zeit ab dem
Beginn des Nachtrags: Wer um 12:38 einen Nachtrag in diese Buchung setzt,
erzeugt drei Abschnitte von 278, 60 und 124 Minuten – und wenn der erste davon
weiterhin seine **ursprünglichen** 462 Minuten zählt, stehen am Ende
462 + 60 + 124 = 646 Minuten auf der Tageszeile.

Der Fehler lag also nicht in der Wochenansicht. Sie hat korrekt summiert, was
in der Datenbank stand.

---

## Die Ursache

Eine Buchung trägt ihre Zeit doppelt:

* als **Ortszeit** – `work_date`, `start_time`, `end_time`. Das ist, was jede
  Ansicht, jeder Export und jeder Nachweis zeigt.
* als **UTC-Stempel** – `started_at_utc`, `ended_at_utc`, dazu die Zeitzone
  `tz_name`. Sie machen Nachtarbeit und Zeitumstellung eindeutig.

`app/worktime.py` ist seit 0.16.0 die **einzige** Stelle, an der eine Dauer
entsteht – und sie liest **bevorzugt** die UTC-Stempel. Nur wenn keine
vorhanden sind (Bestandsbuchungen vor 0.14.0), rechnet sie aus den Ortszeiten.

Damit gilt: Wer eine Buchung kürzt und dabei nur die Ortszeiten umsetzt, ändert
die Anzeige – nicht die gerechnete Dauer. Genau das taten bis 0.20.8 drei
Stellen in `app/crud.py`:

| Stelle | Vorgang |
| --- | --- |
| `_split_closed_entry` | Nachtrag innerhalb einer abgeschlossenen Buchung |
| `_apply_overwrite` | kürzen, teilen und verdrängen beim überschreibenden Bearbeiten |
| `create_manual_time_entry` (Zweig „laufende Buchung") | Nachtrag in die laufende Erfassung |

Alle drei setzten `start_time`/`end_time`/`work_date` sauber um und ließen die
UTC-Stempel stehen. Ihre Kommentare versprachen ausdrücklich, es entstünden
„keine doppelt gezählten Zeiten" – für die Ortszeiten stimmte das auch. Für die
Rechnung nicht.

**Betroffen war deshalb nicht nur „Woche im Blick".** Tages- und Monatssumme,
Saldo, Über- und Minusstunden, die Regelprüfung nach ArbZG sowie PDF- und
Excel-Export lesen dieselbe Quelle und zeigten dieselbe zu große Zahl.

---

## Die Behebung

Die Korrektur liegt bewusst **nicht** in den drei Aufrufern. Sie an drei
Stellen nachzuziehen hätte diesen Fall behoben und den nächsten offen gelassen
– die vierte Stelle, die irgendwann eine Buchung kürzt, hätte den Fehler
zurückgebracht.

Stattdessen hängen die Stempel jetzt an den Ortszeiten. Ein Mapper-Ereignis in
`app/models.py` (`before_insert` und `before_update` auf `TimeEntry`) rechnet
`started_at_utc` und `ended_at_utc` neu aus `work_date`, `start_time`,
`end_time` und `tz_name`, sobald sich eines dieser Felder ändert – vor jedem
INSERT und jedem UPDATE, unabhängig davon, welcher Code die Änderung ausgelöst
hat. Kein Aufrufer muss an die Stempel denken; künftiger Code erbt die
Zusicherung.

Drei Feinheiten:

* **Ein ausdrücklich gesetzter Stempel behält Vorrang.** Beim Ein- und
  Ausstempeln kennt `crud` den Zeitpunkt sekundengenau. Diese genauere Angabe
  darf nicht durch eine gröbere ersetzt werden.
* **Eine laufende Buchung hat kein Ende.** Wird eine Buchung wieder geöffnet,
  wird `ended_at_utc` geleert – sonst würde sie rückwirkend als beendet
  gerechnet.
* **Eine neu angelegte Buchung** ohne eigene Zeitzone bekommt die aktuelle
  Betriebszeitzone als `tz_name` und vollständige Stempel. Bestandsbuchungen
  bekommen hier bewusst nichts nachgetragen.

---

## Migration 24 – bereits gespeicherte Buchungen

Die Angleichung repariert neue Änderungen. Buchungen, die vor dem Update
geteilt oder gekürzt wurden, tragen ihre falschen Stempel weiter. Migration 24
(`_repair_time_entry_utc_stamps`) setzt sie aus den Ortszeiten neu.

* **Ortszeit ist die Wahrheit.** Sie steht in jeder Ansicht, in jedem Export
  und in jedem Nachweis; der Stempel ist der abgeleitete Wert.
* **Nur Buchungen mit hinterlegtem `tz_name`** werden angefasst. Ohne die
  damals gültige Zone ließe sich nichts rekonstruieren, und ein geratener Wert
  wäre in einem Arbeitszeitnachweis schlechter als eine unveränderte Zeile.
* **Datenerhaltend**: Geändert werden ausschließlich die zwei abgeleiteten
  Spalten. Keine Buchung wird gelöscht, keine Ortszeit angerührt, kein Status
  geändert.
* **Beliebig oft wiederholbar**: Beim zweiten Lauf stimmen die Werte bereits
  und es wird nichts geschrieben.
* **Portabel** über SQLite, MySQL/MariaDB und PostgreSQL.
* Die Zahl der angeglichenen Buchungen steht im Anwendungslog.

**Keine Schemaänderung.** Es kommen keine Tabellen, Spalten, Typen, Beziehungen
oder Indizes hinzu; `ensure_schema()` bleibt unverändert. Backups und
Cross-Database-Restore sind nicht berührt – die Migration läuft nach einem
Restore automatisch mit.

Nach dem Update zeigt der gemeldete Tag wieder 7:42 Std.

---

## Tests

`tests/test_v0209.py` mit 20 Tests. Sie prüfen

* den gemeldeten Fall minutengenau: 08:00–15:42 plus Nachtrag 12:38–13:38
  ergibt 462 Minuten, nicht 646,
* dieselbe Rechnung in `_build_weekly_overview` – dort, wo sie gemeldet wurde,
* dass die drei Abschnitte lückenlos aneinander anschließen (278 + 60 + 124),
* das überschreibende **Kürzen** und **Teilen** aus der Verwaltung,
* den Nachtrag in die **laufende** Buchung (geprüft wird ihr Stempel, nicht die
  verstrichene Zeit – eine laufende Buchung endet „jetzt"),
* dass das Ausstempeln seinen sekundengenauen Stempel behält,
* Nachtarbeit über Mitternacht,
* die Migration: Reparatur, Wiederholbarkeit, und dass Buchungen ohne
  Zeitzone unberührt bleiben,
* dass die beiden Mapper-Ereignisse registriert sind – wer sie entfernt, bringt
  den Fehler zurück,
* und den vollständigen Weg über das Formular (`POST /time`).

Eine Prüfung ist bewusst allgemein gehalten und läuft in mehreren Tests mit:
Für **jede** abgeschlossene Buchung in der Datenbank muss die gerechnete Dauer
der aus den Ortszeiten abgeleiteten entsprechen. Laufen sie auseinander, zeigt
die Anwendung andere Zeiten, als sie rechnet – und genau das war der Fehler.

11 der Tests wurden gegen den Stand von 0.20.8 gegengeprüft und schlagen dort
fehl.

---

## Hinweis

Diese Fassung behebt einen Rechenfehler. Sie ist weder eine Aussage über die
vollständige Rechtskonformität der Anwendung noch eine Zertifizierung.

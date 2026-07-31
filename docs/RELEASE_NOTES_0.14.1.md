# Release Notes 0.14.1

Nachbesserung zu 0.14.0. Die Revisionssicherheit war eingebaut, aber an drei
Stellen im Weg: Der Einsatzort verschwand, stornierte Buchungen waren
unsichtbar und zählten trotzdem mit, und Ablehnen ging überhaupt nicht mehr.

> **Keine rechtliche Garantie.** Es gilt unverändert, was in
> [`RELEASE_NOTES_0.14.0.md`](RELEASE_NOTES_0.14.0.md) steht: Diese Umsetzung
> erfüllt technische Anforderungen, sie ist nicht zertifiziert und ersetzt
> keine Rechtsberatung.

## 1. Der Einsatzort hing am Remote-Kennzeichen

**Der gemeldete Fehler:** „Die Standortauswahl fehlt nun beim Stempeln
komplett."

Die Ursache liegt schon in 0.13.0: Die Standortauswahl wurde dorthin gesetzt,
wo vorher der Umschalter „Remote / Vor Ort" stand – und hat dessen Bedingung
gleich mitgeerbt. Sichtbar war sie deshalb nur mit dem Benutzerkennzeichen
**„Einsatzort (Remote/vor Ort)"**. Auch der Server verwarf jeden Standort,
wenn das Kennzeichen fehlte.

Das war falsch gedacht. Ein Firmenstandort ist das **Gegenteil** von
Remote-Arbeit: Wer nie remote arbeitet, muss trotzdem sagen können, an welchem
Standort er war – das ist ja gerade der Sinn der Standorte.

Seit 0.14.1 sind beide Dinge getrennt:

| | Kennzeichen gesetzt | Kennzeichen nicht gesetzt |
|---|---|---|
| **Schnell stempeln** | Umschalter Vor Ort / Remote | kein Feld (es gibt keine Firma) |
| **Auftrag stempeln** | Vor Ort, Remote, Standorte der Firma | Vor Ort, Standorte der Firma |
| **Nachtrag / Bearbeiten** | wie Auftrag stempeln | wie Auftrag stempeln |

Nur die **Option „Remote"** hängt weiter am Kennzeichen – auf der Seite und
serverseitig. Ein Formular, das trotzdem `remote` schickt, wird still auf
„vor Ort" zurückgesetzt; abgewiesen wird nichts.

Betroffen und behoben: Weboberfläche, Mobilansicht, die Buchungsbearbeitung in
der Administration und der Kommentar-Nachtrag über die Stempelansicht (der den
Standort ebenfalls am Kennzeichen festmachte).

## 2. Stornierte Buchungen: sichtbar, und ohne Wirkung auf die Summen

**Die Frage:** „Wo sehe ich stornierte Buchungen?" – Antwort bis 0.14.0:
nirgends richtig. Und schlimmer: Sie zählten weiter mit.

* **Kein Label.** `TIME_ENTRY_STATUS_LABELS` kannte den Stand nicht, die
  Oberfläche zeigte deshalb das englische `Cancelled`. In der eigenen
  Buchungsliste stand sogar „Abgelehnt", weil dort alles außer freigegeben und
  wartend als Ablehnung gelesen wurde.
* **Kein Filter.** In den Auswertungen gab es keine Auswahl „Storniert", und
  ein `?status=cancelled` fiel auf „Freigegeben" zurück.
* **Doppelte Zeit.** Tages- und Wochensumme filterten nur `rejected`. Nach
  einer Korrektur (Storno + Ersatzbuchung) stand dieselbe Zeit **zweimal** in
  der Summe. Die Monatswerte und die Auswertungen waren nicht betroffen, die
  rechnen ausdrücklich mit `approved`.
* **Im Export.** `/api/users/<id>/excel` filterte gar nichts und nahm
  stornierte *und* abgelehnte Buchungen mit.

Seit 0.14.1:

* Der Stand heißt **„Storniert"**, überall.
* Die Auswertungen haben einen Filter dafür; stornierte Zeilen sind gedämpft
  und durchgestrichen dargestellt – zurückgenommen, nicht fehlerhaft.
* In der eigenen Buchungsliste stehen **Grund** und der Hinweis, dass eine
  Ersatzbuchung existiert, direkt daneben.
* Aus jeder Zeile führt ein Weg zur **Historie**; bei einer stornierten
  Buchung ist das der einzige (bearbeiten lässt sie sich nicht mehr).
* Storniert und abgelehnt zählen in **keiner** Summe und in keinem Export mit.

## 3. Ablehnen war nicht durchführbar

0.14.0 verlangt für eine Ablehnung eine Begründung. Das Formular unter
*Administration → Freigaben* hatte kein Feld dafür – jeder Klick auf „Ablehnen"
lief deshalb in „Eine Ablehnung braucht eine Begründung" und passierte nicht.

Das Formular hat jetzt ein Begründungsfeld. Für die **Freigabe** bleibt es
optional (Freigeben ist keine Korrektur), für die **Ablehnung** ist es Pflicht
– geprüft auf dem Server, mit einem früheren Hinweis im Browser, damit die
Seite nicht erst mit einer Fehlermeldung neu lädt. Ohne JavaScript bleibt es
bei der Prüfung auf dem Server.

## 4. Was die Durchsicht sonst noch ergeben hat

* **Kommentar-Nachtrag ohne Spur.** `update_time_entry_notes` änderte
  Kommentar und Einsatzort **ohne** Eintrag in der Historie – ein Loch in der
  Revisionssicherheit, die 0.14.0 versprochen hatte. Der Nachtrag wird jetzt
  historisiert. Nach einer Begründung wird dabei bewusst *nicht* gefragt: Die
  Person bearbeitet ihre eigene Buchung, der Anlass steht im Vorher/Nachher,
  und die Historie hält fest, worüber die Änderung lief. Der Nachtrag
  respektiert außerdem eine gesperrte Periode.
* **Beenden einer laufenden Buchung.** Der Sprung von „läuft" auf eine fertige
  Arbeitszeit hinterließ ebenfalls keine Spur. Dafür gibt es den neuen Vorgang
  **„Beendet"** (`RevisionAction.CLOSED`) – bewusst nicht „Geändert", denn das
  Beenden ist keine Korrektur, sondern der zweite Stempel derselben Buchung,
  und braucht deshalb auch keine Begründung.
* **Beenden bleibt in gesperrten Perioden möglich.** Eine laufende Buchung muss
  sich immer schließen lassen; wäre das gesperrt, bliebe sie für immer offen.
  Das ist jetzt ausdrücklich so dokumentiert und durch einen Test festgehalten.
* **Gesperrte Periode ergab einen 500.** Über `/api/time-entries` und beim
  Stempeln wurde `PeriodLocked` nicht abgefangen. Ein Offline-Client hätte
  einen Serverfehler endlos wiederholt. Jetzt antwortet die API mit **409** und
  dem Grund im Klartext, das Stempeln mit einer Fehlermeldung.
* **Zweite Whitelist.** Der Statusfilter der Auswertungen wird an zwei Stellen
  geprüft; die erste kannte „cancelled" noch nicht und warf die Auswahl still
  weg. Beide sind jetzt gleich.

## Datenbank

**Keine Migration.** 0.14.1 ändert kein Schema. `RevisionAction.CLOSED` ist ein
neuer Wert in der bestehenden Textspalte `time_entry_revisions.action` – dafür
ist nichts anzupassen. Bestandsdaten bleiben unverändert; Buchungen ohne
Beenden-Vermerk in der Historie sind schlicht älter als dieses Release.

## Tests

`tests/test_v0141.py` – 22 Tests: Standortauswahl mit und ohne Kennzeichen
(sichtbar, Remote-Option, Server nimmt an, Remote bleibt gesperrt), Schnell
stempeln unverändert, Label und Filter für Storno, Storno zählt nicht in der
Tagessumme, Storno nicht im Export, Grund für die Beschäftigten sichtbar,
Begründungsfeld bei den Freigaben, Ablehnen mit und ohne Grund, Freigeben ohne
Grund, Historie beim Beenden, Beenden trotz gesperrter Periode, 409 statt 500,
Historie beim Kommentar-Nachtrag und Storno statt Löschen über die API.

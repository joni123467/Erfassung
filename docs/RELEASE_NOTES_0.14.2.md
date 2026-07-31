# Release Notes 0.14.2

Ein Rechenfehler bei halben Urlaubstagen, zwei neue Ansichten für die
Administration und eine Durchsicht der übrigen Zeitberechnungen.

> **Keine rechtliche Garantie.** Es gilt unverändert, was in
> [`RELEASE_NOTES_0.14.0.md`](RELEASE_NOTES_0.14.0.md) steht.

## 1. Halbe Urlaubstage wurden ganz angerechnet

**Der gemeldete Fehler:** Ein Antrag vom 27.–28.07. mit **zwei halben Tagen**
stand in der Adminauswertung mit *16:00 Std*. Richtig sind *8:00 Std* – und
genau das zeigte die Übersicht der Person auch an. Zwei Wege, zwei Ergebnisse.

Die Ursache ist eine Funktion mit einem irreführenden Namen:
`services.calculate_required_vacation_minutes` sieht nur einen *Zeitraum*, nie
den Antrag. Sie zählt Werktage mal Tagessoll und kann halbe Tage gar nicht
kennen. Vier Stellen benutzten sie trotzdem für die Anrechnung:

| Stelle | Wirkung des Fehlers |
|---|---|
| Adminauswertung „Urlaub im Zeitraum" | doppelte Stundenzahl (der gemeldete Fall) |
| Excel-Export | dieselbe doppelte Zahl im Export |
| PDF-Export | doppelte Stundenzahl **und** ganze statt halber Tage in der Tagesspalte |
| `POST /api/vacations` | schrieb bei Überstundenurlaub einen **falschen Wert in die Datenbank** – vom Zeitkonto wäre zu viel abgezogen worden |

Alle vier rechnen jetzt über `services.vacation_minutes_in_range`, das den
Antrag kennt und halbe Tage mit 0,5 gewichtet. Neu ist
`services.vacation_days_in_range` für dieselbe Rechnung in Tagen; der
PDF-Export stellt halbe Tage deutsch mit Komma dar („1,5").

Damit der Fehler nicht wiederkehrt, trägt
`calculate_required_vacation_minutes` jetzt einen ausdrücklichen Hinweis, dass
sie **nicht** für die Urlaubsanrechnung taugt. Als Sollzeitrechnung bleibt sie
richtig und unverändert.

Ganze Tage rechnen exakt wie bisher – die Korrektur betrifft ausschließlich
Anträge mit halbem Anfangs- oder Endtag.

## 2. Urlaubsübersicht für die Administration

Neu unter *Auswertungen → **Urlaubsübersicht*** (`/admin/reports/vacations`):
Anspruch, Übertrag, genommener, beantragter und **verbleibender** Urlaub je
Mitarbeitendem, mit Jahresauswahl und Summenzeile.

* **Verbleibend** zieht genommenen *und* beantragten Urlaub ab – ein offener
  Antrag ist bereits verplant. Steht dort 0 oder weniger, fällt die Zahl
  farblich auf.
* **Überstundenabbau** steht getrennt daneben: Er zehrt vom Zeitkonto, nicht
  vom Urlaubsanspruch.
* Gerechnet wird mit **derselben** Funktion wie in der Ansicht der Person
  (`services.calculate_vacation_summary`). Zwei Zahlen für dieselbe Sache
  dürfen nicht auseinanderlaufen – ein Test hält das fest.

**Berechtigung:** neu `Vacation.Overview` („Urlaubsübersicht einsehen"),
scoped, also mit Geltungsbereich *alle* oder *eigenes Team*. Bewusst getrennt
von `Vacation.Manage`: Den Resturlaub eines Teams zu sehen ist etwas anderes,
als über Anträge zu entscheiden. Wer plant, braucht den Überblick; wer
genehmigt, nicht zwingend umgekehrt. Bestehende Rollen bekommen das Recht
**nicht** automatisch – es ist in der Rollenverwaltung zu vergeben.

Der Blick auf fremde Urlaubsdaten wird wie jeder andere Fremdzugriff im
Zugriffsprotokoll vermerkt (Art. 5 DSGVO).

## 3. Änderungsprotokoll für Stempelungen

Die Frage war: *Gibt es einen Log für Änderungen von Stempelungen?* Seit
0.14.0 wird jede Änderung historisiert – aber nur **je Buchung** erreichbar.
Das beantwortet „was ist mit *dieser* Buchung passiert?", nicht „was wurde in
den letzten Wochen überhaupt angefasst?".

Neu unter *Auswertungen → **Änderungsprotokoll*** (`/admin/time-entries/changes`):
alle Vorgänge über alle Buchungen – Anlage, Beenden, Änderung, Freigabe,
Ablehnung, Stornierung – mit Vorher/Nachher, Bearbeiter, Zeitpunkt und
Begründung. Filter nach Vorgang und Zeitraum (7/30/90/365 Tage), aus jeder
Zeile ein Weg in die Historie der Buchung.

Der Zeitraum bezieht sich auf das **Buchungsdatum**, nicht auf den Zeitpunkt
der Änderung: So bleibt eine späte Korrektur an einer alten Buchung dort, wo
man sie sucht.

Sichtbar mit `Time.View`, begrenzt auf den Geltungsbereich dieses Rechts.

## 4. Feiertage werden gutgeschrieben

Bis 0.14.2 wurde ein gesetzlicher Feiertag **nirgends** angerechnet. Der
Feiertagskalender existierte, die Tage wurden angezeigt, seit 0.14.0 wurde
Feiertagsarbeit sogar gekennzeichnet – aber in die Sollzeit ging jeder Werktag
Mo–Fr ein, auch der Feiertag. Wer an dem Tag nicht arbeitete und keinen Urlaub
buchte, hatte am Monatsende ein Minus von einer Tagessollzeit, obwohl er
nichts versäumt hatte.

Ein Feiertag ist ein bezahlter Ausfalltag. Er wird jetzt mit der
**individuellen Tagessollzeit** gutgeschrieben – genau wie ein Urlaubstag, und
mit derselben Wirkung auf den Saldo:

```
Ist = gestempelte Zeit + Urlaub + Feiertag
Saldo = Ist − Soll
```

Umgesetzt als **Gutschrift**, nicht als Kürzung der Sollzeit. Beides ergibt
denselben Saldo, aber die Gutschrift bleibt sichtbar: In Auswertung und Export
steht, wie viele Stunden aus Feiertagen stammen. Die Sollzeit bleibt die
Sollzeit.

**Regeln im Einzelnen:**

| Fall | Verhalten |
|------|-----------|
| Feiertag Mo–Fr | Gutschrift in Höhe der Tagessollzeit |
| Feiertag Sa/So | keine Gutschrift – kein Arbeitstag, kein Ausfall |
| Teilzeit | Gutschrift nach **individueller** Tagessollzeit (4 Std → 4 Std) |
| Feiertag **im Urlaub** | verbraucht **keinen** Urlaubstag, wird trotzdem gutgeschrieben |
| Feiertag im **Überstundenurlaub** | belastet das Zeitkonto nicht |
| **Arbeit** am Feiertag | zählt zusätzlich – Feiertagsarbeit ist echte Mehrarbeit und wird von der Regelprüfung ohnehin gekennzeichnet (§9 ArbZG) |

Der Punkt „Feiertag im Urlaub" ist kein Detail: Ohne ihn zählte der Tag
doppelt (einmal als Gutschrift, einmal als verbrauchter Urlaubstag) und der
Urlaubsanspruch schrumpfte zu Unrecht. Betroffen sind Urlaubsübersicht,
Resturlaub, Anrechnung und der gespeicherte Wert beim Überstundenurlaub.

Maßgeblich ist die **Feiertagsregion** der Installation (Administration →
Feiertage) – die Anwendung legt die gesetzlichen Feiertage beim Start selbst
an. Wirksam wird die Gutschrift überall: Dashboard, Wochenansicht,
Tagesübersicht, eigene Buchungen, Adminauswertung, Benutzerauswertung,
PDF- und Excel-Export sowie im Offline-Snapshot der Stempel-App.

## 5. Durchsicht der übrigen Zeitberechnungen

Geprüft: Monats- und Zeitraumsollzeit, Ist-Zeit, Über- und Unterstunden,
Urlaubsanrechnung über Monatsgrenzen, Pausen, stornierte Buchungen und
Überstundenurlaub. Alles unauffällig: Monatswerte, Auswertungen und Dashboard
rechnen mit `status = approved` und lassen stornierte wie abgelehnte Buchungen
konsequent draußen (in 0.14.1 korrigiert). Ein Antrag über den Monatswechsel
wird korrekt anteilig aufgeteilt, ein stornierter Urlaubsantrag gibt den
Anspruch zurück, Überstundenurlaub belastet den Urlaubsanspruch nicht.

## Datenbank

**Keine Migration.** 0.14.2 ändert kein Schema. Das neue Recht
`Vacation.Overview` lebt im Rechtekatalog, nicht in einer Tabelle, und die
Feiertagsgutschrift wird bei jeder Abfrage aus dem vorhandenen
Feiertagskalender gerechnet – gespeichert wird dafür nichts.

**Bestehende Salden ändern sich.** Wer die Anwendung schon nutzt, sieht nach
dem Update für jeden vergangenen Feiertag eine Tagessollzeit mehr auf der
Habenseite. Das ist beabsichtigt – es ist die Korrektur eines Minus, das nie
hätte entstehen dürfen.

## Tests

`tests/test_v0142.py` – 34 Tests: der gemeldete Fall (zwei halbe Tage = 8:00
Std) direkt und über die Adminauswertung, ganze Tage unverändert, einzelner
halber Tag, korrekter Wert in der Datenbank über die API, PDF-Formatierung,
Erreichbarkeit und Rechnung der Urlaubsübersicht, Gleichstand mit der Ansicht
der Person, eigene Berechtigung samt Registrierung im Katalog,
Zugriffsprotokoll, Erreichbarkeit und Inhalt des Änderungsprotokolls samt
Filtern, Sollzeit nur an Werktagen, Urlaub über die Monatsgrenze, stornierter
Urlaub und Überstundenurlaub.

Zur Feiertagsgutschrift: Gutschrift in Höhe der Tagessollzeit, individuelle
Tagessollzeit bei Teilzeit, keine Gutschrift am Wochenende, ausgeglichener
Saldo im Feiertagsmonat, Feiertag im Urlaub verbraucht keinen Urlaubstag und
wird trotzdem gutgeschrieben, Arbeit am Feiertag zählt obendrauf und wird
gekennzeichnet, Tagesübersicht, normaler Tag unverändert, eigene Buchungen,
Benutzerauswertung, Offline-Snapshot und Überstundenurlaub über einen
Feiertag.

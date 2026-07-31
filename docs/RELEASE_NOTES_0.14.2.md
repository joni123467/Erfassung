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

## 4. Durchsicht der übrigen Zeitberechnungen

Geprüft: Monats- und Zeitraumsollzeit, Ist-Zeit, Über- und Unterstunden,
Urlaubsanrechnung über Monatsgrenzen, Pausen, stornierte Buchungen und
Überstundenurlaub. Ergebnis:

* **Richtig:** Monatswerte, Auswertungen und Dashboard rechnen mit
  `status = approved` und lassen stornierte wie abgelehnte Buchungen
  konsequent draußen (in 0.14.1 korrigiert). Ein Antrag über den Monatswechsel
  wird korrekt anteilig aufgeteilt. Ein stornierter Urlaubsantrag gibt den
  Anspruch zurück. Überstundenurlaub belastet den Urlaubsanspruch nicht.
* **Befund ohne Änderung – gesetzliche Feiertage zählen in die Sollzeit.**
  `calculate_monthly_target_minutes` zählt jeden Werktag Mo–Fr, auch wenn er
  ein Feiertag ist. Wer an einem Feiertag nicht arbeitet und keinen Urlaub
  bucht, bekommt dadurch ein Minus von einer Tagessollzeit – obwohl die
  Anwendung einen Feiertagskalender führt und die Tage anzeigt.

  Das ist **nicht** geändert worden, und zwar bewusst: Ob ein Feiertag die
  Sollzeit senkt oder getrennt gutgeschrieben wird, ist eine betriebliche
  Entscheidung, und eine Umstellung würde **alle bestehenden Salden
  rückwirkend verschieben** – genau das, was 0.14.0 mit `legacy_auto`
  vermeiden wollte. Ein Test hält den heutigen Stand fest, damit eine
  Umstellung eine bewusste ist und nicht unbemerkt passiert. Wenn das anders
  sein soll, bitte kurz Bescheid geben – die Umstellung selbst ist klein, die
  Frage nach dem Umgang mit Bestandsdaten ist es nicht.

## Datenbank

**Keine Migration.** 0.14.2 ändert kein Schema. Das neue Recht
`Vacation.Overview` lebt im Rechtekatalog, nicht in einer Tabelle.

## Tests

`tests/test_v0142.py` – 22 Tests: der gemeldete Fall (zwei halbe Tage = 8:00
Std) direkt und über die Adminauswertung, ganze Tage unverändert, einzelner
halber Tag, korrekter Wert in der Datenbank über die API, PDF-Formatierung,
Erreichbarkeit und Rechnung der Urlaubsübersicht, Gleichstand mit der Ansicht
der Person, eigene Berechtigung samt Registrierung im Katalog,
Zugriffsprotokoll, Erreichbarkeit und Inhalt des Änderungsprotokolls samt
Filtern, Sollzeit nur an Werktagen, Urlaub über die Monatsgrenze, stornierter
Urlaub, Überstundenurlaub – und der festgehaltene Feiertagsbefund.

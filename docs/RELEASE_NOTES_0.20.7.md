# Release Notes 0.20.7

**Datum:** 2026-08-03
**Art:** Fehlerbehebung und Bedienverbesserung (Patch)

0.20.7 behebt fünf gemeldete Fehler im Urlaubsbereich und in der
Benutzerverwaltung. Der letzte davon – „Woche im Blick" rechnete nicht mit den
hinterlegten Tagesarbeitszeiten – hat eine Durchsicht aller Anzeigen nach sich
gezogen; dabei kam derselbe Fehler an vier weiteren Stellen zum Vorschein.

---

## 1. Die Reiter des Urlaubsbereichs stehen jetzt auf jeder Seite

Bis 0.20.6 gab es die Leiste „Meine Anträge · Mein Kalender · Teamkalender" nur
im Kalender. Von der Antragsseite führte lediglich eine Schaltfläche
**Mein Kalender** im Kartenkopf hinaus – und von dort gab es keinen Weg zurück.

- Die Reiter liegen in `templates/records/_vacation_tabs.html` und werden von
  beiden Seiten eingebunden; sie können damit nicht mehr auseinanderlaufen.
- Die aktive Seite ist markiert (`aria-current="page"`).
- Die Schaltfläche **Mein Kalender** ist entfallen, der Reiter ersetzt sie.
- Den Reiter **Teamkalender** sieht wie bisher nur, wer
  `Vacation.TeamCalendar` hat.

## 2. Der Teamkalender nennt seinen Umfang

Welche Personen der Teamkalender zeigt, entscheidet der Geltungsbereich von
`Vacation.TeamCalendar` – sichtbar war das nirgends. Eine Lücke im Kalender war
damit nicht von einer Lücke in der Berechtigung zu unterscheiden.

Über dem Kalender steht jetzt eine Zeile **„Angezeigt: …"**:

| Geltungsbereich | Anzeige |
| --- | --- |
| Alle | „Alle Gruppen" und die Namen aller Gruppen |
| Gruppen | „Eigene Gruppen" und die Namen der eigenen Gruppen |
| Gruppen, ohne Gruppenzuordnung | „Nur die eigenen Abwesenheiten – keine Gruppe zugeordnet" |
| Selbst | „Nur die eigenen Abwesenheiten" |

## 3. Offene Anträge stehen im Teamkalender

Offene Anträge sah bis 0.20.6 nur, wer zusätzlich `Vacation.Manage` besaß.
Damit ließ sich nicht planen: Erst die Freigabe machte sichtbar, dass jemand
denselben Zeitraum bereits beantragt hatte.

- Offene Anträge erscheinen jetzt für alle, die den Teamkalender sehen dürfen –
  gelb hinterlegt, wie im persönlichen Kalender, und in der Legende erklärt.
- **Die Art der Abwesenheit bleibt verdeckt.** Teamweit steht dort weiterhin
  nur „Abwesend"; vertrauliche Abwesenheitsarten geben ihre Bezeichnung nicht
  preis. Sichtbar wird allein, dass ein Zeitraum belegt ist – genau das, was
  zum Planen nötig ist.
- Ein Antrag mit **angefragter Rücknahme** verschwand bisher aus beiden
  Kalendern, obwohl die Abwesenheit bis zur Freigabe der Rücknahme gilt. Er
  wird jetzt als „Rücknahme angefragt" angezeigt und belegt den Zeitraum.

## 4. QR-Code oben rechts, Arbeitszeitpläne darunter

Im Benutzerformular bilden die drei Karten der Seitenspalte jetzt eine feste
Reihenfolge: **Mobile Anmeldung**, darunter **Arbeitszeitpläne**, darunter
**Urlaubsanspruch buchen**. Zuvor waren sie unmittelbare Rasterkinder und
ordneten sich automatisch an, sodass der QR-Code unten landete.

Nebenbei entfernt: eine **zweite, vollständige Kopie des
Arbeitszeitplan-Dialogs samt Skript im `{% block title %}`**. Sie hat nie etwas
angezeigt, weil `is_edit` erst im Inhaltsblock gesetzt wird und die Bedingung
im Titel deshalb immer falsch war – wäre sie je wahr geworden, hätte die Seite
doppelte Element-IDs bekommen.

## 5. Sollzeiten folgen überall dem Arbeitszeitplan

Seit 0.20.3 speichern Arbeitszeitpläne eigene Sollminuten für alle sieben
Wochentage. `services.target_minutes_for_date` ist die einzige Stelle, die das
auswertet – **fünf Anzeigen fragten sie nicht**:

| Stelle | Vorher | Jetzt |
| --- | --- | --- |
| „Woche im Blick" (Dashboard) | Wochensoll aus dem Stammsatz, Tagessoll pauschal an Mo–Fr | Summe der Tagessollzeiten des Plans |
| Tagesansicht (Reiter Übersicht) | pauschaler Tagesschnitt, unabhängig vom gezeigten Tag | Sollzeit genau dieses Tages |
| `TimeEntry.overtime_minutes` (Excel-Export) | Ist minus pauschaler Tagesschnitt | Ist minus Sollzeit des Buchungstages |
| Urlaubskonto „Verbraucht"/„Resturlaub" | Minuten geteilt durch den Tagesschnitt | Urlaubstage direkt gezählt |
| Offline-Shell (App) | Tages- und Wochensoll pauschal | Sollzeit je Tag aus der Momentaufnahme |

Zwei Beispiele, was das ausmacht:

- **Vier-Tage-Woche, Mo–Do je acht Stunden.** „Woche im Blick" zeigte 40:00
  Wochensoll statt 32:00 und wies dem Freitag ein volles Tagessoll zu.
- **Urlaubswoche im selben Plan.** Vier Urlaubstage zu je acht Stunden sind 32
  Stunden; geteilt durch den Schnitt von 6:24 Std ergab das **fünf** verbrauchte
  Urlaubstage statt vier. Gezählt wird jetzt über `vacation_days_in_range`, das
  den Plan, die halben Tage und die Feiertage kennt.

Ohne hinterlegten Plan bleibt es überall bei der bisherigen Rechnung „Montag
bis Freitag mal Tagessoll" – Bestandsinstallationen sehen keine Änderung.

Für die App wandert die Sollzeit je Kalendertag als `daily_targets` in die
Momentaufnahme (`/mobile/sync-data`). Die beiden Pauschalwerte bleiben im
Baustein `user` erhalten; eine Momentaufnahme, die vor dem Update entstanden
ist, rechnet damit weiter wie bisher.

## 6. Rücknahmeanfragen ließen sich nicht entscheiden

Unter Administration → **Freigaben** gibt es den Abschnitt
*Rücknahmeanfragen*. Seine beiden Schaltflächen – **Rücknahme bestätigen** und
**Ablehnen** – saßen in einem Formular **ohne CSRF-Token**, als einzigem der
Seite. Die CSRF-Prüfung läuft für jede zustandsändernde Anfrage; jeder Klick
endete deshalb auf „403 – Ungültige Sitzung", und der Antrag behielt seinen
Status.

Praktisch hieß das: Zieht jemand einen bereits genehmigten Urlaub zurück,
blieb der Antrag dauerhaft in *Rücknahme angefragt* hängen. Er zählte in
diesem Zustand nicht mehr als verbrauchter Urlaub – die Tage waren also
zurückgegeben –, während die Abwesenheit im Kalender weiter stand. Über die
Oberfläche ließ sich das nicht auflösen.

Behoben durch das fehlende Feld. Zwei Tests sichern das ab: einer prüft **jedes**
POST-Formular aller Vorlagen auf ein Token, ein zweiter spielt den ganzen
Vorgang durch. Ein dritter stellt sicher, dass ein Aufruf **ohne** Token
weiterhin mit 403 abgewiesen wird – die Reparatur darf die Prüfung nicht
aufweichen.

Der zweite Fund derselben Suche war ein Fehlalarm: Im Standortformular
(`templates/admin/company_form.html`) steht das Token außerhalb der
`<form>`-Marken und wird über das HTML-Attribut `form="…"` zugeordnet. Der
Test kennt dieses Muster.

## 7. Weitere Befunde aus der Durchsicht der Anzeigen

- **Benutzerformular, Feld „Wochenarbeitszeit".** Es zeigte 40 Stunden,
  während die Anwendung mit einem Plan über 32 Stunden rechnete – zwei Zahlen,
  von denen die sichtbare die unbenutzte war. Liegt ein Plan vor, steht jetzt
  darunter, welcher gilt und mit wie vielen Wochenstunden.
- **Auswertung „Benutzerauswertung", Fußnote.** Sie beschrieb noch die Rechnung
  „Arbeitstage (Mo–Fr) × Tagessoll"; gerechnet wird seit 0.20.3 über den Plan.
- **Monatsüberschriften auf Deutsch.** Über der Buchungsseite und in der
  Monatszusammenfassung des Dashboards stand noch „06/2026"; die deutschen
  Monatsnamen aus 0.20.1 hatten diese beiden Stellen nicht erreicht. Jetzt
  „Juni 2026", wie im Kalender und in der Regelübersicht.
- **Alle Template-Variablen geprüft.** Ein Durchlauf über sämtliche Vorlagen
  hat keine Variable gefunden, die keine Route liefert – Jinja rendert
  Unbekanntes stillschweigend als leer, genau so entsteht eine Anzeige ohne
  Wert.

---

## Anwenderdurchlauf durch die gesamte Anwendung

Zusätzlich zur Testsuite wurde die Anwendung über HTTP wie von Hand bedient –
fünf Abschnitte, 239 Einzelprüfungen. Jede angezeigte Zahl wurde dabei
**unabhängig nachgerechnet**, nicht mit den Funktionen der Anwendung selbst.

| Abschnitt | Umfang | Ergebnis |
| --- | --- | --- |
| Stempeln, Pausen, Dauern | Anmeldung, Kennwortzwang, Start/Pause/Ende, Einsatzort, §-4-Grenzen, Zeitumstellung, Storno | 26 von 26 |
| Übersichten und Berechnungen | Tages-, Wochen- und Monatswerte, Urlaubskonto, Feiertagsgutschrift, Arbeitszeitplan | 44 von 44 |
| Urlaub, Freigaben, Kalender | Antrag, halber Tag, Genehmigung, Ablehnung, Rücknahme, alle Kalenderansichten, iCalendar-Feed | 41 von 41 |
| Administration und Auswertungen | 32 Verwaltungsseiten, Stammdatenpflege, Buchung bearbeiten, Historie, PDF- und Excel-Export | 68 von 68 |
| Rechte, System, App | 22 gesperrte Seiten für ein Konto ohne Rechte, API, CSRF, Sicherung, Offline-Shell | 60 von 60 |

Einzelne Ergebnisse, die dabei bestätigt wurden:

- **§ 4 ArbZG an den Grenzen.** Glatt sechs Stunden verlangen keine Pause,
  6:01 verlangt 30 Minuten; glatt neun Stunden 30, 9:01 dann 45. Eine nicht
  genommene Pause wird gekennzeichnet, aber nicht abgezogen – die
  Arbeitszeit bleibt so, wie sie war.
- **Unterbrechungen unter 15 Minuten** werden von der Arbeitszeit abgezogen,
  erfüllen die Pausenpflicht aber nicht.
- **Zeitumstellung.** Eine Schicht von 00:00 bis 06:00 am 29. März 2026 dauert
  fünf Stunden, nicht sechs.
- **Stornierte Buchungen** behalten ihre Zeiten und zählen null Minuten.
- **Der iCalendar-Feed** enthält keine Kommentare, ein falsches Token liefert
  404, und nach dem Widerruf liefert der Feed nichts mehr.
- **Geltungsbereiche.** Ein Konto ohne Verwaltungsrechte kommt an keine der
  22 geprüften Verwaltungsseiten, an kein fremdes Konto, an keine fremde
  Buchung und an keinen Auskunftsexport.

### Zum Lizenzbaustein Kalendersynchronisation

Die Durchsetzung von `calendar_sync` wurde in vier Lizenzzuständen geprüft
(ohne Urlaubsbaustein; mit Urlaub ohne `calendar_sync`; mit beiden; sowie
`calendar_sync` ohne Urlaub). In **jedem** unlizenzierten Fall wurde kein
Feed angelegt, und der ICS-Endpunkt bleibt gesperrt. `calendar_sync` setzt
`vacation` voraus; ohne den Urlaubsbaustein bleibt er wirkungslos.

Die Anwendung ist damit vollständig vorbereitet. Was noch fehlt, liegt
**außerhalb dieses Repositorys**: Der Lizenzserver muss `calendar_sync` in der
Liste `features` des signierten Lizenzdokuments ausliefern.

---

## Tests

`tests/test_v0207.py` (44 Tests):

- **Reiter** auf beiden Seiten, aktive Markierung, gemeinsame Vorlage, keine
  verbliebene Schaltfläche.
- **Umfang des Teamkalenders** für alle vier Geltungsbereiche.
- **Offene Anträge** und **Rücknahmeanfragen** im Teamkalender; vertrauliche
  Arten bleiben verdeckt.
- **Seitenspalte**: QR-Code vor den Arbeitszeitplänen, genau ein Dialog, Titel
  ohne Markup.
- **Sollzeiten**: Wochen- und Tagesansicht, Sollzeit bis heute, Samstagsplan,
  unveränderte Rechnung ohne Plan, `overtime_minutes`, Urlaubskonto mit ganzen
  und halben Tagen, Übereinstimmung von Monats- und Wochensoll.
- **Offline-Shell**: `daily_targets` in der Momentaufnahme, Pauschalwerte als
  Rückfallebene, kein `dailyTarget * 5` mehr im Skript.

Die Sollzeit-Tests wurden gegen den Stand von 0.20.6 gegengeprüft und schlagen
dort fehl (`assert 2400 == 300` beim Samstagsplan).

Zusätzlich in einem echten Browser (Chromium/Playwright) nachgemessen:

```
Meine Anträge – Reiter: ['Meine Anträge', 'Mein Kalender', 'Teamkalender'] aktiv: ['Meine Anträge']
Mein Kalender – Reiter: ['Meine Anträge', 'Mein Kalender', 'Teamkalender'] aktiv: ['Mein Kalender']
Teamkalender – Umfang: Angezeigt: Alle Gruppen Administration Montage Verwaltung
Teamkalender – Liste:  … Genehmigt / … Offen / … Rücknahme angefragt
Seitenspalte von oben nach unten: ['Mobile Anmeldung', 'Arbeitszeitpläne', 'Urlaubsanspruch buchen']
Woche im Blick: Wochensoll 32:00 Std · Fr/Sa/So „Frei"
```

Keine Konsolen- oder Netzwerkfehler; kein waagerechter Überlauf bei 390 px.

---

## Migration

Keine. 0.20.7 ändert weder Datenbankschema noch gespeicherte Daten; die
Schemaversion bleibt bei 23.

Die Zahlen in Auswertungen und im Urlaubskonto **können sich ändern** – aber
nur für Personen mit hinterlegtem Arbeitszeitplan, und nur, weil sie vorher
nicht zum Plan passten. Gespeicherte Buchungen und Anträge bleiben unberührt.

Der Versionssprung genügt, damit die korrigierten Skripte installierte
Instanzen erreichen: Der Cache-Name des Service Workers enthält die
Anwendungsversion.

---

## Hinweis

Diese Fassung korrigiert Anzeigen und stellt Bedienwege her. Sie ist weder eine
Aussage über die vollständige Rechtskonformität der Anwendung noch eine
Zertifizierung.

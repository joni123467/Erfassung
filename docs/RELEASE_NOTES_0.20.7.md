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

## 6. Weitere Befunde aus der Durchsicht der Anzeigen

- **Benutzerformular, Feld „Wochenarbeitszeit".** Es zeigte 40 Stunden,
  während die Anwendung mit einem Plan über 32 Stunden rechnete – zwei Zahlen,
  von denen die sichtbare die unbenutzte war. Liegt ein Plan vor, steht jetzt
  darunter, welcher gilt und mit wie vielen Wochenstunden.
- **Auswertung „Benutzerauswertung", Fußnote.** Sie beschrieb noch die Rechnung
  „Arbeitstage (Mo–Fr) × Tagessoll"; gerechnet wird seit 0.20.3 über den Plan.
- **Alle Template-Variablen geprüft.** Ein Durchlauf über sämtliche Vorlagen
  hat keine Variable gefunden, die keine Route liefert – Jinja rendert
  Unbekanntes stillschweigend als leer, genau so entsteht eine Anzeige ohne
  Wert.

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

# Release Notes 0.11.1

Ein Fehler, der Freigaben vollständig blockierte, halbe Urlaubstage und ein
Knopf zum Beantragen einer Lizenz.

## Behoben: Freigaben waren komplett gesperrt

**Symptom.** Jeder Versuch, eine manuelle Buchung freizugeben oder einen
Urlaubsantrag zu genehmigen, endete mit „Buchung gehört nicht zu deinem Team"
bzw. „Urlaubsantrag gehört nicht zu deinem Team" – **auch als globaler
Administrator**.

**Ursache.** Beim Umstieg auf Rollen (0.10.0) wurden die
Berechtigungsschlüssel umbenannt. An drei Stellen blieben die alten
Gruppenrechte-Namen stehen:

| Stelle | stand dort | richtig |
|---|---|---|
| Buchung freigeben/ablehnen | `can_approve_manual_entries` | `Time.Approve` |
| Urlaub genehmigen/ablehnen | `can_manage_vacations` | `Vacation.Manage` |
| Fremde Buchung bearbeiten | `can_edit_time_entries` | `Time.Edit` |

Ein Berechtigungsschlüssel, den die Registry nicht kennt, ergibt den
Geltungsbereich „keiner". Die Prüfung lieferte damit eine leere Menge
zugelassener Benutzer – und verweigerte konsequent jeden Zugriff, unabhängig
von der Rolle. Auch der Superadministrator kam nicht durch.

**Behoben.** Die drei Schlüssel sind korrigiert. Zusätzlich wirft
`_user_in_permission_scope` jetzt einen Fehler, wenn ein unbekannter Schlüssel
übergeben wird, statt stillschweigend alles zu verbieten. Ein Tippfehler fällt
damit sofort auf, statt sich als „Berechtigung fehlt" zu tarnen.

Ein Test prüft außerdem, dass alle von Routen verwendeten Schlüssel in der
Registry existieren.

## Neu: Halbe Urlaubstage

Im Urlaubsformular lassen sich **erster und letzter Tag** einzeln halbieren.
Bei einem eintägigen Antrag genügt ein Häkchen – dort gibt es kein „erster" und
„letzter" Tag.

| Antrag | Urlaubstage |
|---|---|
| Mo–Mi, ganz | 3,0 |
| Mo–Mi, Anfang und Ende halb | 2,0 |
| Nur Mo, halb | 0,5 |
| Fr–Mo, Anfang und Ende halb | 1,0 (Wochenende zählt nie) |

Halbe Tage wirken überall gleich:

- **Urlaubsübersicht** – verbrauchte und geplante Tage in 0,5er-Schritten
- **Tagesgutschrift** – ein halber Tag bringt die halbe Tagessollzeit
- **Überstundenurlaub** – bucht entsprechend nur die Hälfte ab
- **Listen und Freigaben** – halbe Tage tragen ein „½" hinter dem Datum

Bestandsanträge bleiben unverändert ganze Tage; beide Kennzeichen sind bei
ihnen aus.

## Neu: Lizenz beantragen oder erweitern

Auf der Lizenzseite (Administration → System → Lizenz) führt ein Knopf zum
Lizenzserver. Der Text passt sich der Lage an:

- **nicht lizenziert** → „Lizenz beantragen"
- **lizenziert** → „Lizenz erweitern"
- **alle Plätze belegt** → ausdrücklicher Hinweis, dass für weitere Benutzer
  eine größere Lizenz nötig ist

Mitgegeben werden Deployment-ID, Produktkennung, Version, aktuelle Lizenz-ID
und die Zahl der belegten Benutzerplätze – damit der Herausgeber nicht
nachfragen muss. **Nicht** übertragen werden der Aktivierungsschlüssel und
jegliche personenbezogenen Daten.

Der Lizenzserver des Herausgebers (`https://lic.dh-cloud.de`) ist im
Aktivierungsformular vorbelegt. Wer einen eigenen betreibt, trägt dort einfach
seine Adresse ein; der Anfrage-Knopf folgt dann dieser Adresse.

## Datenbank

Migration 15 ergänzt zwei Spalten:

```
vacation_requests.half_day_start  BOOLEAN DEFAULT 0
vacation_requests.half_day_end    BOOLEAN DEFAULT 0
```

Datenerhaltend und idempotent, in beiden Migrationsmechanismen hinterlegt
(`ensure_schema()` und `MIGRATIONS`). Bestandsanträge zählen unverändert als
ganze Tage.

## Tests

`tests/test_v0111.py` – 26 Tests:

- **Freigaben**: Buchung freigeben und ablehnen, Urlaub genehmigen und
  ablehnen (jeweils als Superadministrator auf einen fremden Benutzer), ein
  unbekannter Schlüssel schlägt hörbar fehl, und alle von Routen verwendeten
  Schlüssel existieren in der Registry.
- **Halbe Tage**: Faktorregeln inklusive Eintagesfall, Tageszählung,
  Wochenenden, halbe Sollzeit, Jahresübersicht, Tagesgutschrift, Formular,
  Speicherung beider Kennzeichen, Bestandsanträge, Anzeige.
- **Lizenzanfrage**: Knopf vorhanden, Adresse trägt den Kontext und keine
  Geheimnisse, eigener Server wird berücksichtigt, Formular vorbelegt.

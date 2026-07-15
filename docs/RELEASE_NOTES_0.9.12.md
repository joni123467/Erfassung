# Release Notes 0.9.12

## Überblick

Die Team-Rechte („Team & Freigaben") erhalten einen **Geltungsbereich**: Jedes
dieser Rechte kann pro Gruppe entweder auf das **eigene Team (Gruppe)** oder
auf **alle Benutzer** wirken. Bisher galten diese Rechte immer für alle
Benutzer.

## Neue Funktionen

### Dreistufige Vergabe der Team-Rechte

Im Gruppenformular werden „Manuelle Buchungen freigeben", „Urlaubsanträge
verwalten", „Zeitübersichten einsehen" und „Zeitbuchungen bearbeiten" nicht
mehr als Checkbox, sondern als Bereichsauswahl vergeben:

| Auswahl | Wirkung |
|---------|---------|
| Nicht erlaubt | Recht nicht vorhanden |
| Eigenes Team (Gruppe) | Recht wirkt nur auf Benutzer derselben Gruppe |
| Alle Benutzer | Recht wirkt auf alle Benutzer (bisheriges Verhalten) |

### Durchsetzung

Bei „Eigenes Team" gilt überall:

- **Freigaben** (Administration → Zeiterfassung → Freigaben): Es erscheinen
  nur manuelle Buchungen und Urlaubsanträge von Benutzern der eigenen Gruppe.
  Freigabe-/Ablehnungs-POSTs auf fremde Datensätze werden serverseitig mit
  klarer Meldung abgelehnt.
- **Berichte & Exporte** (Team-Zeitübersicht, Benutzerauswertung, PDF/Excel):
  enthalten nur Benutzer der eigenen Gruppe.
- **Zeitbuchungen bearbeiten**: Bearbeitungsseite, Aktualisieren und Löschen
  fremder Buchungen werden abgelehnt – ebenso das Umbuchen einer Buchung auf
  einen Benutzer außerhalb des Teams.

Administratorrechte wirken unverändert immer auf alle Benutzer; die
Bereichsauswahlen stehen dann gesperrt auf „Alle Benutzer".

### Übersicht

Die Gruppenliste kennzeichnet Team-beschränkte Rechte im Badge-Tooltip mit
„(eigenes Team)".

## Datenbank

Neue Spalten in `groups` (Migration 11, idempotent, datenerhaltend):

| Spalte | Default |
|--------|---------|
| `can_approve_manual_entries_scope` | `'all'` |
| `can_manage_vacations_scope` | `'all'` |
| `can_view_time_reports_scope` | `'all'` |
| `can_edit_time_entries_scope` | `'all'` |

Der Default `'all'` erhält exakt das Bestandsverhalten: Bereits vergebene
Team-Rechte wirken nach dem Update weiterhin auf alle Benutzer, bis der
Geltungsbereich aktiv umgestellt wird.

## Upgrade-Hinweise

Standard-Update genügt; die Migration läuft beim Start automatisch. Wer
Team-Verantwortliche auf ihr Team beschränken möchte, stellt die betreffenden
Rechte in der Gruppe auf „Eigenes Team (Gruppe)" um.

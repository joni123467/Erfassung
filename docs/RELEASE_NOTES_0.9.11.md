# Release Notes 0.9.11

## Überblick

Die Gruppenberechtigungen wurden überarbeitet: Alle Rechte sind jetzt in
Kategorien gegliedert und im Gruppenformular als übersichtliche
Berechtigungsmatrix mit Beschreibungen dargestellt – angelehnt an bekannte
Rollen-/Rechteverwaltungen. Neu sind Selbstbedienungsrechte, mit denen sich
z. B. das nachträgliche Bearbeiten von Kommentaren pro Gruppe erlauben oder
entziehen lässt.

## Neue Funktionen

### Kategorisierte Berechtigungsmatrix

Das Gruppenformular (Administration → Benutzer → Gruppen) zeigt die Rechte in
vier Kategorien, jeweils mit Titel und Kurzbeschreibung:

- **Eigene Zeiterfassung** (Standard: erlaubt)
  - Manuelle Zeitbuchungen nachtragen
  - Eigene Kommentare nachträglich bearbeiten
  - Urlaubsanträge stellen
- **Aufträge & Firmen**
  - Firmen beim Stempeln anlegen
  - Firmen verwalten (Administration) – neu delegierbar, bisher Admin-only
- **Team & Freigaben**
  - Manuelle Buchungen freigeben
  - Urlaubsanträge verwalten
  - Team-Zeitübersichten einsehen
  - Zeitbuchungen aller Benutzer bearbeiten
- **Verwaltung**
  - Benutzer verwalten

Administratorrechte umfassen automatisch alle Rechte; die Einzelrechte werden
im Formular dann angehakt und gesperrt dargestellt. Die Gruppenübersicht fasst
vergebene Rechte als Badges je Kategorie zusammen („Team & Freigaben: 2/4").

### Durchsetzung in Web, mobiler App und Offline-Betrieb

- Entzogene Rechte blenden die zugehörigen Funktionen aus (Formular
  „Manuelle Buchung", Urlaubsantrags-Formulare, Kommentar-Dialog/-Button,
  Feld „Neue Firma anlegen").
- Alle Rechte werden zusätzlich serverseitig geprüft (`POST /time`,
  `POST /vacations`, `/punch update_notes`, Administration → Firmen) –
  auch für offline eingereihte Aktionen.
- Die mobile App und die Offline-Shell erhalten die Rechte über
  `/mobile/sync-data` (`permissions`) und passen die Oberfläche an.

### Zentrales Berechtigungs-Register

`app/permissions.py` ist die einzige Quelle der Wahrheit für alle
Gruppenrechte (Schlüssel, Titel, Beschreibung, Kategorie, Standardwert).
Gruppenformular, Formular-Parsing und Übersicht leiten sich daraus ab.

## Datenbank

Neue Spalten in `groups` (Migration 10, idempotent, datenerhaltend):

| Spalte | Default | Hinweis |
|--------|---------|---------|
| `can_manage_companies` | 0 | Admin-Gruppen werden auf 1 gesetzt |
| `can_manual_time_entries` | 1 | Bestandsverhalten bleibt erhalten |
| `can_edit_own_notes` | 1 | Bestandsverhalten bleibt erhalten |
| `can_request_vacations` | 1 | Bestandsverhalten bleibt erhalten |

Benutzer ohne Gruppe behalten die Selbstbedienungsrechte.

## Upgrade-Hinweise

Standard-Update genügt; die Migration läuft beim Start automatisch. Bestehende
Gruppen verhalten sich unverändert, bis Rechte aktiv entzogen werden.

# Release Notes 0.9.19

## Überblick

Zwei Erweiterungen: **Abteilungsadministratoren** können ihren Bereich jetzt
tatsächlich selbst verwalten (bisher kam nur der Gesamtadministrator in die
Administrationsmenüs), und kollidierende Buchungen lassen sich nach einer
**Rückfrage gezielt überschreiben**.

## Neue Funktionen

### Abteilungsadministration

Bisher waren der Administration-Link und der Bereich `/admin` fest an volle
Adminrechte (`is_admin`) gebunden. Eine Gruppe mit Team-Rechten (Freigaben,
Buchungen bearbeiten …) kam schlicht nicht hinein – die Rechte liefen ins Leere.

Neu:

- **Zugang bei jeder Administrationsberechtigung**: Wer mindestens ein
  Admin-Recht besitzt, sieht den Administration-Link. `/admin` leitet
  automatisch auf die erste erlaubte Seite (Benutzer → Freigaben →
  Zeitübersichten → Gruppen → Firmen → Feiertage → Terminals → System).
  Die Navigation zeigt weiterhin ausschließlich freigegebene Bereiche.
- **„Benutzer verwalten“ mit Geltungsbereich**: Das Recht ist jetzt – wie die
  Team-Rechte aus 0.9.12 – dreistufig vergeben:

  | Auswahl | Wirkung |
  |---------|---------|
  | Nicht erlaubt | kein Zugriff auf die Benutzerverwaltung |
  | Eigenes Team (Gruppe) | nur Benutzer der eigenen Gruppe |
  | Alle Benutzer | alle Benutzer (bisheriges Verhalten) |

  Bei „Eigenes Team“ sind Benutzerliste, Detailseite sowie Anlegen, Ändern und
  Löschen auf die eigene Gruppe begrenzt.
- **Schutz vor Rechteausweitung**: Im Bereich „Eigenes Team“ ist nur die eigene
  Gruppe zuweisbar – insbesondere keine Administratorgruppe. Das Auswahlfeld
  zeigt nur zulässige Gruppen, und der Server lehnt abweichende Zuweisungen ab.

Typische Konfiguration einer Abteilungsleitung: „Benutzer verwalten“,
„Manuelle Buchungen freigeben“, „Urlaubsanträge verwalten“,
„Zeitbuchungen bearbeiten“ und „Zeitübersichten einsehen“ – jeweils mit
Bereich **Eigenes Team**.

### Buchungen überschreiben mit Bestätigung

Führt eine Änderung zu einer **neuen** Überschneidung, wird sie nicht mehr
abgelehnt. Stattdessen erscheint eine Bestätigungsseite mit den neuen und den
bisherigen Zeiten sowie einer Tabelle der betroffenen Buchungen (Datum,
Zeitraum, Mitarbeiter, Firma) und der jeweiligen Auswirkung:

| Situation | Auswirkung |
|-----------|------------|
| Bestehende Buchung wird vollständig überdeckt | wird gelöscht |
| Teilweise Überlappung | wird gekürzt (neue Zeiten werden genannt) |
| Neue Zeiten liegen mittendrin | wird geteilt (beide Abschnitte werden genannt) |

Erst „Überschreiben und speichern“ führt die Änderung aus. „Zurück zum
Bearbeiten“ und „Abbrechen“ lassen alles unverändert.

**Laufende Buchungen werden nie gelöscht**, sondern ab dem Ende der neuen
Buchung fortgeführt – eine laufende Zeiterfassung bricht durch eine Korrektur
nicht ab.

## Datenbank

Neue Spalte in `groups` (Migration 12, idempotent, datenerhaltend):

| Spalte | Default |
|--------|---------|
| `can_manage_users_scope` | `'all'` |

Der Default erhält das Bestandsverhalten: Bereits vergebene
Benutzerverwaltungs-Rechte gelten weiterhin für alle Benutzer, bis der
Geltungsbereich umgestellt wird.

## Upgrade-Hinweise

Standard-Update genügt; die Migration läuft beim Start automatisch. Um eine
Abteilungsleitung einzurichten, in deren Gruppe die gewünschten Rechte auf
„Eigenes Team“ stellen.

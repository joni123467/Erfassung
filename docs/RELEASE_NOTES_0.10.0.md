# Release Notes 0.10.0

## Überblick

Die Rechteverwaltung ist auf ein sauberes **RBAC-Modell** umgestellt:
Berechtigungen kommen ausschließlich über **Rollen**, Gruppen sind reine
Organisation. Ein Benutzer kann in mehreren Gruppen und mehreren Rollen sein.

Bestehende Installationen werden beim ersten Start automatisch überführt –
**niemand verliert Rechte**.

## Das neue Modell

```
Benutzer ──< Gruppen        (Abteilung, Team, Standort – keine Rechte)
Benutzer ──< Rollen ──< Berechtigung + Geltungsbereich
```

| Bisher | Jetzt |
|--------|-------|
| genau eine Gruppe je Benutzer | beliebig viele Gruppen |
| Rechte als Spalten auf der Gruppe | Rollen mit Berechtigungen |
| `is_admin` umgeht alles | Systemrolle Superadministrator |
| „Eigenes Team“ = gleiche Gruppen-ID | „Eigene Gruppen“ = gemeinsame Gruppe |

## Berechtigungen und Geltungsbereiche

| Kategorie | Berechtigungen | Bereich wählbar |
|-----------|----------------|-----------------|
| Eigene Zeiterfassung | `Own.Time.Edit`, `Own.Comment.Edit`, `Own.Vacation.Request` | – |
| Aufträge & Firmen | `Company.Create`, `Company.Manage` | – |
| Zeiten & Freigaben | `Time.Approve`, `Time.Edit`, `Time.View` | ✔ |
| Urlaub | `Vacation.Manage` | ✔ |
| Benutzerverwaltung | `User.View`, `User.Create`, `User.Edit`, `User.Delete` | ✔ |
| System | `System.Groups`, `System.Terminals`, `System.Roles`, `System.Settings`, `System.Backup` | – |

Geltungsbereiche: **Nicht erlaubt**, **Nur eigene**, **Eigene Gruppen**,
**Alle Benutzer**. Bei mehreren Rollen gilt der weiteste Bereich. Der Server
prüft ihn bei jeder Aktion, nicht nur beim Anzeigen.

## Systemrollen

| Rolle | Umfang |
|-------|--------|
| **Superadministrator** | alle Berechtigungen inklusive Rollen, Systemeinstellungen und Sicherung |
| **Administrator** | alle Berechtigungen außer `System.Roles`, `System.Settings`, `System.Backup` |

Beide sind unveränderlich und bekommen bei Updates automatisch neu
hinzugekommene Rechte.

> **Hinweis zur Vorlage:** Gefordert waren „Administrator besitzt alle Rechte“
> *und* ein Superadministrator, der sich durch Rollen-, System- und
> Backupverwaltung unterscheidet. Beides zusammen ist widersprüchlich; gewählt
> wurde die Variante, die beide Rollen unterscheidbar macht. Für den Bestand ist
> das folgenlos, weil bisherige Administratorgruppen auf **Superadministrator**
> abgebildet werden.

## Was sich in der Oberfläche ändert

- **Administration → Benutzer → Gruppen**: nur noch Name, Beschreibung und
  Mitglieder.
- **Administration → Benutzer → Rollen**: Berechtigungsmatrix mit
  Bereichsauswahl je Recht, Beschreibung, Aktiv-Schalter.
- **Administration → Benutzer → Berechtigungen**: nur lesende Übersicht aller
  Rechte samt der Rollen, die sie besitzen.
- **Benutzerformular**: Mehrfachauswahl für Gruppen **und** Rollen. Ohne das
  Recht „Rollen verwalten“ erscheint die Rollenauswahl nicht.

## Umstellung bestehender Installationen

Migration 14, idempotent und datenerhaltend:

1. Bisherige Gruppenzugehörigkeit wandert nach `user_groups`.
2. Mitglieder von Administratorgruppen erhalten **Superadministrator**.
3. Jede Gruppe mit Rechten wird zur Rolle **„Migration – &lt;Gruppenname&gt;“**
   mit identischem Rechteumfang (inklusive Bereich: „Eigenes Team“ → „Eigene
   Gruppen“); alle Mitglieder erhalten sie.
4. Die Rechte-Spalten der Gruppen werden geleert.

Nach dem Update empfiehlt es sich, die Migrationsrollen zu sichten und in
sprechende Rollen zu überführen (z. B. „Teamleiter“, „Auswertung“).

## Schutz vor Rechteausweitung

- Rollen zuweisen erfordert `System.Roles`.
- Systemrollen darf ausschließlich ein Superadministrator vergeben.
- `System.Roles`, `System.Settings` und `System.Backup` lassen sich nicht über
  eine selbst angelegte Rolle weitergeben.
- Gruppen sind nur im eigenen Geltungsbereich zuweisbar.
- Seeding stellt sicher, dass immer mindestens ein Superadministrator existiert.

## API

- Neu: `GET/POST /api/roles`, `POST /api/roles/{id}`.
- `/api/groups` bleibt bestehen; mitgesendete Rechte-Felder werden ignoriert.
- `/api/users` akzeptiert weiterhin `group_id` und zusätzlich `group_ids` /
  `role_ids`.
- CLI: `list-roles`, `create-user --role`, `list-users` zeigt Gruppen und Rollen.

## Datenbank

| Tabelle | Inhalt |
|---------|--------|
| `roles` | `name`, `description`, `is_system`, `is_active` |
| `role_permissions` | `role_id`, `permission_key`, `scope` |
| `user_roles` | `user_id`, `role_id` |
| `user_groups` | `user_id`, `group_id` |
| `groups` | neu: `description`; Rechte-Spalten entfallen aus dem Modell |

`users.group_id` bleibt als Spalte erhalten (Lesen alter Backups), wird aber
nicht mehr ausgewertet.

## Upgrade-Hinweise

Standard-Update genügt; die Migration läuft beim Start automatisch. Ein Backup
**vor** dem Update lässt sich weiterhin einspielen – die Migration läuft danach
erneut und baut die Rollen neu auf.

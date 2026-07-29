# Migrationsplan: Rollenbasierte Rechteverwaltung (RBAC)

Ziel: Berechtigungen werden ausschließlich über **Rollen** vergeben. **Gruppen**
sind reine Organisationseinheiten (Abteilung, Team, Standort) ohne jede Logik.
Ein Benutzer kann in beliebig vielen Gruppen und Rollen sein.

Dieses Dokument beschreibt Zielmodell, Abbildung des Bestands, Reihenfolge der
Umstellung und die bewussten Abweichungen von der Vorlage.

---

## 1. Ausgangslage

| Aspekt | Bisher |
|--------|--------|
| Zugehörigkeit | `users.group_id` – **genau eine** Gruppe |
| Berechtigungen | 10 Boolean-Spalten auf `groups` |
| Geltungsbereich | 5 Spalten `<recht>_scope` (`group` / `all`) |
| Administrator | `groups.is_admin` – umgeht alle Prüfungen |
| „Eigenes Team“ | Benutzer mit derselben `group_id` |
| Prüfung | verstreute Helfer in `app/main.py` (`_has_group_permission`, `_permission_scope`, `_scoped_user_ids`, …) |

Probleme: Rechte und Organisation sind vermischt, ein Benutzer kann nur einem
Team angehören, jedes neue Recht braucht eine Spalte, und die Prüflogik liegt
über die gesamte Anwendung verteilt.

---

## 2. Zielmodell

```
User ──< user_groups >── Group        (Organisation, keine Logik)
User ──< user_roles  >── Role ──< role_permissions >── Permission + Scope
```

### Entitäten

| Tabelle | Inhalt |
|---------|--------|
| `groups` | `name`, `description` – **keine** Rechte, kein `is_admin`, keine Scopes |
| `user_groups` | `user_id`, `group_id` (n:m) |
| `roles` | `name`, `description`, `is_system`, `is_active` |
| `user_roles` | `user_id`, `role_id` (n:m) |
| `role_permissions` | `role_id`, `permission_key`, `scope` |

Berechtigungen selbst stehen **im Code** (`app/permissions.py`) und nicht in der
Datenbank: Key, Kategorie, Anzeigename, Beschreibung, Scope-Unterstützung. Die
Datenbank speichert nur die Zuordnung Rolle → Recht (+ Scope). So können neue
Rechte ohne Migration ergänzt werden, und ein Recht kann nie „verwaisen“.

### Berechtigungen

| Kategorie | Key | Scope |
|-----------|-----|-------|
| Eigene Zeiterfassung | `Own.Time.Edit` | – (immer Self) |
| | `Own.Comment.Edit` | – |
| | `Own.Vacation.Request` | – |
| Aufträge & Firmen | `Company.Create` | – |
| | `Company.Manage` | – |
| Zeiten & Freigaben | `Time.Approve` | ✔ |
| | `Time.Edit` | ✔ |
| | `Time.View` | ✔ |
| Urlaub | `Vacation.Manage` | ✔ |
| Benutzerverwaltung | `User.View` | ✔ |
| | `User.Create` | ✔ |
| | `User.Edit` | ✔ |
| | `User.Delete` | ✔ |
| System | `System.Settings` | – |
| | `System.Backup` | – |
| | `System.Groups` | – |
| | `System.Roles` | – |
| | `System.Terminals` | – |

### Scopes

| Scope | Bedeutung |
|-------|-----------|
| `none` | Recht nicht vergeben |
| `self` | nur die eigenen Daten |
| `groups` | Benutzer, die **mindestens eine Gruppe** mit dem Handelnden teilen (plus er selbst) |
| `all` | alle Benutzer |

Mehrere Rollen: Es gilt jeweils der **weiteste** Scope (`all` > `groups` >
`self` > `none`). Rechte ohne Scope-Unterstützung sind reine Ja/Nein-Rechte.

### Systemrollen

| Rolle | Rechte | Änderbar |
|-------|--------|----------|
| **Administrator** | alle Rechte außer den Superadministrator-Vorbehalten, Scope `all` | nein |
| **Superadministrator** | **alle** Rechte, Scope `all` | nein |

Superadministrator-Vorbehalte: `System.Roles`, `System.Settings`,
`System.Backup`.

> **Abweichung von der Vorlage (bewusst):** Die Vorlage schreibt „Administrator
> besitzt automatisch alle Berechtigungen“ und listet gleichzeitig
> Rollenverwaltung, Systemeinstellungen und Backups als Unterscheidungsmerkmal
> des Superadministrators. Beides zusammen ist nicht widerspruchsfrei. Gewählt
> wurde die zweite Lesart, weil nur sie die beiden Rollen unterscheidbar macht.
> Für den Bestand ist das folgenlos: Bisherige Administratorgruppen werden auf
> **Superadministrator** abgebildet (siehe 3.), verlieren also nichts.

---

## 3. Abbildung des Bestands

Läuft einmalig als Migration 14, idempotent und datenerhaltend.

### 3.1 Mitgliedschaften

Für jeden Benutzer mit `group_id` entsteht ein Eintrag in `user_groups`.
`users.group_id` bleibt zunächst als Spalte bestehen (Lesen alter Backups),
wird von der Anwendung aber nicht mehr ausgewertet.

### 3.2 Rechte → Rollen

| Bestand | Ergebnis |
|---------|----------|
| Gruppe mit `is_admin = 1` | Mitglieder erhalten die Systemrolle **Superadministrator** |
| Gruppe mit mindestens einem Recht | neue Rolle **„Migration – &lt;Gruppenname&gt;“** mit genau diesen Rechten und Scopes; alle Mitglieder erhalten sie |
| Gruppe ohne Rechte | keine Rolle |

Anschließend werden sämtliche Rechte-Spalten der Gruppen auf `0` gesetzt.

### 3.3 Abbildung der einzelnen Rechte

| Bisher | Neu | Scope-Übernahme |
|--------|-----|-----------------|
| `can_manual_time_entries` | `Own.Time.Edit` | – |
| `can_edit_own_notes` | `Own.Comment.Edit` | – |
| `can_request_vacations` | `Own.Vacation.Request` | – |
| `can_create_companies` | `Company.Create` | – |
| `can_manage_companies` | `Company.Manage` | – |
| `can_approve_manual_entries` | `Time.Approve` | `group` → `groups`, `all` → `all` |
| `can_edit_time_entries` | `Time.Edit` | dito |
| `can_view_time_reports` | `Time.View` | dito |
| `can_manage_vacations` | `Vacation.Manage` | dito |
| `can_manage_users` | `User.View`, `User.Create`, `User.Edit`, `User.Delete` | dito (alle vier) |

Die bisherigen Selbstbedienungsrechte galten **ohne** Gruppe als erlaubt. Damit
niemand nach dem Update plötzlich weniger darf, bleiben `Own.*` implizit für
jeden Benutzer aktiv, solange ihm keine Rolle diese Rechte ausdrücklich entzieht
(siehe 4.3).

---

## 4. Umsetzung

### 4.1 Reihenfolge der Commits

1. **Plan** (dieses Dokument).
2. **Datenmodell & PermissionService** – neue Tabellen, Registry, zentrale
   Prüfung, Migration 14, Seeding der Systemrollen. Bestehende Helfer in
   `app/main.py` delegieren an den Service; Verhalten bleibt gleich.
3. **Backend & API** – Gruppen verlieren Rechte (Model, Schemas, CRUD, CLI),
   Routen prüfen ausschließlich über den Service, Rollen-API.
4. **Oberfläche** – Rollenverwaltung, Berechtigungsübersicht, Gruppeneditor ohne
   Rechte, Benutzerformular mit Mehrfachauswahl.
5. **Tests & Dokumentation** – Unit-Tests für Rechte- und Scope-Prüfung,
   Regressionstests, CHANGELOG/README/Release Notes.

### 4.2 PermissionService

Eine Stelle, die alles beantwortet:

| Methode | Zweck |
|---------|-------|
| `has(user, key)` | Recht vorhanden (Scope ≠ `none`) |
| `scope(user, key)` | weitester Scope über alle Rollen |
| `allowed_user_ids(db, user, key)` | `None` = alle, sonst erlaubte Benutzer-IDs |
| `can_access_user(db, user, key, target_id)` | Zugriff auf einen bestimmten Benutzer |
| `permissions(user)` | Kompaktes Abbild für Templates/Navigation |

Keine Route greift mehr direkt auf Gruppen oder Rollen zu.

### 4.3 Verhaltensgarantien

- Rechte ohne Rolle: `Own.*` bleiben erlaubt (Bestandsverhalten), alle anderen
  Rechte sind ohne Rolle nicht vorhanden.
- `Scope = groups` prüft **Schnittmenge der Gruppen**, nicht mehr Gleichheit
  einer einzelnen Gruppen-ID.
- Rechteausweitung bleibt ausgeschlossen: Wer Rollen nicht verwalten darf
  (`System.Roles`), kann anderen auch keine Rollen zuweisen.

### 4.4 API-Kompatibilität

- `/api/groups` bleibt bestehen; mitgesendete Rechte-Felder werden ignoriert.
- `/api/users` akzeptiert weiterhin `group_id` (wird als einzelne
  Mitgliedschaft angelegt) und zusätzlich `group_ids` / `role_ids`.
- Neu: `/api/roles`.

### 4.5 Datensicherung

Backup und Restore arbeiten metadatengetrieben über alle Modelltabellen – die
neuen Tabellen sind damit automatisch enthalten. Ein Backup **vor** dem Update
lässt sich weiterhin einspielen; die Migration läuft danach erneut.

---

## 5. Risiken

| Risiko | Gegenmaßnahme |
|--------|---------------|
| Benutzer verliert nach dem Update Rechte | Migration bildet jede Gruppe 1:1 auf eine Rolle ab; `is_admin` → Superadministrator |
| Niemand kann mehr Rollen verwalten | Seeding stellt sicher, dass mindestens ein Benutzer Superadministrator ist |
| Alte Backups ohne die neuen Tabellen | Migration läuft nach dem Restore erneut und baut die Rollen neu auf |
| Verstreute Alt-Prüfungen bleiben zurück | Schritt 3 entfernt alle Gruppen-Prüfungen; Tests decken jede Route ab |

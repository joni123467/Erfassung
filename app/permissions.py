"""Zentrale Registry aller Berechtigungen (RBAC).

Berechtigungen leben ausschließlich im Code – die Datenbank speichert nur die
Zuordnung *Rolle → Berechtigung (+ Geltungsbereich)*. Dadurch lassen sich neue
Rechte ohne Migration ergänzen, und ein Recht kann nie verwaisen.

Aufbau nach dem Muster bekannter Rollenverwaltungen (Personio, Jira,
Nextcloud): Rechte sind in Kategorien gruppiert, jedes Recht hat Key,
Anzeigename und Kurzbeschreibung.

Geltungsbereich (Scope) – nur für Rechte über *andere* Benutzer:

``none``
    Recht nicht vergeben.
``self``
    Nur die eigenen Daten.
``groups``
    Benutzer, die mindestens eine Gruppe mit dem Handelnden teilen.
``all``
    Alle Benutzer.

Besitzt ein Benutzer mehrere Rollen, gilt jeweils der **weiteste** Scope.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPE_NONE = "none"
SCOPE_SELF = "self"
SCOPE_GROUPS = "groups"
SCOPE_ALL = "all"

#: Reihenfolge von eng nach weit – bestimmt, welcher Scope bei mehreren Rollen gewinnt.
SCOPE_ORDER: tuple[str, ...] = (SCOPE_NONE, SCOPE_SELF, SCOPE_GROUPS, SCOPE_ALL)

SCOPE_LABELS: dict[str, str] = {
    SCOPE_NONE: "Nicht erlaubt",
    SCOPE_SELF: "Nur eigene",
    SCOPE_GROUPS: "Eigene Gruppen",
    SCOPE_ALL: "Alle Benutzer",
}

#: Auswahl im Rolleneditor für Rechte mit Geltungsbereich.
SCOPE_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (scope, SCOPE_LABELS[scope]) for scope in SCOPE_ORDER
)


def scope_rank(scope: str | None) -> int:
    """Position eines Scopes in :data:`SCOPE_ORDER` (unbekannt = ``none``)."""
    try:
        return SCOPE_ORDER.index(scope or SCOPE_NONE)
    except ValueError:
        return 0


def widest_scope(*scopes: str | None) -> str:
    """Weitester der übergebenen Geltungsbereiche."""
    return max((s or SCOPE_NONE for s in scopes), key=scope_rank, default=SCOPE_NONE)


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    description: str
    #: Recht über andere Benutzer – im Rolleneditor mit Geltungsbereich.
    scoped: bool = False
    #: Betrifft ausschließlich die eigenen Daten; ohne Rolle erlaubt (Bestandsverhalten).
    self_service: bool = False
    #: Nur der Superadministrator darf dieses Recht besitzen.
    superadmin_only: bool = False


@dataclass(frozen=True)
class PermissionCategory:
    key: str
    label: str
    description: str
    permissions: tuple[Permission, ...]


CATEGORIES: tuple[PermissionCategory, ...] = (
    PermissionCategory(
        key="own",
        label="Eigene Zeiterfassung",
        description=(
            "Was ein Benutzer an seinen eigenen Buchungen und Anträgen tun darf. "
            "Ohne Rolle sind diese Rechte erlaubt; eine Rolle kann sie entziehen."
        ),
        permissions=(
            Permission(
                key="Own.Time.Edit",
                label="Manuelle Zeitbuchungen nachtragen",
                description=(
                    "Vergangene Arbeitszeiten über das Formular nachtragen. "
                    "Nachträge müssen weiterhin freigegeben werden."
                ),
                self_service=True,
            ),
            Permission(
                key="Own.Comment.Edit",
                label="Eigene Kommentare nachträglich bearbeiten",
                description=(
                    "Kommentar einer eigenen Buchung nach dem Beenden eines "
                    "Auftrags bzw. der Arbeitszeit anpassen (mobil und Web)."
                ),
                self_service=True,
            ),
            Permission(
                key="Own.Vacation.Request",
                label="Urlaubsanträge stellen",
                description="Eigene Urlaubs- und Überstundenanträge einreichen und zurückziehen.",
                self_service=True,
            ),
        ),
    ),
    PermissionCategory(
        key="companies",
        label="Aufträge & Firmen",
        description="Umgang mit Firmen beim Stempeln und in der Verwaltung.",
        permissions=(
            Permission(
                key="Company.Create",
                label="Firmen beim Stempeln anlegen",
                description="Beim Starten eines Auftrags neue Firmen direkt anlegen.",
            ),
            Permission(
                key="Company.Manage",
                label="Firmen verwalten",
                description="Firmenstammdaten in der Administration anlegen, bearbeiten und löschen.",
            ),
        ),
    ),
    PermissionCategory(
        key="time",
        label="Zeiten & Freigaben",
        description=(
            "Rechte über Buchungen anderer Benutzer. Der Geltungsbereich legt "
            "fest, für wen sie gelten."
        ),
        permissions=(
            Permission(
                key="Time.Approve",
                label="Manuelle Buchungen freigeben",
                description="Nachgetragene Zeitbuchungen freigeben oder ablehnen.",
                scoped=True,
            ),
            Permission(
                key="Time.Edit",
                label="Zeitbuchungen bearbeiten",
                description="Buchungen korrigieren, anlegen und löschen.",
                scoped=True,
            ),
            Permission(
                key="Time.View",
                label="Zeitübersichten einsehen",
                description="Zeitkonten, Berichte und Exporte einsehen.",
                scoped=True,
            ),
        ),
    ),
    PermissionCategory(
        key="vacation",
        label="Urlaub",
        description="Bearbeitung von Urlaubs- und Überstundenanträgen.",
        permissions=(
            Permission(
                key="Vacation.Manage",
                label="Urlaubsanträge verwalten",
                description="Anträge genehmigen, ablehnen und zurücknehmen.",
                scoped=True,
            ),
            # Bewusst getrennt von ``Vacation.Manage``: Den Resturlaub eines
            # Teams zu sehen ist etwas anderes, als über Anträge zu
            # entscheiden. Wer plant, braucht den Überblick; wer genehmigt,
            # nicht zwingend umgekehrt.
            Permission(
                key="Vacation.Overview",
                label="Urlaubsübersicht einsehen",
                description=(
                    "Anspruch, genommenen und verbleibenden Urlaub der "
                    "Mitarbeitenden einsehen."
                ),
                scoped=True,
            ),
        ),
    ),
    PermissionCategory(
        key="users",
        label="Benutzerverwaltung",
        description=(
            "Zugriff auf Benutzerkonten. Der Geltungsbereich legt fest, welche "
            "Konten sichtbar bzw. bearbeitbar sind."
        ),
        permissions=(
            Permission(
                key="User.View",
                label="Benutzer einsehen",
                description="Benutzerliste und Detailseiten öffnen.",
                scoped=True,
            ),
            Permission(
                key="User.Create",
                label="Benutzer anlegen",
                description="Neue Benutzerkonten anlegen.",
                scoped=True,
            ),
            Permission(
                key="User.Edit",
                label="Benutzer bearbeiten",
                description="Stammdaten, Arbeitszeit- und Urlaubsregeln ändern.",
                scoped=True,
            ),
            Permission(
                key="User.Delete",
                label="Benutzer löschen",
                description="Benutzerkonten samt Buchungen entfernen.",
                scoped=True,
            ),
        ),
    ),
    PermissionCategory(
        key="system",
        label="System",
        description="Administration der Anwendung selbst.",
        permissions=(
            Permission(
                key="System.Groups",
                label="Gruppen verwalten",
                description="Organisationsgruppen anlegen, umbenennen und Mitglieder zuordnen.",
            ),
            Permission(
                key="System.Terminals",
                label="Terminals & Feiertage verwalten",
                description="Zeiterfassungsterminals einrichten und Feiertage pflegen.",
            ),
            Permission(
                key="System.Roles",
                label="Rollen verwalten",
                description="Rollen anlegen, Berechtigungen vergeben und Rollen zuweisen.",
                superadmin_only=True,
            ),
            Permission(
                key="System.Settings",
                label="Systemeinstellungen",
                description="Logging, Datenbank, Synchronisation und Systemstatus.",
                superadmin_only=True,
            ),
            Permission(
                key="System.Backup",
                label="Sicherung & Wiederherstellung",
                description="Backups einrichten, ausführen und Wiederherstellungen starten.",
                superadmin_only=True,
            ),
        ),
    ),
)

ALL_PERMISSIONS: tuple[Permission, ...] = tuple(
    permission for category in CATEGORIES for permission in category.permissions
)

PERMISSION_KEYS: tuple[str, ...] = tuple(permission.key for permission in ALL_PERMISSIONS)

PERMISSIONS_BY_KEY: dict[str, Permission] = {
    permission.key: permission for permission in ALL_PERMISSIONS
}

SELF_SERVICE_KEYS: tuple[str, ...] = tuple(
    permission.key for permission in ALL_PERMISSIONS if permission.self_service
)

SCOPED_KEYS: tuple[str, ...] = tuple(
    permission.key for permission in ALL_PERMISSIONS if permission.scoped
)

SUPERADMIN_KEYS: tuple[str, ...] = tuple(
    permission.key for permission in ALL_PERMISSIONS if permission.superadmin_only
)

#: Name der beiden Systemrollen (nicht löschbar, nicht änderbar).
ROLE_ADMINISTRATOR = "Administrator"
ROLE_SUPERADMINISTRATOR = "Superadministrator"
SYSTEM_ROLE_NAMES: tuple[str, ...] = (ROLE_SUPERADMINISTRATOR, ROLE_ADMINISTRATOR)


def default_scope(permission: Permission) -> str:
    """Scope, den ein Recht bei „vergeben“ ohne weitere Angabe erhält."""
    if permission.scoped:
        return SCOPE_ALL
    if permission.self_service:
        return SCOPE_SELF
    return SCOPE_ALL


def system_role_grants(role_name: str) -> dict[str, str]:
    """Rechte einer Systemrolle: ``{key: scope}``.

    Der Superadministrator besitzt alles; der Administrator alles außer den
    Superadministrator-Vorbehalten (Rollen, Systemeinstellungen, Backups).
    """
    grants: dict[str, str] = {}
    for permission in ALL_PERMISSIONS:
        if permission.superadmin_only and role_name != ROLE_SUPERADMINISTRATOR:
            continue
        grants[permission.key] = default_scope(permission)
    return grants


def normalize_scope(permission: Permission, raw: str | None) -> str:
    """Formulareingabe auf einen gültigen Scope abbilden."""
    value = (raw or SCOPE_NONE).strip().lower()
    if value not in SCOPE_ORDER:
        value = SCOPE_NONE
    if value == SCOPE_NONE:
        return SCOPE_NONE
    if not permission.scoped:
        # Rechte ohne Geltungsbereich sind reine Ja/Nein-Rechte.
        return default_scope(permission)
    return value


def parse_form_values(form) -> dict[str, str]:
    """Berechtigungen eines Rollenformulars lesen: ``{key: scope}``.

    Rechte mit Geltungsbereich kommen als Auswahl ``scope__<key>``, alle
    anderen als Checkbox ``perm__<key>``. Nicht vergebene Rechte fehlen im
    Ergebnis.
    """
    values: dict[str, str] = {}
    for permission in ALL_PERMISSIONS:
        if permission.scoped:
            scope = normalize_scope(permission, form.get(f"scope__{permission.key}"))
        else:
            checked = form.get(f"perm__{permission.key}") in ("on", "1", "true")
            scope = default_scope(permission) if checked else SCOPE_NONE
        if scope != SCOPE_NONE:
            values[permission.key] = scope
    return values

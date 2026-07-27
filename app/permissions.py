"""Zentrales Register der Gruppenberechtigungen.

Einzige Quelle der Wahrheit für alle Gruppenrechte: Model-Spalten
(``models.Group``), Formular-Parsing, Gruppenformular und Gruppenübersicht
leiten sich hieraus ab. Neue Berechtigungen werden ausschließlich hier (plus
Model-Spalte + Migration) ergänzt – die UI folgt automatisch.

Aufbau nach dem Muster bekannter Rollen-/Rechteverwaltungen (z. B.
Personio, Jira, Nextcloud): Berechtigungen sind in Kategorien gruppiert,
jede Berechtigung hat Titel und Kurzbeschreibung.

Zwei Arten von Berechtigungen:

- ``self_service=True``: Rechte, die das eigene Arbeiten betreffen
  (z. B. Kommentare nachträglich bearbeiten). Standard ist **erlaubt**;
  Benutzer ohne Gruppe behalten diese Rechte (Bestandsverhalten).
- ``self_service=False``: Team-/Verwaltungsrechte. Standard ist
  **nicht erlaubt**; Benutzer ohne Gruppe haben sie nicht.
  Administratorgruppen (``is_admin``) besitzen immer alle Rechte.

Rechte über andere Benutzer (``scoped=True``) haben zusätzlich einen
**Geltungsbereich** (Spalte ``<key>_scope``): ``'group'`` beschränkt das
Recht auf Benutzer der eigenen Gruppe (Team), ``'all'`` gilt für alle
Benutzer. Im Formular werden sie dreistufig dargestellt
(Nicht erlaubt / Eigenes Team / Alle Benutzer).
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPE_GROUP = "group"
SCOPE_ALL = "all"
SCOPE_CHOICES = (
    ("none", "Nicht erlaubt"),
    (SCOPE_GROUP, "Eigenes Team (Gruppe)"),
    (SCOPE_ALL, "Alle Benutzer"),
)


def scope_column(key: str) -> str:
    return f"{key}_scope"


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    description: str
    default: bool = False
    self_service: bool = False
    scoped: bool = False

    @property
    def scope_key(self) -> str:
        return scope_column(self.key)


@dataclass(frozen=True)
class PermissionCategory:
    key: str
    label: str
    description: str
    permissions: tuple[Permission, ...]


CATEGORIES: tuple[PermissionCategory, ...] = (
    PermissionCategory(
        key="self_service",
        label="Eigene Zeiterfassung",
        description=(
            "Was Mitglieder dieser Gruppe an ihren eigenen Buchungen tun dürfen. "
            "Diese Rechte sind standardmäßig aktiviert."
        ),
        permissions=(
            Permission(
                key="can_manual_time_entries",
                label="Manuelle Zeitbuchungen nachtragen",
                description=(
                    "Vergangene Arbeitszeiten über das Formular nachtragen. "
                    "Nachträge müssen weiterhin freigegeben werden."
                ),
                default=True,
                self_service=True,
            ),
            Permission(
                key="can_edit_own_notes",
                label="Eigene Kommentare nachträglich bearbeiten",
                description=(
                    "Kommentar einer eigenen Buchung nach dem Beenden eines "
                    "Auftrags bzw. der Arbeitszeit anpassen (mobil und Web)."
                ),
                default=True,
                self_service=True,
            ),
            Permission(
                key="can_request_vacations",
                label="Urlaubsanträge stellen",
                description="Eigene Urlaubs- und Überstundenanträge einreichen und zurückziehen.",
                default=True,
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
                key="can_create_companies",
                label="Firmen beim Stempeln anlegen",
                description="Beim Starten eines Auftrags neue Firmen direkt anlegen.",
            ),
            Permission(
                key="can_manage_companies",
                label="Firmen verwalten",
                description="Firmenstammdaten in der Administration anlegen, bearbeiten und löschen.",
            ),
        ),
    ),
    PermissionCategory(
        key="team",
        label="Team & Freigaben",
        description=(
            "Rechte über Buchungen und Anträge anderer Benutzer. Geltungsbereich "
            "wählbar: nur Benutzer der eigenen Gruppe (Team) oder alle Benutzer."
        ),
        permissions=(
            Permission(
                key="can_approve_manual_entries",
                label="Manuelle Buchungen freigeben",
                description="Nachgetragene Zeitbuchungen anderer Benutzer freigeben oder ablehnen.",
                scoped=True,
            ),
            Permission(
                key="can_manage_vacations",
                label="Urlaubsanträge verwalten",
                description="Urlaubsanträge anderer Benutzer genehmigen, ablehnen und zurücknehmen.",
                scoped=True,
            ),
            Permission(
                key="can_view_time_reports",
                label="Zeitübersichten einsehen",
                description="Zeitkonten, Berichte und Exporte anderer Benutzer einsehen.",
                scoped=True,
            ),
            Permission(
                key="can_edit_time_entries",
                label="Zeitbuchungen bearbeiten",
                description="Buchungen anderer Benutzer korrigieren, anlegen und löschen.",
                scoped=True,
            ),
        ),
    ),
    PermissionCategory(
        key="administration",
        label="Verwaltung",
        description=(
            "Zugriff auf Verwaltungsbereiche der Anwendung. Der Geltungsbereich "
            "legt fest, ob nur die eigene Abteilung (Gruppe) oder alle Benutzer "
            "verwaltet werden dürfen."
        ),
        permissions=(
            Permission(
                key="can_manage_users",
                label="Benutzer verwalten",
                description=(
                    "Benutzerkonten und deren Einstellungen anlegen und bearbeiten. "
                    "Bei „Eigenes Team“ nur Benutzer der eigenen Gruppe; "
                    "Administratorgruppen können dann nicht vergeben werden."
                ),
                scoped=True,
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


def parse_form_values(form) -> dict[str, object]:
    """Liest alle Berechtigungen aus einem (Starlette-)Formular.

    Checkbox-Rechte kommen als ``on``; Rechte mit Geltungsbereich als
    Dreifach-Auswahl ``<key>_scope`` (none/group/all) und werden in Boolean
    (Recht vorhanden) + Scope-Spalte zerlegt.
    """
    values: dict[str, object] = {}
    for permission in ALL_PERMISSIONS:
        if permission.scoped:
            raw = str(form.get(permission.scope_key) or "none")
            if raw not in ("none", SCOPE_GROUP, SCOPE_ALL):
                raw = "none"
            values[permission.key] = raw != "none"
            values[permission.scope_key] = raw if raw != "none" else SCOPE_ALL
        else:
            values[permission.key] = form.get(permission.key) == "on"
    return values


def grant_all() -> dict[str, object]:
    values: dict[str, object] = {}
    for permission in ALL_PERMISSIONS:
        values[permission.key] = True
        if permission.scoped:
            values[permission.scope_key] = SCOPE_ALL
    return values

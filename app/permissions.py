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
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    description: str
    default: bool = False
    self_service: bool = False


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
        description="Rechte über Buchungen und Anträge anderer Benutzer.",
        permissions=(
            Permission(
                key="can_approve_manual_entries",
                label="Manuelle Buchungen freigeben",
                description="Nachgetragene Zeitbuchungen anderer Benutzer freigeben oder ablehnen.",
            ),
            Permission(
                key="can_manage_vacations",
                label="Urlaubsanträge verwalten",
                description="Urlaubsanträge anderer Benutzer genehmigen, ablehnen und zurücknehmen.",
            ),
            Permission(
                key="can_view_time_reports",
                label="Team-Zeitübersichten einsehen",
                description="Zeitkonten, Berichte und Exporte aller Benutzer einsehen.",
            ),
            Permission(
                key="can_edit_time_entries",
                label="Zeitbuchungen aller Benutzer bearbeiten",
                description="Buchungen anderer Benutzer korrigieren, anlegen und löschen.",
            ),
        ),
    ),
    PermissionCategory(
        key="administration",
        label="Verwaltung",
        description="Zugriff auf Verwaltungsbereiche der Anwendung.",
        permissions=(
            Permission(
                key="can_manage_users",
                label="Benutzer verwalten",
                description="Benutzerkonten und deren Einstellungen anlegen und bearbeiten.",
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


def parse_form_values(form) -> dict[str, bool]:
    """Liest alle Berechtigungs-Checkboxen aus einem (Starlette-)Formular."""
    return {key: form.get(key) == "on" for key in PERMISSION_KEYS}


def grant_all() -> dict[str, bool]:
    return {key: True for key in PERMISSION_KEYS}

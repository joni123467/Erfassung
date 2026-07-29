"""Zentrale Rechteprüfung (RBAC).

Einzige Stelle, an der Berechtigungen ausgewertet werden. Der Weg ist immer
derselbe::

    User → UserRoles → RolePermissions → Permission + Scope

Gruppen tragen **keine** Rechte mehr; sie bestimmen ausschließlich, für wen ein
Recht mit Geltungsbereich ``groups`` gilt.

Alle Funktionen sind auch mit ``user=None`` aufrufbar (nicht angemeldet →
keine Rechte), damit Aufrufer keine Sonderfälle brauchen.
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy.orm import Session

from . import models
from . import permissions as registry
from .permissions import (
    SCOPE_ALL,
    SCOPE_GROUPS,
    SCOPE_NONE,
    SCOPE_SELF,
)


def _active_roles(user: Optional[models.User]) -> list[models.Role]:
    if not user:
        return []
    return [role for role in getattr(user, "roles", []) or [] if role.is_active]


def is_superadmin(user: Optional[models.User]) -> bool:
    """Besitzt der Benutzer die Systemrolle „Superadministrator“?"""
    return any(
        role.name == registry.ROLE_SUPERADMINISTRATOR for role in _active_roles(user)
    )


def scope(user: Optional[models.User], key: str) -> str:
    """Weitester Geltungsbereich dieses Rechts über alle aktiven Rollen.

    Selbstbedienungsrechte (``Own.*``) gelten ohne jede Rolle als erlaubt –
    so verlieren Bestandsinstallationen nach der Umstellung nichts. Sobald
    mindestens eine Rolle zugewiesen ist, entscheiden ausschließlich die
    Rollen.
    """
    permission = registry.PERMISSIONS_BY_KEY.get(key)
    if permission is None or user is None:
        return SCOPE_NONE
    roles = _active_roles(user)
    if not roles:
        return SCOPE_SELF if permission.self_service else SCOPE_NONE
    granted = SCOPE_NONE
    for role in roles:
        value = role.permission_map.get(key)
        if value:
            granted = registry.widest_scope(granted, value)
    return granted


def has(user: Optional[models.User], key: str) -> bool:
    """Ist das Recht überhaupt vorhanden (Geltungsbereich ≠ ``none``)?"""
    return scope(user, key) != SCOPE_NONE


def has_any(user: Optional[models.User], keys: Iterable[str]) -> bool:
    return any(has(user, key) for key in keys)


def allowed_user_ids(
    db: Session, user: Optional[models.User], key: str
) -> Optional[set[int]]:
    """Benutzer, auf die ein Recht wirkt.

    ``None`` bedeutet „keine Einschränkung“ (Scope ``all``). Sonst die Menge
    der erlaubten Benutzer-IDs: bei ``groups`` alle Mitglieder der eigenen
    Gruppen (und man selbst), bei ``self`` nur man selbst, bei ``none`` leer.
    """
    granted = scope(user, key)
    if granted == SCOPE_ALL:
        return None
    if granted == SCOPE_NONE or user is None:
        return set()
    if granted == SCOPE_SELF:
        return {user.id}
    group_ids = [group.id for group in user.groups]
    if not group_ids:
        return {user.id}
    rows = (
        db.query(models.user_groups.c.user_id)
        .filter(models.user_groups.c.group_id.in_(group_ids))
        .all()
    )
    ids = {row[0] for row in rows}
    ids.add(user.id)
    return ids


def can_access_user(
    db: Session, user: Optional[models.User], key: str, target_user_id: Optional[int]
) -> bool:
    """Darf ``user`` das Recht auf den Zielbenutzer anwenden?"""
    allowed = allowed_user_ids(db, user, key)
    if allowed is None:
        return True
    return target_user_id is not None and target_user_id in allowed


def shares_group(user: Optional[models.User], other: Optional[models.User]) -> bool:
    """Haben beide Benutzer mindestens eine gemeinsame Gruppe?"""
    if not user or not other:
        return False
    return bool(user.group_ids & other.group_ids)


# --- Ableitungen für Navigation und Templates ----------------------------------

#: Bereiche des Administrationsmenüs und die Rechte, die sie sichtbar machen.
_AREA_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "users": ("User.View", "User.Create", "User.Edit", "User.Delete"),
    "groups": ("System.Groups",),
    "roles": ("System.Roles",),
    "companies": ("Company.Manage",),
    "holidays": ("System.Terminals",),
    "integrations": ("System.Terminals",),
    "approvals_manual": ("Time.Approve",),
    "approvals_vacations": ("Vacation.Manage",),
    "reports": ("Time.View",),
    "edit_time_entries": ("Time.Edit",),
    "system": ("System.Settings",),
    "backup": ("System.Backup",),
}


def area_permissions(user: Optional[models.User]) -> dict[str, bool]:
    """Kompaktes Rechte-Abbild für Navigation und Templates."""
    result = {area: has_any(user, keys) for area, keys in _AREA_PERMISSIONS.items()}
    result["approvals"] = result["approvals_manual"] or result["approvals_vacations"]
    result["create_companies"] = has(user, "Company.Create")
    result["superadmin"] = is_superadmin(user)
    # Steuert, ob der Administrationsbereich überhaupt erreichbar ist.
    result["any"] = any(
        result[area]
        for area in (
            "users", "groups", "roles", "companies", "holidays", "approvals",
            "reports", "edit_time_entries", "integrations", "system", "backup",
        )
    )
    return result


#: Startseiten des Administrationsbereichs in Reihenfolge der Bevorzugung.
ADMIN_ENTRY_PAGES: tuple[tuple[str, str], ...] = (
    ("users", "/admin/users"),
    ("approvals", "/admin/approvals"),
    ("reports", "/admin/reports/time"),
    ("groups", "/admin/groups"),
    ("roles", "/admin/roles"),
    ("companies", "/admin/companies"),
    ("holidays", "/admin/holidays"),
    ("integrations", "/admin/terminals"),
    ("system", "/admin/system/status"),
    ("backup", "/admin/system/backups"),
)


def landing_page(user: Optional[models.User]) -> Optional[str]:
    areas = area_permissions(user)
    for key, url in ADMIN_ENTRY_PAGES:
        if areas.get(key):
            return url
    return None


def has_admin_access(user: Optional[models.User]) -> bool:
    return bool(user) and area_permissions(user)["any"]


# --- Rollenvergabe ---------------------------------------------------------------

def assignable_roles(db: Session, user: Optional[models.User]) -> list[models.Role]:
    """Rollen, die dieser Benutzer anderen zuweisen darf.

    Ohne ``System.Roles`` gar keine. Wer keine Systemrolle besitzt, kann auch
    keine vergeben – sonst ließen sich die eigenen Rechte ausweiten.
    """
    if not has(user, "System.Roles"):
        return []
    query = db.query(models.Role).order_by(models.Role.name)
    if is_superadmin(user):
        return query.all()
    return [role for role in query.all() if not role.is_system]


def assignable_groups(db: Session, user: Optional[models.User]) -> list[models.Group]:
    """Gruppen, die dieser Benutzer bei der Benutzerverwaltung vergeben darf."""
    query = db.query(models.Group).order_by(models.Group.name)
    if scope(user, "User.Edit") == SCOPE_ALL or has(user, "System.Groups"):
        return query.all()
    if not user:
        return []
    return sorted(user.groups, key=lambda group: group.name)

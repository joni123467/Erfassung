"""Kommandozeilen-Verwaltung für Erfassung-Benutzer.

Ausführen (lokal):       python -m app.manage <befehl> [optionen]
Ausführen (Container):   docker exec -it erfassung python -m app.manage <befehl> [optionen]

Befehle:
  list-users                Alle Benutzer auflisten
  list-groups               Alle Gruppen (inkl. Admin-Kennzeichen) auflisten
  create-user               Neuen Benutzer anlegen
  reset-password            Passwort eines Benutzers zurücksetzen

Die DB wird über die Umgebungsvariable DATABASE_URL bestimmt (gleich wie die
Web-App). Ohne Angabe wird ./erfassung.db verwendet.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import string
import sys
from typing import Optional

from sqlalchemy.exc import IntegrityError

from . import crud, database, models, schemas, security


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────
def _session():
    # Tabellen sicherstellen (idempotent), damit die CLI auch auf einer frischen
    # DB funktioniert, ohne dass zuvor die Web-App gestartet wurde.
    models.Base.metadata.create_all(bind=database.engine)
    return database.SessionLocal()


def _generate_password(length: int = 16) -> str:
    """Erzeuge ein zufälliges Passwort, das die Stärke-Regeln erfüllt."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*?-_+="
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        try:
            security.validate_password_strength(candidate)
            return candidate
        except ValueError:
            continue


def _obtain_password(args, *, confirm: bool) -> str:
    """Passwort aus --password, --random oder interaktiver Eingabe gewinnen."""
    if getattr(args, "random", False):
        password = _generate_password()
        print(f"Generiertes Passwort: {password}")
        return password
    if args.password:
        return args.password
    if not sys.stdin.isatty():
        _fail(
            "Kein Passwort angegeben. Nutze --password, --random "
            "oder führe den Befehl interaktiv (TTY) aus."
        )
    while True:
        first = getpass.getpass("Neues Passwort: ")
        if confirm:
            second = getpass.getpass("Passwort wiederholen: ")
            if first != second:
                print("Die Passwörter stimmen nicht überein. Bitte erneut.")
                continue
        try:
            security.validate_password_strength(first)
        except ValueError as exc:
            print(f"Ungültiges Passwort: {exc}")
            continue
        return first


def _fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"Fehler: {message}", file=sys.stderr)
    raise SystemExit(1)


def _find_user(db, *, username: Optional[str], user_id: Optional[int]) -> models.User:
    user = None
    if user_id is not None:
        user = crud.get_user(db, user_id)
    elif username:
        user = crud.get_user_by_username(db, username.strip())
    if not user:
        _fail("Benutzer nicht gefunden.")
    return user


def _resolve_group_id(db, group_ref: Optional[str]) -> Optional[int]:
    if not group_ref:
        return None
    if group_ref.isdigit():
        group = crud.get_group(db, int(group_ref))
    else:
        group = (
            db.query(models.Group)
            .filter(models.Group.name == group_ref)
            .first()
        )
    if not group:
        _fail(
            f"Gruppe '{group_ref}' nicht gefunden. "
            "Verfügbare Gruppen via 'list-groups' anzeigen."
        )
    return group.id


# ── Befehle ──────────────────────────────────────────────────────────────────
def cmd_list_users(args) -> None:
    db = _session()
    try:
        users = crud.get_users(db)
        if not users:
            print("Keine Benutzer vorhanden.")
            return
        rows = []
        for u in users:
            group = u.group.name if u.group else "-"
            is_admin = "ja" if (u.group and u.group.is_admin) else "nein"
            pw_change = "ja" if u.must_change_password else "nein"
            rows.append((str(u.id), u.username, u.full_name, u.email, group, is_admin, pw_change))
        headers = ("ID", "Benutzername", "Name", "E-Mail", "Gruppe", "Admin", "PW-Wechsel")
        widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
        line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
        print(line)
        print("  ".join("-" * widths[i] for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\n{len(users)} Benutzer.")
    finally:
        db.close()


def cmd_list_groups(args) -> None:
    db = _session()
    try:
        groups = crud.get_groups(db)
        if not groups:
            print("Keine Gruppen vorhanden.")
            return
        for g in groups:
            flags = "ADMIN" if g.is_admin else "Standard"
            print(f"[{g.id}] {g.name}  ({flags})")
    finally:
        db.close()


def cmd_create_user(args) -> None:
    db = _session()
    try:
        group_id = _resolve_group_id(db, args.group)
        password = _obtain_password(args, confirm=True)
        try:
            user = crud.create_user(
                db,
                schemas.UserCreate(
                    username=args.username.strip(),
                    full_name=args.full_name.strip(),
                    email=args.email.strip(),
                    group_id=group_id,
                    standard_weekly_hours=args.weekly_hours,
                    password=password,
                ),
            )
        except IntegrityError:
            db.rollback()
            _fail("Benutzername oder E-Mail ist bereits vergeben.")
        except ValueError as exc:
            db.rollback()
            _fail(str(exc))

        # crud.create_user setzt must_change_password immer auf True.
        if not args.force_change:
            user.must_change_password = False
            db.commit()
            db.refresh(user)

        print("Benutzer angelegt:")
        print(f"  ID:               {user.id}")
        print(f"  Benutzername:     {user.username}")
        print(f"  Name:             {user.full_name}")
        print(f"  E-Mail:           {user.email}")
        print(f"  PIN:              {user.pin_code}")
        print(f"  Gruppe:           {user.group.name if user.group else '-'}")
        print(f"  Passwortwechsel:  {'erforderlich' if user.must_change_password else 'nein'}")
    finally:
        db.close()


def cmd_reset_password(args) -> None:
    db = _session()
    try:
        user = _find_user(db, username=args.username, user_id=args.id)
        password = _obtain_password(args, confirm=True)
        try:
            security.validate_password_strength(password)
        except ValueError as exc:
            _fail(str(exc))
        user.password_hash = security.hash_password(password)
        user.must_change_password = bool(args.force_change)
        db.commit()
        print(
            f"Passwort für '{user.username}' (ID {user.id}) wurde zurückgesetzt."
        )
        print(
            "  Passwortwechsel bei nächster Anmeldung: "
            f"{'ja' if user.must_change_password else 'nein'}"
        )
    finally:
        db.close()


# ── Argument-Parser ──────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.manage",
        description="Benutzerverwaltung für Erfassung (Konsole).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-users", help="Alle Benutzer auflisten")
    p_list.set_defaults(func=cmd_list_users)

    p_groups = sub.add_parser("list-groups", help="Alle Gruppen auflisten")
    p_groups.set_defaults(func=cmd_list_groups)

    p_create = sub.add_parser("create-user", help="Neuen Benutzer anlegen")
    p_create.add_argument("--username", required=True, help="Anmeldename (eindeutig)")
    p_create.add_argument("--full-name", required=True, dest="full_name", help="Voller Name")
    p_create.add_argument("--email", required=True, help="E-Mail (eindeutig)")
    p_create.add_argument("--group", help="Gruppen-ID oder -Name (für Admin-Rechte)")
    p_create.add_argument(
        "--weekly-hours", type=float, default=40.0, dest="weekly_hours",
        help="Wochenarbeitszeit in Stunden (Standard: 40)",
    )
    p_create.add_argument("--password", help="Passwort direkt setzen (sonst Abfrage)")
    p_create.add_argument("--random", action="store_true", help="Zufallspasswort erzeugen und ausgeben")
    p_create.add_argument(
        "--force-change", action=argparse.BooleanOptionalAction, default=True,
        help="Passwortwechsel bei erster Anmeldung erzwingen (Standard: ja)",
    )
    p_create.set_defaults(func=cmd_create_user)

    p_reset = sub.add_parser("reset-password", help="Passwort zurücksetzen")
    target = p_reset.add_mutually_exclusive_group(required=True)
    target.add_argument("--username", help="Benutzer per Anmeldename wählen")
    target.add_argument("--id", type=int, help="Benutzer per ID wählen")
    p_reset.add_argument("--password", help="Passwort direkt setzen (sonst Abfrage)")
    p_reset.add_argument("--random", action="store_true", help="Zufallspasswort erzeugen und ausgeben")
    p_reset.add_argument(
        "--force-change", action=argparse.BooleanOptionalAction, default=True,
        help="Passwortwechsel bei nächster Anmeldung erzwingen (Standard: ja)",
    )
    p_reset.set_defaults(func=cmd_reset_password)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

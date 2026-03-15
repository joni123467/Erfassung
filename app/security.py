from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    encoded_salt = base64.b64encode(salt).decode("ascii")
    encoded_digest = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${encoded_salt}${encoded_digest}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, rounds_text, encoded_salt, encoded_digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        salt = base64.b64decode(encoded_salt.encode("ascii"))
        digest = base64.b64decode(encoded_digest.encode("ascii"))
    except (ValueError, TypeError):
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(computed, digest)


def validate_password_strength(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Kennwort muss mindestens 10 Zeichen lang sein")
    if not re.search(r"[A-ZÄÖÜ]", password):
        raise ValueError("Kennwort muss mindestens einen Großbuchstaben enthalten")
    if not re.search(r"[a-zäöüß]", password):
        raise ValueError("Kennwort muss mindestens einen Kleinbuchstaben enthalten")
    if not re.search(r"\d", password):
        raise ValueError("Kennwort muss mindestens eine Zahl enthalten")
    if not re.search(r"[^A-Za-z0-9ÄÖÜäöüß]", password):
        raise ValueError("Kennwort muss mindestens ein Sonderzeichen enthalten")

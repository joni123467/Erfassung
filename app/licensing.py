"""Lizenzierung der Installation gegen den Erfassung-Lizenzserver.

Ablauf
------

1. **Deployment-ID** – beim ersten Start wird eine zufällige, dauerhafte
   Kennung erzeugt (``config/license.json``). Sie enthält keinerlei
   Hardware- oder Personenbezug, ist also nur eine Zufallszahl, die diese
   Installation von einer anderen unterscheidbar macht.
2. **Aktivierung** – der Administrator trägt Serveradresse und
   Aktivierungsschlüssel ein. Die Anwendung ruft
   ``POST /v1/activations`` auf und erhält ein signiertes Lizenzdokument.
   Wiederholte Aufrufe mit derselben Deployment-ID sind idempotent.
3. **Offline-Prüfung** – bei jedem Start und bei jeder Statusabfrage wird das
   gespeicherte Dokument gegen die eingebetteten Ed25519-Schlüssel geprüft
   (:mod:`app.licensing_keys`). Der Lizenzserver muss dafür nicht erreichbar
   sein.

Was durchgesetzt wird
---------------------

Nur die Benutzerzahl (``max_users``) und der Ablauf (``expires_at``). Eine
Installation ohne Lizenz läuft bewusst weiter – ein Update darf einen
bestehenden Betrieb nicht lahmlegen –, zeigt aber im Administrationsbereich
einen Hinweis. Ist die Lizenz abgelaufen oder ungültig, lassen sich keine
neuen Benutzer mehr anlegen; alles Übrige bleibt nutzbar.

Grenze
------

Eine einmalige Aktivierung verhindert weitere reguläre Aktivierungen, aber
nicht das vollständige Klonen einer bereits aktivierten Installation. Das ist
kein vollständiger Kopierschutz und wird auch nicht als solcher dargestellt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import __version__, paths
from .licensing_keys import EMBEDDED_PUBLIC_KEYS, PUBLIC_KEYS_ENV

LOGGER = logging.getLogger(__name__)


def _log(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    """In den Kanal ``license.log`` schreiben, sobald das Logging steht.

    Der Import erfolgt bewusst spät: :mod:`app.licensing` wird sehr früh
    geladen, teilweise noch bevor die Logging-Konfiguration existiert.
    """
    try:
        from . import logging_setup

        logging_setup.log_license(message, level=level, user=user)
    except Exception:  # pragma: no cover - Logging darf nie etwas blockieren
        LOGGER.log(level, message)


#: Produktkennung, die der Lizenzserver für diese Anwendung führt.
PRODUCT_ID = "erfassung"

#: Lizenzserver des Herausgebers – Vorbelegung im Aktivierungsformular.
#: Wer einen eigenen betreibt, trägt dort einfach seine Adresse ein.
DEFAULT_SERVER_URL = "https://lic.dh-cloud.de"

#: Vom Lizenzserver unterstützte Dokumentversion.
SUPPORTED_SCHEMA_VERSION = 1

SIGNATURE_FIELD = "signature"

_LICENSE_PATH = paths.CONFIG_DIR / "license.json"

#: Zeitlimit für jeden Aufruf des Lizenzservers (Verbindung + Antwort).
HTTP_TIMEOUT_SECONDS = 15.0

#: Abstand der selbsttätigen Nachfrage beim Lizenzserver.
CHECK_INTERVAL_HOURS = 24

#: Übergangsfrist nach einer gemeldeten Sperre. Erst danach werden die
#: lizenzpflichtigen Bereiche geschlossen – Stempeln bleibt immer möglich,
#: damit keine Arbeitszeit verloren geht.
GRACE_PERIOD_DAYS = 14

# --- Funktionsbausteine ----------------------------------------------------

#: Zubuchbare Bausteine. Was hier **nicht** steht, gehört zur Basis und ist in
#: jeder Lizenz enthalten: Stempeln, eigene Zeitübersicht, Benutzer- und
#: Rollenverwaltung, Sicherungen.
FEATURES: dict[str, str] = {
    "orders": "Aufträge & Firmen",
    "vacation": "Urlaubsplanung",
    "reports": "Auswertungen & Exporte",
    "terminals": "RFID-Terminals",
}

# --- Zustände --------------------------------------------------------------

STATUS_UNLICENSED = "unlicensed"
STATUS_VALID = "valid"
STATUS_EXPIRED = "expired"
STATUS_INVALID = "invalid"

STATUS_LABELS = {
    STATUS_UNLICENSED: "Nicht lizenziert",
    STATUS_VALID: "Lizenziert",
    STATUS_EXPIRED: "Abgelaufen",
    STATUS_INVALID: "Ungültig",
}


class LicenseError(RuntimeError):
    """Fehler bei Aktivierung oder Prüfung – die Meldung ist für Menschen."""


# --- Kanonische Form und Signaturprüfung -----------------------------------

def canonical_json(document: dict[str, Any]) -> bytes:
    """Deterministische Serialisierung – identisch zum Lizenzserver.

    Sortierte Schlüssel, keine Leerzeichen, kein ASCII-Escaping. Weicht diese
    Funktion auch nur um ein Zeichen ab, schlägt jede Signaturprüfung fehl.
    """
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def signing_payload(document: dict[str, Any]) -> bytes:
    """Signierte Bytes: das Dokument ohne das Feld ``signature``."""
    return canonical_json({k: v for k, v in document.items() if k != SIGNATURE_FIELD})


def _b64u_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def embedded_public_keys() -> dict[str, str]:
    """Vom Herausgeber mitgelieferte Schlüssel, optional per Umgebung ersetzt."""
    override = os.environ.get(PUBLIC_KEYS_ENV)
    if override:
        try:
            parsed = json.loads(override)
        except json.JSONDecodeError:
            LOGGER.warning("%s enthält kein gültiges JSON – wird ignoriert.", PUBLIC_KEYS_ENV)
            return dict(EMBEDDED_PUBLIC_KEYS)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
        LOGGER.warning("%s muss ein JSON-Objekt sein – wird ignoriert.", PUBLIC_KEYS_ENV)
    return dict(EMBEDDED_PUBLIC_KEYS)


def public_keys(config: Optional["LicenseConfig"] = None) -> dict[str, str]:
    """Alle Schlüssel, mit denen ein Lizenzdokument geprüft werden darf.

    Eingebettete Schlüssel des Herausgebers haben Vorrang; ergänzt werden die
    bei der Aktivierung übernommenen Schlüssel des eigenen Lizenzservers.
    """
    keys = dict((config or load_config()).trusted_keys)
    keys.update(embedded_public_keys())
    return keys


def fingerprint(pem: str) -> str:
    """``SHA256:<vier Gruppen>`` – identisch zum Lizenzserver.

    Damit lässt sich mit bloßem Auge abgleichen, ob diese Installation den
    richtigen Lizenzserver erwischt hat.
    """
    digest = hashlib.sha256(pem.strip().encode("ascii")).hexdigest()
    return "SHA256:" + ":".join(digest[i : i + 4] for i in range(0, 16, 4)).upper()


def _load_public_key(pem: str) -> Optional[Ed25519PublicKey]:
    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        LOGGER.error("Hinterlegter Prüfschlüssel ist unbrauchbar: %s", exc)
        return None
    return key if isinstance(key, Ed25519PublicKey) else None


def verify_signature(document: dict[str, Any], keys: Optional[dict[str, str]] = None) -> bool:
    """Signatur des Dokuments gegen den zur ``key_id`` passenden Schlüssel prüfen."""
    available = public_keys() if keys is None else keys
    key_id = document.get("key_id")
    signature = document.get(SIGNATURE_FIELD)
    if not isinstance(key_id, str) or not isinstance(signature, str):
        return False
    pem = available.get(key_id)
    if not pem:
        return False
    public_key = _load_public_key(pem)
    if public_key is None:
        return False
    try:
        public_key.verify(_b64u_decode(signature), signing_payload(document))
    except (InvalidSignature, ValueError):
        return False
    return True


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """RFC-3339-Zeitstempel des Lizenzdokuments lesen (immer mit Zeitzone)."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- Persistenz ------------------------------------------------------------

@dataclass
class LicenseConfig:
    """Inhalt von ``config/license.json``.

    Der Aktivierungsschlüssel wird hier abgelegt, damit die Installation ihre
    Lizenz ohne erneute Eingabe nachprüfen kann. Er erscheint nie in der
    Oberfläche, nie im Log und nie in einem Einstellungsexport – ausgegeben
    wird ausschließlich die maskierte Form (:func:`masked_activation_key`).
    """

    deployment_id: str = ""
    server_url: str = ""
    activation_key: str = ""
    document: dict[str, Any] = field(default_factory=dict)
    activated_at: str = ""
    last_checked_at: str = ""
    #: ``{key_id: PEM}`` – bei der ersten Aktivierung vom Lizenzserver
    #: übernommen und danach unveränderlich (siehe :func:`adopt_public_keys`).
    trusted_keys: dict[str, str] = field(default_factory=dict)
    #: Vom Lizenzserver gemeldete Sperre: ``suspended``, ``revoked`` oder
    #: ``expired``. Leer, solange die Lizenz gilt.
    blocked_status: str = ""
    #: Zeitpunkt der **ersten** Sperrmeldung – Beginn der Übergangsfrist.
    blocked_since: str = ""
    #: Klartextbegründung des Servers für die Anzeige.
    blocked_reason: str = ""
    #: Letzter erfolgreicher Kontakt zum Lizenzserver (beliebige Antwort).
    last_contact_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "server_url": self.server_url,
            "activation_key": self.activation_key,
            "document": self.document,
            "activated_at": self.activated_at,
            "last_checked_at": self.last_checked_at,
            "trusted_keys": self.trusted_keys,
            "blocked_status": self.blocked_status,
            "blocked_since": self.blocked_since,
            "blocked_reason": self.blocked_reason,
            "last_contact_at": self.last_contact_at,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "LicenseConfig":
        config = cls()
        if not isinstance(payload, dict):
            return config
        config.deployment_id = str(payload.get("deployment_id") or "")
        config.server_url = str(payload.get("server_url") or "")
        config.activation_key = str(payload.get("activation_key") or "")
        document = payload.get("document")
        config.document = document if isinstance(document, dict) else {}
        config.activated_at = str(payload.get("activated_at") or "")
        config.last_checked_at = str(payload.get("last_checked_at") or "")
        trusted = payload.get("trusted_keys")
        config.trusted_keys = (
            {str(k): str(v) for k, v in trusted.items()} if isinstance(trusted, dict) else {}
        )
        config.blocked_status = str(payload.get("blocked_status") or "")
        config.blocked_since = str(payload.get("blocked_since") or "")
        config.blocked_reason = str(payload.get("blocked_reason") or "")
        config.last_contact_at = str(payload.get("last_contact_at") or "")
        return config


def _config_path() -> Path:
    # paths.CONFIG_DIR wird beim Import festgelegt; Tests setzen die Umgebung
    # vorher, deshalb genügt der Modulwert.
    return _LICENSE_PATH


def load_config() -> LicenseConfig:
    path = _config_path()
    if not path.exists():
        return LicenseConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Lizenzdatei %s ist unlesbar: %s", path, exc)
        return LicenseConfig()
    return LicenseConfig.from_dict(payload)


def save_config(config: LicenseConfig) -> None:
    """Speichern mit engen Dateirechten – die Datei enthält den Schlüssel."""
    path = _config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - hängt von der Umgebung ab
        raise LicenseError(f"Konfigurationsordner nicht beschreibbar: {exc}") from exc
    payload = json.dumps(config.to_dict(), indent=2, sort_keys=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:  # pragma: no cover - hängt von der Umgebung ab
        raise LicenseError(f"Lizenzdatei nicht schreibbar: {exc}") from exc


def harden_config_permissions() -> None:
    """Dateirechte der Lizenzdatei auf 0600 setzen, falls sie abweichen.

    Wird nach einem Restore aufgerufen: Beim Auspacken eines Archivs erhält
    ``license.json`` die Standardrechte, obwohl sie den Aktivierungsschlüssel
    enthält.
    """
    path = _config_path()
    try:
        if path.exists() and (path.stat().st_mode & 0o777) != 0o600:
            path.chmod(0o600)
    except OSError as exc:  # pragma: no cover - hängt von der Umgebung ab
        _log(
            f"Dateirechte der Lizenzdatei konnten nicht gesetzt werden: {exc}",
            level=logging.WARNING,
        )


def deployment_id() -> str:
    """Dauerhafte Kennung dieser Installation; wird bei Bedarf erzeugt.

    Format ``erfassung-<32 Hexzeichen>``: rein zufällig, ohne Hardwarebezug
    und passend zum Muster, das der Lizenzserver erwartet.
    """
    config = load_config()
    if config.deployment_id:
        return config.deployment_id
    config.deployment_id = f"erfassung-{secrets.token_hex(16)}"
    save_config(config)
    _log("Deployment-ID für die Lizenzierung erzeugt.")
    return config.deployment_id


def masked_activation_key(key: str) -> str:
    """Nur die letzten vier Zeichen zeigen – für Oberfläche und Log."""
    cleaned = (key or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= 4:
        return "•" * len(cleaned)
    return "••••-" + cleaned[-4:]


# --- Status ----------------------------------------------------------------

@dataclass
class LicenseStatus:
    """Ergebnis der Offline-Prüfung – frei von Geheimnissen."""

    status: str = STATUS_UNLICENSED
    reason: str = ""
    license_id: str = ""
    customer_name: str = ""
    edition: str = ""
    product_id: str = ""
    max_users: int = 0
    features: list[str] = field(default_factory=list)
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    key_id: str = ""
    deployment_id: str = ""
    server_url: str = ""
    activated_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    activation_key_masked: str = ""
    users_in_use: int = 0
    #: Fingerprint des Schlüssels, mit dem geprüft wurde – zum Abgleich mit
    #: der Instanzseite des Lizenzservers.
    key_fingerprint: str = ""
    #: Vom Server gemeldete Sperre (``suspended``/``revoked``/``expired``).
    blocked_status: str = ""
    #: Beginn der Übergangsfrist.
    blocked_since: Optional[datetime] = None
    #: Begründung des Servers.
    blocked_reason: str = ""
    #: Letzter erfolgreicher Kontakt zum Lizenzserver.
    last_contact_at: Optional[datetime] = None

    @property
    def label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def is_valid(self) -> bool:
        return self.status == STATUS_VALID

    @property
    def is_configured(self) -> bool:
        return self.status != STATUS_UNLICENSED

    @property
    def unlimited_users(self) -> bool:
        """``max_users = 0`` bedeutet im Lizenzdokument „unbegrenzt“."""
        return self.max_users <= 0

    @property
    def days_until_expiry(self) -> Optional[int]:
        if self.expires_at is None:
            return None
        return (self.expires_at - _utcnow()).days

    @property
    def expires_soon(self) -> bool:
        remaining = self.days_until_expiry
        return remaining is not None and 0 <= remaining <= 30

    @property
    def users_remaining(self) -> Optional[int]:
        if self.unlimited_users:
            return None
        return max(self.max_users - self.users_in_use, 0)

    @property
    def is_blocked(self) -> bool:
        """Hat der Lizenzserver diese Installation gesperrt gemeldet?"""
        return bool(self.blocked_status)

    @property
    def grace_days_left(self) -> Optional[int]:
        """Verbleibende Tage der Übergangsfrist; ``None`` ohne Sperre."""
        if not self.blocked_since:
            return None
        used = (_utcnow() - self.blocked_since).total_seconds() / 86400
        return max(0, int(GRACE_PERIOD_DAYS - used) + (1 if used % 1 else 0))

    @property
    def grace_expired(self) -> bool:
        """Ist die Übergangsfrist abgelaufen und greift die Sperre?"""
        remaining = self.grace_days_left
        return remaining is not None and remaining <= 0

    @property
    def features_enforced(self) -> bool:
        """Werden Funktionsbausteine überhaupt durchgesetzt?

        Nur mit gültiger Lizenz. Eine Installation ohne Lizenz bleibt bewusst
        offen – ein Update darf einen laufenden Betrieb nicht beschneiden.
        """
        return self.status == STATUS_VALID

    def has_feature(self, name: str) -> bool:
        """Ist dieser Baustein nutzbar?

        Ohne Lizenz ist alles offen; mit gültiger Lizenz entscheidet das
        Dokument. Nach abgelaufener Übergangsfrist einer Sperre ist alles
        Zubuchbare zu.
        """
        if self.grace_expired:
            return False
        if not self.features_enforced:
            return True
        return name in self.features
    def to_dict(self) -> dict[str, Any]:
        """Für die API – ohne Aktivierungsschlüssel und ohne Signatur."""

        def stamp(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if value else None

        return {
            "status": self.status,
            "label": self.label,
            "reason": self.reason,
            "license_id": self.license_id,
            "customer_name": self.customer_name,
            "edition": self.edition,
            "product_id": self.product_id,
            "max_users": self.max_users,
            "unlimited_users": self.unlimited_users,
            "users_in_use": self.users_in_use,
            "users_remaining": self.users_remaining,
            "features": list(self.features),
            "issued_at": stamp(self.issued_at),
            "expires_at": stamp(self.expires_at),
            "days_until_expiry": self.days_until_expiry,
            "key_id": self.key_id,
            "key_fingerprint": self.key_fingerprint,
            "blocked_status": self.blocked_status,
            "blocked_reason": self.blocked_reason,
            "blocked_since": stamp(self.blocked_since),
            "grace_days_left": self.grace_days_left,
            "grace_expired": self.grace_expired,
            "last_contact_at": stamp(self.last_contact_at),
            "deployment_id": self.deployment_id,
            "server_url": self.server_url,
            "activated_at": stamp(self.activated_at),
            "last_checked_at": stamp(self.last_checked_at),
        }


def _status_from_document(
    document: dict[str, Any], config: LicenseConfig, *, expected_deployment: str
) -> LicenseStatus:
    status = LicenseStatus(
        deployment_id=expected_deployment,
        server_url=config.server_url,
        activated_at=_parse_timestamp(config.activated_at),
        last_checked_at=_parse_timestamp(config.last_checked_at),
        activation_key_masked=masked_activation_key(config.activation_key),
        blocked_status=config.blocked_status,
        blocked_since=_parse_timestamp(config.blocked_since),
        blocked_reason=config.blocked_reason,
        last_contact_at=_parse_timestamp(config.last_contact_at),
    )
    status.license_id = str(document.get("license_id") or "")
    status.customer_name = str(document.get("customer_name") or "")
    status.edition = str(document.get("edition") or "")
    status.product_id = str(document.get("product_id") or "")
    status.key_id = str(document.get("key_id") or "")
    try:
        status.max_users = int(document.get("max_users") or 0)
    except (TypeError, ValueError):
        status.max_users = 0
    features = document.get("features")
    status.features = sorted(str(item) for item in features) if isinstance(features, list) else []
    status.issued_at = _parse_timestamp(document.get("issued_at"))
    status.expires_at = _parse_timestamp(document.get("expires_at"))

    schema_version = document.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        status.status = STATUS_INVALID
        status.reason = (
            f"Das Lizenzdokument hat Version {schema_version!r}; diese Anwendung "
            f"unterstützt Version {SUPPORTED_SCHEMA_VERSION}. Bitte die Anwendung aktualisieren."
        )
        return status
    if not verify_signature(document, public_keys(config)):
        status.status = STATUS_INVALID
        status.reason = (
            "Die Signatur des Lizenzdokuments ist ungültig oder der Schlüssel ist unbekannt."
        )
        return status
    if status.product_id != PRODUCT_ID:
        status.status = STATUS_INVALID
        status.reason = f"Das Lizenzdokument gehört zum Produkt „{status.product_id}“."
        return status
    if str(document.get("deployment_id") or "") != expected_deployment:
        status.status = STATUS_INVALID
        status.reason = (
            "Das Lizenzdokument wurde für eine andere Installation ausgestellt. "
            "Nach einem Serverwechsel bitte erneut aktivieren."
        )
        return status
    if status.expires_at is not None and status.expires_at <= _utcnow():
        status.status = STATUS_EXPIRED
        status.reason = "Die Lizenz ist abgelaufen."
        return status

    pem = public_keys(config).get(status.key_id)
    if pem:
        status.key_fingerprint = fingerprint(pem)
    status.status = STATUS_VALID
    return status


def current_status(db: Any = None) -> LicenseStatus:
    """Gespeicherte Lizenz offline prüfen. Ohne Netzzugriff.

    Wird eine Datenbanksitzung übergeben, enthält das Ergebnis zusätzlich die
    aktuell belegten Benutzerplätze.
    """
    config = load_config()
    expected = config.deployment_id or deployment_id()
    if not config.document:
        status = LicenseStatus(
            status=STATUS_UNLICENSED,
            reason="Für diese Installation ist keine Lizenz hinterlegt.",
            deployment_id=expected,
            server_url=config.server_url,
        )
    else:
        status = _status_from_document(config.document, config, expected_deployment=expected)
    if db is not None:
        status.users_in_use = count_users(db)
    return status


def count_users(db: Any) -> int:
    """Anzahl der Benutzerkonten, die auf die Lizenz angerechnet werden."""
    from . import models

    return int(db.query(models.User).count() or 0)


def license_request_url(db: Any = None) -> str:
    """Adresse für „Lizenz beantragen oder erweitern".

    Führt auf die Anfrageseite des hinterlegten Lizenzservers und nimmt die
    Angaben mit, die der Herausgeber ohnehin braucht: Deployment-ID, aktuelle
    Lizenz und die tatsächlich belegten Benutzerplätze. Es werden **keine**
    personenbezogenen Daten und **kein** Aktivierungsschlüssel übertragen –
    die Adresse landet nur im Browser des Administrators.
    """
    from urllib.parse import urlencode

    config = load_config()
    status = current_status(db)
    base = (config.server_url or DEFAULT_SERVER_URL).rstrip("/")
    params = {
        "product_id": PRODUCT_ID,
        "deployment_id": status.deployment_id,
        "app_version": __version__,
        "users_in_use": str(status.users_in_use),
    }
    if status.license_id:
        params["license_id"] = status.license_id
    if not status.unlimited_users:
        params["current_max_users"] = str(status.max_users)
    return f"{base}/request?{urlencode(params)}"


def has_feature(name: str, status: Optional[LicenseStatus] = None) -> bool:
    """Ist dieser Funktionsbaustein nutzbar?

    Ohne hinterlegte Lizenz ist alles offen – ein Update darf einen laufenden
    Betrieb nicht beschneiden. Mit gültiger Lizenz entscheidet das Dokument.
    Nach abgelaufener Übergangsfrist einer Sperre ist alles Zubuchbare zu.
    """
    return (status or current_status()).has_feature(name)


# --- Durchsetzung ----------------------------------------------------------

def user_limit_error(db: Any, *, additional: int = 1) -> Optional[str]:
    """Meldung, falls ``additional`` weitere Benutzer nicht erlaubt sind.

    ``None`` heißt: anlegen ist erlaubt. Eine Installation ohne Lizenz wird
    absichtlich nicht blockiert – siehe Modulbeschreibung.
    """
    status = current_status(db)
    if status.status == STATUS_UNLICENSED:
        return None
    if status.status == STATUS_EXPIRED:
        return (
            "Die Lizenz ist abgelaufen. Es lassen sich keine neuen Benutzer anlegen, "
            "bis die Lizenz erneuert wurde."
        )
    if status.status == STATUS_INVALID:
        return (
            "Die hinterlegte Lizenz ist ungültig. Es lassen sich keine neuen Benutzer "
            "anlegen, bis die Installation erneut aktiviert wurde."
        )
    if status.unlimited_users:
        return None
    if status.users_in_use + additional > status.max_users:
        return (
            f"Die Lizenz erlaubt {status.max_users} Benutzer; "
            f"{status.users_in_use} sind bereits angelegt."
        )
    return None


# --- Lizenzserver ----------------------------------------------------------

def normalize_server_url(value: str) -> str:
    """Serveradresse säubern und auf ``http(s)`` festnageln."""
    url = (value or "").strip().rstrip("/")
    if not url:
        raise LicenseError("Bitte die Adresse des Lizenzservers angeben.")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if url.startswith("http://") and not _is_local(url):
        _log(f"Lizenzserver ohne HTTPS angesprochen: {url}", level=logging.WARNING)
    return url


def _is_local(url: str) -> bool:
    return any(host in url for host in ("://localhost", "://127.0.0.1", "://[::1]"))


def _post(url: str, payload: dict[str, Any]) -> httpx.Response:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            return client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise LicenseError(f"Der Lizenzserver ist nicht erreichbar: {exc}") from exc


def _raise_for_activation(response: httpx.Response) -> None:
    """Antwort des Lizenzservers in eine verständliche Meldung übersetzen."""
    if response.status_code == 403:
        raise LicenseError(
            "Die Aktivierung wurde abgelehnt. Mögliche Gründe: falscher oder bereits "
            "vollständig genutzter Aktivierungsschlüssel, gesperrte oder abgelaufene "
            "Lizenz. Bitte den Support kontaktieren."
        )
    if response.status_code == 429:
        raise LicenseError(
            "Zu viele Aktivierungsversuche. Bitte einige Minuten warten und erneut versuchen."
        )
    if response.status_code == 422:
        raise LicenseError("Der Lizenzserver hat die Anfrage abgelehnt (ungültige Eingabe).")
    raise LicenseError(f"Unerwartete Antwort des Lizenzservers (HTTP {response.status_code}).")


def fetch_public_keys(server_url: str) -> dict[str, str]:
    """Öffentliche Prüfschlüssel des Lizenzservers abholen.

    Ein öffentlicher Schlüssel ist kein Geheimnis – mit ihm lassen sich
    Signaturen nur prüfen, nie erzeugen. Der Abruf ist deshalb unauthentifiziert.
    """
    url = normalize_server_url(server_url)
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(f"{url}/v1/instance/public-key")
    except httpx.HTTPError as exc:
        raise LicenseError(f"Der Lizenzserver ist nicht erreichbar: {exc}") from exc
    if response.status_code != 200:
        raise LicenseError(
            "Der Lizenzserver hat keinen Prüfschlüssel geliefert "
            f"(HTTP {response.status_code})."
        )
    try:
        payload = response.json()
        key_id = str(payload["key_id"])
        pem = str(payload["public_key"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LicenseError("Der Lizenzserver hat eine unerwartete Antwort geschickt.") from exc
    if _load_public_key(pem) is None:
        raise LicenseError("Der Lizenzserver hat einen unbrauchbaren Prüfschlüssel geliefert.")
    return {key_id: pem}


def adopt_public_keys(config: LicenseConfig, offered: dict[str, str]) -> dict[str, str]:
    """Angebotene Schlüssel übernehmen – aber niemals einen bestehenden ersetzen.

    Beim ersten Kontakt wird dem Server vertraut (wie bei SSH). Danach ist der
    Schlüssel je ``key_id`` unveränderlich: Wer sich später mit einem anderen
    Schlüssel für dieselbe ``key_id`` ausgibt, wird abgewiesen. Ein Angreifer,
    der den Server austauscht, kann damit keine eigenen Lizenzen unterschieben.

    Eine echte Schlüsselrotation läuft über eine **neue** ``key_id`` – die wird
    anstandslos ergänzt.
    """
    trusted = dict(config.trusted_keys)
    embedded = embedded_public_keys()
    for key_id, pem in offered.items():
        known = trusted.get(key_id) or embedded.get(key_id)
        if known and known.strip() != pem.strip():
            raise LicenseError(
                f"Der Lizenzserver weist sich für „{key_id}“ mit einem anderen "
                f"Prüfschlüssel aus als bisher (bekannt: {fingerprint(known)}, "
                f"angeboten: {fingerprint(pem)}). Die Aktivierung wurde "
                "abgebrochen. Das ist zu erwarten, wenn der Lizenzserver neu "
                "aufgesetzt wurde – dann bitte die Lizenz hier entfernen und "
                "neu aktivieren. Andernfalls den Herausgeber kontaktieren."
            )
        if not known:
            trusted[key_id] = pem
    return trusted


def activate(server_url: str, activation_key: str) -> LicenseStatus:
    """Installation aktivieren und das signierte Dokument ablegen.

    Der Aufruf ist idempotent: Dieselbe Deployment-ID verbraucht keinen
    weiteren Aktivierungsplatz, sodass sich die Lizenz beliebig oft
    nachprüfen lässt.
    """
    key = (activation_key or "").strip()
    if not key:
        raise LicenseError("Bitte den Aktivierungsschlüssel eingeben.")
    url = normalize_server_url(server_url)
    config = load_config()
    if not config.deployment_id:
        deployment_id()  # erzeugt und speichert die Kennung
        config = load_config()

    # Prüfschlüssel zuerst: Ohne ihn ließe sich das Lizenzdokument gleich
    # darauf gar nicht prüfen. Ein Wechsel des Schlüssels bricht hier ab,
    # bevor irgendetwas gespeichert wird.
    trusted = adopt_public_keys(config, fetch_public_keys(url))

    response = _post(
        f"{url}/v1/activations",
        {
            "activation_key": key,
            "product_id": PRODUCT_ID,
            "deployment_id": config.deployment_id,
            "app_version": __version__,
        },
    )
    if response.status_code != 200:
        _raise_for_activation(response)

    try:
        document = response.json()["license"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LicenseError("Der Lizenzserver hat eine unerwartete Antwort geschickt.") from exc
    if not isinstance(document, dict):
        raise LicenseError("Der Lizenzserver hat eine unerwartete Antwort geschickt.")

    # Erst prüfen, dann speichern: Ein Dokument, das die Offline-Prüfung nicht
    # besteht, hilft niemandem und würde die Installation nur blockieren.
    candidate = LicenseConfig(
        deployment_id=config.deployment_id,
        server_url=url,
        activation_key=key,
        document=document,
        activated_at=config.activated_at or _utcnow().isoformat(),
        last_checked_at=_utcnow().isoformat(),
        trusted_keys=trusted,
    )
    status = _status_from_document(
        document, candidate, expected_deployment=config.deployment_id
    )
    if status.status == STATUS_INVALID:
        raise LicenseError(f"Das erhaltene Lizenzdokument ist nicht verwendbar: {status.reason}")

    save_config(candidate)
    _log(
        f"Lizenz aktiviert: license_id={status.license_id or '-'} "
        f"status={status.status} Schlüssel={masked_activation_key(key)}"
    )
    return status


def refresh_from_server() -> tuple[bool, str]:
    """Zustand beim Lizenzserver nachfragen. Gibt ``(erreicht, Meldung)``.

    Der Leitgedanke: **Ein unerreichbarer Server darf niemals sperren.** Nur
    eine ausdrückliche Sperrmeldung startet die Übergangsfrist; jede Störung
    lässt die gespeicherte Lizenz unverändert weiterlaufen.

    Meldet der Server wieder ``active``, verfällt eine laufende Frist sofort
    und das frische Dokument ersetzt das alte – so wirken Änderungen an
    Benutzerzahl und Bausteinen ohne Zutun des Kunden.
    """
    config = load_config()
    if not config.server_url or not config.activation_key or not config.document:
        return False, "Keine Lizenz hinterlegt."

    url = normalize_server_url(config.server_url)
    try:
        response = _post(
            f"{url}/v1/activations/state",
            {
                "activation_key": config.activation_key,
                "product_id": PRODUCT_ID,
                "deployment_id": config.deployment_id,
            },
        )
    except LicenseError as exc:
        # Genau hier endet der Ausfall: nichts ändern, nichts sperren.
        _log(f"Lizenzserver nicht erreichbar – Lizenz gilt unverändert weiter: {exc}")
        return False, str(exc)

    if response.status_code == 404:
        # Älterer Lizenzserver ohne Zustandsendpunkt: kein Grund zur Sorge.
        _log("Lizenzserver kennt die Zustandsabfrage nicht – Lizenz gilt weiter.")
        return False, "Der Lizenzserver unterstützt die regelmäßige Prüfung nicht."
    if response.status_code != 200:
        _log(
            f"Zustandsabfrage beantwortet mit HTTP {response.status_code} – "
            "Lizenz gilt unverändert weiter.",
            level=logging.WARNING,
        )
        return False, f"Unerwartete Antwort des Lizenzservers (HTTP {response.status_code})."

    try:
        payload = response.json()
        state = str(payload["status"])
    except (ValueError, KeyError, TypeError):
        return False, "Der Lizenzserver hat eine unerwartete Antwort geschickt."

    config = load_config()  # frisch lesen, es könnte sich zwischenzeitlich geändert haben
    config.last_contact_at = _utcnow().isoformat()

    if state == "active":
        document = payload.get("license")
        if isinstance(document, dict):
            candidate = LicenseConfig(**{**config.to_dict(), "document": document})
            checked = _status_from_document(
                document, candidate, expected_deployment=config.deployment_id
            )
            if checked.status == STATUS_INVALID:
                _log(
                    f"Frisches Lizenzdokument abgelehnt: {checked.reason}",
                    level=logging.WARNING,
                )
                save_config(config)
                return True, checked.reason
            config.document = document
            config.last_checked_at = _utcnow().isoformat()
        if config.blocked_status:
            _log("Lizenz ist wieder freigegeben – Übergangsfrist beendet.")
        config.blocked_status = ""
        config.blocked_since = ""
        config.blocked_reason = ""
        save_config(config)
        return True, "Lizenz bestätigt."

    if state in ("suspended", "revoked", "expired"):
        reason = str(payload.get("reason") or "")
        if not config.blocked_status:
            # Erste Meldung: ab hier läuft die Übergangsfrist.
            config.blocked_since = _utcnow().isoformat()
            _log(
                f"Lizenz vom Server als „{state}“ gemeldet. Übergangsfrist von "
                f"{GRACE_PERIOD_DAYS} Tagen beginnt.",
                level=logging.WARNING,
            )
        config.blocked_status = state
        config.blocked_reason = reason
        save_config(config)
        return True, reason or f"Lizenz gesperrt ({state})."

    save_config(config)
    return True, f"Unbekannte Antwort des Lizenzservers: {state!r}"


def due_for_check(status: Optional[LicenseStatus] = None) -> bool:
    """Ist die nächste selbsttätige Nachfrage fällig?"""
    state = status or current_status()
    if not state.is_configured:
        return False
    last = state.last_contact_at or state.last_checked_at
    if last is None:
        return True
    return (_utcnow() - last).total_seconds() >= CHECK_INTERVAL_HOURS * 3600


def recheck() -> LicenseStatus:
    """Lizenz beim Server nachprüfen – mit den gespeicherten Angaben."""
    config = load_config()
    if not config.server_url or not config.activation_key:
        raise LicenseError(
            "Für eine erneute Prüfung fehlen Serveradresse und Aktivierungsschlüssel. "
            "Bitte die Installation erneut aktivieren."
        )
    return activate(config.server_url, config.activation_key)


def deactivate() -> None:
    """Aktivierungsplatz freigeben und die lokale Lizenz entfernen.

    Der Platz wird nur dann beim Server freigegeben, wenn dieser erreichbar
    ist; lokal wird die Lizenz in jedem Fall entfernt, damit ein Serverwechsel
    auch offline möglich bleibt. Die Deployment-ID bleibt erhalten.
    """
    config = load_config()
    if config.server_url and config.activation_key and config.deployment_id:
        try:
            response = _post(
                f"{config.server_url}/v1/activations/deactivate",
                {
                    "activation_key": config.activation_key,
                    "product_id": PRODUCT_ID,
                    "deployment_id": config.deployment_id,
                },
            )
            if response.status_code not in (200, 204):
                _log(
                    f"Lizenzserver meldete beim Freigeben HTTP {response.status_code}.",
                    level=logging.WARNING,
                )
        except LicenseError as exc:
            _log(
                f"Aktivierungsplatz konnte nicht freigegeben werden: {exc}",
                level=logging.WARNING,
            )

    save_config(
        LicenseConfig(
            deployment_id=config.deployment_id,
            server_url=config.server_url,
            # Übernommene Prüfschlüssel bleiben erhalten: Sie sind kein
            # Geheimnis, und ein späterer Schlüsselwechsel fällt so weiterhin auf.
            trusted_keys=config.trusted_keys,
        )
    )
    _log("Lizenz lokal entfernt.")


__all__ = [
    "LicenseConfig",
    "LicenseError",
    "LicenseStatus",
    "DEFAULT_SERVER_URL",
    "PRODUCT_ID",
    "STATUS_EXPIRED",
    "STATUS_INVALID",
    "STATUS_UNLICENSED",
    "STATUS_VALID",
    "activate",
    "canonical_json",
    "count_users",
    "current_status",
    "deactivate",
    "due_for_check",
    "adopt_public_keys",
    "deployment_id",
    "embedded_public_keys",
    "fetch_public_keys",
    "fingerprint",
    "harden_config_permissions",
    "has_feature",
    "license_request_url",
    "load_config",
    "masked_activation_key",
    "normalize_server_url",
    "public_keys",
    "recheck",
    "refresh_from_server",
    "save_config",
    "signing_payload",
    "user_limit_error",
    "verify_signature",
]

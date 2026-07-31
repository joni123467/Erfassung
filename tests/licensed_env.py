"""Eine vollwertige Testlizenz für alle Tests, die nicht die Lizenz prüfen.

Seit 0.12.1 schaltet ausschließlich das Lizenzdokument die zubuchbaren
Bausteine frei – ohne Lizenz sind Aufträge, Urlaubsplanung, Auswertungen und
Terminals gesperrt. Die Fachtests dieser Bereiche sollen weiterhin die
Fachlogik prüfen und nicht die Lizenzierung; sie rufen deshalb einmal
:func:`activate` auf und arbeiten danach als vollständig lizenzierte
Installation.

Verwendung in der App-Fixture einer Testdatei, **nach** dem Import von
``app.main``::

    import licensed_env

    import app.main as main

    licensed_env.activate()

Die Lizenzprüfung selbst wird in ``test_v0110.py``, ``test_v0120.py`` und
``test_v0121.py`` geprüft – die legen ihre Lizenzen selbst an und benutzen
dieses Modul nicht.

Der hier erzeugte Schlüssel entsteht beim Import und lebt nur im Testprozess.
Er landet als ``trusted_keys`` in der Lizenzdatei der jeweiligen Testinstanz,
also genau dort, wo bei einer echten Installation der bei der Aktivierung
übernommene Schlüssel des Lizenzservers steht. Eine Umgebungsvariable braucht
es dafür nicht.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_ID = "test-suite"

_PRIVATE_KEY = Ed25519PrivateKey.generate()
PUBLIC_PEM = _PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode("ascii")

#: Alle zubuchbaren Bausteine – der Normalfall für einen Fachtest.
ALL_FEATURES = ("orders", "vacation", "reports", "terminals")


def _sign(document: dict) -> dict:
    payload = json.dumps(
        {key: value for key, value in document.items() if key != "signature"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    signed = dict(document)
    signed["signature"] = (
        base64.urlsafe_b64encode(_PRIVATE_KEY.sign(payload)).decode("ascii").rstrip("=")
    )
    return signed


def document(deployment_id: str, *, features=None, max_users: int = 0) -> dict:
    """Ein gültig signiertes Lizenzdokument für diese Installation."""
    return _sign(
        {
            "schema_version": 1,
            "license_id": "ERF-TESTSUITE",
            "customer_name": "Testlauf",
            "product_id": "erfassung",
            "deployment_id": deployment_id,
            "edition": "test",
            "features": sorted(ALL_FEATURES if features is None else features),
            "max_users": max_users,  # 0 = unbegrenzt
            "issued_at": datetime.now(tz=timezone.utc).replace(
                microsecond=0
            ).isoformat().replace("+00:00", "Z"),
            "expires_at": None,
            "key_id": KEY_ID,
        }
    )


def activate(*, features=None, max_users: int = 0) -> None:
    """Diese Installation lizenzieren. Nach dem Import von ``app.main``."""
    from app import licensing

    deployment_id = licensing.deployment_id()
    licensing.save_config(
        licensing.LicenseConfig(
            deployment_id=deployment_id,
            # Bewusst leer: Ohne eingetragene Adresse greift überall der
            # Standard-Lizenzserver, und Tests, die genau das prüfen (Vorbelegung
            # des Formulars, Anfrage-Adresse), bleiben aussagekräftig.
            server_url="",
            activation_key="ERF-TESTSUITE-0000",
            document=document(deployment_id, features=features, max_users=max_users),
            activated_at=datetime.now(tz=timezone.utc).isoformat(),
            last_checked_at=datetime.now(tz=timezone.utc).isoformat(),
            trusted_keys={KEY_ID: PUBLIC_PEM},
        )
    )

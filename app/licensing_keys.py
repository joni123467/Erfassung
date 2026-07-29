"""Öffentliche Prüfschlüssel des Lizenzservers.

Die Signatur eines Lizenzdokuments wird ausschließlich **offline** gegen die
hier hinterlegten Ed25519-Schlüssel geprüft. Der Lizenzserver muss dafür nicht
erreichbar sein.

Beim Release trägt der Herausgeber seinen öffentlichen Schlüssel in
:data:`EMBEDDED_PUBLIC_KEYS` ein – erzeugt mit::

    python -m app.cli keygen --private-out /run/secrets/license_signing_key.pem

(im Lizenzserver-Repository). Ausgegeben wird das öffentliche PEM; der
**private** Schlüssel verlässt den Lizenzserver nie.

Schlüsselrotation: Der Bezeichner ``key_id`` steht in jedem Lizenzdokument.
Beim Wechsel bleibt der alte Eintrag stehen, bis alle Installationen ein neu
signiertes Dokument erhalten haben – dann erst wird er entfernt.

Für Entwicklung und Tests lassen sich die Schlüssel über die Umgebungsvariable
``ERFASSUNG_LICENSE_PUBLIC_KEYS`` (JSON-Objekt ``{"key_id": "<PEM>"}``)
überschreiben. Dass ein Betreiber der selbstgehosteten Anwendung diese Datei
austauschen kann, ist bekannt und in den Release Notes als Restrisiko
festgehalten: Die Lizenzprüfung schützt vor versehentlicher Mehrfachnutzung,
nicht vor bewusster Manipulation der eigenen Installation.
"""

from __future__ import annotations

#: ``{key_id: öffentliches Ed25519-PEM}``. Leer = keine Lizenzprüfung möglich;
#: die Anwendung meldet dann den Zustand „nicht lizenziert“ und läuft weiter.
EMBEDDED_PUBLIC_KEYS: dict[str, str] = {}

#: Name der Umgebungsvariablen für den Test-/Entwicklungsschlüssel.
PUBLIC_KEYS_ENV = "ERFASSUNG_LICENSE_PUBLIC_KEYS"

__all__ = ["EMBEDDED_PUBLIC_KEYS", "PUBLIC_KEYS_ENV"]

# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.3.8] – 2026-06-11

### Fixed

- **Anmeldung mit „403 – Ungültige Sitzung" repariert (zwei zusammenhängende
  Fehler in der CSRF-Absicherung):**
  1. **Middleware-Reihenfolge:** Starlette wendet Middleware in umgekehrter
     Registrierungsreihenfolge an – die zuletzt registrierte läuft *außen*. Die
     `CSRFMiddleware` war nach der `SessionMiddleware` registriert und lief damit
     *vor* ihr. Beim CSRF-Check war die Session daher noch nicht geladen
     (`scope["session"]` fehlte), sodass **jeder** POST – inklusive `/login` –
     mit `403` abgewiesen wurde. Reihenfolge korrigiert (CSRF zuerst, Session
     zuletzt registriert ⇒ Session läuft außen).
  2. **Request-Body wurde verbraucht:** Die `CSRFMiddleware` (vormals
     `BaseHTTPMiddleware`) las das Formular per `await request.form()`, wodurch
     der Body-Stream geleert wurde und der `/login`-Handler keine Felder mehr
     erhielt (`422 Field required`). Die Middleware ist nun eine **reine
     ASGI-Middleware**, die den Body puffert und über ein frisches
     `receive`-Callable an die Anwendung **weiterreicht**.
  Ergebnis: Anmeldung funktioniert wieder; falsche Zugangsdaten liefern wieder
  die reguläre Fehlermeldung (HTTP 400) statt eines 403, und fehlende/ungültige
  CSRF-Token werden weiterhin korrekt mit 403 abgelehnt.

### Grund der Versionsanhebung

Patch (`0.3.7` → `0.3.8`): Behebung eines kritischen Fehlers, der die Anmeldung
vollständig blockierte. Keine Änderung an Datenmodell oder Geschäftslogik.

## [0.3.7] – 2026-06-11

### Fixed

- **Docker-Image in Portainer deploybar (behebt „error 500" beim Deploy):**
  Der Build (`docker/build-push-action@v6`) hängte standardmäßig
  Provenance-/SBOM-Attestations an das Image. Dadurch wurde das Image als
  **OCI Image Index** veröffentlicht, der zusätzlich ein Attestation-Manifest mit
  `platform: unknown/unknown` enthält. Dieser Zusatz-Eintrag bringt Portainer und
  ältere Docker-/Registry-Tooling beim Deploy zum Fehler („no matching manifest" /
  HTTP 500). Der Workflow erzeugt nun mit `provenance: false`, `sbom: false` und
  explizitem `platforms: linux/amd64` ein **schlankes Single-Platform-Manifest**
  (identisch zu `docker build && docker push`). Das Image `:0.3.7` ist damit ohne
  Sonderbehandlung deploybar.

### Grund der Versionsanhebung

Patch (`0.3.6` → `0.3.7`): reiner Build-/Auslieferungs-Fix. Es wurde kein
Anwendungscode geändert. Eigene Version (statt Überschreiben von `0.3.6`), damit
Portainer/Docker garantiert ein frisches, sauberes Manifest ziehen und kein zuvor
gecachter `0.3.6`-Index verwendet wird.

## [0.3.6] – 2026-06-11

### Hintergrund

Die mobile Oberfläche (`/mobile`) ist bereits seit `0.3.5` eine offline-first PWA
(Service Worker, IndexedDB-Datenhaltung, Offline-Aktionsqueue mit Idempotenz und
Reconnect-Synchronisation). Mit `0.3.6` wird diese PWA produktionshärtend
vervollständigt – minimal-invasiv, ohne Eingriff in die Business-Logik.

### Changed / Fixed

- **Automatische Service-Worker-Versionierung (behebt Stale-Cache-Risiko):**
  Der Cache-Name in `static/sw.js` war fest auf `erfassung-mobile-v0.3.5`
  verdrahtet. Wurde `VERSION` erhöht, ohne die Datei manuell anzupassen, blieb der
  alte Cache aktiv und Clients konnten auf veralteten Assets „hängen bleiben".
  Der Cache-Name wird nun zur Laufzeit aus dem `?v=`-Parameter der
  SW-Registrierung abgeleitet (`new URLSearchParams(self.location.search)`), der
  wiederum aus `app_version` / `VERSION` stammt. Damit erzeugt jede Versionsanhebung
  automatisch einen neuen Cache; der alte wird beim `activate`-Event entfernt.
- **`static/app.js`** registriert den Service Worker jetzt mit der aus
  `import.meta.url` (`?v=…`) ermittelten Version statt mit einer hartcodierten
  Versionsnummer (`?v=0.3.5`).

### Added

- **Manifest vervollständigt** (`static/manifest.webmanifest`): Felder `id`
  (`"/mobile"`), `dir` (`"ltr"`) und `categories` (`["business", "productivity"]`)
  ergänzt. Das verbessert die eindeutige App-Identität (Installierbarkeit/Updates)
  und die Einordnung bei App-Store-/Launcher-Integrationen.
- **Dokumentation:** README um Abschnitte „Updates & Service-Worker-Versionierung"
  und „Installierbarkeit" erweitert; Versionsangabe von `0.1.7` auf `0.3.6`
  korrigiert. Diese Changelog-Datei sowie Release Notes
  (`docs/RELEASE_NOTES_0.3.6.md`) neu angelegt.

### Grund der Versionsanhebung

Patch-Release (`0.3.5` → `0.3.6`): Es handelt sich um Härtung und Vervollständigung
einer bestehenden Funktion (PWA/Offline), nicht um eine neue, brechende oder
umfangreiche Feature-Erweiterung. Es wurden keine bestehenden Endpunkte, Datenmodelle
oder die Business-Logik verändert.

## [0.3.5]

- Offline-first-PWA-Architektur der mobilen Oberfläche (Service Worker,
  IndexedDB, Offline-Queue mit `client_action_id`-Idempotenz,
  Reconnect-Synchronisation, Konfliktbehandlung per State-Replay).

## [0.3.4]

- Fix: HTTP-500 bei `/mobile/sync-data` behoben.

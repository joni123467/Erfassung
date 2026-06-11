# Release Notes – Erfassung 0.3.7

**Alte Version:** 0.3.6
**Neue Version:** 0.3.7
**Datum:** 2026-06-11
**Typ:** Patch (Build-/Auslieferungs-Fix – kein Anwendungscode geändert)

---

## Problem

Das Deployment des Images `:0.3.6` schlug in Portainer mit **HTTP 500** fehl,
während ältere Images problemlos liefen.

## Diagnose

- Der GitHub-Actions-Build (`container-publish.yml`) lief erfolgreich und das Image
  `:0.3.6` wurde nach GHCR gepusht – der Build selbst war **nicht** defekt.
- Inspektion der GHCR-Manifeste zeigte: **alle** Images werden als
  **OCI Image Index** (`application/vnd.oci.image.index.v1+json`) veröffentlicht,
  der neben dem `linux/amd64`-Manifest ein zusätzliches **Attestation-Manifest**
  mit `platform: unknown/unknown` enthält. Ursache: `docker/build-push-action@v6`
  hängt standardmäßig **Provenance-/SBOM-Attestations** an.
- Dieser `unknown/unknown`-Eintrag im Index ist ein bekannter Auslöser für
  Deploy-Fehler in Portainer und älterem Docker-/Registry-Tooling
  („no matching manifest for linux/amd64" bzw. HTTP 500).

## Fix

`.github/workflows/container-publish.yml` – im Schritt „Build and push":

```yaml
platforms: linux/amd64
provenance: false
sbom: false
```

Damit veröffentlicht der Build ein **schlankes Single-Platform-Image-Manifest**
(genau wie `docker build && docker push`) ohne Attestation-Index. Das Image `:0.3.7`
ist dadurch ohne Sonderbehandlung in Portainer deploybar.

## Warum neue Version statt Überschreiben von 0.3.6

Portainer/Docker können das zuvor gezogene (fehlerhafte) `0.3.6`-Manifest gecacht
haben. Eine neue, unveränderliche Tag-Version `0.3.7` erzwingt einen frischen,
sauberen Pull.

## Deployment

In Portainer (Stack/Compose) den Image-Tag auf `0.3.7` setzen:

```yaml
services:
  erfassung:
    image: ghcr.io/joni123467/erfassung:0.3.7
```

Anschließend Stack neu deployen / Image neu ziehen.

## Sofort-Workaround (falls vor dem 0.3.7-Build benötigt)

Ein vorhandenes Image lässt sich auch direkt über das **amd64-Child-Manifest**
(unter Umgehung des Index) deployen, z. B.:

```bash
docker pull ghcr.io/joni123467/erfassung@sha256:b9a724c7c6b716367ec9b5a1f23c9113be8e3864120193ebc32211d84c0f13b8
```

(Das ist das `linux/amd64`-Manifest von `0.3.6`. Lädt dieses fehlerfrei, während der
Tag `0.3.6` fehlschlägt, bestätigt das den Attestation-Index als Ursache.)

## Auswirkungen auf die Anwendung

- **Keine.** Es wurde ausschließlich der Build-/Publish-Workflow angepasst. App-Code,
  Endpunkte, Datenmodell und die PWA-/Offline-Funktionen sind unverändert.

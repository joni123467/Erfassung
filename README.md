# Erfassung

Erfassung ist eine FastAPI-basierte Zeiterfassungsanwendung (Web-App) mit Benutzer-/Gruppenverwaltung, Arbeitszeitbuchungen, Urlaubsverwaltung, Feiertagssynchronisation und Exportfunktionen.

**Version:** `0.3.6`

> Die mobile Oberfläche (`/mobile`) ist eine installierbare, offline-fähige PWA.
> Details siehe Abschnitt [„Mobile Offline-Funktion"](#mobile-offline-funktion-mobile) und [`CHANGELOG.md`](CHANGELOG.md).

## Deployment-Standard (neu)

Der Standardweg ist jetzt vollständig image-basiert:

1. Code nach GitHub pushen
2. GitHub Actions baut das Docker-Image
3. Image wird in die GitHub Container Registry (GHCR) veröffentlicht
4. Portainer deployt dieses GHCR-Image per Stack/Compose

> Portainer baut **nicht** lokal, sondern zieht ein bereits gebautes Image.

## Einstiegspunkt und Laufzeit

- FastAPI-App: `app.main:app`
- Standardport: `8000`
- Container-Startkommando:
  `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Lokale Entwicklung

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker (lokal)

```bash
docker build -t erfassung:0.1.7 .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=sqlite:////app/data/erfassung.db \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  erfassung:0.1.7
```

## GHCR & GitHub Actions

Der Workflow liegt unter `.github/workflows/container-publish.yml` und veröffentlicht nach GHCR.

### Trigger

- Push auf `main`
- Push von Tags `v*` (z. B. `v0.1.7`)
- Manuell über `workflow_dispatch`

### Tags

- Versions-Tag aus `VERSION` (hier `0.1.7`)
- `latest` auf `main`
- Git-Tag (`v0.1.7`)

### Erwartetes Image

Beispiel:

`ghcr.io/OWNER/erfassung:0.1.7`

`OWNER` ist der GitHub-Owner (User oder Organisation) des Repositories.

## Deployment mit Portainer

Für Portainer ist die bereitgestellte `compose.yaml` gedacht. Sie referenziert ein GHCR-Image (ohne lokalen Build).

### Beispiel

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.1.7
    container_name: erfassung
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: sqlite:////app/data/erfassung.db
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
```

## Persistenz (wichtig)

Für produktiven Betrieb sollten folgende Pfade persistent gemountet werden:

- `/app/data` (inkl. SQLite-DB `erfassung.db`)
- `/app/logs`
- `/app/config` (z. B. Integrationskonfigurationen wie TimeMoto)

Optional zusätzlich:

- `.env`-Datei im Stack/Host, falls eigene Umgebungsvariablen genutzt werden

## Was du selbst anpassen musst

- `OWNER` im Image-Namen (`ghcr.io/OWNER/erfassung:0.1.7`)
- optional Image-Name/Tag (`erfassung`, `0.1.7`, `latest`)
- Volume-Hostpfade (`./data`, `./logs`, `./config`)
- ggf. zusätzliche Umgebungsvariablen (z. B. für DB/Integrationen)

## Hinweise zu privaten Repositories

GHCR funktioniert auch mit privaten Repositories. In Portainer muss dann ein Registry-Zugang (PAT mit `read:packages`) hinterlegt werden, damit das private Image gezogen werden kann.

## Mobile Offline-Funktion (`/mobile`)

Die mobile Oberfläche ist als pragmatische **Offline-first-PWA** umgesetzt.

### Was offline funktioniert

- Laden der mobilen Seite `/mobile` inklusive zentraler Assets per Service Worker.
- Start/Stop von Arbeitszeitbuchungen.
- Pausenstart/Pausenende.
- Firmen-/Auftragsstart und -ende.
- Kommentar-/Notizfelder in mobilen Aktionen.
- Offline erstellte Urlaubsanträge.

### Lokale Datenhaltung (letzte 6 Monate)

Die App speichert mobilrelevante Serverdaten für ca. 6 Monate (183 Tage) lokal im Browser (IndexedDB):

- Zeitbuchungen/Stempelhistorie.
- Firmenliste.
- Urlaubsanträge.
- Aktiven Buchungszustand und mobile Kennzahlen.
- Metadaten wie `lastSyncAt`.

### Synchronisation

- Automatische Synchronisation beim Start der mobilen Seite.
- Automatische Synchronisation beim Wechsel von Offline zu Online.
- Offline-Aktionen bleiben persistent in einer lokalen Queue gespeichert (auch nach Browser-Neustart).
- Idempotenz über `client_action_id` je Aktion, damit doppelte Übertragungen vermieden werden.
- Teilfehler lassen verbleibende Queue-Einträge intakt und werden später erneut versucht.
- Doppelte Offline-Startaktionen werden über effektiven Zustand + `client_action_id` robust entdoppelt, um überlappende Laufzeitbuchungen zu vermeiden.

### Statusmeldungen in der mobilen App

Die mobile Seite zeigt nutzerfreundlich an:

- Online/Offline-Serverstatus.
- Ob lokale Daten verfügbar sind.
- Anzahl ausstehender Offline-Aktionen.
- Zeitstempel der letzten erfolgreichen Synchronisation.

### Einschränkungen

- Eine **neue Anmeldung** benötigt weiterhin Serververbindung.
- Eine bereits aktive Sitzung mit lokal gespeicherten Mobil-Daten kann offline weiterarbeiten.
- Fokus liegt bewusst auf der mobilen Kernfunktion (Stempeln/Synchronisation), nicht auf vollständiger Offline-Abdeckung aller Admin-/Desktop-Seiten.

### Browser-Unterstützung

- Moderne Browser mit Service Worker + IndexedDB (aktuelles Chrome/Edge/Safari/Firefox mobile).
- Bei deaktiviertem IndexedDB fällt die App auf reduzierte Browser-Speicherung zurück.

### Updates & Service-Worker-Versionierung

- Der Service Worker leitet seinen Cache-Namen (`erfassung-mobile-v<VERSION>`) zur
  Laufzeit aus dem `?v=`-Parameter ab, mit dem er registriert wird. Dieser Parameter
  stammt aus `app_version` (Datei `VERSION`).
- **Folge:** Beim Anheben der Version in `VERSION` ändert sich automatisch der
  Cache-Name. Der alte Cache wird beim `activate`-Event gelöscht (`skipWaiting()` +
  `clients.claim()`), sodass ausgelieferte JS/CSS-Assets nicht „eingefroren" bleiben.
- Es ist **kein** manuelles Editieren von `static/sw.js` oder `static/app.js` pro
  Release mehr nötig.

### Installierbarkeit

Installierbar auf Android, iOS, Windows, macOS und Linux über das Manifest
(`static/manifest.webmanifest`) mit `id`, `start_url`, `scope`, `display: standalone`
sowie Icons in 192px, 512px und SVG (maskable).

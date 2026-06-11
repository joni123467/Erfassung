# Release Notes – Erfassung 0.3.6

**Alte Version:** 0.3.5
**Neue Version:** 0.3.6
**Datum:** 2026-06-11
**Typ:** Patch (Härtung/Vervollständigung der bestehenden PWA – keine Änderung an der Business-Logik)

---

## Zusammenfassung

Die mobile Oberfläche `/mobile` ist eine installierbare, offline-fähige Progressive
Web App. Die offline-first-Architektur (Service Worker, IndexedDB, Offline-Queue mit
Idempotenz und automatischer Synchronisation bei Reconnect) wurde bereits in `0.3.5`
eingeführt. `0.3.6` schließt die verbleibende produktionsrelevante Lücke und
vervollständigt das Manifest – **minimal-invasiv**, ohne bestehende Funktionen oder
Endpunkte zu verändern.

## Grund der Versionsanhebung

Die zuvor hartcodierte Service-Worker-Cache-Version (`erfassung-mobile-v0.3.5`)
hätte bei künftigen Versionssprüngen zu „eingefrorenen" (veralteten) Client-Assets
führen können, weil der alte Cache ohne Namensänderung nicht invalidiert wird.
Diese Schwachstelle wird behoben. Da es sich um Härtung einer bestehenden Funktion
handelt (kein neues Feature, keine Breaking Changes), erfolgt ein Patch-Sprung.

## Durchgeführte Änderungen

1. **Service-Worker-Cache-Versionierung zur Laufzeit** (`static/sw.js`)
   Der Cache-Name wird aus dem `?v=`-Query der SW-Registrierung abgeleitet, der aus
   `VERSION` / `app_version` stammt. Jede Versionsanhebung erzeugt damit automatisch
   einen neuen Cache; der alte wird beim `activate`-Event gelöscht
   (`skipWaiting()` + `clients.claim()` waren bereits vorhanden).

2. **Service-Worker-Registrierung versioniert** (`static/app.js`)
   Registrierung nutzt nun die aus `import.meta.url` ermittelte Version statt der
   hartcodierten `?v=0.3.5`.

3. **Manifest vervollständigt** (`static/manifest.webmanifest`)
   Ergänzt: `id` (`"/mobile"`), `dir` (`"ltr"`), `categories`
   (`["business", "productivity"]`).

4. **Versionsanhebung & Dokumentation**
   `VERSION` auf `0.3.6`; README-Version korrigiert (von veraltetem `0.1.7`) und um
   Abschnitte zu SW-Versionierung/Installierbarkeit erweitert; `CHANGELOG.md` und
   diese Release Notes angelegt.

## Auswirkungen auf bestehende Funktionen

- **Keine.** Es wurden keine API-Endpunkte, Datenbankmodelle, Templates der
  Desktop-Oberfläche oder Geschäftsregeln geändert.
- Die Offline-Funktionen (Start/Stop, Pausen, Auftrag/Firma, Urlaubsanträge,
  lokale Speicherung, Reconnect-Sync, Konfliktbehandlung) bleiben unverändert.

## Abnahmekriterien – Status

| Kriterium | Status | Nachweis |
| --- | --- | --- |
| Als PWA installierbar | ✅ | Manifest (`id`, `start_url`, `scope`, `display: standalone`) + Icons 192/512/SVG + registrierter Service Worker |
| Offline nutzbar nach erstem Laden | ✅ | `offlineFirstNavigation()` liefert `/mobile` aus dem Cache; Fallback auf `mobile-offline-shell.html` |
| Zeiterfassung offline (Start/Stop) | ✅ | Offline-Formulare `data-offline="punch"`, Queue in IndexedDB |
| Pausen offline | ✅ | Aktionen `start_break` / `end_break` in der Offline-Queue |
| Offline-Daten werden später synchronisiert | ✅ | `performReconnectSync()` → `flushOfflineQueue()` mit `client_action_id`-Idempotenz |
| Konflikterkennung/-behandlung | ✅ | State-Replay gegen Server-Snapshot (`recomputeEffectiveState`, `validatePunchActionAgainstState`) |
| Service Worker arbeitet korrekt / kein Stale-Cache | ✅ | Cache-Name an Version gekoppelt; alter Cache wird bei `activate` gelöscht |
| Icons inkl. 192 + 512 + maskable | ✅ | `static/icons/icon-192.png`, `icon-512.png` (maskable), `icon.svg` (maskable) |
| Versionsnummer erhöht | ✅ | `0.3.5` → `0.3.6` |

### Hinweis zum Lighthouse-PWA-Score

Der Lighthouse-PWA-Audit erfordert eine laufende Instanz über HTTPS (bzw.
`localhost`) und einen Headless-Browser; er lässt sich in dieser Umgebung nicht
automatisiert ausführen. Anhand der erfüllten technischen Anforderungen
(valides Manifest mit `id`/Icons/`display`, registrierter Service Worker mit
Offline-Navigations-Fallback, korrekte Versionierung, HTTPS im Produktivbetrieb)
ist der maximal erreichbare PWA-Score zu erwarten.

**Manuelle Verifikation (empfohlen):**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Browser → http://localhost:8000/mobile anmelden,
# DevTools → Lighthouse → Kategorie „Progressive Web App" ausführen,
# danach DevTools → Network → „Offline" und /mobile neu laden.
```

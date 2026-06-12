# Release Notes – Erfassung 0.5.1

**Alte Version:** 0.5.0
**Neue Version:** 0.5.1
**Datum:** 2026-06-11
**Typ:** Patch – Behebung dreier Regressionen aus dem 0.5.0-Offline-Refactoring

> Vorgabe eingehalten: Die funktionierende Offline-Architektur (Offline-Start,
> Service Worker, IndexedDB, Offline-Stempelungen, Sync-Queue, Wiederanlauf,
> Duplikatvermeidung, automatische Synchronisation) wurde **nicht** verändert.
> Jede Änderung wurde auf Auswirkungen darauf geprüft und per Regressionstest
> bestätigt.

---

## Phase 1 – Root-Cause-Analyse

### Problem 2 + 3 (gemeinsame Ursache): Doppelklick-Navigation & Admin nicht erreichbar

In 0.5.0 wurde der Service Worker korrekt im Scope `/` registriert (vorher schlug
die Registrierung fehl, der Worker war faktisch inaktiv). Dadurch wurde sein
Navigations-Handler erstmals für **alle** Seiten wirksam:

`static/sw.js`, `offlineFirstNavigation()` liefert für jede Navigation den
**gecachten `/mobile`-Eintrag** „cache-first" und aktualisiert ihn im Hintergrund.
Da der Worker nun den gesamten Origin kontrolliert, betraf das **jede** Seite:

- **Problem 2 (Doppelklick):** Beim Klick auf `/dashboard`, `/records/*` usw.
  lieferte der Worker zunächst den zuvor gecachten Inhalt; erst der im Hintergrund
  nachgeladene Inhalt erschien beim **nächsten** Klick → „erst der zweite Klick
  navigiert". Zusätzlich verunreinigte jede Navigation den `/mobile`-Cache-Eintrag.
- **Problem 3 (Admin):** `GET /admin` ist serverseitig ein **legitimer** `303`
  → `/admin/users` (bzw. `/dashboard` für Nicht-Admins, `/login` für Gäste,
  siehe `app/main.py:2165`). Der Worker fing die Navigation ab und lieferte den
  `/mobile`-Cache statt dem Redirect zu folgen → „Administration nicht erreichbar".
  Der im Log sichtbare `303` ist der Hintergrund-Fetch des Workers und **korrekt**.

**Der `303` ist also richtig – entfernt wurde nichts davon.** Ursache war die zu
breite Navigations-Übernahme durch den Service Worker.

### Problem 1: Arbeitszeitverlauf falsch sortiert

Zwei Stellen sortierten aufsteigend (ältester Eintrag oben):

- `app/main.py:_build_daily_overview` (Desktop-Dashboard „Heute"):
  `sorted(entries, key=lambda e: (e.start_time, e.id))` – aufsteigend.
- `app/main.py` `entries_sorted` (Administration → Zeitberichte, PDF/Excel):
  `sorted(entries, key=(work_date, start_time, name))` – aufsteigend.

Alle übrigen Listen waren bereits absteigend (DB-Queries `ORDER BY ... DESC`,
mobile Tagesansicht) bzw. ein Kalenderraster (Wochenansicht Mo–So) und blieben
unverändert.

## Phase 2 – Betroffene Dateien

| Datei | Änderung |
| --- | --- |
| `static/sw.js` | Navigations-Handler übernimmt nur noch `/mobile`; alle anderen Navigationen gehen ans Netzwerk. |
| `app/main.py` | `_build_daily_overview` und `entries_sorted` auf „neueste zuerst" umgestellt. |
| `VERSION`, `README.md`, `CHANGELOG.md`, `docs/RELEASE_NOTES_0.5.1.md` | Version 0.5.1 + Doku. |

## Phase 3 – Code-Patches (Auszug)

**Service Worker – nur `/mobile` offline-first** (`static/sw.js`):

```js
if (request.mode === 'navigate' || request.destination === 'document') {
  if (url.pathname === '/mobile' || url.pathname === '/mobile/') {
    event.respondWith(offlineFirstNavigation(request));
  }
  return; // alle anderen Navigationen: normales Netzwerk-Verhalten
}
```

**Sortierung – neueste zuerst** (`app/main.py`):

```python
# Desktop-Dashboard „Heute"
entries = sorted(entries, key=lambda entry: (entry.start_time, entry.id), reverse=True)

# Administration → Zeitberichte / Export (stabil: Datum/Zeit desc, Name asc)
entries_sorted = sorted(entries, key=lambda i: i.user.full_name.lower() if i.user else "")
entries_sorted = sorted(entries_sorted, key=lambda i: (i.work_date, i.start_time), reverse=True)
```

## Phase 4 – Regression-Test-Ergebnisse (automatisiert)

**Navigation / Administration**
- `GET /sw.js` → 200, `Service-Worker-Allowed: /` (Offline-`/mobile` erhalten).
- Service Worker übernimmt nur noch `/mobile`-Navigationen (verifiziert im Code).
- `/admin` (Admin) → `303` → `/admin/users`; `/admin/users` → `200`.
- `/admin` (Mitarbeiter) → `303` → `/dashboard`; `/admin` (anonym) → `303` → `/login`.
  → Redirects unverändert und korrekt; ohne SW-Hijack folgt der Browser ihnen sofort.

**Arbeitszeitverlauf**
- `_build_daily_overview`: Reihenfolge `16:00, 13:00, 10:00, 08:00` (neueste zuerst).
- `entries_sorted`: neueste zuerst; `total_minutes` unverändert (Summe ordnungs-unabhängig).

**Offline / Synchronisation (must-not-break – erneut bestätigt)**
- Offline `start_work@08:00` + `end_work@16:00`, später synchronisiert → genau
  **eine** geschlossene Buchung, Dauer 450 min (8 h − 30 min Pause).
- Idempotenz: erneutes Senden derselben `client_action_id` → `duplicate:true`,
  keine zweite Buchung.
- `/sw.js`, IndexedDB-Queue, Sync-Vertrag (`{ok,duplicate,retryable}`) unverändert.

### Manueller Geräte-Check (empfohlen)
- iOS-PWA / Chrome Android / Desktop: Menüpunkte und Seitenwechsel reagieren beim
  **ersten** Klick; Administration und Unterseiten öffnen zuverlässig; mobile
  Offline-Erfassung und Synchronisation funktionieren wie in 0.5.0.

## Auswirkungen / Kompatibilität

- Keine Änderung an Datenmodell, Berechnungen, CSRF, Auth oder der Offline-Engine.
- Nach Merge baut der Workflow `ghcr.io/joni123467/erfassung:0.5.1`. Der neue
  Service Worker (neuer Cache-Name aus der Version) ersetzt beim nächsten
  Online-Aufruf automatisch den alten und leert dessen Cache.

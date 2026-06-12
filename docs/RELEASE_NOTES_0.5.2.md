# Release Notes – Erfassung 0.5.2

**Alte Version:** 0.5.1
**Neue Version:** 0.5.2
**Datum:** 2026-06-12
**Typ:** Patch – drei Korrekturen in der Mobile-/PWA-Anwendung (`/mobile`)

> Vorgabe eingehalten: Die bestehende Offline-First-Architektur (Offline-Start,
> Service Worker, IndexedDB, Offline-Stempelungen, Sync-Queue, Wiederanlauf,
> Duplikatvermeidung, Auto-Sync) wurde **nicht** verändert. Jede Änderung wurde
> auf Auswirkungen geprüft und per Regressionstest abgesichert.

---

## Phase 1 – Root-Cause-Analyse

### Problem 1 – Auftragsstart-Dialog bleibt geöffnet
`static/mobile.js`, `handleOfflineSubmission()` ruft nach dem Absenden `form.reset()`
auf, **schließt aber das Modal nicht**. Das `start_company`-Formular liegt in
`#mobile-order-modal` (siehe `static/mobile-offline-shell.html` / mobile Dashboard) –
nach erfolgreichem Start blieb der Dialog daher offen.

### Problem 2 – Urlaubsanträge verschwinden nach Synchronisation
Die mobile Urlaubsliste (`[data-vacation-list]`) wurde nur durch das
Server-Template (beim Online-Laden) und durch `appendVacationPreview()` für
Offline-Entwürfe befüllt. Es gab **keine** Funktion, die die Liste aus dem
gecachten Snapshot (`snapshot.data.vacations`) rendert. Nach der Synchronisation
bzw. nach einem Reload (Service Worker liefert die gecachte Shell) wurden
synchronisierte Anträge daher nicht mehr angezeigt.
Zusätzlich lieferte das Backend (`get_mobile_history_vacations` via
`/mobile/sync-data`) nur das `days`-Fenster (Standard 30 Tage) statt aller
Anträge des laufenden Jahres.

### Problem 3 – Synchronisationsanzeige falsch („4 Offline-Aktionen warten")
`flushOfflineQueue()` behielt `retryable`-Aktionen dauerhaft in der Queue. Ein
verwaister Stempel-Stopp (`end_work`/`end_break`/`end_company`), dessen Buchung
serverseitig bereits geschlossen ist, antwortet mit `retryable:true` – die Aktion
blieb liegen **und** blockierte (über `punchBlocked`) die Bereinigung der übrigen
Queue. Folge: Der Zähler in IndexedDB (`ACTION_STORE`) sank nie auf 0, obwohl die
Daten längst synchronisiert waren („Phantom-Einträge").

### Gemeinsame Untersuchung (Problem 2 + 3)
Beide hingen an der Zusammenführung von lokalem Store und Serverdaten:
- Problem 2: fehlende **Anzeige** aus dem Snapshot.
- Problem 3: fehlende **Bereinigung** der Queue bei eindeutiger Server-Antwort.
Es war **nicht** dieselbe einzelne Ursache, aber dasselbe Themenfeld (Store ↔ Server).

## Phase 2 – Betroffene Dateien

| Datei | Änderung |
| --- | --- |
| `static/mobile.js` | Modal-Schließen nach Submit; neue `renderVacations()`; Einbindung in Load/Sync/Tab/Submit; `flushOfflineQueue` entfernt Aktionen bei jeder eindeutigen Server-Antwort. |
| `app/main.py` | `/mobile/sync-data` liefert Urlaubsanträge für das gesamte laufende Jahr. |
| `VERSION`, `README.md`, `CHANGELOG.md`, `docs/RELEASE_NOTES_0.5.2.md` | Version 0.5.2 + Doku. |

## Phase 3 – Code-Patches (Auszug)

**Problem 1 – Modal schließen** (`static/mobile.js`):
```js
form.reset();
const modal = form.closest('.modal');
if (modal) {
  modal.classList.remove('is-visible');
  modal.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
}
```

**Problem 2 – Urlaubsliste aus Snapshot + Queue** (`static/mobile.js`,
`renderVacations()`): rendert alle Anträge des laufenden Jahres (alle Status) plus
noch nicht synchronisierte Offline-Anträge; aufgerufen beim Laden, nach jeder
Synchronisation, beim Öffnen des Urlaub-Tabs und nach dem Absenden.
Backend (`app/main.py`):
```python
vacation_since = min(since_date, date(today.year, 1, 1))
vacations = crud.get_mobile_history_vacations(db, user.id, vacation_since)
```

**Problem 3 – Queue-Bereinigung** (`static/mobile.js`, `flushOfflineQueue()`):
```js
if (result.ok || result.duplicate) { /* delete */ }
else { /* jede eindeutige Server-Antwort: delete -> keine Phantom-Einträge */ }
// nur thrown (Netzwerk/Auth/5xx) -> behalten und Reihenfolge wahren
```

## Phase 4 – Regression-Test-Ergebnisse (automatisiert)

- `mobile.js` Syntax OK; App-Import OK.
- **Urlaub (aktuelles Jahr):** Antrag vom 10.01. wird bei `days=30` mitgeliefert
  (zuvor außerhalb des Fensters) → sichtbar; Status (`pending`/`approved`/… ) ist
  serialisiert. **PASS**.
- **Phantom-Counter:** verwaister `end_work` → Server `{ok:false, retryable:true}`
  → Client entfernt die Aktion bei dieser eindeutigen Antwort → keine
  Phantom-Einträge mehr.
- **Offline-Sync (must-not-break):** `start_work@08:00` + `end_work@16:00`
  → genau eine geschlossene Buchung (450 min); erneutes Senden derselben
  `client_action_id` → `duplicate:true`, keine zweite Buchung (unverändert grün).
- **Vorherige Fixes:** `/admin`-Redirect-Kette und Sortierung (0.5.1) sowie
  Service-Worker-`/mobile`-Scope unverändert.

### Manueller Geräte-Check (empfohlen)
- Auftrag starten → Dialog schließt automatisch, kein Mehrfachstart.
- Urlaub-Tab: alle Anträge des Jahres sichtbar (auch nach Sync), Status korrekt.
- Einstellungen: Zähler steht nach Sync auf „Keine ausstehenden Offline-Aktionen".
- Offline weiterhin: Start, Stempelungen, Aufträge, Urlaubsanträge, Wieder-Sync.

## Auswirkungen / Kompatibilität

- Keine Änderung an Datenmodell, Berechnungen, CSRF, Auth oder der Offline-Engine.
- Nach Merge baut der Workflow `ghcr.io/joni123467/erfassung:0.5.2`.

# Release Notes – Erfassung 0.5.0

**Alte Version:** 0.4.0
**Neue Version:** 0.5.0
**Datum:** 2026-06-11
**Typ:** Minor – Reparatur und Härtung der Offline-PWA

---

## 1. Root-Cause-Analyse

### Fehler 1 – App startet offline nicht (Safari: „Seite nicht gefunden")

**Ursache:** Der Service Worker wurde unter `/static/sw.js` ausgeliefert
(`StaticFiles`), aber mit `navigator.serviceWorker.register('/static/sw.js', {scope: '/'})`
registriert (`static/app.js`). Der maximal erlaubte Scope eines Service Workers ist
sein **eigener Pfad** (`/static/`); ein breiterer Scope (`/`) ist nur mit dem
HTTP-Header `Service-Worker-Allowed` zulässig, den `StaticFiles` nicht sendet.

**Folge:** Der Browser **lehnt die Registrierung ab**. Das `install`-Event läuft
nie, `cache.addAll(CORE_ASSETS)` und das Vorab-Cachen von `/mobile` finden nicht
statt. Online funktioniert die App trotzdem (Netzwerk), und der Fehler wird vom
`.catch()` verschluckt – deshalb fiel es erst offline auf. Ohne aktiven Worker
kann `/mobile` offline nicht bedient werden → „Seite nicht gefunden".

### Fehler 2 – Offline-Stempelungen unvollständig synchronisiert (v. a. Arbeitsende)

Drei zusammenwirkende Defekte, jeweils mit Datenverlust:

1. **Falsche Redirect-Auswertung** (`static/mobile.js`, `postQueuedAction`):
   Der Client sendete mit `redirect: 'manual'` und wertete jede `opaqueredirect`/
   Status-0-Antwort als „Sitzung abgelaufen". Der `/punch`-Endpunkt antwortet
   aber bei **jedem** Erfolg mit `303`. Damit warf jede erfolgreiche Buchung eine
   Ausnahme → die Queue-Bereinigung verließ sich auf einen brüchigen Ersatzpfad.

2. **Vorab-Verwerfen von Ereignissen** (`processPunchSubmission`): Vor dem
   Speichern lief eine clientseitige Zustandsprüfung
   (`validatePunchActionAgainstState`), die das Ereignis bei „nicht erlaubt"
   **verwarf** (`return`, kein Speichern). Zusammen mit
   `recomputeEffectiveState`, das einen **eingefrorenen Lade-Zustand**
   (`initialServerState`) dem frischen Server-Snapshot vorzog, kippte der
   effektive Zustand nach dem Sync eines `start_work` zurück auf „arbeitet
   nicht" – das anschließende **`end_work` wurde verworfen** und nie übertragen.

3. **Löschen ungesendeter Aktionen** (`flushOfflineQueue`): Aktionen wurden
   anhand clientseitiger Vermutung aus der Queue **gelöscht** statt gesendet.
   Der Server wiederum beendet ein `end_work` ohne offene Buchung **stillschweigend**
   (303, keine DB-Änderung, kein Idempotenz-Eintrag) – der Verlust blieb unsichtbar.

### Zusatzbefund – Falsche Zeiten

Der Server stempelte jede Buchung mit `datetime.now()` (keine Client-Zeit). Offline
erfasste Ereignisse erhielten damit die **Synchronisationszeit**: ein um 8 Stunden
versetzter Arbeitstag wurde mit Dauer ~0 gespeichert, und mehrere im selben Moment
synchronisierte Buchungen kollidierten (`OVERLAPPING_TIME_ENTRY` → HTTP 500).

## 2. Betroffene Dateien

| Datei | Änderung |
| --- | --- |
| `static/app.js` | Registriert den Service Worker als `/sw.js` (Root-Scope). |
| `app/main.py` | Neue Route `GET /sw.js` mit `Service-Worker-Allowed: /`; JSON-Antworten für Sync-Aufrufe an `/punch` & `/vacations`; `event_time`-Parameter; saubere Overlap-Antwort statt 500. |
| `static/mobile.js` | `postQueuedAction` (JSON statt Redirect-Raten), `flushOfflineQueue` (senden statt verwerfen), `processPunchSubmission` (immer speichern), `syncServerData` (Basiszustand aktualisieren), Ereigniszeitstempel. |
| `static/sw.js` | Unverändert in Logik (Versionierung wie gehabt); wird nun via `/sw.js` ausgeliefert. |

## 3. Konkrete Änderungen (Auszug)

**Service Worker im Root-Scope** (`app/main.py`):

```python
@app.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    content = (_STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    return Response(content, media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})
```

**Maschinenlesbares Sync-Ergebnis** (`app/main.py`): `/punch` und `/vacations`
liefern bei `Accept: application/json` `{ok, duplicate, retryable, message}`
(HTTP 200), bei fehlender Sitzung `401`. Browser-Formular-POSTs (`Accept: text/html`)
behalten die 303-Weiterleitung.

**Queue-and-forward** (`static/mobile.js`, `flushOfflineQueue`): jede Aktion wird in
Reihenfolge gesendet; Entfernen nur bei `ok`/`duplicate`; `retryable` (z. B.
Reihenfolgeproblem) und Transportfehler belassen die Aktion in der Queue.

**Echte Ereigniszeit** (`static/mobile.js` → `event_time`, `app/main.py` →
`_parse_event_time`).

## 4. Verbesserungen

- Robuste IndexedDB-Queue: Ereignisse werden ausnahmslos zuerst lokal gespeichert.
- Zuverlässige Synchronisation: Server ist Wahrheitsquelle; Idempotenz verhindert
  Dubletten; keine clientseitigen Löschungen ungesendeter Aktionen.
- Stabiler Offline-Start: Worker im Root-Scope mit korrektem Header.
- Korrekte Zeiterfassung offline durch Ereigniszeitstempel.

## 5. Testplan

### Automatisiert verifiziert (gegen temporäre DB)

- `GET /sw.js` → 200, `Content-Type: application/javascript`, `Service-Worker-Allowed: /`.
- Offline-Szenario: `start_work@08:00`, `end_work@16:00`, später synchronisiert →
  **genau eine** Buchung 08:00–16:00, korrekt geschlossen, Dauer = 8 h − 30 min
  Pause = 450 min; **kein** Datenverlust.
- Idempotenz: erneutes Senden derselben `client_action_id` → `{ok:true, duplicate:true}`,
  **keine** zweite Buchung.
- `end_work` ohne offene Buchung → `{ok:false, retryable:true}` (bleibt in Queue,
  wird nach `start_work` erneut versucht).
- Browser-Formular-POST (`Accept: text/html`) → weiterhin `303`.

### Manuell (Geräte)

**Safari iOS / installierte PWA auf dem iPhone**
1. `/mobile` online öffnen und anmelden (Service Worker installiert sich).
2. „Zum Home-Bildschirm hinzufügen", PWA einmal online öffnen.
3. Flugmodus aktivieren, PWA neu starten → App startet, Buchungsmaske erscheint.
4. Arbeitsbeginn, Pause, Arbeitsende offline erfassen.
5. Flugmodus aus → automatische Synchronisation; in der Übersicht erscheinen alle
   Ereignisse mit den **tatsächlichen** Uhrzeiten, keine Dubletten.

**Chrome Android**
1. PWA installieren, online laden.
2. DevTools/Netzwerk offline (oder Flugmodus), mehrere Buchungen erfassen.
3. Online schalten → Queue-Zähler geht auf 0, Daten vollständig.

**Desktop-Browser (Chrome/Firefox)**
1. DevTools → Application → Service Workers: Worker mit Scope `/` aktiv.
2. Offline-Checkbox setzen, `/mobile` neu laden → lädt aus Cache.
3. Buchungen erfassen, wieder online → vollständige Synchronisation.
4. Desktop-Dashboard (`/dashboard`): Stempeln per Formular funktioniert wie bisher
   (303-Weiterleitung).

## 6. Auswirkungen / Kompatibilität

- Desktop-Web-Oberfläche unverändert (303-Verhalten bleibt).
- CSRF-Schutz, Datenmodell und Geschäftslogik unverändert.
- Nach Merge baut der Workflow `ghcr.io/joni123467/erfassung:0.5.0`.

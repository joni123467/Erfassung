# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.7.0] – 2026-06-13

### Added – Dark Mode (vollständig, umschaltbar)

- **Umschalter Hell/Dunkel** im Desktop-Header und im Mobile-Footer
  (auch in der Offline-Shell der PWA). Die Wahl wird in `localStorage`
  (`erfassung-theme`) gespeichert und bleibt beim Neuladen erhalten; ohne
  gespeicherte Wahl folgt die App der Systemeinstellung
  (`prefers-color-scheme`).
- **Kein Flackern:** ein Inline-Snippet im `<head>` wendet das gespeicherte
  Theme vor dem ersten Paint an; `static/theme.js` (neu, im Service-Worker-
  Precache) verdrahtet die Toggle-Buttons und hält `theme-color` synchron.
- **Dunkle Palette** (kein reines Schwarz): Hintergrund `#0f172a`, Flächen
  `#111827`, Karten `#1e293b`, Rahmen `#334155`, Text `#f8fafc`, gedämpfter
  Text `#94a3b8`, Primärfarbe `#3b82f6`. Umgesetzt ausschließlich als
  Token-Overrides unter `:root[data-theme="dark"]` – keine komponentenweisen
  Sonderfälle.

### Changed – Design-System konsequent durchgezogen

- **Radius-Skala als einzige Quelle:** `--radius-xs` 3px (Tabs, Badges,
  Chips), `--radius-sm` 5px (Buttons, Inputs, Selects), `--radius-md` 6px,
  `--radius-lg` 8px (Karten, Dialoge). Alle fest codierten `border-radius`-
  Werte (inkl. `50%` beim Mobile-Einstellungsbutton) entfernt; nichts ist
  mehr runder als 8px.
- **Einheitliche Control-Höhen:** `--control-h` (2.5rem) für Inputs, Selects
  und Buttons; `--control-h-sm` (2rem) nur für kompakte Tabellen-Buttons.
  Filterleisten (u. a. „Feiertage verwalten", Buchungen, Zeitübersichten)
  haben jetzt durchgehend gleiche Höhen in einer Zeile.
- **Navigation modernisiert:** kompakter Sticky-Header (3.5rem), SVG-Icons
  statt Emojis, ruhige Hover-Zustände (neutraler Wash), klarer aktiver
  Zustand; Bereichs-Tabs (Admin, Buchungen/Urlaub) als Underline-Tabs statt
  Pill-Container; Footer als dezente Trennlinie statt blauem Balken.
- **Alle Farben tokenisiert:** sämtliche hartcodierten Hex-/RGBA-Werte in
  `styles.css` (Modals, Login, Alerts, Formulare, Tabellen-Streifen,
  Status-Badges, Mobile-Listen …) durch Design-Tokens ersetzt – Voraussetzung
  dafür, dass der Dark Mode überall greift. Einzige Ausnahme: der QR-Code
  behält bewusst einen weißen Hintergrund (Scanbarkeit).
- **Manifest/Theme-Color** auf die aktuelle Palette aktualisiert
  (`#2563eb`, Hintergrund `#f8fafc`).

### Grund der Versionsanhebung

Minor (`0.6.0` → `0.7.0`): neues Feature (umschaltbarer Dark Mode) plus
sichtbares, aber rein darstellungsbezogenes Design-Refactoring.

## [0.6.0] – 2026-06-12

### Changed – UI-Redesign (modernes SaaS-/Business-Erscheinungsbild)

Reines Design-/UX-Update – **keine** Änderung an Funktionen, APIs, Datenmodell,
Synchronisation, Offline-Funktion oder Geschäftslogik. Betroffen ist
ausschließlich `static/styles.css`.

- **Design-System / Tokens:** zentrale `:root`-Token-Ebene (Farben, Radien,
  Schatten, Status, Focus-Ring). Alle Komponenten konsumieren diese Tokens, wodurch
  Desktop und Mobile durchgängig wie ein Produkt wirken.
- **Farbpalette:** tiefes Blau als Primärfarbe (`#2563eb` / Hover `#1d4ed8`),
  Slate-Neutraltöne, ruhiger Hintergrund (`#f8fafc`), weiße Karten. Statusfarben
  vereinheitlicht: Grün (aktiv), Amber (Pause), Blau (Urlaub/Info), Rot (Fehler).
- **Kanten statt Pillen:** kleine Border-Radien (Buttons/Inputs/Badges 6px, Karten
  /Dialoge 8px); alle `999px`-Pillen entfernt.
- **Buttons:** Primary (klare Fläche, dezenter Schatten, Hover, Focus-Ring),
  Secondary (zurückhaltender Neutral-Outline), Danger (klar rot).
- **Karten:** 1px-Rahmen + dezente Schatten statt starker Schlagschatten; mehr
  Ruhe, klare Trennung. KPI-Karten vereinheitlicht.
- **Tabellen:** ruhige Kopfzeile (Uppercase, gedämpft), Zeilen-Hover, bessere
  Lesbarkeit.
- **Mobile (`/mobile`):** Header, Tabs, Stempelbuttons, Auftrags- und
  Urlaubsansicht auf dasselbe Token-System umgestellt – wirkt wie eine
  installierbare Business-App, nicht wie eine Website.
- **Dark Mode:** vorbereitet (Token-Overrides unter `html[data-theme="dark"]`),
  bewusst **nicht** automatisch aktiv – Standard bleibt Hell.

### Grund der Versionsanhebung

Minor (`0.5.2` → `0.6.0`): umfassendes, sichtbares Redesign (nur Darstellung),
ohne funktionale Änderungen.

## [0.5.2] – 2026-06-12

### Fixed – Mobile-/PWA-Funktionen

- **Auftragsstart-Dialog blieb geöffnet:** `handleOfflineSubmission` setzte das
  Formular zwar zurück, schloss aber das Modal nicht. Nach erfolgreichem Start
  (queue-first, also immer erfolgreich) wird das umgebende Modal jetzt
  automatisch geschlossen; der Nutzer sieht wieder die normale Ansicht.
- **Urlaubsanträge verschwanden nach der Synchronisation:** Die mobile Urlaubsliste
  wurde nur serverseitig (beim Online-Laden) bzw. für Offline-Entwürfe befüllt –
  es gab **keine** clientseitige Darstellung aus dem gecachten Snapshot. Nach
  Sync/Reload waren synchronisierte Anträge daher nicht mehr sichtbar. Neu:
  `renderVacations()` zeigt **alle Anträge des laufenden Jahres** (offen,
  genehmigt, abgelehnt, storniert, Rücknahme angefragt sowie noch nicht
  synchronisierte Offline-Anträge) mit Zeitraum, Typ und Status. Backend:
  `/mobile/sync-data` liefert Urlaubsanträge nun für das **gesamte laufende Jahr**
  (zuvor nur das `days`-Fenster).
- **Synchronisationsanzeige zeigte Phantom-Aktionen („4 Offline-Aktionen warten"
  trotz Sync):** In der Queue konnten Aktionen dauerhaft hängen bleiben – etwa
  ein verwaister Stempel-Stopp (`end_*`), dessen Buchung serverseitig längst
  geschlossen ist und der mit `retryable` beantwortet wurde (das blockierte zudem
  die übrige Queue). `flushOfflineQueue` entfernt eine Aktion jetzt bei **jeder
  eindeutigen Server-Antwort** (Erfolg, Duplikat oder definitive Ablehnung);
  nur bei echten Transport-/Auth-Fehlern bleibt sie erhalten. Echte
  Reihenfolge-Abhängigkeiten bleiben über den Transientfehler-Pfad gewahrt.
  Ergebnis: Der Zähler entspricht exakt dem Queue-Zustand – keine Phantom-Einträge.

### Nicht verändert (Offline-Architektur erhalten)

- Offline-Start, Service Worker, IndexedDB-Speicherung, Offline-Stempelungen,
  Sync-Queue, Wiederanlauf, Idempotenz/Duplikatvermeidung und automatische
  Synchronisation bleiben unverändert (per Regressionstest bestätigt).

### Grund der Versionsanhebung

Patch (`0.5.1` → `0.5.2`): gezielte Korrekturen dreier Mobile-Funktionen ohne
Eingriff in die Offline-Architektur, Datenmodell oder Geschäftslogik.

## [0.5.1] – 2026-06-11

### Fixed – Regressionen nach dem 0.5.0-Offline-Refactoring

- **Navigation reagierte erst beim zweiten Klick & Administration nicht
  erreichbar (gleiche Ursache):** Mit 0.5.0 wurde der Service Worker erstmals im
  Scope `/` aktiv. Sein `offlineFirstNavigation` bediente daraufhin **jede**
  Navigation cache-first aus dem einen `/mobile`-Cache-Eintrag. Folge: andere
  Seiten (`/dashboard`, `/admin`, `/records/*`) zeigten beim ersten Klick den
  zuvor gecachten Inhalt und erst der zweite Klick die richtige Seite; der
  legitime `303`-Redirect von `/admin` → `/admin/users` wurde nie befolgt
  („Administration nicht erreichbar"). Der Worker bedient nun **ausschließlich
  die `/mobile`-Route** offline-first; alle übrigen Navigationen gehen direkt
  ans Netzwerk und funktionieren beim ersten Klick. Offline-Verhalten von
  `/mobile`, Caching statischer Assets und die Sync-Logik bleiben unverändert.
- **Arbeitszeitverlauf falsch sortiert:** Zwei Ansichten sortierten aufsteigend
  (ältester Eintrag oben). Sie zeigen jetzt **neueste Einträge zuerst**:
  - Desktop-Dashboard „Heute" (`_build_daily_overview`).
  - Administration → Zeitberichte inkl. PDF-/Excel-Export (`entries_sorted`;
    Datum/Startzeit absteigend, Name aufsteigend als Tiebreaker).
  Geändert wurde ausschließlich die Anzeige-/Export-Reihenfolge – Zeitstempel,
  Arbeits-/Pausenzeiten, Summen, Datenbank und Synchronisation bleiben unberührt.
  (Mobile Tages-/Wochenansicht, Buchungsliste und Freigaben waren bereits
  absteigend bzw. Kalenderraster und blieben unverändert.)

### Grund der Versionsanhebung

Patch (`0.5.0` → `0.5.1`): gezielte Regressionsbehebung, keine Änderung an den
Offline-Komponenten (Start, Service-Worker-Caching, IndexedDB, Queue, Sync,
Duplikatvermeidung).

## [0.5.0] – 2026-06-11

### Fixed – Offline-PWA zuverlässig gemacht

- **Offline-Start scheiterte (Safari/iOS: „Seite nicht gefunden"):**
  Der Service Worker wurde unter `/static/sw.js` ausgeliefert, aber mit
  `{scope: '/'}` registriert. Der maximal erlaubte Scope eines Workers ist sein
  eigener Pfad (`/static/`); ein breiterer Scope erfordert den Header
  `Service-Worker-Allowed`, den `StaticFiles` nicht sendet. Dadurch wurde die
  **Registrierung vom Browser abgelehnt**, das `install`-Event lief nie, nichts
  wurde vorab gecacht – die App konnte offline nicht starten. Der Worker wird nun
  von der Wurzel (`GET /sw.js`) mit `Service-Worker-Allowed: /` ausgeliefert und
  als `/sw.js` registriert, sodass Scope `/` gültig ist und `/mobile` offline
  bedient wird.
- **Offline-Stempelungen wurden nicht vollständig synchronisiert (v. a.
  Arbeitsende):** Mehrere zusammenwirkende Ursachen behoben:
  1. `postQueuedAction` nutzte `redirect: 'manual'` und wertete **jede**
     303-Antwort als „Sitzung abgelaufen". Da `/punch` bei Erfolg immer per 303
     antwortete, schlug jede erfolgreiche Buchung clientseitig fehl. Die
     Endpunkte liefern bei `Accept: application/json` nun eine **maschinenlesbare
     JSON-Antwort** (`{ok, duplicate, retryable, message}`).
  2. `processPunchSubmission` **verwarf** Ereignisse vor dem Speichern anhand
     einer clientseitigen Zustandsprüfung. In Kombination mit einem eingefrorenen
     Lade-Zustand führte das dazu, dass das **Arbeitsende verworfen** wurde. Jede
     Buchung wird jetzt **immer** zuerst in IndexedDB gespeichert.
  3. `flushOfflineQueue` löschte nicht gesendete Aktionen aufgrund clientseitiger
     Vermutung (Datenverlust). Es wird nun **jede** Aktion in Erstellungsreihenfolge
     an den Server gesendet; entfernt wird sie nur bei eindeutiger Server-Antwort
     (Erfolg/duplikat). Server-Idempotenz (`client_action_id`) verhindert Dubletten.
  4. Der effektive Zustand wird nach jeder Synchronisation aus dem frischen
     Server-Snapshot aktualisiert (statt am eingefrorenen Lade-Zustand zu hängen).
- **Offline-Zeiten waren falsch (Sync-Zeit statt Ereigniszeit):** Der Server
  stempelte jede Buchung mit `datetime.now()`. Offline erfasste Ereignisse
  bekamen damit die (spätere) Synchronisationszeit – ein um 8 h versetzter
  Arbeitstag wurde z. B. mit Dauer 0 erfasst. Der Client sendet nun die echte
  lokale Ereigniszeit (`event_time`), die der Server verwendet (mit Plausibilitäts-
  Grenzen). Online-Buchungen verhalten sich unverändert.
- **Robustheit:** Eine `start_work`-Buchung, deren Intervall sich mit einer
  vorhandenen Buchung überschneidet, liefert jetzt eine saubere, endgültige
  Fehlerantwort statt eines HTTP 500 (das ein Offline-Client endlos wiederholt
  hätte).

### Unverändert / kompatibel

- Normale Browser-Formular-POSTs (`Accept: text/html`) erhalten weiterhin die
  klassische 303-Weiterleitung – die Desktop-Web-Oberfläche ist nicht betroffen.
- CSRF-Schutz, Datenmodell und Geschäftslogik bleiben unverändert.

### Grund der Versionsanhebung

Minor (`0.4.0` → `0.5.0`): überarbeitete Offline-Synchronisations-Engine inkl.
neuem JSON-Sync-Vertrag und client-seitigen Ereigniszeitstempeln.

## [0.4.0] – 2026-06-11

### Added

- **Konsolen-Benutzerverwaltung (`app/manage.py`):** Neues CLI-Werkzeug zur
  Administration ohne Web-Oberfläche – ideal für Notfälle (z. B. verlorener
  Admin-Zugang) und Erstinbetriebnahme.
  - `list-users` – alle Benutzer auflisten (ID, Benutzername, Name, E-Mail,
    Gruppe, Admin, Passwortwechsel-Flag).
  - `list-groups` – Gruppen inkl. Admin-Kennzeichen auflisten.
  - `create-user` – Benutzer anlegen (Passwort interaktiv, per `--password`
    oder `--random`; Gruppenzuordnung per ID/Name; `--weekly-hours`;
    `--no-force-change`).
  - `reset-password` – Passwort per `--username` oder `--id` zurücksetzen
    (interaktiv, `--password` oder `--random`; `--force-change/--no-force-change`).
  - Aufruf im Container: `docker exec -it erfassung python -m app.manage <befehl>`.
  - Nutzt dieselbe DB (`DATABASE_URL`), Passwort-Hashing (PBKDF2) und
    Stärke-Prüfung wie die Web-App; PIN-Vergabe erfolgt automatisch.
- **README:** Abschnitt „Benutzerverwaltung über die Konsole (CLI)" mit Anleitung
  und Beispielen ergänzt.

### Grund der Versionsanhebung

Minor (`0.3.8` → `0.4.0`): additive neue Funktionalität (Administrations-CLI). Keine
Änderung an bestehender Web-/Geschäftslogik, am Datenmodell oder an Endpunkten.

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

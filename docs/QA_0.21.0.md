# Abschluss- und Prüfbericht 0.21.0

Stand: 3. November 2026. Entwicklungsbranch: `version-0.21.0`, ausgehend von
`022b752` / Version 0.20.9. Zielbetrieb: installierte iOS-PWA pro Benutzer,
Deutschland, SQLite und mindestens eine Woche offline. Keine Veröffentlichung
und kein Produktivdeployment wurden durchgeführt.

## Ergebnis und Ursachen

Die Synchronisation wurde innerhalb der bestehenden FastAPI-/Jinja-/JavaScript-
Architektur überarbeitet. Ein Frameworkwechsel war dafür nicht erforderlich.
Die Implementierung und ihre lokalen Prüfungen sind abgeschlossen. Die unten
genannten Geräte- und externen Integrationsprüfungen stehen noch aus;
eine vollständige Freigabe für den iOS-Produktivbetrieb wird daher nicht behauptet.

Der konkrete alte iOS-Zustand ist nach der vom Benutzer vorgenommenen
Neuinstallation nicht mehr untersuchbar. Die Analyse konnte daher keine einzelne
Ursache dieses konkreten Vorfalls beweisen. Im alten Code wurden jedoch vier
Verlust-/Blockadepfade isoliert reproduziert: Löschen trotz wiederholbarer
Ablehnung, Erfolg bei HTTP 200 ohne gültige JSON-Bestätigung, scheinbare Speicherung
ohne IndexedDB und ein dauerhaft gesetztes Sync-Flag nach einem Speicherfehler.
Eine Neuinstallation entfernt die zugehörigen lokalen Zustände; sie erklärt die
vorübergehende Besserung, ist aber keine datenerhaltende Fehlerbehebung.

Weitere behobene Risiken: getrennte Commits für Buchung und Dublettennachweis,
fehlende Kontozuordnung, konkurrierende Übertragungen, sofortige Worker-Aktivierung,
Cache-Löschung und eine falsche Anzeige laufender Arbeitszeit nach Offline-Neustart.
Ein Fehler nach erfolgreicher Speicherung wird jetzt ausdrücklich von einem
fehlgeschlagenen Speichervorgang unterschieden.

## Umsetzung

- **Lokale Daten:** gemeinsame Outbox für Seite und Worker; IndexedDB-Version 5
  migriert vorhandene Stores ohne Löschung. Stabile IDs, Kontozuordnung,
  bestätigte Transaktionen, geordnete Übertragung, persistierter Backoff und
  ein atomarer Lease schützen Speicherung und Wiederholung. Export und additive
  Wiederherstellung behalten die ursprünglichen IDs.
- **API und Backend:** Protokoll 1 verlangt passende Empfangsbestätigungen.
  Migration 25 ergänzt `mobile_sync_receipts`. SQLite-Schreibsperre und
  Savepoints fassen Buchung, Revisionen und Dublettennachweis in einer äußeren
  Transaktion zusammen. Alte Endpunkte bleiben verfügbar und sichern Ereignisse
  mit Aktions-ID einschließlich fachlicher Ablehnungen serverseitig.
- **Konflikte:** das eigene Recht `Time.Sync.Resolve` steuert Prüfung,
  begründete Korrektur/Wiederholung und Ablehnung im jeweiligen Zuständigkeitsbereich.
  Originaldaten und Entscheidungen bleiben nachvollziehbar; Folgeereignisse warten.
- **Worker und Updates:** vollständige versionierte statische Hülle, keine
  gecachten Sitzungs-/API-Antworten, kontrollierte Aktivierung mit Prüfung aller
  offenen Mobilfenster. Ausstehende Buchungen bleiben beim Workerwechsel erhalten.
- **Oberfläche:** dauerhafte Anzeige für lokal gespeichert, ausstehend, offline,
  laufenden Abgleich, Fehler, Anmeldebedarf, Freigabe und verfügbare Updates.
  Buchungsdetails und Sicherungsfunktionen ergänzen die bestehende Mobilansicht.
  Statusmeldungen verwenden ARIA-Live-Regionen und vorhandene Design-/Dark-Mode-Tokens.
- **Betrieb:** bisherige Docker-/GHCR-/Portainer-Architektur, getrennte Volumes
  und automatische Migrationen bleiben erhalten. Basisimage-Digest, Hash-Lock
  und funktionaler Compose-Healthcheck verbessern die Reproduzierbarkeit.

Details, Protokoll und Rollout:
[PWA_SYNCHRONISATION.md](PWA_SYNCHRONISATION.md).

## Ausgeführte Prüfungen

| Prüfung | Ergebnis | Aussage |
| --- | --- | --- |
| Vollständige Python-Suite, Python 3.11.17 | 910 bestanden, 0 fehlgeschlagen, 0 übersprungen | Alle 42 Testdateien in vier isolierten Prozessen mit getrennten temporären Verzeichnissen; kein pytest-xdist |
| Node-Test-Suite | 17 bestanden, 0 fehlgeschlagen, 0 übersprungen | IndexedDB, Queue, Identität, Backoff, Lease und Fehlerbehandlung |
| Playwright / System-Chromium | 15 bestanden | Reale Browser-, IndexedDB-, Service-Worker- und HTTP-Abläufe, ohne automatische Testwiederholungen |
| Playwright / WebKit | 15 bestanden | Am 3. November nachgeholt; gemeinsam mit Chromium 30/30 bestanden, ohne übersprungene Tests oder Wiederholungen |
| Docker-Build | Erfolgreich | Hash-geprüfte Python-Pakete, festgelegtes Python-3.11-Basisimage; Cloud-CA nur als temporäres BuildKit-Secret |
| Containerstart und Neustart | Erfolgreich | Health 0.21.0, Login, Stempelpaar, Dublettenquittung, Konfliktseite und Worker-Version; Benutzer, Schema 25, Quittungen, Konfiguration und Logs bleiben erhalten |
| Entwicklungsumgebung neu starten | Erfolgreich | Upgrade auf Schema 25, SQLite-Integrität, unveränderte Benutzer-/Konfigurationsprüfsummen, Health und Assets |
| Setup wiederholen | Erfolgreich | Python-Hash-Lock, Paketprüfung und npm ci; keine Versionsdateien durch Setup verändert |
| JavaScript-Syntax und Git-Diff | Erfolgreich | Syntaxprüfung der geänderten Skripte, keine Whitespace-Fehler |

Der erste vollständige Python-Lauf fand zwei veraltete Erwartungen für die neue
Berechtigung und Migrationsnummer. Diese wurden aktualisiert; die vollständige
abschließende Suite besteht. Im Browserlauf wurde außerdem ein Rennen im
Testaufbau korrigiert: Die Netzunterbrechung muss vor dem Einreihen installiert
werden, da der automatische Abgleich sonst bereits erfolgreich senden kann.
Deprecation-Warnungen vorhandener Python-Abhängigkeiten bleiben vorhanden.

Die neuen Backendtests prüfen insbesondere sieben Tage alte Zeitpunkte,
Sommer-/Winterzeit, parallele identische Requests, gleiche ID mit anderen Daten,
Abbruch nach einem internen CRUD-Commit, Rücknahme teilweise ausgeführter
zusammengesetzter Aktionen, Konfliktentscheidungen, Berechtigungsgrenzen,
Legacy-Endpunkte, wiederholbare Migration und logischen Backup-/Restore-Erhalt.

Die Browserfälle umfassen Online-Stempeln, mehrere Offline-Ereignisse,
Seiten- und vollständigen Browserprozess-Neustart, automatische Nachübertragung,
abgelaufene Sitzung mit Neuanmeldung, sichtbare Konflikte, nicht löschende
Wiederherstellung, parallele Tabs, schmalen Bildschirm, Verbindungsabbruch nach
Servercommit, HTML statt Quittung, Migration einer echten IndexedDB v4,
Workerwechsel mit ausstehenden Buchungen und Schutz ungespeicherter Eingaben,
bestätigte laufende Arbeit nach Offline-Neustart, vierzehn Stempel einer
simulierten Offline-Woche und einen Lesefehler nach erfolgreicher Speicherung.

Die lokalen Rohprotokolle und XML-Ergebnisse liegen in der Cloud-Arbeitsumgebung
unter `/workspace/erfassung-cloud/`, insbesondere `final-tests/all.xml`,
`node-tests-final.log`, `browser-tests-final.log`, `docker-build-final.log` und
`docker-smoke-result.txt`. Die Browser-Nachprüfung vom 3. November steht in
`browser-tests-ci-fix.log`. Diese temporären Ausgaben gehören nicht ins Repository.

## CI/CD, Abhängigkeiten und Skills

`.github/workflows/checks.yml` prüft Python, Node, Chromium, WebKit sowie
Containerstart und Neustart als getrennte Jobs auf Ubuntu 24.04. Der bestehende
Container-Publishing-Workflow wartet auf alle diese Prüfungen. Der bisherige
Checkname `tests` bleibt als gemeinsamer Abschlusscheck erhalten und verlangt
den Erfolg aller Einzelprüfungen. Der erste
[GitHub-Lauf](https://github.com/joni123467/Erfassung/actions/runs/41473637069)
bestand Python und JavaScript, scheiterte im Browser-Schritt und übersprang
deshalb Docker. Das war kein Scheitern sämtlicher Tests.

Bei der Nachprüfung wurden unter WebKit drei Fehler der Testsimulation
reproduziert: Playwright-Routing fing die Service-Worker-kontrollierten
Anfragen nicht ab; statt des simulierten Fehlers kam die normale erfolgreiche
Serverantwort. Die Fehler werden nun ausschließlich im Testserver ausgelöst.
Der Abbruchtest trennt die HTTP-Verbindung nach tatsächlichem Commit und prüft
danach dieselbe offene ID sowie die Dublettenquittung beim Wiederholen.
Kein Test wurde deaktiviert, kein Erwartungswert gelockert und kein Service
Worker für diese Prüfungen abgeschaltet. Die drei korrigierten Fälle bestanden
lokal unter WebKit; anschließend bestanden alle 30 Browserfälle in Chromium und
WebKit gemeinsam. Außerdem wartet die Anmelde-Fixture jetzt auf die tatsächliche
Service-Worker-Kontrolle, statt eine laufende Start-Synchronisation durch einen
zusätzlichen Reload abzubrechen. Dieser künstliche Abbruch konnte den gültigen
30-Sekunden-Lease hinterlassen und die 12-Sekunden-Erwartung der Fixture verletzen.
Die eigenständigen Reload- und vollständigen Browserneustart-Tests bleiben erhalten.
Den aktuellen CI-Stand zeigt
[PR #178](https://github.com/joni123467/Erfassung/pull/178); dieser Bericht ist
kein Nachweis einer Containerveröffentlichung.

Die direkten Python-Abhängigkeiten wurden nicht geändert. `requirements.lock`
fixiert zusätzlich ihre transitiven Versionen mit Hashes. Neue, ausschließlich
für Tests verwendete npm-Abhängigkeiten: `@playwright/test` 1.64.1 und
`fake-indexeddb` 6.2.7; ihre Auflösung ist in `package-lock.json` festgelegt.
Es wurden keine zusätzlichen Laufzeit-Frameworks oder externen Dienste eingeführt.

Verwendeter Skill: `cloud-environment-onboarding:setup` für Installation,
Startprüfung und gespeicherte Cloud-Konfiguration. Keine weiteren Skills wurden
installiert. Setup- und Startanweisungen sind als Konfigurationsentwurf gespeichert;
dieser Vorgang aktiviert oder veröffentlicht die Umgebung nicht.

## Offene Abnahmen und Betriebsgrenzen

- **Lokaler WebKit-Test nachgeholt:** der Download war zunächst blockiert,
  funktioniert inzwischen aber für WebKit. Fehlende Debian-Bibliotheken wurden
  aus signierten Paketquellen isoliert im lokalen Browser-Bundle ergänzt und
  ihre Ladefähigkeit geprüft. Die globale ldconfig-Vorprüfung wurde nur lokal
  übersprungen, weil diese Bibliotheken außerhalb der Systemverzeichnisse
  liegen. GitHub installiert Browser und Systembibliotheken regulär über
  `playwright install --with-deps`; dort wird keine Vorprüfung abgeschaltet.
- **Physisches iOS-Gerät:** kein realer Test über sieben Kalendertage,
  Betriebssystem-Updates, Speicherbereinigung oder Energiesparmodus. Automatisiert
  wurde das Alter der Ereignisse simuliert; das ist kein siebentägiger Gerätetest.
- **Externe Datenbanken/Integrationen:** SQLite wurde live geprüft. Keine neue
  vollständige Live-Matrix zwischen MySQL, MariaDB und PostgreSQL und keine
  echten externen Backup-/Terminaldienste. Vor einer entsprechenden Veröffentlichung
  gelten zusätzlich die Release-Prüfpflichten aus `AGENTS.md`.
- **iOS-Hintergrundbetrieb:** eine suspendierte oder geschlossene PWA kann nicht
  zuverlässig übertragen. Start, Rückkehr in den Vordergrund, Netzrückkehr und
  manueller Abgleich lösen die Wiederholung aus.
- **Browserdaten:** Deinstallation, manuelles Löschen oder Betriebssystem-
  Speicherbereinigung können lokale Daten entfernen. Die Anwendung verhindert
  eigenes vorzeitiges Löschen und stellt Sicherungsfunktionen bereit; eine
  absolute Garantie gegen Löschung durch das Betriebssystem ist nicht möglich.
- **Einmaliger Altclient-Übergang:** ältere PWAs ohne Updatehinweis gegebenenfalls
  vollständig schließen und wieder öffnen. Installation und Website-Daten behalten,
  erfolgreichen Versionswechsel kontrollieren. Ein Serverupdate ersetzt keinen
  bereits geladenen alten Clientcode.

## Reproduzierbare Kommandos

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install pytest==8.3.5
ERFASSUNG_DISABLE_SCHEDULER=1 python -m pytest -q
npm ci
npm test
npx playwright install --with-deps chromium webkit
npm run test:browser
docker build -t erfassung:0.21.0 .
```

Tests in einer separaten Shell ohne produktive DB-Pfadvariablen ausführen.
Die Test-Fixtures verwenden eigene Datenbanken, Konfigurationen und Lizenzen.
Für den vorhandenen Cloud-Chromium:
`ERFASSUNG_CHROMIUM_PATH=/usr/bin/chromium npm run test:browser -- --project=chromium`.

Die Commits trennen Synchronisation/Oberfläche/Tests und reproduzierbare
Container-/CI-Prüfungen. Ihre endgültigen IDs stehen im Abschlussbericht und
in `git log` auf `version-0.21.0`.

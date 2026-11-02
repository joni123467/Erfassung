# PWA-Synchronisation ab 0.21.0

Zielplattform ist eine installierte iOS-PWA pro Benutzer in Deutschland. Eine
mindestens siebentägige Offlinephase darf ausstehende Ereignisse nicht verwerfen.
Die folgenden Zusicherungen gelten, solange der Browser seine Website-Daten
behält. Deinstallation, manuelles Löschen und eine Speicherbereinigung durch das
Betriebssystem können Browserdaten entfernen; keine Webanwendung kann dies
absolut verhindern. Die PWA bittet um persistenten Speicher, soweit unterstützt,
und bietet einen Export und eine additive Wiederherstellung der Buchungen an.

## Befund und Grenzen der Ursachenzuordnung

Gemeldet wurde ein Synchronisationsausfall nach einem Update und ungefähr sieben
Tagen Nichtbenutzung; nach Neuinstallation funktionierte der Abgleich wieder.
Die betroffene Installation wurde bereits neu eingerichtet. Ihr damaliger
IndexedDB-, Cache- und Sitzungszustand steht daher nicht zur Verfügung.

Im bisherigen Code wurden vier Fehlerpfade isoliert reproduziert:

- `retryable: true` wurde beim Leeren der Queue ignoriert; das Ereignis wurde
  gelöscht und gegebenenfalls trotzdem vollständiger Erfolg angezeigt.
- HTTP 200 ohne lesbares JSON galt als erfolgreiche Buchungsbestätigung.
- Ohne IndexedDB kehrten Speicheraufrufe erfolgreich zurück, obwohl nichts
  gespeichert wurde.
- Ein fehlgeschlagener Metadaten-Schreibvorgang vor `try/finally` ließ die
  Synchronisationssperre dauerhaft gesetzt.

Hinzu kamen ungefilterte Cache-Bereinigung, nicht geschlossene DB-Verbindungen,
sofortige Worker-Aktivierung mit Reload, fehlende Wiederholungsplanung,
Benutzerwechsel ohne Outbox-Zuordnung sowie getrennte Commits für Buchung und
Dublettennachweis. Ein weiterer Browserbefund war ein falscher Ausgangszustand:
Die statische Hülle setzte eine bestätigte laufende Buchung nach Offline-Neustart
auf „bereit“. Diese Fehler erklären mögliche Ausfälle und Verluste. Sie beweisen
nicht, welcher einzelne Auslöser das bereits zurückgesetzte iOS-Gerät traf.

## Persistenz und Eigentümer

`static/mobile-sync.js` wird von Mobilseite und Service Worker verwendet.
IndexedDB `erfassung-mobile`, Version 5, behält die bisherigen Stores und ihre
Schlüssel: `pendingActions`, `mobileData`, `meta`. Die Migration löscht nichts.
Verbindungen schließen bei `versionchange`; eine blockierte Öffnung meldet nach
fünf Sekunden einen Fehler. Nur `transaction.oncomplete` bestätigt eine Speicherung.

Jedes Ereignis erhält eine UUID, Benutzer-ID, ursprünglichen Zeitpunkt und eine
über Tabs hinweg monoton geordnete Erstellungszeit. Die Oberfläche bestätigt erst
nach dem dauerhaften Einreihen. Ohne nutzbaren Speicher oder Kontozuordnung gibt
es eine Fehlermeldung statt einer Erfolgsmeldung. Ausstehende Ereignisse haben
keine altersbasierte Löschfrist. ISO-Zeitstempel neuer Ereignisse enthalten UTC;
die Fachlogik übernimmt sie in der Betriebszeitzone (Deutschland: Europe/Berlin).

Alte Queue-Einträge werden anhand des letzten authentifizierten Snapshots dem
ursprünglichen Benutzer zugeordnet. Fehlt dieser Nachweis, erfolgt keine
stillschweigende Übernahme: Export und ausdrückliche Zuordnung nach Anmeldung
stehen in den Sync-Details bereit. Bei abweichendem Konto wird nicht übertragen.
Eine Sicherung wird nur in das passende Konto importiert; bestehende IDs mit
abweichenden Inhalten werden nicht überschrieben.

## Übertragungsprotokoll 1

`GET /api/mobile/session` liefert den angemeldeten Benutzer, ein aktuelles
CSRF-Token und die unterstützte Protokollversion. Die Outbox benötigt keinen
erfolgreichen Download der vollständigen Berichte, um Buchungen zu senden.

`POST /api/mobile/actions` erhält `protocol`, `owner_id`, `client_action_id`,
`kind` (punch/vacation) und `payload`. CSRF- und Sitzungsprüfung bleiben aktiv.
Der Server prüft die Zuordnung gegen die angemeldete Sitzung. Eine Bestätigung
enthält dieselbe Benutzer-/Aktions-ID, die Protokollversion, `received: true`,
eine numerische `receipt_id` und genau einen Zustand:

| Zustand | Bedeutung | Verhalten auf dem Gerät |
| --- | --- | --- |
| applied | Fachlich verbucht | Bestätigung archivieren, Outbox-Eintrag atomar entfernen |
| conflict | Sicher empfangen, fachlich ungeklärt | Original behalten, Freigabe anzeigen, nachfolgende Ereignisse anhalten |
| rejected | Berechtigt und begründet abgelehnt | Original/Entscheidung archivieren, Begründung sichtbar halten |

HTML, Weiterleitungen, unvollständige oder unpassende Bestätigungen sind kein
Erfolg. Bei HTTP-/Netzwerkfehlern, Zeitüberschreitung und abgelaufener Anmeldung
bleiben die Ereignisse erhalten. Wiederholungen verwenden immer dieselbe ID.
Die Wartezeit steigt mit Zufallsanteil bis ungefähr einer Minute; manueller
Abgleich, erneute Verbindung und App-Resume können sofort wiederholen.

Ein atomarer, erneuerbarer IndexedDB-Lease (30 Sekunden) koordiniert Tabs und
Worker. Nach einem Prozessabbruch verfällt er. Das lokale Lauf-Flag wird auch
bei Speicherfehlern freigegeben. Antworten und ihre vollständige JSON-Nutzlast
unterliegen einem Timeout. Der Snapshot wird erst nach dem Upload aktualisiert;
bestätigte Ereignisse nach dem letzten Snapshot dienen bis dahin als lokale
Anzeigegrundlage. „Synchronisiert“ bedeutet eine leere Outbox und einen
vollständigen Abgleich, nicht bloß einen erfolgreichen Ping.

## Atomare Verarbeitung und Konfliktfreigabe

Migration 25 erzeugt `mobile_sync_receipts` einschließlich Unique-Index auf
Benutzer und Aktions-ID. Originaldaten, Payload-Hash, Status, Begründung und
Entscheider bleiben erhalten. Existierende Erfolgsmarker werden erkannt.

SQLite beginnt vor dem Lesen mit `BEGIN IMMEDIATE`; andere SQL-Backends sperren
die Benutzerzeile. Die bestehende Fachlogik arbeitet in Savepoints innerhalb
einer äußeren Transaktion. Buchung, Revisionen, Dublettennachweis und Quittung
werden gemeinsam bestätigt. Scheitert ein Teilschritt, werden dessen Änderungen
zurückgerollt; ein fachlicher Konflikt wird anschließend dauerhaft gespeichert.
Auch ältere Formular-Endpunkte mit Aktions-ID verwenden die äußere Transaktion.

`Time.Sync.Resolve` ist ein eigenes Recht mit den üblichen Geltungsbereichen
selbst/Gruppen/alle. Systemadministratoren erhalten es über die bestehende
Rollensynchronisation; individuelle Rollen müssen es ausdrücklich erhalten.
Unter Administration → Zeiterfassung → Synchronisationskonflikte lassen sich
Originalzeitpunkt und Konflikt prüfen, der Zeitpunkt bei Bedarf begründet
korrigieren und die Buchung erneut anwenden oder begründet ablehnen. Bestehende
Buchungen werden dabei nicht automatisch überschrieben. Jede Entscheidung steht
im Auditlog, die Bearbeitung in den dauerhaften Empfangsdaten. Ein bloßes Recht
zum Freigeben manueller Nachträge genügt nicht.

Die neue Tabelle wird über beide Schemawege angelegt und als normale
SQLAlchemy-Tabelle in logische Backups und Restore aufgenommen. Vor einem
Produktivupdate bleibt ein reguläres Backup erforderlich. Alte Backups ohne die
Tabelle bleiben lesbar; neue Empfangsdaten können aus alten Backups naturgemäß
nicht rekonstruiert werden.

## Service Worker und Releases

Der Worker installiert die komplette statische Hülle und ihre versionierten
Assets, bevor er als wartend verfügbar ist. Er cached keine personalisierte
HTML-Seite und keine API-/Sitzungsantworten. Dateien eines aktiven Releases
werden nicht im Hintergrund durch die Dateien eines anderen Releases ersetzt.
Nur eigene Cache-Namen werden bereinigt; ein Vorgänger bleibt für den Übergang.

Ein Update wird angezeigt und ausdrücklich angenommen. Alle offenen mobilen
Fenster müssen ihre laufenden Speicher-/Sync-Vorgänge und Eingaben abgeschlossen
haben. Während der Aktivierungszusage werden neue Eingaben kurz gesperrt. Ein
Veto oder verschwundenes Fenster führt zu keiner dauerhaften Sperre. Der
anschließende Reload liest die unveränderte Outbox wieder ein. Laufende,
bereits gespeicherte Arbeitszeit wird dadurch nicht beendet.

Für den erstmaligen Wechsel von einer alten PWA ohne Updatehinweis kann es
nötig sein, alle Erfassung-Fenster vollständig zu schließen und wieder zu
öffnen. Die Installation und ihre Website-Daten behalten; nicht deinstallieren
und keine offenen Buchungen löschen. Alte Clients können ihre bisherigen
Formular-Endpunkte weiterverwenden, besitzen aber noch nicht die neuen lokalen
Schutzmaßnahmen. Im Betrieb müssen aktualisierte PWA-Versionen kontrolliert
werden; ein Backendupdate allein repariert keinen bereits laufenden alten JS-Code.

Jedes Release ändert VERSION und damit die Workerbytes. Bereits veröffentlichte
Versionen/Assets nicht unter unveränderter Versionsnummer austauschen. Ein
Rollback auf Code mit älterer IndexedDB-Version ist kein verlustfreier
Client-Downgrade; vorwärtskompatible Korrekturreleases bevorzugen.

## iOS und Wiederanlauf

Bei Start, Rückkehr in den Vordergrund, `pageshow`, Netzrückkehr und manuellem
Abgleich wird synchronisiert; bei sichtbarer App zusätzlich alle 15 Sekunden
unter Beachtung des Backoffs. Unterstützt ein Browser Background Sync, kann der
Worker dieselbe Outbox übertragen. iOS bietet dies nicht zuverlässig an: Eine
geschlossene/suspendierte App muss zum Übertragen wieder geöffnet werden.

Sieben Tage alte Stempelungen und eine abgelaufene Sitzung sind automatisiert
prüfbar. Ein tatsächlicher siebentägiger iOS-Dauertest, Speicherbereinigung durch
das Betriebssystem und Geräte-Energiesparmodi müssen zusätzlich auf einem
physischen Gerät geprüft werden. WebKit unter Linux ersetzt diesen Gerätetest
nicht.

## Entwicklung und Prüfung

Python 3.11, `pip install --require-hashes -r requirements.lock`, danach
`pip install pytest==8.3.5`. `pytest -q` führt die Python-Suite aus.
`requirements.txt` bleibt die Liste direkter Abhängigkeiten; den Hash-Lock bei
beabsichtigten Updates mit `uv pip compile --python 3.11 --generate-hashes
--output-file requirements.lock requirements.txt` neu erzeugen und prüfen.

`npm ci && npm test` prüft Persistenz und Koordination mit fake-indexeddb.
`npx playwright install --with-deps chromium webkit && npm run test:browser`
prüft Browser-/Service-Worker-Verhalten mit eigenen Benutzern und einer
isolierten temporären SQLite-Instanz. Für einen vorhandenen Chromium kann
`ERFASSUNG_CHROMIUM_PATH=/usr/bin/chromium` gesetzt werden. Die Testserver-Hooks
liegen ausschließlich in `tests/browser/`; es gibt keine Produktions-Test-API.

`docker build -t erfassung:0.21.0 .` nutzt den Hash-Lock. In einer Umgebung mit
vertrauenswürdigem Unternehmens-/Cloud-CA-Bundle kann BuildKit dieses via
`--secret id=build_ca,src=/pfad/zum/ca-bundle.pem` nur während der Installation
bereitstellen. TLS-Verifikation bleibt aktiv; das Bundle wird nicht ins Image
kopiert. Deployment bleibt Docker/GHCR/Portainer mit config/data/logs.
GitHub Actions prüft Python, JavaScript, Chromium/WebKit und Containerstart vor
der Imageveröffentlichung. Ein lokaler Testlauf ist keine Bestätigung eines
bereits ausgeführten GitHub-Actions-Laufs.

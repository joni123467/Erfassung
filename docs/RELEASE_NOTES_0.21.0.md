# Release Notes 0.21.0

Diese Version sichert die PWA-Synchronisation gegen nachgewiesene Verlust- und
Blockadepfade ab. Schwerpunkt sind installierte iOS-PWAs nach Updates und
längerer Nichtbenutzung. Die bestehende FastAPI-/Jinja-/JavaScript-Anwendung und
das Docker-/GHCR-/Portainer-Deployment bleiben erhalten.

## Behobene Ursachen

Wiederholbare Ablehnungen wurden bisher aus der Warteschlange gelöscht, HTTP
200 ohne lesbares JSON wurde als Erfolg behandelt, fehlendes IndexedDB konnte
eine Speicherung vortäuschen und ein Speicherfehler konnte die Synchronisation
dauerhaft sperren. Diese Pfade wurden isoliert nachgestellt und durch
Verhaltenstests abgesichert. Die bereits neu installierte betroffene iOS-PWA
lässt keine nachträgliche eindeutige Zuordnung ihres konkreten Ausfalls zu.

Zusätzlich wurden Kontozuordnung, konkurrierende Übertragungen, abgelaufene
Anmeldungen, Offline-Anzeige und der Update-Lebenszyklus abgesichert. Der
bisherige Cache-Löschknopf kann keine offenen Aktionen mehr entfernen.

## Neue Verarbeitung

- Jede Buchung wird vor einer lokalen Erfolgsmeldung in IndexedDB bestätigt.
- Die gemeinsame Outbox für Seite und Worker erhält unveränderliche IDs,
  Benutzerzuordnung, Wiederholungsstatus und Backoff.
- Der Server bestätigt ein Ereignis ausdrücklich mit passender Benutzer-/ID-
  Zuordnung. Buchung, Revisionen und Dublettennachweis werden atomar gespeichert.
- Konflikte werden dauerhaft erfasst und sichtbar gemacht; nachfolgende
  Ereignisse bleiben in Reihenfolge auf dem Gerät. Auch abgewiesene Aktionen
  älterer Clients mit Aktions-ID werden serverseitig zur Prüfung gesichert.
- Eine erneute Anmeldung oder ein Update löscht keine offenen Buchungen.
- Export und additive Wiederherstellung sichern Original-IDs; bestehende
  abweichende Ereignisse und fremde Konten werden nicht überschrieben.

## Freigabe und Oberfläche

Unter Administration → Zeiterfassung → **Synchronisationskonflikte** prüfen
Berechtigte Originalereignis und Zeitpunkt. Sie können eine Buchung begründet
noch einmal anwenden, bei Bedarf den Zeitpunkt korrigieren oder sie begründet
ablehnen. Das Original bleibt erhalten, die Entscheidung wird protokolliert.
Das neue Recht **`Time.Sync.Resolve`** besitzt die üblichen Geltungsbereiche.
Individuelle Rollen erhalten es nicht automatisch; Systemrollen werden aktualisiert.

Die mobile Oberfläche zeigt dauerhaft, ob Buchungen lokal gespeichert,
übertragen, offline, fehlerhaft oder zur Freigabe offen sind. Anmeldebedarf und
verfügbare Updates haben eigene Aktionen. Die Darstellung verwendet die
bestehenden Designtokens und funktioniert auch bei schmalem Bildschirm und im
Dark Mode. Eine außerhalb des Bildschirms liegende Hinweisblase wurde korrigiert.

## Updates, Migration und Betrieb

IndexedDB Version 5 behält die vorhandenen Stores und Ereignisse. Eine fehlende
Legacy-Kontozuordnung wird nicht geraten. Der Service Worker verwendet eine
neutrale Offline-Hülle und versionierte Assets. Updates warten auf Zustimmung
und abgeschlossene Eingaben/Übertragungen aller offenen mobilen Fenster.

Migration **25** legt `mobile_sync_receipts` datenerhaltend und wiederholbar an;
die automatische Schemaergänzung und der versionierte Runner sind angepasst.
Logische Backups enthalten die neue Tabelle. Ältere Backups bleiben einlesbar.
Konfiguration, Geschäftsdaten und Logs bleiben in ihren bisherigen Volumes.

Für das erstmalige Update älterer PWA-Versionen ohne Updatehinweis gegebenenfalls
alle Erfassung-Fenster schließen und erneut öffnen. **Keine Neuinstallation,
kein Löschen der Website-Daten.** Im Betrieb die erfolgreiche Aktualisierung
kontrollieren. Ein neuer Server allein ersetzt keinen bereits geladenen alten
Clientcode.

Der Container verwendet einen festgelegten Basisimage-Digest sowie einen
Hash-geprüften Abhängigkeits-Lock. Compose prüft den funktionalen Health-Endpunkt.
GitHub Actions führt Python-, JavaScript- und Chromium/WebKit-Tests sowie einen
Containerstart mit Neustartprüfung vor dem Publishing als getrennte Checks aus.
Browserfehler werden direkt an der Teststelle annotiert. Die Simulation von
Netzabbrüchen und falschen HTTP-Antworten erfolgt im isolierten Testserver;
Playwright-Routing allein erfasst Service-Worker-Anfragen unter WebKit nicht
zuverlässig.

## Nachweise und Grenzen

Die automatisierten Prüfungen decken Offline-Ereignisse über sieben Tage,
Neuanmeldung, parallele Übertragung, Verbindungsabbruch nach Servercommit,
Konfliktfreigaben, unpassende Antworten, alte IndexedDB-Daten und kontrollierte
Workerwechsel ab. Die konkreten Ausführungsergebnisse stehen im
[Prüfbericht](QA_0.21.0.md).

Auf iOS wird bei geöffneter App und bei Rückkehr in den Vordergrund abgeglichen.
Eine geschlossene/suspendierte PWA kann nicht zuverlässig im Hintergrund laufen.
Deinstallation, manuelles Löschen und Betriebssystem-Speicherbereinigung können
Browserdaten entfernen. Ein realer iOS-Gerätetest über eine Woche bleibt eine
eigene Abnahme; simuliertes Ereignisalter und Linux-WebKit ersetzen ihn nicht.

Technik, Wiederherstellung, Rollout und Tests:
[Synchronisationsarchitektur](PWA_SYNCHRONISATION.md).

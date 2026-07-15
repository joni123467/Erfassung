# Release Notes 0.9.13

## Überblick

Wartungsrelease für die PWA: Installierte Apps – insbesondere auf iOS –
erkennen neue Versionen jetzt zuverlässig und aktualisieren sich automatisch.
Zuvor konnte eine installierte PWA dauerhaft auf einem alten Stand hängen
bleiben (Symptom: Synchronisation funktionierte erst nach Neuinstallation
wieder). Außerdem dokumentiert: die PWA ist auch am Desktop/PC nutzbar.

## Fehlerbehebungen

### PWA-Updates erreichen installierte Geräte

Ursache des Problems: Die App-Version steckte nur in der
Service-Worker-Registrierungs-URL (`/sw.js?v=…`). Die installierte PWA lädt
`/mobile` jedoch aus dem Service-Worker-Cache – die alte Seite registrierte
wieder die alte URL, das Skript selbst war byte-identisch, und der Browser
erkannte nie ein Update. Behoben durch mehrere Maßnahmen:

1. **Version im Skriptinhalt**: `GET /sw.js` brennt die Version in den
   Skriptinhalt ein (`self.__ERFASSUNG_VERSION`). Jedes Release ändert damit
   die Bytes des Workers – der Update-Check des Browsers greift immer,
   unabhängig davon, wie alt die registrierende Seite ist.
2. **Aktive Update-Prüfung**: Registrierung mit `updateViaCache: 'none'`;
   `registration.update()` bei jedem App-Start, beim Zurückholen in den
   Vordergrund (App-Resume) und sobald ein Sync eine geänderte
   Server-Version meldet.
3. **Einmaliger Auto-Reload**: Übernimmt der neue Worker die Kontrolle, lädt
   sich die Seite einmalig neu – frische Assets sind sofort aktiv. Kein
   Reload bei Erstinstallation, kein Reload-Loop; ausstehende
   Offline-Aktionen bleiben erhalten (IndexedDB).
4. **Saubere Asset-Übernahme**: Beim Installieren lädt der Worker die Assets
   mit `cache: 'no-cache'`, damit kein staler HTTP-Cache in die neue
   Cache-Version gelangt.
5. **Konstante Registrierungs-URL**: Die Registrierung nutzt `/sw.js` ohne
   `?v=`-Parameter. Zuvor verlor `app.js` beim Ausliefern aus dem
   Service-Worker-Cache seinen Versionsparameter (`import.meta.url` ohne
   `?v`) und registrierte `/sw.js?v=dev` – der Worker lief dann mit dem
   Cache-Namen `erfassung-mobile-vdev`, wodurch die versionsbasierte
   Cache-Rotation auf installierten Geräten komplett ausgehebelt war. Genau
   das erklärte das beobachtete Verhalten, dass Updates erst nach einer
   Neuinstallation der PWA ankamen.

## Neue Funktionen

### Synchronisation bei App-Resume

Beim Wechsel der PWA in den Vordergrund (`visibilitychange`) wird automatisch
synchronisiert. Bisher geschah das nur beim Seitenstart und beim
`online`-Ereignis – eine tagelang im Hintergrund geparkte iOS-PWA
synchronisierte daher nicht mehr.

## PWA am Desktop/PC

Die mobile Oberfläche (`/mobile`) läuft auch im Desktop-Browser – ohne
Installation oder als installierte App (Chrome/Edge: Symbol in der
Adressleiste bzw. Menü → „App installieren"). Details im neuen
README-Abschnitt „PWA am Desktop/PC verwenden".

## Datenbank

Keine Schemaänderungen; keine Migration erforderlich.

## Upgrade-Hinweise

Standard-Update genügt. **Einmalig** benötigen bereits installierte PWAs noch
einen Start mit Serververbindung, damit der neue Update-Mechanismus aktiv
wird (der Browser erkennt das geänderte `/sw.js` beim nächsten
Navigations-/Update-Check); ab dann kommen Updates automatisch an. Hängt ein
Gerät sehr weit zurück, hilft letztmalig Neuinstallation oder „Website-Daten
löschen".

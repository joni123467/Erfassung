# Release Notes 0.22.2

Eine Wiederverbindung oder ein Klick auf „Erneut synchronisieren“ konnte
während eines bereits laufenden Abgleichs seine Anforderung zum sofortigen
Wiederholen verlieren. Die Buchung blieb gespeichert, musste aber auf einen
späteren automatischen Versuch warten. Die Anforderung wird jetzt bis zur
Verarbeitung im aktuellen Durchlauf oder im Folgelauf beibehalten.

Kontozuordnung, Reihenfolge, Sperre zwischen Fenstern und Prüfung der
Empfangsbestätigung gelten unverändert. Es wird keine Buchung allein aufgrund
eines erneuten Versuchs aus der Warteschlange entfernt.

## Prüfung des Offline-Neustarts

Der Veröffentlichungsworkflow für 0.22.1 scheiterte nach dem Merge an einer
zwölfsekündigen Erwartung im Chromium-Test zum Ausstempeln nach einem
Offline-Neustart. Ein unterbrochenes Fenster kann jedoch seine bis zu
30 Sekunden gültige Synchronisationssperre hinterlassen. Die sichtbare App
versucht den Abgleich alle 15 Sekunden erneut.

Die betroffenen Wiederanlaufprüfungen verwenden deshalb gemeinsam ein
50-Sekunden-Fenster innerhalb eines 75-Sekunden-Testbudgets. Normale
Online-Stempelungen und unmittelbare Wiederholungsversuche bleiben bei ihren
kurzen Zeitlimits. Es gibt keine globalen Testwiederholungen.

Die GitHub-Prüfung startet für Pull Requests und deren weitere Commits sowie
unverändert vor jeder Image-Veröffentlichung. Der zusätzliche Branch-Push-Lauf
entfällt: Er startete dieselbe Suite doppelt und hinterließ durch gegenseitiges
Abbrechen irreführende `cancelled`-Checks. Ein Branch ohne Pull Request startet
keinen separaten Prüflauf; die sechs vollständigen PR-/Release-Prüfungen bleiben.

Der gemeldete Fall wird gezielt mit einer verwaisten Sperre reproduziert:
Arbeitsbeginn bestätigen, offline neu laden, Arbeitsende lokal speichern,
wieder verbinden und die automatische Übertragung abwarten. Der Test prüft
danach genau eine geschlossene Buchung, unveränderte Ereignis-IDs und zwei
passende Empfangsbestätigungen. Er leert keine Warteschlange, löscht keine
Sperre und klickt nicht manuell auf Wiederholen. Drei JavaScript-Tests halten
zusätzlich Sitzung, Übersichtsladen beziehungsweise Sperrfreigabe kontrolliert an und prüfen,
dass eine dazwischen eintreffende Wiederholungsanforderung erhalten bleibt.

## Aktualisierung

Nach Merge und erfolgreichem Workflow **Build and publish container to GHCR**
in Portainer das Image auf `ghcr.io/joni123467/erfassung:0.22.2` setzen.
Vorhandene Einbindungen für `config`, `data` und `logs` beibehalten.

Keine neue Datenbankmigration; Schema 26, Konfiguration, Anmeldeschlüssel,
Outboxformat und vorhandene Buchungen bleiben erhalten. Die Korrekturen am
Betriebsdatum aus 0.22.1 und die Oberfläche aus 0.22.0 sind enthalten.

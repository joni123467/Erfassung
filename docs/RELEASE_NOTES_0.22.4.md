# Release Notes 0.22.4

## Handy, PC und vergessenes Ausstempeln

Die PWA gleicht vor einer Online-Stempelung den Buchungsstand ab. Hat ein
anderes Gerät inzwischen gestempelt, zeigt sie den aktuellen Zustand und bittet
darum, die gewünschte Aktion erneut auszuwählen. Neue Ereignisse enthalten den
bekannten Lauf-/Pausenzustand und den ursprünglichen Beginn. Der Server prüft
diesen Bezug innerhalb seiner bestehenden Benutzersperre. Eine alte
Aus-/Pausenstempelung darf dadurch keine inzwischen neue Arbeitszeit verändern.
Gleichzeitig gestartete oder widersprüchliche Offline-Ereignisse bleiben als
nachvollziehbare Konflikte erhalten; es wird kein tatsächliches Arbeitsende geraten.

Ab zwölf Stunden Laufzeit erscheint „Ausstempeln vergessen?“. Beim Beenden oder
Auftragswechsel fragt die PWA nach, ob durchgehend gearbeitet wurde. Alternativ
lässt sich ein früheres tatsächliches Ende mit Begründung eingeben. Das schließt
nur die zuvor angezeigte Arbeitszeit; einen gewünschten neuen Auftrag danach
separat starten. Die zwölf Stunden sind eine Erinnerung, keine Arbeitszeitgrenze.

Die Korrektur wird vor der Übertragung lokal gespeichert. Nach Offline-Neustart
bleiben Zeitpunkt und ursprünglicher Buchungsbezug erhalten. Serverseitig sind
Beginn, Buchungs-ID (wenn bekannt), Endzeit und bereits erfasste Pausen geschützt.
Begründung und Bearbeiter stehen in der Buchungshistorie. Eine bereits beendete
oder inzwischen andere Buchung erfordert Prüfung. Echte lange Dienste können
ausdrücklich bestätigt werden, ohne die erfasste Dauer zu begrenzen.

## Verständliche Konfliktursachen

Bei einer fehlgeschlagenen Stempelung konnte die PWA „Auftrag läuft bereits“
anzeigen, obwohl eine Überschneidung oder eine gesperrte Abrechnungsperiode
die Buchung verhinderte. Die JSON-Antwort bevorzugte einen allgemeinen
Statustext gegenüber der eigentlichen Fehlerursache. Sie gibt jetzt wie die
HTML-Antwort den Fehler aus. Das gilt auch beim erneuten Prüfen bestehender
Synchronisationskonflikte und für ältere Formular-Clients.
Die PWA nennt Ursache und Bearbeitungsweg direkt im Synchronisationsstatus,
auch nach Neuladen. Beim Wiederherstellen des lokalen Zustands bleiben die
originalen Stempelzeitpunkte erhalten; bestätigte Beginnzeitpunkte enthalten
den UTC-Versatz, damit der Gerätevergleich nicht von der Gerätezeitzone abhängt.

## Bestehende Konflikte bearbeiten

1. Ausstehende Buchungen in der PWA über „Details & Sicherung“ exportieren.
2. Unter Administration → Zeiterfassung → Synchronisationskonflikte den
   betroffenen Vorgang mit Begründung erneut „Prüfen und verbuchen“. Nach dem
   Update wird dabei auch ein zuvor verdeckter Fehler sichtbar.
3. Bei einer Überschneidung vorhandene Zeiten anhand des tatsächlichen
   Arbeitsablaufs korrigieren. Ein Beispiel: Ein Auftragsstart um 11:35 Uhr
   kollidiert mit einer allgemeinen Buchung von 10:52 Uhr bis 02:14 Uhr am
   Folgetag. Fand der Wechsel tatsächlich um 11:35 Uhr statt, endet der
   allgemeine Abschnitt dort. Den Offline-Start unverändert erneut prüfen.
4. Nach erfolgreicher Prüfung in der PWA „Jetzt abgleichen“ auswählen und
   die folgenden Buchungen und Endzeiten kontrollieren.

„Prüfen und verbuchen“ erzwingt keine Überschreibung. Nur tatsächlich doppelte
Ereignisse nach Prüfung begründet ablehnen. Die PWA und ihre Website-Daten
behalten; die Änderung allein löst keine bestehenden Zeitkonflikte auf.

## Daten und Aktualisierung

Keine Schemaänderung: Schema 26, Originaldaten der Synchronisation,
Berechtigungen und lokale Buchungen bleiben erhalten. Bestehende Fehlermeldungen
werden bei einer ausdrücklichen erneuten Prüfung aktualisiert; bloßes Wiederholen
derselben Übertragung liefert weiterhin die gespeicherte Empfangsbestätigung.

Nach Merge und erfolgreichem Veröffentlichungsworkflow das Image
`ghcr.io/joni123467/erfassung:0.22.4` laden. Vorhandene Einbindungen für
`config`, `data` und `logs` beibehalten. Kein Zurücksetzen der PWA erforderlich.
Das PWA-Update auf Handy und PC annehmen. Bereits gespeicherte Ereignisse älterer
Versionen bleiben verarbeitbar, enthalten aber noch keinen Geräte-Zustandsbezug.

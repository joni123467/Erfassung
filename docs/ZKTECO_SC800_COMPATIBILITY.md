# ZKTeco SC800 – Kompatibilitätsbericht

Stand: 7. September 2026. **Firmware- und Realgerätetest stehen aus.** „Verifiziert“ bedeutet daher nur: in öffentlich zugänglichem Hersteller-Material für das SC800 nachgewiesene Hardware-/Produkteigenschaft, nicht ein erfolgreicher Test dieses Repositories am Gerät.

Quellenbasis: ZKTeco-Produktseite/-Datenblatt zum SC800 sowie die ZKTeco-PUSH/ADMS-Protokollfamilie. Das gerätespezifische, vollständige **SC800 T&A PUSH Protocol Manual inklusive Firmware-Matrix und Command-Satz lag bei der Implementierung nicht vor**. Community-Code wurde nicht als Beleg für SC800-Produktionseigenschaften behandelt.

| Funktion | Status | Implementiert | Bemerkung |
|---|---|---:|---|
| RFID lesen | VERIFIZIERT | indirekt | SC800-Hardwarefunktion; die Serverzuordnung ist vorhanden. Ob die Kartennummer im konkreten ATTLOG übertragen wird, muss erfasst werden. |
| PIN | VERIFIZIERT | nein | Gerät kann PIN; PINs werden absichtlich weder angenommen noch gespeichert. |
| A&C Push / Konvertierung zu T&A Push | VERIFIZIERT | nein | Hersteller nennt die Fähigkeit; Aktivierung/Menübezeichnung ist firmwareabhängig. |
| T&A Push | WAHRSCHEINLICH / NOCH ZU TESTEN | ja, konservativer Eingang | `/iclock/cdata` und `/iclock/getrequest`; SC800-Firmware am Realgerät prüfen. |
| ATTLOG-Ereignisse empfangen | WAHRSCHEINLICH / NOCH ZU TESTEN | ja | Tab-getrennte User-ID, lokale Zeit, Status, Verify, Work Code; abweichende Feldsätze werden nicht geraten. |
| Offline-Ereignisse | WAHRSCHEINLICH / NOCH ZU TESTEN | serverseitig ja | Batch wird chronologisch verarbeitet und dedupliziert; Retry-Verhalten des Geräts testen. |
| Mitarbeiter/Karten übertragen | NICHT VERFÜGBAR / NICHT DOKUMENTIERT | nein | Exakter SC800-Command-Satz, Escaping, Limits und ACK-Semantik fehlen. |
| Benutzer ändern/löschen | NICHT VERFÜGBAR / NICHT DOKUMENTIERT | nein | Kein geratenes `DATA UPDATE`/`DELETE` in Produktionscode. |
| Karte anlernen | NICHT VERFÜGBAR / NICHT DOKUMENTIERT | manuelle Alternative | Karte wird im Adminbereich eingetragen; Event-/Capture-Workflow muss am Gerät verifiziert werden. |
| Uhr/Zeitzone synchronisieren | NICHT VERFÜGBAR / NICHT DOKUMENTIERT | nein | Command und DST-Verhalten der konkreten Firmware fehlen. |
| Firmware auslesen | WAHRSCHEINLICH / NOCH ZU TESTEN | Datenfeld vorbereitet | Verbindungsparameter der Firmware müssen per Capture bestätigt werden. |
| Heartbeat/Status | WAHRSCHEINLICH / NOCH ZU TESTEN | ja | `getrequest` aktualisiert letzten Kontakt; Online-Anzeige basiert auf Push-Kontakt. |
| Remote Reboot | NICHT VERFÜGBAR / NICHT DOKUMENTIERT | nein | Kein Befehl ohne offizielle Command-Dokumentation. |
| HTTPS | VERIFIZIERT | serverseitig ja | Hersteller nennt HTTPS; Zertifikats-/SNI-Unterstützung der Firmware testen. |
| Communication Key | WAHRSCHEINLICH / NOCH ZU TESTEN | serverseitige Option | SHA-256-Hash eines vorgeschalteten `X-Terminal-Key`; native Geräteübertragung dieses Headers ist **nicht** belegt. Alternativ Proxy-mTLS/IP-Allowlist. |

## Fehlende Nachweise vor Produktionsfreigabe

Benötigt wird das zur installierten Firmware passende offizielle SC800-PUSH-Handbuch oder ein freigegebener HTTPS-Mitschnitt: exakte Initialantwort auf `cdata`, Queryparameter, ATTLOG-Feldzahl/-bedeutung (insbesondere Karten-ID/Event-ID), ACK-/Retry-Regeln, Authentisierung, Heartbeat, Command-IDs, Benutzer-/Kartenformat, Zeitzonen- und DST-Semantik sowie maximale Body-/Batchgrößen. Bis dahin sind ausgehende Synchronisation, Zeitsync und Reboot absichtlich gesperrt.

# Release Notes 0.23.0

## Zeiterfassung ohne Lizenzierung

Erfassung benötigt keinen Lizenzserver und keine Aktivierung mehr. Entfernt
wurden die Serveranbindung, Hintergrundprüfungen, Signatur- und Schlüsselverwaltung,
Funktionssperren, Benutzerlimits, Lizenzseite, Lizenz-API und Lizenz-Logging.
Aufträge mit Firmen und Standorten, Urlaubsplanung, Auswertungen, Terminals und
persönliche bzw. Team-Kalenderfeeds stehen gemäß den bestehenden Rollenrechten
bereit. Anmeldung, CSRF-Schutz, Freigaben und Gruppenzuständigkeiten bleiben bestehen.

Weboberfläche, PWA auf Handy und PC sowie Offline-Synchronisation benötigen
keine Test- oder Produktivlizenz. Die Schutzmaßnahmen aus 0.22.4 gegen
widersprüchliche Gerätestände und vergessenes Ausstempeln bleiben erhalten.
Bestehende fachliche Synchronisationskonflikte müssen weiterhin geprüft werden.

## Update und vorhandene Daten

Keine Schemaänderung (weiterhin Schema 26). Geschäftsdaten, Rollen, laufende
Buchungen und ausstehende PWA-Ereignisse bleiben erhalten. Alte Sicherungen
sind weiter nutzbar; enthaltene `config/license.json` wird nicht zurückgespielt.
Alte Logging-Konfigurationen mit `license_logging` werden weiterhin eingelesen;
das ausgediente Feld wird ignoriert.

Eine bereits vorhandene `config/license.json` und `ERFASSUNG_LICENSE_*`-Variablen
werden nicht mehr ausgewertet und können entfernt werden. Das Update löscht
keine bestehenden Dateien. Alte Lizenzprotokolle können entsprechend der eigenen
Aufbewahrungsregeln bereinigt werden. Es erfolgen keine Lizenzserver-Abfragen.

Nach Merge und erfolgreichem Veröffentlichungsworkflow das Image
`ghcr.io/joni123467/erfassung:0.23.0` laden. Die Volumes `config`, `data` und
`logs` beibehalten. Das PWA-Update auf Handy und PC annehmen und einmal online
abgleichen; keine Website-Daten löschen. Damit werden auch bisher durch die
Lizenz ausgeblendete Firmen- und Urlaubsinformationen neu geladen.

Der separate Lizenzserver wird für diese Version nicht mehr benötigt. Nach
Umstellung aller abhängigen Installationen kann er außer Betrieb genommen werden.
Dieses Update verändert oder löscht dessen eigenes Repository und Deployment nicht.

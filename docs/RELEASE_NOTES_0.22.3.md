# Release Notes 0.22.3

Die PWA zeigt die Stempelaktionen vor der Synchronisationsbox. „Jetzt abgleichen“
und „Details & Sicherung“ stehen unter dem Inhalt des geöffneten Bereichs.
Das gilt ebenso für den Offline-Start. Die Statusanzeige und alle bisherigen
Sicherungs-, Anmelde- und Updateaktionen bleiben erreichbar. Der Details-Link
öffnet die Details im Bereich „Mehr“ und führt den Tastaturfokus dorthin.

Das Urlaubsformular begrenzt die Datumsfelder auch für die native Darstellung
von iOS. Formularspalten dürfen auf schmalen Bildschirmen schrumpfen; Eingaben,
Auswahlfelder und Kommentare bleiben innerhalb ihrer Karten. Die Checkbox für
den Überstundenabbau verwendet ihre normale Breite. Online- und Offline-Ansicht
verwenden dieselbe Anordnung der Absenden-Schaltfläche.
Zusätzliche Rahmen und Innenabstände um die Karten entfallen; dadurch bleibt
mehr Platz für Eingaben. „Vor Ort / Remote“ kann auf schmalen Geräten umbrechen.

Die Browserprüfung berücksichtigt ausgefüllte Datumsfelder, lange Kommentare,
Firmenauswahl, optionale Firmenanlage, Buchungsnotizen, Einstellungen und
geöffnete Synchronisationsdetails bei 320, 390, 768 und 844 Pixel Breite.
Feldgrenzen werden gegen Labels, Formulare und Karten geprüft, damit ein
versteckter Überstand nicht durch die äußere Seitenbegrenzung übersehen wird.
Chromium und WebKit decken die Browserdarstellung ab; ein physisches iPhone
steht in dieser Umgebung nicht zur Verfügung.

## Validierung

- 54 Browsertests in Chromium und WebKit erfolgreich, einschließlich Offline-
  Wiederanlauf, Stempelungen, Pausen und der neuen Formularprüfungen.
- 24 JavaScript- und 87 gezielte Python-Tests erfolgreich.
- Container-Neustart erhält Daten, Konfiguration und Logs.
- Upgrades auf vier Datenbanktypen, alle zwölf Datenbankwechsel und zwölf
  Cross-Database-Restores sowie ein älteres Archiv auf allen vier Backends
  erfolgreich geprüft.

## Aktualisierung

Nach Merge und erfolgreichem Veröffentlichungsworkflow das Image
`ghcr.io/joni123467/erfassung:0.22.3` laden. Die vorhandenen Einbindungen für
`config`, `data` und `logs` beibehalten. Die PWA übernimmt die versionierten
Assets über den vorhandenen Updateablauf; keine Neuinstallation erforderlich.

Keine neue Migration: Schema 26, Zeitberechnung, Berechtigungen und lokale
Buchungen bleiben erhalten.

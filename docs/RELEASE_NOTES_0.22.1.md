# Release Notes 0.22.1

Version 0.22.1 behebt eine Abweichung zwischen Stempelungen und Tagesansicht
auf Servern mit UTC-Zeitzone. Beispielsweise ist um 23:10 UTC im Winter in
Deutschland bereits 00:10 des Folgetags. Die Stempelung wurde korrekt dem
neuen Tag zugeordnet, die Übersicht zeigte jedoch noch den Vortag. Dadurch
fehlten die neue Buchung und der Kommentarzugang nach dem Ausstempeln.

Web-/PWA-Übersicht, Tages-/Wochenmarkierung, Monatskonto, Standardzeiträume
und mobile Synchronisationsdaten verwenden jetzt die konfigurierte
Betriebszeitzone (standardmäßig Europe/Berlin). Auch das vorausgefüllte Datum
im Nachtragsformular folgt diesem Tag. Eine ausdrücklich gewählte
historische Ansicht bleibt erhalten. Die gespeicherten Zeitstempel werden
nicht verändert.

Der Fehler wurde im Veröffentlichungsworkflow für 0.22.0 durch
`test_mobile_dashboard_contains_notes_modal_and_button` erkannt: 1.031 Tests
bestanden, einer scheiterte. Deshalb wurde der Image-Build übersprungen und
Portainer konnte das Image `0.22.0` nicht finden. Eine neue Registry-Anmeldung
behebt ein fehlendes Image nicht.

## Prüfung

Deterministische Regressionstests simulieren Winter und Sommer, Tages-,
Wochen-, Monats- und Jahreswechsel auf einem UTC-Server sowie einen normalen
Tageszeitpunkt. Geprüft werden tatsächliches Ein-/Ausstempeln, zehn Minuten
Arbeitszeit, Kommentaränderung, Web-/PWA-Tages- und Wochenansicht, historische
Auswahl, Nachtragsdatum, Synchronisationsdaten und Standardzeiträume. Vor der Korrektur
scheiterten alle vier Fälle mit unterschiedlichem UTC-/Betriebsdatum.

Zwei bestehende Nachtragstests laufen zusätzlich zu einer festen Tageszeit
um 00:45 und 00:55 Betriebszeit. Überschreitet ihr Nachtrag Mitternacht,
senden sie ausdrücklich „Ende am Folgetag“. Die Validierung im Produkt wird
nicht gelockert; Teilen und Ablehnung während laufender Pause bleiben geprüft.

## Aktualisierung und Portainer

Nach Merge und erfolgreichem Workflow **Build and publish container to GHCR**
steht das Image `ghcr.io/joni123467/erfassung:0.22.1` bereit. Erst danach im
Stack die Image-Zeile ändern und neu deployen. Bestehende Einbindungen für
`config`, `data` und `logs` beibehalten. Bei eigenen Forks den Registry-Eigentümer
entsprechend ersetzen.

Keine neue Datenbankmigration; Schema 26 bleibt bestehen. Es ändern sich
weder Buchungsdaten noch Backupformat, Volumes, Rechte oder Konfiguration.
Die Erweiterungen aus 0.22.0 bleiben enthalten.

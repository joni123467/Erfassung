# Release Notes 0.22.0

Version 0.22.0 überarbeitet die produktive Weboberfläche, Administration und
PWA. Die bestehenden Erfassungs-, Freigabe- und Verwaltungsabläufe bleiben
erhalten. Zusätzlich werden Fehler beim Teilen von Buchungen, bei Pausen,
Storno/Ersatz und bei Nachtarbeit mit Zeitumstellung behoben.

## Navigation und Arbeitsübersicht

Im Web führt eine Seitenleiste zu **Übersicht**, **Meine Zeiten**, **Urlaub**,
**Mein Konto** und zur berechtigten **Administration**. Auf kleinen Bildschirmen
öffnet **Menü** dieselben Bereiche. Die Administration gliedert sich in
**Benutzer**, **Zeiterfassung**, **Sicherung**, **System** und **Einstellungen**.
Vorhandene Rechte, Gruppenzuständigkeiten und Lizenzbedingungen gelten auch für
direkte Seiten- und Formularaufrufe.

Die PWA verwendet die unteren Bereiche **Übersicht**, **Meine Zeiten**,
**Urlaub** und **Mehr**. Der Urlaubsbereich bleibt lizenzabhängig. Unter **Mehr**
sind Zeitkonto, Konto und App-Anmeldung, Darstellung, Offline-Datenzeitraum und
Synchronisation erreichbar; berechtigte Personen finden auch den Zugang zur
Administration. Die vorhandene Offline-Hülle und die installierte PWA werden
weiterverwendet.

Die Stempelkarte zeigt den aktuellen Zustand und die heutige Nettoarbeitszeit.
Feiertagsgutschriften sind getrennt benannt. Darunter lässt sich der Verlauf
als Tag oder Woche anzeigen und zu anderen Daten wechseln. Alle Stempelaktionen
betreffen weiterhin den aktuellen Zeitpunkt, auch wenn gerade eine vergangene
Woche angezeigt wird. Monatskonto, Urlaubssaldo, Überstundenlimit und Feiertage
bleiben verfügbar. Formulare, Kalender, Tabellen und lange Namen sind für schmale
Bildschirme und das helle beziehungsweise dunkle Design angepasst.

## Persönliche Einstellung und mobile Anmeldung

Unter **Mein Konto → Meine Darstellung** wird **Tag** oder **Woche** als
Startansicht gespeichert. Dieselbe Einstellung gilt im Web und in der PWA und
kann dort unter **Mehr** geändert werden. Speichern benötigt eine Verbindung;
die bestätigte Einstellung wird für das jeweilige Konto lokal vorgehalten.
Die vorübergehende Umschaltung im Verlauf ändert den gespeicherten Standard
nicht. Helles oder dunkles Design bleibt eine Einstellung des Geräts.

**Mein Konto → Meine mobile Anmeldung** zeigt den eigenen QR-Code, bietet
Download und Neuerzeugen an und benötigt eine Verbindung. Der bestehende
QR-Zugang in den administrativen Benutzereinstellungen bleibt erhalten. Die
Anmeldung per QR ist weiterhin optional. Codes werden lokal erzeugt; Konto und
QR-Antworten erhalten private beziehungsweise `no-store`-Cachevorgaben. Das
bisherige Tokenformat und dessen Gültigkeit bleiben unverändert. Neuerzeugen
widerruft bereits ausgegebene, noch gültige Codes nicht.

## Vollständige Formulare und korrigierte Zeiterfassung

Der Auftragsdialog bietet weiterhin vorhandene Firmen und zugehörige Standorte.
Mit `Company.Create` und freigeschaltetem Auftragsbaustein kann dort optional eine
neue Firma angelegt werden. Der Schnellstart ohne Auftrag verwendet weiterhin
**Vor Ort / Remote**. **Zeit nachtragen** öffnet das vollständige Formular mit
Datum, Start, Ende, Pause, Firma, Einsatzort und Kommentar.

Für einen Nachtrag von beispielsweise **22:00 bis 06:00 Uhr** ist die neue
Auswahl **Ende am Folgetag** ausdrücklich zu setzen. Das Datum bezeichnet den
Arbeitsbeginn. Ohne Bestätigung bleibt eine Endzeit vor der Startzeit ein Fehler;
gleiche Start- und Endzeiten werden abgewiesen. Bei gesetzter Bestätigung muss
die Endzeit vor der Startzeit liegen. Die Periodensperre wird auch für den
Folgetag geprüft.

Die Korrekturen an der Buchungsverarbeitung betreffen insbesondere:

- **Pausen beim Teilen:** Erfasste Pausen werden den Zeitabschnitten zugeordnet,
  in denen sie tatsächlich liegen. Die verbleibenden Buchungsteile behalten ihre
  relevanten Metadaten; die Änderungen bleiben in der Historie nachvollziehbar.
- **Atomarer Ersatz:** Storno und Ersatz werden in einer Transaktion gespeichert.
  Ein Konflikt oder Fehler beim Erstellen des Ersatzes hinterlässt keine bereits
  stornierte Originalbuchung.
- **Nachtschichten:** Ein Nachtrag innerhalb einer abgeschlossenen Schicht
  berücksichtigt beide Kalendertage. Das gilt etwa für **23:00–01:00** und für
  **01:00–02:00 am Folgetag** innerhalb einer Schicht von **22:00–06:00**.
- **UTC und Zeitumstellung:** Bekannte UTC-Grenzen bleiben erhalten, wenn nur
  eine andere Buchungsgrenze verändert wird. Insbesondere wird der Beginn einer
  Buchung in der wiederholten Herbststunde beim Beenden nicht neu interpretiert.
  Nachtgrenzen werden als lokaler Folgetag bestimmt, bevor die Umrechnung nach
  UTC erfolgt; ein Kalendertag wird nicht pauschal als 24 UTC-Stunden behandelt.
- **Echte Pausenkorrektur:** In der administrativen Buchungsbearbeitung lassen
  sich vorhandene, beendete Pausenintervalle mit Beginn, Ende und Begründung
  korrigieren. Erforderlich sind `Time.Edit` für die betreffende Person und eine
  offene Abrechnungsperiode. Laufende Pausen, Überschneidungen und Intervalle
  außerhalb der Buchung werden abgewiesen. Der Freigabestatus bleibt erhalten;
  Vorher/Nachher und Begründung werden protokolliert. Bei vorhandenen Intervallen
  kann deren Summe nicht unabhängig von den tatsächlichen Pausenzeiten verändert
  werden.

Nicht genommene gesetzliche Pausen werden weiterhin nicht als genommen gebucht.
Die Pausenwarnung neuer Buchungen bezieht sich auf Nettoarbeitszeit: 9:30 Stunden
Anwesenheit mit 30 Minuten Pause ergeben 9 Stunden Arbeit und keine zusätzliche
15-Minuten-Warnung. Altbuchungen mit `legacy_auto` behalten ihre bisherige
Berechnung. Die entsprechende Benutzereinstellung ist als Altregel beschriftet.
Online-Stempelungen ohne brauchbare Gerätezeit verwenden die Betriebszeitzone
auch auf einem UTC-Server.

Buchungs- und Urlaubsformulare, Kommentaränderungen, Rücknahmen, persönliche und
Teamkalender, optionale Kalenderfeeds, Freigaben, Auswertungen und Exporte bleiben
erreichbar. Das gilt auch für Benutzer, Rollen, Rechte, Firmen, Standorte,
Terminals, Backups, Wiederherstellung, Datenbankverwaltung und
Synchronisationskonflikte. Die vorhandenen Prüfungen auf Anmeldung, CSRF,
Berechtigung, Zuständigkeit und Lizenz werden durch die Darstellung nicht
ersetzt.

## Schema, Update und Betrieb

Migration **26** ergänzt ausschließlich das neue Benutzerfeld
`users.overview_preference` als `VARCHAR(8) NOT NULL` mit Standard `day`;
das ORM verwendet `String(8)`. Automatische Schemaergänzung über `ensure_schema()`
und versionierter Migrationsrunner verwenden denselben idempotenten Pfad.
Fehlende Werte werden ergänzt; vorhandene Einstellungen bleiben erhalten.
Bestandskonten starten zunächst mit der Tagesansicht. Die Korrekturen an
Buchungen und Pausen benötigen keine neuen Buchungs- oder Pausentabellen.

Eine Prüfung gegen echtes PostgreSQL deckte zusätzlich ältere
Migrationsanweisungen auf, die numerische SQL-Literale `1` und `0` für
Boolean-Spalten verwendeten. Diese Pfade verwenden jetzt passende
Boolean-Bindings beziehungsweise `TRUE`-/`FALSE`-Standardwerte. Bei historischen
Gruppenflags wird der tatsächliche Spaltentyp berücksichtigt, sodass auch alte
INTEGER-Spalten weiter verarbeitet werden. Das betrifft sowohl den Neuaufbau
als auch das Upgrade einer Datenbank. Die bisherigen Migrationsnummern bleiben
unverändert; nur Eintrag 26 wird ergänzt. Die Ergebnisse der Backendmatrix
werden im Prüfbericht ausgewiesen. Reservierte Spaltennamen in der Migration
der Abwesenheitstypen werden für MySQL und MariaDB dialektsicher quotiert.

Die reale Wiederherstellungsprüfung hat außerdem einen bestehenden Fehler
aufgedeckt: Ein Archiv konnte `config/database.json` des Zielsystems ersetzen.
Der Restore übernimmt jetzt ausschließlich die vorhandenen Anwendungseinstellungen
(`system`, `logging`, `backup`, `retention`, `license`, `timemoto`), während
Datenbank- und Deploymentkonfiguration erhalten bleiben. Normalisierte Archivpfade
und umgeleitete Dateipfade können diesen Schutz nicht umgehen. Backups archivieren
die Konfiguration weiterhin vollständig.

Die vorhandenen **config-, data- und logs-Volumes weiterverwenden**. Deployment,
logische Backups und Wiederherstellung verwenden weiterhin die bestehenden
Abläufe. Beim Einlesen älterer Daten ergänzt die Schemaaktualisierung das neue
Benutzerfeld. Die neuen Darstellungsassets werden versionsgebunden geladen und
in den Service-Worker-Assets berücksichtigt.

**Keine PWA-Neuinstallation und kein Löschen der Website-Daten erforderlich.**
Den vorhandenen Updatehinweis verwenden. Bei älteren Clients ohne sichtbaren
Updatehinweis gegebenenfalls alle Erfassung-Fenster schließen und erneut öffnen.
Offene Buchungen, Outbox, Empfangsbestätigungen und Konfliktfreigabe bleiben im
bestehenden Synchronisationsablauf. Die bekannten iOS-Grenzen bei geschlossener
App oder vom Betriebssystem entfernten Browserdaten ändern sich durch das
Oberflächenupdate nicht; siehe
[Synchronisationsarchitektur und Betrieb](PWA_SYNCHRONISATION.md).

## Prüfung

Die Regressionstests umfassen Erfassung und Pausen, Auftragswechsel,
Nachträge/Überschreiben, Storno/Ersatz, Nachtarbeit und Zeitumstellung sowie
Rechte, Migration und die persönlichen Einstellungen. Die Browserprüfung
verwendet die tatsächliche Anwendung mit isolierten Testkonten und prüft Web,
PWA, schmale Ansichten und bestehende Offline-/Synchronisationsabläufe.

Die konkreten Ausführungsergebnisse und verbleibenden Grenzen stehen im
[Prüfbericht zu 0.22.0](QA_0.22.0.md).

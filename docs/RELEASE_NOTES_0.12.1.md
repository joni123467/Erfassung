# Release Notes 0.12.1 – Ohne Lizenz keine zubuchbare Funktion

0.12.0 hat die Funktionsbausteine eingeführt, eine Installation **ohne** Lizenz
aber offen gelassen. Der Gedanke dahinter war, dass ein Update keinen
laufenden Betrieb beschneiden darf. Das Ergebnis war allerdings widersprüchlich:

> Wer *keine* Lizenz hatte, konnte mehr als wer eine Lizenz ohne Bausteine
> hatte.

Damit war die Lizenz folgenlos – genau das, was sie nicht sein soll. Ab 0.12.1
entscheidet ausschließlich das Lizenzdokument.

## Was jetzt gilt

| Zustand | Zubuchbare Bausteine | Neue Benutzer |
|---|---|---|
| Nicht lizenziert | keine | nein |
| Lizenziert | was das Dokument nennt | bis `max_users` |
| Abgelaufen | keine | nein |
| Ungültig | keine | nein |
| Gesperrt, Frist läuft | wie im Dokument | bis `max_users` |
| Gesperrt, Frist abgelaufen | keine | bis `max_users` |

Zubuchbar sind weiterhin `orders` (Aufträge & Firmen), `vacation`
(Urlaubsplanung), `reports` (Auswertungen & Exporte) und `terminals`
(RFID-Terminals).

## Was offen bleibt

Unverändert und in **jedem** Zustand:

- Stempeln: Arbeitszeit, Pausen, Kommentare, Einsatzort
- eigene Zeitübersicht und eigene Buchungen
- die bereits angelegten Benutzer, Gruppen und Rollen
- Sicherung und Wiederherstellung
- Systemeinstellungen, Logs, Datenbankverwaltung, Lizenzseite

Das ist keine Kulanz, sondern die Grenze der Durchsetzung: Wer nicht stempeln
kann, verliert Arbeitszeit, die sich nicht nachholen lässt. Wer nicht sichern
kann, verliert sie endgültig. Und wer sich nicht anmelden kann, kommt an seine
eigenen Daten nicht mehr heran. **Eine Lizenzfrage darf keine Daten kosten.**

Eine Installation ohne Lizenz kann damit genau so viel wie eine reine
Stempel-Lizenz – nicht mehr und nicht weniger.

## Neue Benutzer

Ohne gültige Lizenz lässt sich kein Benutzer mehr anlegen. Über die Oberfläche
mit Klartextmeldung, über `POST /api/users` mit **HTTP 402**. Bestehende
Benutzer bleiben unangetastet, arbeiten normal weiter und lassen sich weiterhin
bearbeiten.

Die Grundausstattung einer frischen Installation entsteht beim ersten Start und
geht **nicht** durch diese Prüfung. Eine noch nicht aktivierte Installation
lässt sich also einrichten, anmelden und aktivieren – sonst wäre die
Aktivierung selbst unerreichbar.

## Wirkung auf Bestandsinstallationen

Wer bisher **ohne** Lizenz gearbeitet hat, verliert mit diesem Update
Aufträge, Urlaubsplanung, Auswertungen und Terminals sowie die Benutzeranlage.
Die Daten bleiben vollständig erhalten und sind nach einer Aktivierung sofort
wieder erreichbar – auf der Lizenzseite führt „Lizenz beantragen“ direkt zum
Lizenzserver.

Das ist eine bewusste Verschärfung gegenüber 0.12.0 und der eigentliche Zweck
dieses Release.

## Kleinigkeiten

- `GET /api/license` liefert zusätzlich `feature_access`: was **tatsächlich**
  nutzbar ist, im Unterschied zu `features` aus dem Dokument. Nach einer
  abgelaufenen Sperrfrist fällt beides auseinander.
- `LicenseStatus.add_ons_available` ersetzt `features_enforced`. Die Frage ist
  jetzt „kann diese Lizenz überhaupt etwas freischalten?“ statt „wird
  überhaupt durchgesetzt?“ – durchgesetzt wird immer.
- Gesperrtes verschwindet jetzt auch außerhalb der Administration aus der
  Oberfläche: der Urlaubsreiter unter „Buchungen“, die Urlaubsübersicht auf
  dem Dashboard und Reiter samt Antragsformular in der Mobilansicht. Auch die
  Offline-Synchronisation (`GET /mobile/sync-data`) liefert dann keine
  Urlaubsdaten mehr und meldet `request_vacations: false`, damit die
  Offline-Shell einen gesperrten Antrag nicht in die Warteschlange stellt.
- Der Hinweisbalken nennt die Folge, nicht nur den Status.
- „Nicht lizenziert“ steht beim Start als Warnung in `license.log`.

## Behoben

`GET /api/users/{id}/excel` war nicht lizenzpflichtig. Der Endpunkt ist eine
Auswertung, ließ sich am Pfadpräfix aber nicht von der Benutzer-API
unterscheiden, die zur Basis gehört – der Export lief deshalb an der
Middleware vorbei. Sie kennt jetzt zusätzlich Muster für solche Einzelfälle.

## Was sich nicht ändert

- **Ein unerreichbarer Lizenzserver sperrt nie.** Störung, Netzausfall,
  Wartung – die gespeicherte Lizenz läuft unverändert weiter. Nur eine
  ausdrückliche Sperrmeldung startet die Übergangsfrist von 14 Tagen.
- Die Prüfung selbst bleibt offline; der Server wird nur für Aktualisierungen
  gebraucht.
- Keine Schemaänderung, keine Migration.

## Tests

`tests/test_v0121.py` – 27 Tests: jeder zubuchbare Bereich ohne Lizenz zu
(Oberfläche mit 303 auf das Dashboard, API mit 402), Basis offen, Navigation
ohne die gesperrten Punkte, Benutzeranlage abgewiesen, Stempeln und Anmelden
weiterhin möglich, abgelaufene und ungültige Lizenz schalten nichts frei, eine
gültige Lizenz öffnet weiterhin genau das Genannte, Oberfläche und
Synchronisationsantwort blenden Gesperrtes aus.

Die übrigen Testdateien liefen bisher **ohne** Lizenz – was vorher niemandem
auffiel, weil ohne Lizenz alles offen war. Sie aktivieren ihre Testinstanz
jetzt über `tests/licensed_env.py` mit einem selbst signierten Dokument mit
allen Bausteinen und prüfen damit weiterhin Fachlogik statt Lizenzierung. Dass
das nötig wurde, ist der beste Beleg dafür, dass die Sperre jetzt wirkt.

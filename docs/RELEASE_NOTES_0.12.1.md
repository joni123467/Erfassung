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

## Änderungen wirken schnell

Eine Lizenzänderung nützt wenig, wenn sie erst am nächsten Tag ankommt. Drei
Wege führen jetzt dorthin:

| Auslöser | Wirkt |
|---|---|
| Knopf „Lizenz aktualisieren" | sofort |
| Neustart des Containers | sofort |
| selbsttätige Nachfrage | spätestens nach einer Stunde |

Die selbsttätige Nachfrage lief bisher **täglich**, jetzt **stündlich** – das
sind 24 Anfragen pro Installation und Tag, für den Lizenzserver nichts. Wer es
anders braucht, stellt `ERFASSUNG_LICENSE_CHECK_MINUTES` ein (Untergrenze 5
Minuten, damit eine Fehlkonfiguration den Lizenzserver nicht flutet; ein
unbrauchbarer Wert wird ignoriert und protokolliert, statt den Start zu
verhindern).

**Beim Start** wird einmal ungefragt nachgefragt, unabhängig vom Intervall.
Ein Neustart ist der Moment, in dem jemand hinschaut – da soll der Lizenzstand
stimmen. Die Prüfung läuft im Hintergrundthread und hält den Start nicht auf.

### Der Knopf „Lizenz aktualisieren"

Auf der Lizenzseite unter „Verwaltung". Er holt den aktuellen Stand sofort und
sagt anschließend, **was sich geändert hat**:

> Lizenz bestätigt. Benutzer 5 → 25; neu: Urlaubsplanung.

Technisch die Zustandsabfrage (`POST /v1/activations/state`), die bei gültiger
Lizenz ein frisch signiertes Dokument mitliefert. Kennt der Lizenzserver den
Endpunkt nicht, wird auf die vollständige Aktivierung zurückgefallen – die ist
idempotent und verbraucht keinen weiteren Aktivierungsplatz.

Der bisherige Knopf „Erneut prüfen" heißt jetzt **„Neu aktivieren"** und tut
weiterhin genau das: die vollständige Aktivierung wiederholen, etwa nach einem
Wechsel des Lizenzservers.

### Und wenn der Lizenzserver weg ist?

**Dann ändert sich nichts.** Das gilt für alle drei Wege gleichermaßen: Die
hinterlegte Lizenz bleibt in vollem Umfang gültig, bis sie abläuft. Der Knopf
meldet den Ausfall als Hinweis, der Vorfall landet in `license.log` – mehr
passiert nicht. Nur eine *ausdrückliche* Sperrmeldung des Servers startet die
Übergangsfrist von 14 Tagen.

Dass die Nachfrage jetzt häufiger läuft, ändert daran nichts: Aus 24
erfolglosen Versuchen pro Tag wird keine Sperre.

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

**Auftragsbezogenes Stempeln lief ohne Lizenz weiter.** Web und Stempel-App
boten weiterhin an, auf eine Firma bzw. einen Auftrag zu stempeln – obwohl das
zum Baustein `orders` gehört. Der Grund: `/punch` war bewusst ganz von der
Middleware ausgenommen, damit eine Lizenzfrage niemals das Stempeln blockiert.
Genau darin lag die Lücke.

Jetzt gilt fein getrennt:

| Aktion | Ohne `orders` |
|---|---|
| Arbeitszeit starten/beenden, Pausen, Kommentare | offen |
| Auftrag starten (`start_company`) | abgewiesen |
| Firma bei einem Nachtrag angeben | abgewiesen |
| **Auftrag beenden** (`end_company`) | **offen** |

Dass „Auftrag beenden" offen bleibt, ist Absicht: Läuft eine Lizenz mitten im
Auftrag aus, muss sich die laufende Buchung schließen lassen. Sonst hinge sie
fest und es ginge Arbeitszeit verloren.

Aus der Oberfläche verschwindet der Auftragsteil vollständig – Dashboard,
Mobilansicht und die Offline-Synchronisation liefern ohne `orders` keine
Firmenliste und `create_companies: false`.

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

`tests/test_v0121.py` – 41 Tests: jeder zubuchbare Bereich ohne Lizenz zu
(Oberfläche mit 303 auf das Dashboard, API mit 402), Basis offen, Navigation
ohne die gesperrten Punkte, Benutzeranlage abgewiesen, Stempeln und Anmelden
weiterhin möglich, abgelaufene und ungültige Lizenz schalten nichts frei, eine
gültige Lizenz öffnet weiterhin genau das Genannte, Oberfläche und
Synchronisationsantwort blenden Gesperrtes aus. Dazu: Auftragsstart
gesperrt und Auftragsende offen, stündliches Intervall samt Grenzen der
Umgebungsvariablen, Nachfrage beim Start, und „Lizenz aktualisieren“ –
wirkt sofort, nennt die Änderung, und lässt bei unerreichbarem Server
alles unangetastet.

Die übrigen Testdateien liefen bisher **ohne** Lizenz – was vorher niemandem
auffiel, weil ohne Lizenz alles offen war. Sie aktivieren ihre Testinstanz
jetzt über `tests/licensed_env.py` mit einem selbst signierten Dokument mit
allen Bausteinen und prüfen damit weiterhin Fachlogik statt Lizenzierung. Dass
das nötig wurde, ist der beste Beleg dafür, dass die Sperre jetzt wirkt.

# Release Notes 0.12.2 – Lizenzänderungen wirken schnell

0.12.1 hat die Funktionsbausteine scharf gestellt. Damit fielen zwei Dinge auf,
die dieses Release erledigt: Auftragsbezogenes Stempeln lief noch ohne Lizenz
weiter, und eine Lizenzänderung brauchte bis zu einen Tag, bis sie ankam.

## Behoben: Auftragsbezogenes Stempeln

Web und Stempel-App boten weiterhin an, auf eine Firma bzw. einen Auftrag zu
stempeln – obwohl das zum Baustein `orders` gehört. Der Grund: `/punch` war
bewusst ganz von der Lizenz-Middleware ausgenommen, damit eine Lizenzfrage
niemals das Stempeln blockiert. Nur ist „auf einen Auftrag stempeln" eben nicht
dasselbe wie „stempeln" – genau darin lag die Lücke.

Jetzt gilt fein getrennt:

| Aktion | Ohne `orders` |
|---|---|
| Arbeitszeit starten/beenden, Pausen, Kommentare | offen |
| Auftrag starten (`start_company`) | abgewiesen |
| Firma bei einem Nachtrag (`POST /time`) angeben | abgewiesen |
| **Auftrag beenden** (`end_company`) | **offen** |

Dass „Auftrag beenden" offen bleibt, ist Absicht: Läuft eine Lizenz mitten im
Auftrag aus, muss sich die laufende Buchung schließen lassen. Sonst hinge sie
fest und es ginge Arbeitszeit verloren.

Aus der Oberfläche verschwindet der Auftragsteil vollständig. Dashboard und
Mobilansicht bekommen ohne `orders` eine leere Firmenliste und
`can_create_companies = false`; damit greifen die vorhandenen Weichen von
selbst. `GET /mobile/sync-data` liefert `companies: []` und
`create_companies: false`, also stellt die Offline-Shell einen Auftragsstart
gar nicht erst in die Warteschlange.

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
unbrauchbarer Wert wird protokolliert und ignoriert, statt den Start zu
verhindern).

**Beim Start** wird einmal ungefragt nachgefragt, unabhängig vom Intervall.
Ein Neustart ist der Moment, in dem jemand hinschaut – da soll der Lizenzstand
stimmen. Die Prüfung läuft im Hintergrundthread und hält den Start nicht auf.

### Der Knopf „Lizenz aktualisieren"

Auf der Lizenzseite unter „Verwaltung". Er holt den aktuellen Stand sofort und
sagt anschließend, **was sich geändert hat**:

> Lizenz bestätigt. Benutzer 5 → 25; neu: Urlaubsplanung.

Verglichen werden Zustand, Benutzerzahl, Laufzeit, hinzugekommene und
entfallene Bausteine sowie eine aufgehobene oder neue Sperre.

Technisch die Zustandsabfrage (`POST /v1/activations/state`), die bei gültiger
Lizenz ein frisch signiertes Dokument mitliefert. Kennt der Lizenzserver den
Endpunkt nicht, wird auf die vollständige Aktivierung zurückgefallen – die ist
idempotent und verbraucht keinen weiteren Aktivierungsplatz.

Der bisherige Knopf „Erneut prüfen" heißt jetzt **„Neu aktivieren"** und tut
weiterhin genau das: die vollständige Aktivierung wiederholen, etwa nach einem
Wechsel des Lizenzservers. Zwei Knöpfe mit fast demselben Text nebeneinander
wären nur verwirrend gewesen.

### Und wenn der Lizenzserver weg ist?

**Dann ändert sich nichts.** Das gilt für alle drei Wege gleichermaßen: Die
hinterlegte Lizenz bleibt in vollem Umfang gültig, bis sie abläuft. Der Knopf
meldet den Ausfall als Hinweis, der Vorfall landet in `license.log` – mehr
passiert nicht. Nur eine *ausdrückliche* Sperrmeldung des Servers startet die
Übergangsfrist von 14 Tagen.

Dass die Nachfrage jetzt häufiger läuft, ändert daran nichts: Aus 24
erfolglosen Versuchen pro Tag wird keine Sperre.

## Datenbank

Keine Schemaänderung, keine Migration.

## Tests

`tests/test_v0121.py` wächst auf **41 Tests**. Neu in diesem Release:

- **Aufträge**: Oberfläche ohne „Auftrag starten", `start_company` abgewiesen,
  Nachtrag mit Firma abgewiesen, Firmenliste und `create_companies` in
  `/mobile/sync-data` leer bzw. `false`, ein laufender Auftrag lässt sich nach
  Wegfall der Lizenz beenden, und mit `orders` funktioniert weiterhin alles.
- **Intervall**: stündlicher Standard, Umgebungsvariable samt Untergrenze und
  unbrauchbaren Werten, Fälligkeit nach einer Stunde, Nachfrage beim Start.
- **„Lizenz aktualisieren"**: wirkt sofort (gesperrter Bereich ist unmittelbar
  danach erreichbar), nennt die Änderung, meldet eine aufgehobene Sperre, und
  lässt bei unerreichbarem Server alles unangetastet.

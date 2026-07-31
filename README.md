# Erfassung

Erfassung ist eine FastAPI-basierte Zeiterfassungsanwendung (Web-App) mit Benutzer-/Gruppenverwaltung, Arbeitszeitbuchungen, Urlaubsverwaltung, Feiertagssynchronisation und Exportfunktionen.

**Version:** `0.12.2`

> Seit 0.12.2: **Lizenzänderungen wirken schnell.** Die Nachfrage läuft
> **stündlich** statt täglich und zusätzlich **bei jedem Start**; der neue
> Knopf **„Lizenz aktualisieren"** holt den Stand sofort und nennt, was sich
> geändert hat. Behoben: Auftragsbezogenes Stempeln lief ohne den Baustein
> `orders` weiter – Firmen- und Auftragsauswahl sind jetzt gesperrt, „Auftrag
> beenden" und das reine Stempeln bleiben offen. Ein unerreichbarer
> Lizenzserver nimmt weiterhin **nichts** weg. Details in
> [`docs/RELEASE_NOTES_0.12.2.md`](docs/RELEASE_NOTES_0.12.2.md).

> Seit 0.12.1: **Ohne Lizenz keine zubuchbare Funktion.** 0.12.0 hatte eine
> unlizenzierte Installation offen gelassen – damit war die Lizenz folgenlos,
> denn *keine* Lizenz gab mehr Rechte als eine ohne Bausteine. Jetzt schaltet
> ausschließlich das Lizenzdokument frei, und ohne gültige Lizenz lassen sich
> auch keine neuen Benutzer anlegen. Die Basis – Stempeln, eigene
> Zeitübersicht, vorhandene Benutzer, Sicherungen – bleibt in jedem Fall offen.
> Details in [`docs/RELEASE_NOTES_0.12.1.md`](docs/RELEASE_NOTES_0.12.1.md).

> Seit 0.12.0: **Funktionsbausteine und regelmäßige Lizenzprüfung** – eine
> Lizenz schaltet `orders`, `vacation`, `reports` und `terminals` frei;
> Stempeln bleibt immer enthalten. Die Installation fragt täglich beim
> Lizenzserver nach. Ein unerreichbarer Server sperrt **nie**; eine gemeldete
> Sperre wirkt erst nach 14 Tagen Übergangsfrist. Details unter
> [„Funktionsbausteine"](#funktionsbausteine).

> Seit 0.11.1: **Halbe Urlaubstage** – erster und letzter Tag eines Antrags
> lassen sich einzeln halbieren (0,5 Urlaubstage, halbe Tagessollzeit). Dazu
> ein Knopf „Lizenz beantragen/erweitern" auf der Lizenzseite. Behoben: Das
> Freigeben von Buchungen und Urlaub war seit 0.10.0 vollständig gesperrt –
> Details in [`docs/RELEASE_NOTES_0.11.1.md`](docs/RELEASE_NOTES_0.11.1.md).

> Seit 0.11.0: **Lizenzierung** – eine Installation lässt sich einmalig gegen
> den [Erfassung-Lizenzserver](https://github.com/joni123467/Erfassung_Lizenzserver)
> aktivieren und prüft ihre Lizenz danach **offline**. Durchgesetzt werden die
> lizenzierte Benutzerzahl und das Ablaufdatum; ohne Lizenz läuft die Anwendung
> unverändert weiter und zeigt nur einen Hinweis. Details unter
> [„Lizenzierung"](#lizenzierung).

> Seit 0.10.0: **Rollenbasierte Rechteverwaltung (RBAC)** – Berechtigungen
> kommen ausschließlich über **Rollen**; Gruppen sind reine Organisation, und
> ein Benutzer kann in mehreren Gruppen und Rollen sein. Bestehende
> Gruppenrechte werden beim ersten Start automatisch in Rollen überführt.
> Details unter [„Rollen & Berechtigungen"](#rollen--berechtigungen).

> Seit 0.9.21: **Einsatzort je Buchung (Remote / vor Ort)** – wird der
> Einsatzort für einen Benutzer freigeschaltet, erscheint beim Stempeln und bei
> manuellen Buchungen ein Umschalter **Vor Ort ⇄ Remote** (seit 0.9.22 als
> farbige Schaltfläche statt kleiner Checkbox). Details unter
> [„Einsatzort (Remote / vor Ort)"](#einsatzort-remote--vor-ort).

> Seit 0.9.20: **Stempelzeiten im PDF der Benutzerauswertung** – der
> Administrations-Export bietet optional zusätzlich alle einzelnen Buchungen je
> Benutzer, so wie Benutzer sie schon aus ihrer eigenen Arbeitszeitübersicht
> kennen. Details unter [„Auswertungen & Exporte"](#auswertungen--exporte).

> Seit 0.9.19: **Abteilungsadministration & Überschreiben mit Bestätigung** –
> Gruppen mit Team-Rechten erreichen jetzt den Administrationsbereich und
> verwalten ihre eigene Abteilung; kollidierende Buchungen lassen sich nach
> Rückfrage gezielt überschreiben. Details unter
> [„Rollen & Berechtigungen"](#rollen--berechtigungen).

> Seit 0.9.18: **Minutengenaue Überschneidungsprüfung** – direkt
> aneinandergrenzende Buchungen (Terminal-Importe speichern Sekunden) lösen
> beim Bearbeiten keine falsche „Überschneidung" mehr aus.

> Seit 0.9.16: **Bearbeiten trotz bestehender Überschneidung** – eine Buchung
> lässt sich jetzt auch dann korrigieren (z. B. verkürzen), wenn eine bereits
> vorhandene Überlappung (etwa eine noch laufende Buchung) den Zeitraum
> berührt; nur *neu* entstehende Konflikte werden abgelehnt.

> Seit 0.9.15: **Nachtrag zwischen bestehenden Buchungen & Bearbeiten aus den
> Berichten** – eine manuelle Buchung, die in eine abgeschlossene Buchung
> fällt, teilt diese automatisch (wie bei der laufenden Buchung); die
> Einzelbuchungs-Tabelle der Zeitübersichten bietet Berechtigten einen
> Bearbeiten-Link.

> Seit 0.9.14: **Nachtrag bei laufender Arbeitszeit** – eine manuelle Buchung
> (z. B. ein Telefonat), die in die laufende Buchung fällt, teilt diese
> automatisch: bisheriger Teil wird abgeschlossen, der Nachtrag eingefügt,
> die Arbeitszeit läuft ab dem Nachtragsende unverändert weiter.

> Seit 0.9.13: **Zuverlässige PWA-Updates** – installierte PWAs (insbesondere
> iOS) erkennen neue Versionen jetzt automatisch bei App-Start/-Resume und
> nach jedem Sync und laden sich einmalig selbst neu; zusätzlich wird beim
> Zurückholen in den Vordergrund synchronisiert. Details unter
> [„Updates & Service-Worker-Versionierung"](#updates--service-worker-versionierung).

> Seit 0.9.12: **Geltungsbereich für Team-Rechte** – Freigaben, Berichte und
> Buchungsbearbeitung lassen sich je Gruppe auf das **eigene Team (Gruppe)**
> oder **alle Benutzer** eingrenzen. Details unter
> [„Rollen & Berechtigungen"](#rollen--berechtigungen).

> Seit 0.9.11: **Überarbeitete Gruppenberechtigungen** – kategorisierte
> Berechtigungsmatrix in der Gruppenverwaltung mit neuen Rechten für
> Selbstbedienung (manuelle Buchungen, Kommentare nachträglich bearbeiten,
> Urlaubsanträge stellen) und Firmenverwaltung. Details unter
> [„Rollen & Berechtigungen"](#rollen--berechtigungen).

> Seit 0.9.10: **Mobile Stempel-Fixes & Kommentar-Nachbearbeitung** – die
> Firmensuche der mobilen App übernimmt gewählte Vorschläge zuverlässig in die
> Buchung, und nach dem Beenden eines Auftrags bzw. der Arbeitszeit kann der
> Kommentar der Buchung optional nachbearbeitet werden.

> Seit 0.9.9: **Docker-Erstinitialisierung** der Datenbank über `DB_*`-ENV-
> Variablen, **datenbankunabhängige (logische) Backups** und **Cross-Database
> Restore** (z. B. SQLite-Backup → PostgreSQL). Details unter
> [„Docker Deployment"](#docker-deployment).

> Die mobile Oberfläche (`/mobile`) ist eine installierbare, offline-fähige PWA.
> Details siehe Abschnitt [„Mobile Offline-Funktion"](#mobile-offline-funktion-mobile) und [`CHANGELOG.md`](CHANGELOG.md).

## Deployment-Standard (neu)

Der Standardweg ist jetzt vollständig image-basiert:

1. Code nach GitHub pushen
2. GitHub Actions baut das Docker-Image
3. Image wird in die GitHub Container Registry (GHCR) veröffentlicht
4. Portainer deployt dieses GHCR-Image per Stack/Compose

> Portainer baut **nicht** lokal, sondern zieht ein bereits gebautes Image.

## Einstiegspunkt und Laufzeit

- FastAPI-App: `app.main:app`
- Standardport: `8000`
- Container-Startkommando:
  `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Lokale Entwicklung

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker (lokal)

```bash
docker build -t erfassung:0.10.1 .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=sqlite:////app/data/erfassung.db \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  erfassung:0.10.1
```

## GHCR & GitHub Actions

Der Workflow liegt unter `.github/workflows/container-publish.yml` und veröffentlicht nach GHCR.

### Trigger

- Push auf `main`
- Push von Tags `v*` (z. B. `v0.10.1`)
- Manuell über `workflow_dispatch`

### Tags

- Versions-Tag aus `VERSION` (hier `0.10.1`)
- `latest` auf `main`
- Git-Tag (`v0.10.1`)

### Erwartetes Image

Beispiel:

`ghcr.io/OWNER/erfassung:0.10.1`

`OWNER` ist der GitHub-Owner (User oder Organisation) des Repositories.

## Deployment mit Portainer

Für Portainer ist die bereitgestellte `compose.yaml` gedacht. Sie referenziert ein GHCR-Image (ohne lokalen Build).

### Beispiel

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.10.1
    container_name: erfassung
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: sqlite:////app/data/erfassung.db
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
```

## Benutzerverwaltung über die Konsole (CLI)

Für Notfälle und Administration ohne Web-Oberfläche gibt es ein Konsolen-Werkzeug
(`app/manage.py`). Es nutzt dieselbe Datenbank wie die Web-App (Umgebungsvariable
`DATABASE_URL`) sowie dieselbe Passwort-Prüfung (mind. 10 Zeichen, Groß-/Klein­buchstabe,
Zahl, Sonderzeichen).

### Aufruf

Im laufenden Docker-Container (empfohlen im Produktivbetrieb – nutzt automatisch das
gemountete `/app/data`):

```bash
docker exec -it erfassung python -m app.manage <befehl> [optionen]
```

> `erfassung` ist der Container-Name aus der `compose.yaml`. Bei abweichendem Namen
> entsprechend anpassen (`docker ps`).

Lokal (Entwicklung):

```bash
python -m app.manage <befehl> [optionen]
```

### Benutzer auflisten

```bash
docker exec -it erfassung python -m app.manage list-users
```

Zeigt ID, Benutzername, Name, E-Mail, Gruppe, Admin-Kennzeichen und ob beim nächsten
Login ein Passwortwechsel erzwungen wird.

### Gruppen auflisten

```bash
docker exec -it erfassung python -m app.manage list-groups
```

Hilfreich, um die Gruppen-ID/den -Namen für `--group` zu finden (Admin-Rechte hängen
an der Gruppe).

### Benutzer anlegen

```bash
docker exec -it erfassung python -m app.manage create-user \
  --username mmustermann \
  --full-name "Max Mustermann" \
  --email max@example.com \
  --group Administration \
  --weekly-hours 40
```

- Ohne `--password` wird das Passwort interaktiv (verdeckt) abgefragt.
- `--password "Geheim!2345"` setzt es direkt (Vorsicht: erscheint in der Shell-History).
- `--random` erzeugt ein sicheres Zufallspasswort und gibt es einmalig aus.
- `--group` akzeptiert Gruppen-**ID oder -Name**; für Admin-Rechte die Admin-Gruppe
  (Standard: `Administration`) angeben.
- Standardmäßig muss der Benutzer das Passwort bei der ersten Anmeldung ändern.
  Mit `--no-force-change` wird das deaktiviert.

### Passwort zurücksetzen

```bash
# per Benutzername, mit interaktiver Abfrage
docker exec -it erfassung python -m app.manage reset-password --username mmustermann

# per ID, mit Zufallspasswort
docker exec -it erfassung python -m app.manage reset-password --id 1 --random

# direkt gesetztes Passwort, ohne erzwungenen Wechsel
docker exec -it erfassung python -m app.manage reset-password \
  --username admin --password "NeuesPasswort!1" --no-force-change
```

Standardmäßig wird nach dem Zurücksetzen ein Passwortwechsel bei der nächsten
Anmeldung verlangt (`--no-force-change` deaktiviert das).

### Hinweise

- Das voreingestellte Administratorkonto lautet `admin` (Erst-PIN/-Passwort `0000`).
  Über `reset-password --username admin --random` lässt sich ein sicheres Passwort
  vergeben, falls der Zugang verloren ging.
- Alle Befehle geben bei Fehlern (unbekannter Benutzer, doppelter Benutzername/E-Mail,
  zu schwaches Passwort) eine verständliche Meldung und den Exit-Code `1` zurück.

## Rollen & Berechtigungen

Seit 0.10.1 gilt ein rollenbasiertes Modell (RBAC):

```
Benutzer ──< Gruppen        (Organisation: Abteilung, Team, Standort)
Benutzer ──< Rollen ──< Berechtigung + Geltungsbereich
```

- **Gruppen** tragen **keine** Rechte. Sie bilden die Organisation ab und
  bestimmen, für wen ein Recht mit dem Bereich „Eigene Gruppen" gilt.
  Ein Benutzer kann in **mehreren** Gruppen sein.
- **Rollen** bündeln Berechtigungen und werden Benutzern direkt zugewiesen –
  ebenfalls mehrere gleichzeitig. Bei mehreren Rollen gilt jeweils der
  **weiteste** Geltungsbereich.

Verwaltung unter **Administration → Benutzer → Gruppen / Rollen /
Berechtigungen**.

### Berechtigungen

| Kategorie | Key | Bereich wählbar |
|-----------|-----|-----------------|
| Eigene Zeiterfassung | `Own.Time.Edit`, `Own.Comment.Edit`, `Own.Vacation.Request` | – |
| Aufträge & Firmen | `Company.Create`, `Company.Manage` | – |
| Zeiten & Freigaben | `Time.Approve`, `Time.Edit`, `Time.View` | ✔ |
| Urlaub | `Vacation.Manage` | ✔ |
| Benutzerverwaltung | `User.View`, `User.Create`, `User.Edit`, `User.Delete` | ✔ |
| System | `System.Groups`, `System.Terminals`, `System.Roles`, `System.Settings`, `System.Backup` | – |

### Geltungsbereiche

| Bereich | Wirkung |
|---------|---------|
| Nicht erlaubt | Recht nicht vergeben |
| Nur eigene | ausschließlich die eigenen Daten |
| Eigene Gruppen | alle Benutzer, die mindestens eine Gruppe mit dem Handelnden teilen |
| Alle Benutzer | keine Einschränkung |

Der Server prüft den Bereich bei **jeder** Aktion – nicht nur beim Anzeigen.

### Systemrollen

| Rolle | Umfang |
|-------|--------|
| **Superadministrator** | alle Berechtigungen inkl. Rollen, Systemeinstellungen und Sicherung |
| **Administrator** | alle Berechtigungen **außer** `System.Roles`, `System.Settings`, `System.Backup` |

Beide sind nicht änderbar und erhalten bei Updates automatisch neu
hinzugekommene Rechte. Wer Rollen zuweisen möchte, braucht `System.Roles`;
Systemrollen darf ausschließlich ein Superadministrator vergeben. Damit lässt
sich über eine selbst angelegte Rolle niemand mehr Rechte verschaffen, als er
selbst besitzt.

### Beispiel: Abteilungsleitung

Eine Rolle „Teamleiter“ mit

| Recht | Bereich |
|-------|---------|
| `User.View`, `User.Edit` | Eigene Gruppen |
| `Time.View`, `Time.Edit`, `Time.Approve` | Eigene Gruppen |
| `Vacation.Manage` | Eigene Gruppen |

gibt Zugriff auf genau die Benutzer der eigenen Gruppen – unabhängig davon, wie
viele Gruppen das sind.

### Selbstbedienungsrechte

`Own.*` betrifft nur die eigenen Buchungen und Anträge. Benutzer **ohne Rolle**
behalten diese Rechte (Bestandsverhalten); neue Rollen bringen sie voreingestellt
mit. Entzogene Rechte blenden die Funktionen in Web und mobiler App aus und
werden serverseitig durchgesetzt – auch für Offline-Aktionen.

### Umstellung bestehender Installationen

Beim ersten Start nach dem Update (Migration 14, datenerhaltend):

1. Die bisherige Gruppenzugehörigkeit wandert nach `user_groups`.
2. Mitglieder von Administratorgruppen erhalten **Superadministrator**.
3. Jede Gruppe mit Rechten wird zur Rolle **„Migration – &lt;Gruppenname&gt;“**
   mit denselben Rechten und Bereichen; ihre Mitglieder bekommen sie zugewiesen.
4. Die Rechte-Spalten der Gruppen werden geleert.

Niemand verliert dadurch Rechte. Details siehe
[`docs/RBAC_MIGRATIONSPLAN.md`](docs/RBAC_MIGRATIONSPLAN.md).

## Lizenzierung

Die Anwendung kann sich gegen den **Erfassung-Lizenzserver** aktivieren
(eigenes Repository
[`joni123467/Erfassung_Lizenzserver`](https://github.com/joni123467/Erfassung_Lizenzserver)).
Die Aktivierung ist einmalig, die Prüfung läuft danach **offline**.

> Administration → System → **Lizenz**

### Ablauf

1. **Deployment-ID** – beim ersten Start erzeugt die Anwendung eine dauerhafte
   Zufallskennung (`erfassung-<32 Hexzeichen>`) in `config/license.json`. Sie
   enthält **keine** Hardwaremerkmale, **keine** personenbezogenen Daten und
   nicht den Hostnamen. Solange das `config`-Volume mitwandert, überlebt sie
   einen Serverumzug – die Lizenz muss dann nicht erneut aktiviert werden.
2. **Aktivieren** – Adresse des Lizenzservers und Aktivierungsschlüssel
   eintragen. Die Anwendung ruft `POST /v1/activations` auf und erhält ein
   Ed25519-signiertes Lizenzdokument.
3. **Offline prüfen** – bei jedem Start und jeder Statusabfrage werden
   Schemaversion, Signatur, Produktkennung, Deployment-ID und Ablaufdatum
   geprüft. Der Lizenzserver muss dafür nicht erreichbar sein.

„Erneut prüfen“ holt jederzeit ein frisches Dokument – nötig nach einer
Verlängerung oder Erweiterung. Der Aufruf ist idempotent und verbraucht keinen
weiteren Aktivierungsplatz. „Lizenz entfernen“ gibt den Platz beim Lizenzserver
frei, damit eine andere Installation aktiviert werden kann.

### Was durchgesetzt wird

| Zustand | Wirkung |
|---------|---------|
| **Nicht lizenziert** | Keine neuen Benutzer, kein zubuchbarer Baustein. Die Basis bleibt offen. |
| **Lizenziert** | Neue Benutzer nur bis `max_users` (`0` = unbegrenzt); freigeschaltet ist, was das Dokument nennt. Ab 30 Tagen vor Ablauf erscheint eine Warnung. |
| **Abgelaufen / ungültig** | Keine neuen Benutzer, kein zubuchbarer Baustein. Stempeln, eigene Zeitübersicht, vorhandene Benutzer und Sicherungen bleiben uneingeschränkt nutzbar. |

Über die Oberfläche wird die Grenze mit Klartextmeldung abgewiesen, über
`POST /api/users` mit **HTTP 402**. Bestehende Benutzer werden nie gesperrt
oder gelöscht. `GET /api/license` liefert den Status als JSON (nur mit
`System.Settings`, ohne Schlüssel und ohne Signatur).

### Umgang mit dem Aktivierungsschlüssel

Der Schlüssel liegt in `config/license.json`, damit die Lizenz ohne erneute
Eingabe nachgeprüft werden kann. Abgesichert ist er so:

- Dateirechte **0600**,
- in der Oberfläche nur maskiert (`••••-1234`),
- in `license.log` und allen anderen Protokollen ebenfalls nur maskiert,
- **nicht** im Einstellungsexport (`/admin/system/settings/export`),
- **nicht** in `GET /api/license`.

Wer ihn gar nicht speichern will, entfernt nach der Aktivierung das Feld
`activation_key` aus `config/license.json`. Die Lizenz bleibt gültig; nur
„Erneut prüfen“ verlangt dann wieder eine Eingabe.

### Prüfschlüssel

Der Lizenzserver signiert das Lizenzdokument mit seinem **privaten** Schlüssel,
Erfassung prüft es mit dem **öffentlichen**. Dieser wird **automatisch bei der
ersten Aktivierung übernommen** (`GET /v1/instance/public-key`) – zu kopieren
ist nichts.

Danach ist er je `key_id` unveränderlich: Weist sich derselbe Server später mit
einem anderen Schlüssel aus, bricht die Aktivierung ab, ohne etwas zu
überschreiben. Eine echte Rotation läuft über eine neue `key_id` und wird
ergänzt.

Auf der Lizenzseite steht ein **Fingerprint** (`SHA256:…`), der auch im
Lizenzserver unter „Instanz" erscheint. Wer möchte, gleicht ihn ab.

Wer den Schlüssel fest verdrahten will – dann ist auch der erste Kontakt
abgesichert –, trägt das PEM in `app/licensing_keys.py` ein:

```python
EMBEDDED_PUBLIC_KEYS = {
    "k1": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n",
}
```

Ein so eingebetteter Schlüssel hat Vorrang. Für Entwicklung und Tests lässt
sich die Zuordnung über `ERFASSUNG_LICENSE_PUBLIC_KEYS` (JSON
`{"key_id": "<PEM>"}`) überschreiben.

### Grenze des Kopierschutzes

Die einmalige Aktivierung verhindert weitere **reguläre** Aktivierungen, aber
**nicht** das vollständige Klonen einer bereits aktivierten Installation: Wer
`config`- und `data`-Volume kopiert, erhält eine zweite laufende Installation
mit demselben Lizenzdokument. Das System ist damit **kein** vollständiger
Kopierschutz. Weitere Restrisiken – Widerruf wirkt erst bei der nächsten
Prüfung, die Ablaufprüfung nutzt die lokale Uhr, und wer den Quellcode ändert,
kann die Prüfung entfernen – stehen in
[`docs/RELEASE_NOTES_0.11.0.md`](docs/RELEASE_NOTES_0.11.0.md).

## Einsatzort (Remote / vor Ort)

Optionales Feld je Buchung: fand der Termin **vor Ort** statt oder **remote**
(z. B. per Telefon)? Es wird – wie das Zeitkonto – **je Benutzer** in der
Benutzerverwaltung freigeschaltet:

> Administration → Benutzer → *Benutzer* → **Zeitkonto & Buchungen** →
> „Einsatzort erfassen (Remote / vor Ort)"

Ist die Option aus, erscheint das Feld nirgends und alle Buchungen gelten als
vor Ort – der bisherige Zustand bleibt unverändert.

Ist sie an, steht ein **Umschalter** an den unten genannten Stellen. Er
wechselt Farbe und Beschriftung (seit 0.9.22, davor eine Checkbox):

| Zustand | Darstellung |
|---------|-------------|
| Nicht gesetzt | grau – „Einsatzort · **Vor Ort**" |
| Gesetzt | blau – „Einsatzort · **Remote**" |

Stellen:

| Stelle | Wirkung |
|--------|---------|
| Arbeitszeit starten (Web & mobil) | die gestartete Buchung wird als Remote erfasst |
| Auftrag starten (Web & mobil) | die gestartete Auftragsbuchung wird als Remote erfasst |
| Manuelle Buchung (Nachtrag) | der Nachtrag wird als Remote erfasst |
| Kommentar der letzten Buchung bearbeiten (mobil) | Einsatzort nachträglich korrigieren |
| Administration → Zeitbuchung bearbeiten | Einsatzort korrigieren |

Weitere Eigenschaften:

- **Offline-fähig**: Der Wert wird in der mobilen App mit der Stempelung in
  die Offline-Warteschlange gelegt und beim Synchronisieren übertragen. Der
  Umschalter ist eine per CSS gestaltete Checkbox und funktioniert deshalb auch
  in der Offline-Shell ohne JavaScript.
- **Teilen bleibt konsistent**: Wird eine Buchung durch einen Nachtrag geteilt,
  übernehmen beide Abschnitte den Einsatzort der Ursprungsbuchung.
- **Anzeige**: Remote-Buchungen tragen in den Buchungslisten, den
  Zeitübersichten und den Freigaben ein Kennzeichen „Remote" neben der Firma.
- **Exporte**: PDF und Excel zeigen eine zusätzliche Spalte **„Ort"** (Remote /
  Vor Ort) – aber nur, wenn im Zeitraum mindestens eine Buchung remote erfasst
  wurde. Wer den Einsatzort nicht nutzt, bekommt unveränderte Exporte.
- **Bestandsdaten**: Alle vorhandenen Buchungen gelten als vor Ort. Wird die
  Option für einen Benutzer wieder deaktiviert, bleiben bereits erfasste
  Remote-Kennzeichen erhalten (sie werden nur nicht mehr neu vergeben).

## Urlaub

Urlaubsanträge laufen über `/records/vacations`. Zusätzlich zu ganzen Tagen
lassen sich **erster und letzter Tag halbieren** (seit 0.11.1): Beim Antrag
stehen unter Start- und Enddatum je ein Häkchen „nur ein halber Tag". Bei einem
eintägigen Antrag genügt eines davon.

| Antrag | Angerechnete Urlaubstage |
|--------|--------------------------|
| Mo–Mi, ganz | 3,0 |
| Mo–Mi, Anfang und Ende halb | 2,0 |
| nur Mo, halb | 0,5 |
| Fr–Mo, Anfang und Ende halb | 1,0 (Wochenenden zählen nie) |

Ein halber Tag bringt die halbe Tagessollzeit – in der Urlaubsübersicht, der
Tagesgutschrift, den Auswertungen und beim Überstundenurlaub. In den Listen
erscheint er als „½" hinter dem Datum. Bestandsanträge bleiben ganze Tage.

## Funktionsbausteine

Eine Lizenz schaltet Bereiche frei. **Immer enthalten** und nie gesperrt:

- Stempeln (Arbeitszeit, Pausen, Kommentare)
- eigene Zeitübersicht und eigene Buchungen
- Benutzer-, Gruppen- und Rollenverwaltung
- Sicherung und Wiederherstellung
- Systemeinstellungen, Logs, Datenbankverwaltung

Zubuchbar sind vier Bausteine:

| Baustein | Schaltet frei |
|---|---|
| `orders` | Aufträge, Firmen, auftragsbezogenes Stempeln |
| `vacation` | Urlaubsanträge, Urlaubskonten, Urlaubsfreigaben |
| `reports` | PDF-/Excel-Exporte, Benutzer- und Team-Auswertungen |
| `terminals` | RFID-Terminals und Geräte-Synchronisation |

Eine Lizenz ohne jeden Baustein ist damit eine reine **Stempel-Lizenz** – und
genau so viel kann eine Installation ohne Lizenz auch.

Gesperrte Bereiche verschwinden aus der Navigation; wer die Adresse direkt
aufruft, landet mit einem Hinweis auf dem Dashboard. Die API antwortet mit
**HTTP 402**. Abgesichert ist das über eine Middleware, nicht Route für Route –
so kann kein Endpunkt versehentlich offen bleiben.

Das gilt nicht nur für die Administration: Ohne `vacation` verschwinden der
Urlaubsreiter unter „Buchungen“, die Urlaubsübersicht auf dem Dashboard sowie
Reiter und Antragsformular der Mobilansicht. Auch `GET /mobile/sync-data`
liefert dann keine Urlaubsdaten und meldet `request_vacations: false`, damit
die Offline-Shell einen gesperrten Antrag nicht in die Warteschlange stellt.

Ohne `orders` entfällt der gesamte Auftragsteil: keine Firmenauswahl im
Dashboard, kein „Auftrag starten" in der Stempel-App, keine Firmenliste in der
Synchronisation. `start_company` und ein Nachtrag mit Firma werden auch
serverseitig abgewiesen.

| Aktion | Ohne `orders` |
|---|---|
| Arbeitszeit starten/beenden, Pausen, Kommentare | offen |
| Auftrag starten | abgewiesen |
| Firma bei einem Nachtrag angeben | abgewiesen |
| **Auftrag beenden** | **offen** |

„Auftrag beenden" bleibt bewusst offen: Läuft eine Lizenz mitten im Auftrag
aus, muss sich die laufende Buchung schließen lassen – sonst hinge sie fest.

> **Ohne gültige Lizenz ist kein zubuchbarer Baustein nutzbar** – das gilt für
> „nicht lizenziert“ genauso wie für „abgelaufen“ und „ungültig“. Freischalten
> kann nur das Lizenzdokument.

Was dabei **nicht** gesperrt wird, steht oben unter „Immer enthalten“. Der
Grund ist nicht Kulanz: Wer nicht stempeln kann, verliert Arbeitszeit, die
sich nicht nachholen lässt, und wer nicht sichern kann, verliert sie
endgültig. Eine Lizenzfrage darf keine Daten kosten – und niemanden aus seinen
eigenen Daten aussperren.

### Regelmäßige Prüfung

Die Installation fragt beim Lizenzserver nach (`POST /v1/activations/state`)
und bekommt dabei ein frisch signiertes Dokument. Änderungen an Benutzerzahl,
Laufzeit oder Bausteinen wirken damit **ohne Zutun des Kunden**:

| Auslöser | Wirkt |
|---|---|
| Knopf „Lizenz aktualisieren“ | sofort |
| Neustart des Containers | sofort |
| selbsttätige Nachfrage | spätestens nach einer Stunde |

Das Intervall lässt sich über `ERFASSUNG_LICENSE_CHECK_MINUTES` einstellen
(Standard 60, Untergrenze 5). Den Zeitpunkt des letzten Kontakts zeigt die
Lizenzseite.

**„Lizenz aktualisieren“** holt den Stand sofort und nennt in der Rückmeldung,
was sich geändert hat – etwa „Benutzer 5 → 25; neu: Urlaubsplanung“.
**„Neu aktivieren“** wiederholt die vollständige Aktivierung, etwa nach einem
Wechsel des Lizenzservers. Beides ist idempotent und verbraucht keinen
weiteren Aktivierungsplatz.

### Wenn der Lizenzserver ausfällt

**Nichts passiert.** Eine Störung, ein Netzausfall oder ein abgeschalteter
Server lassen die gespeicherte Lizenz unverändert weiterlaufen – die Prüfung
ist ohnehin offline. Der Vorfall landet in `license.log`, sonst merkt niemand
etwas. Nur eine *ausdrückliche* Sperrmeldung des Servers ändert etwas.

Das gilt für jeden Weg gleichermaßen: stündliche Nachfrage, Prüfung beim
Start und „Lizenz aktualisieren“ können nichts wegnehmen. Auch aus 24
erfolglosen Versuchen am Tag wird keine Sperre; die Lizenz bleibt in vollem
Umfang gültig, bis sie abläuft.

### Wenn eine Lizenz gesperrt wird

Meldet der Server `suspended`, `revoked` oder `expired`, beginnt eine
**Übergangsfrist von 14 Tagen**:

| Zeitraum | Wirkung |
|---|---|
| Tag 0–14 | Deutlicher Hinweis mit Restfrist auf jeder Administrationsseite. Alles funktioniert weiter. |
| ab Tag 15 | Aufträge, Urlaubsplanung, Auswertungen und Terminals sind gesperrt. |
| immer | Stempeln, eigene Zeitübersicht, Benutzerverwaltung und Sicherungen bleiben offen. |

Gibt der Herausgeber die Lizenz wieder frei, endet die Frist bei der nächsten
Nachfrage sofort – oder direkt über „Erneut prüfen“.

Dass Stempeln nie gesperrt wird, ist Absicht: Eine Lizenzfrage darf keine
Arbeitszeitdaten kosten.

## Auswertungen & Exporte

| Auswertung | Aufruf | Formate |
|------------|--------|---------|
| Eigene Arbeitszeitübersicht | `/records` | PDF (inkl. Einzelbuchungen), Excel |
| Zeitübersichten (alle/Team) | `/admin/reports/time` | PDF, Excel |
| Benutzerauswertung | `/admin/reports/users` | PDF (optional inkl. Stempelzeiten), Excel |

### Stempelzeiten in der Benutzerauswertung (seit 0.9.20)

Die Benutzerauswertung zeigt je Benutzer eine Summenzeile (Buchungen,
Arbeitszeit, Pausen, Soll, Urlaub, Über-/Minusstunden). Über die Option
**„Stempelzeiten"** neben dem PDF-Export enthält das PDF zusätzlich für jeden
gelisteten Benutzer eine Tabelle mit den **einzelnen freigegebenen Buchungen**
des Zeitraums – dieselben Spalten wie in der persönlichen Arbeitszeitübersicht:

| Datum | Firma | Start | Ende | Arbeitszeit | Status | Kommentar |
|-------|-------|-------|------|-------------|--------|-----------|

- Die Option wirkt nur auf den PDF-Export (Parameter `entries=1`); der
  Excel-Export bleibt die reine Summenauswertung.
- Der Geltungsbereich von „Zeitübersichten einsehen" gilt unverändert: Ein
  Abteilungsadministrator exportiert ausschließlich Buchungen des eigenen Teams.
- Ohne Buchungen im Zeitraum erscheint je Benutzer der Hinweis „Keine
  freigegebenen Buchungen im Zeitraum."

## Datenbank (SQLite, MySQL, MariaDB, PostgreSQL)

Standard ist SQLite. Unterstützt werden außerdem **MySQL 8+, MariaDB 10.6+ und
PostgreSQL 14+** (Treiber `PyMySQL` und `psycopg2-binary` sind enthalten).
MariaDB und PostgreSQL sind die empfohlenen Produktivdatenbanken, SQLite eignet
sich für Einzelplatz-, Test- und Entwicklungsumgebungen.

Das aktive Datenbanksystem kann seit 0.9.7 direkt über die Oberfläche unter
**Administration → System → Datenbank** verwaltet und gewechselt werden. Vor
jedem Wechsel wird automatisch ein Sicherheitsbackup erstellt, anschließend
werden alle Daten verlustfrei übertragen und auf Integrität geprüft; schlägt
etwas fehl, bleibt die bisherige Datenbank aktiv (kein Datenverlust, keine
Downtime). Die Auswahl wird persistent in `config/database.json` gespeichert und
hat Vorrang vor `DATABASE_URL`.

Alternativ lässt sich das Backend weiterhin per Umgebungsvariable vorgeben:

```
DATABASE_URL: mysql+pymysql://benutzer:passwort@db-host:3306/erfassung
DATABASE_URL: postgresql+psycopg2://benutzer:passwort@db-host:5432/erfassung
```

Schemaänderungen werden beim Start automatisch und dialektübergreifend
angewandt (Versionsstand in der Tabelle `schema_migrations`). Upgrades von
älteren Versionen (0.6.x/0.7.x/0.8.x) sind ohne Datenverlust möglich.

## Docker Deployment

### Unterstützte Datenbanken

| Datenbank | Eignung |
|-----------|---------|
| ⭐ **PostgreSQL** | Empfohlene Referenzinstallation für den Produktivbetrieb |
| ⭐ **MariaDB** | Empfohlen für den Produktivbetrieb |
| MySQL | Produktiv geeignet |
| SQLite | Entwicklung, Tests, kleine Installationen |

### Erstinitialisierung über Docker ENV (seit 0.9.9)

Bei einer **Neuinstallation** (noch keine `config/database.json` vorhanden) kann
die Datenbank vollständig über ENV-Variablen vorkonfiguriert werden. Beim ersten
Start wird daraus die Konfiguration erzeugt, persistiert, getestet und migriert.

| Variable | Beschreibung | Beispiel |
|----------|--------------|----------|
| `DB_TYPE` | `sqlite` / `mysql` / `mariadb` / `postgresql` | `postgresql` |
| `DB_HOST` | Host (Servertypen) | `postgres` |
| `DB_PORT` | Port (Servertypen) | `5432` |
| `DB_NAME` | Datenbankname | `timetracking` |
| `DB_USER` | Benutzer | `timetracking` |
| `DB_PASSWORD` | Passwort | `secret` |
| `DB_SSL` | TLS aktivieren | `false` |
| `DB_PATH` | Pfad der SQLite-Datei (nur SQLite) | `/data/app.db` |

> **Wichtig:** ENV-Variablen dienen **ausschließlich der Erstinitialisierung**.
> Existiert bereits eine `config/database.json`, werden die ENV-Variablen
> ignoriert und niemals überschrieben. Die Datenbank bleibt danach vollständig
> über **Administration → System → Datenbank** verwaltbar; dort wird auch
> angezeigt, ob die Konfiguration aus Docker ENV oder über das Webinterface
> erstellt wurde.

### PostgreSQL (empfohlene Referenzinstallation) ⭐

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.10.1
    container_name: erfassung
    restart: unless-stopped
    depends_on: [postgres]
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: postgresql
      DB_HOST: postgres
      DB_PORT: "5432"
      DB_NAME: timetracking
      DB_USER: timetracking
      DB_PASSWORD: changeme
      DB_SSL: "false"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
  postgres:
    image: postgres:16
    container_name: erfassung-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: timetracking
      POSTGRES_USER: timetracking
      POSTGRES_PASSWORD: changeme
    volumes:
      - ./pgdata:/var/lib/postgresql/data
```

### MariaDB ⭐

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.10.1
    container_name: erfassung
    restart: unless-stopped
    depends_on: [mariadb]
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: mariadb
      DB_HOST: mariadb
      DB_PORT: "3306"
      DB_NAME: timetracking
      DB_USER: timetracking
      DB_PASSWORD: changeme
      DB_SSL: "false"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
  mariadb:
    image: mariadb:11
    container_name: erfassung-mariadb
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: timetracking
      MARIADB_USER: timetracking
      MARIADB_PASSWORD: changeme
      MARIADB_ROOT_PASSWORD: changeme-root
    volumes:
      - ./mariadb:/var/lib/mysql
```

### MySQL

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.10.1
    container_name: erfassung
    restart: unless-stopped
    depends_on: [mysql]
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: mysql
      DB_HOST: mysql
      DB_PORT: "3306"
      DB_NAME: timetracking
      DB_USER: timetracking
      DB_PASSWORD: changeme
      DB_SSL: "false"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
  mysql:
    image: mysql:8
    container_name: erfassung-mysql
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: timetracking
      MYSQL_USER: timetracking
      MYSQL_PASSWORD: changeme
      MYSQL_ROOT_PASSWORD: changeme-root
    volumes:
      - ./mysql:/var/lib/mysql
```

### SQLite (Entwicklung / Tests / kleine Installationen)

```yaml
services:
  erfassung:
    image: ghcr.io/OWNER/erfassung:0.10.1
    container_name: erfassung
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      DB_TYPE: sqlite
      DB_PATH: /app/data/erfassung.db
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
```

> In **allen** Beispielen sind die drei persistenten Volumes `config`, `data`
> und `logs` eingebunden – diese müssen erhalten bleiben, damit Konfiguration,
> Geschäftsdaten und Protokolle Neustarts überleben.

## Backups (datenbankunabhängig, seit 0.9.9)

Unter **Administration → Backups** lassen sich Sicherungen (Datenbank +
Konfiguration, optional Logs) lokal sowie auf **FTP/FTPS** oder **SMB3**
ablegen. Zugangsdaten werden persistent im `config`-Volume gespeichert und nie
im Klartext protokolliert. Es gibt einen Verbindungstest, konfigurierbare
Aufbewahrung, eine Integritätsprüfung nach jeder Sicherung und eine Historie.

Backups sind seit 0.9.9 **datenbankunabhängig (logisch)**: Die Daten werden als
JSON je Tabelle exportiert (`data/database.json`) statt als rohe Datenbankdatei.
Jedes Archiv enthält Metadaten (`app_version`, `backup_format_version`,
`database_type`, `schema_version`, `created_at`, Datensatzanzahlen) – diese
dienen ausschließlich der Analyse/Information und lösen niemals einen
automatischen Datenbankwechsel aus.

### Cross-Database Restore (seit 0.9.9)

Ein logisches Backup kann **unabhängig vom ursprünglichen Datenbanktyp** in die
aktuell konfigurierte Datenbank wiederhergestellt werden (z. B. SQLite-Backup →
PostgreSQL, MariaDB-Backup → PostgreSQL, PostgreSQL-Backup → SQLite). Ablauf:
Backup analysieren → Daten extrahieren → in die **aktive** Datenbank importieren
(ORM, eine Transaktion) → Migrationen ausführen → Integritätsprüfung. Vor jeder
Wiederherstellung wird automatisch ein Sicherheitsbackup (`pre_restore_*.zip`)
erstellt. Eine Vorschau zeigt vorab Backup- und Systeminformationen.

> **Restore importiert ausschließlich Daten.** Der aktive Datenbanktyp, die
> Datenbankkonfiguration sowie die ENV-/Docker-Einstellungen werden dabei
> niemals verändert.

## Terminalverwaltung (Zeiterfassungsterminals)

Unter **Administration → Zeiterfassung → Terminals** werden Zeiterfassungs-
terminals zentral verwaltet (seit 0.9.8). Die Ansicht ist analog zu den
Backup-Jobs aufgebaut: eine Tabelle mit Name, Typ, Status, letzter Verbindung
und letzter Synchronisation sowie den Aktionen Bearbeiten, Verbindung testen,
Synchronisieren, Aktivieren/Deaktivieren und Löschen. Über **„Neues Terminal“**
öffnet sich ein kompaktes Modal.

Die Verwaltung basiert auf einer **Treiber-/Plugin-Architektur**
(`app/integrations/terminals/`): Jeder Terminaltyp ist ein eigener Treiber, der
sich in einer Registry registriert. Es gibt **keine hartkodierte TimeMoto-Logik**
in der Oberfläche – weitere Typen (z. B. ZKTeco, Suprema, generische REST-/CSV-
Terminals) lassen sich ohne Umbauten ergänzen. Aktuell wird der Typ **TimeMoto**
ausgeliefert.

Der frühere eigene Menüpunkt „TimeMoto TM-616“ wurde durch diese
Terminalverwaltung ersetzt; eine vorhandene `config/timemoto.json` wird beim
Upgrade automatisch und verlustfrei als Terminal übernommen. Terminalaktionen
werden im Logkanal `terminal` (`logs/terminal.log`) protokolliert; der
Systemstatus zeigt Anzahl, Online-/Offline-Terminals sowie die letzte
Synchronisation und den letzten Synchronisationsfehler.

## Persistenz (wichtig)

Für produktiven Betrieb sollten folgende Pfade persistent gemountet werden:

- `/app/data` (inkl. SQLite-DB `erfassung.db` und `data/backups`)
- `/app/logs` (strukturierte Logdateien)
- `/app/config` (Konfigurationen: System, Logging, Backup-Ziele, Datenbank)

Optional zusätzlich:

- `.env`-Datei im Stack/Host, falls eigene Umgebungsvariablen genutzt werden

## Was du selbst anpassen musst

- `OWNER` im Image-Namen (`ghcr.io/OWNER/erfassung:0.10.1`)
- optional Image-Name/Tag (`erfassung`, `0.10.1`, `latest`)
- Volume-Hostpfade (`./data`, `./logs`, `./config`)
- ggf. zusätzliche Umgebungsvariablen (z. B. für DB/Integrationen)

## Hinweise zu privaten Repositories

GHCR funktioniert auch mit privaten Repositories. In Portainer muss dann ein Registry-Zugang (PAT mit `read:packages`) hinterlegt werden, damit das private Image gezogen werden kann.

## Mobile Offline-Funktion (`/mobile`)

Die mobile Oberfläche ist als pragmatische **Offline-first-PWA** umgesetzt.

### Was offline funktioniert

- Laden der mobilen Seite `/mobile` inklusive zentraler Assets per Service Worker.
- Start/Stop von Arbeitszeitbuchungen.
- Pausenstart/Pausenende.
- Firmen-/Auftragsstart und -ende.
- Firmensuche mit Vorschlagsliste: ein gewählter Vorschlag wird automatisch in
  die Firmenauswahl übernommen (ab 0.9.10); zusätzlich löst der Server den
  Suchtext als Fallback über den Firmennamen auf.
- Kommentar-/Notizfelder in mobilen Aktionen.
- Kommentar nachbearbeiten (ab 0.9.10): Nach „Auftrag beenden" bzw.
  „Arbeitszeit beenden" öffnet sich optional ein Dialog, um den Kommentar der
  beendeten Buchung anzupassen; zusätzlich gibt es unter den Stempel-Aktionen
  den Button „Kommentar der letzten Buchung bearbeiten" (Buchungen des
  aktuellen Tages).
- Offline erstellte Urlaubsanträge.

### Lokale Datenhaltung (letzte 6 Monate)

Die App speichert mobilrelevante Serverdaten für ca. 6 Monate (183 Tage) lokal im Browser (IndexedDB):

- Zeitbuchungen/Stempelhistorie.
- Firmenliste.
- Urlaubsanträge.
- Aktiven Buchungszustand und mobile Kennzahlen.
- Metadaten wie `lastSyncAt`.

### Synchronisation

- Automatische Synchronisation beim Start der mobilen Seite.
- Automatische Synchronisation beim Wechsel von Offline zu Online.
- Offline-Aktionen bleiben persistent in einer lokalen Queue gespeichert (auch nach Browser-Neustart).
- **Queue-and-forward (ab 0.5.0):** Jedes Ereignis wird zuerst unconditional in
  IndexedDB gespeichert und dann in Erstellungsreihenfolge an den Server gesendet.
  Eine Aktion wird nur entfernt, wenn der Server sie eindeutig bestätigt – der
  Server (mit `client_action_id`-Idempotenz) ist die alleinige Wahrheitsquelle.
  Dadurch keine verlorenen Stempelungen und keine Dubletten.
- Die Sync-Endpunkte (`/punch`, `/vacations`) antworten bei `Accept: application/json`
  mit `{ok, duplicate, retryable, message}`, sodass der Client zuverlässig
  entscheidet, ob eine Aktion erledigt ist oder erneut gesendet werden muss.
- **Echte Ereigniszeit (ab 0.5.0):** Der Client sendet die lokale Zeit der Aktion
  (`event_time`); offline erfasste Zeiten bleiben korrekt, auch wenn erst Stunden
  später synchronisiert wird.

### Service Worker / Offline-Start

- Der Service Worker wird von der Wurzel ausgeliefert (`GET /sw.js`) mit dem
  Header `Service-Worker-Allowed: /`, damit sein Scope die `/mobile`-`start_url`
  abdeckt. (Ein unter `/static/` ausgelieferter Worker kann nicht für `/`
  registriert werden – das verhinderte früher den Offline-Start auf iOS/Safari.)
- Beim ersten Online-Aufruf installiert der Worker und legt App-Shell, CSS, JS und
  Icons in den Cache. Danach startet `/mobile` vollständig ohne Netzwerk.

### Statusmeldungen in der mobilen App

Die mobile Seite zeigt nutzerfreundlich an:

- Online/Offline-Serverstatus.
- Ob lokale Daten verfügbar sind.
- Anzahl ausstehender Offline-Aktionen.
- Zeitstempel der letzten erfolgreichen Synchronisation.

### Einschränkungen

- Eine **neue Anmeldung** benötigt weiterhin Serververbindung.
- Eine bereits aktive Sitzung mit lokal gespeicherten Mobil-Daten kann offline weiterarbeiten.
- Fokus liegt bewusst auf der mobilen Kernfunktion (Stempeln/Synchronisation), nicht auf vollständiger Offline-Abdeckung aller Admin-/Desktop-Seiten.

### Browser-Unterstützung

- Moderne Browser mit Service Worker + IndexedDB (aktuelles Chrome/Edge/Safari/Firefox mobile).
- Bei deaktiviertem IndexedDB fällt die App auf reduzierte Browser-Speicherung zurück.

### Updates & Service-Worker-Versionierung

- Die Route `GET /sw.js` **brennt die Version in den Skriptinhalt ein**
  (`self.__ERFASSUNG_VERSION`, Quelle: Datei `VERSION`) und liefert mit
  `Cache-Control: no-cache` aus. Jedes Release ändert damit die Skript-Bytes –
  der Update-Check des Browsers erkennt die neue Version auch dann, wenn eine
  installierte PWA noch eine alte gecachte Seite (mit alter
  Registrierungs-URL) ausführt. Vorher blieb die PWA in diesem Fall dauerhaft
  auf dem alten Stand hängen (Update kam erst nach Neuinstallation an).
- Der Cache-Name (`erfassung-mobile-v<VERSION>`) folgt der eingebrannten
  Version; der alte Cache wird beim `activate`-Event gelöscht (`skipWaiting()`
  + `clients.claim()`). Beim Installieren lädt der Worker die Assets mit
  `cache: 'no-cache'`, damit kein staler HTTP-Cache in die neue Cache-Version
  gelangt.
- **Aktive Update-Prüfung (ab 0.9.13):** Die Registrierung nutzt
  `updateViaCache: 'none'`; zusätzlich stößt die App `registration.update()`
  bei jedem Start, beim Zurückholen in den Vordergrund (App-Resume, wichtig
  für iOS) und nach jedem Sync mit geänderter Server-Version an. Übernimmt
  ein neuer Worker die Kontrolle, lädt sich die Seite **einmalig automatisch
  neu**, sodass sofort die frischen Assets aktiv sind (Offline-Queue bleibt
  erhalten – sie liegt persistent in IndexedDB).
- **Sync bei App-Resume (ab 0.9.13):** Beim Wechsel der PWA in den Vordergrund
  wird automatisch synchronisiert – zuvor geschah das nur beim Seitenstart
  und beim `online`-Ereignis.
- Es ist **kein** manuelles Editieren von `static/sw.js` oder `static/app.js` pro
  Release mehr nötig.

### PWA am Desktop/PC verwenden

Ja – die mobile Oberfläche ist nicht auf Smartphones beschränkt:

- **Ohne Installation:** `/mobile` einfach im Desktop-Browser öffnen; alle
  Funktionen (Stempeln, Offline-Queue, Synchronisation) stehen zur Verfügung.
- **Als installierte App:** Chrome/Edge am PC bieten über das Symbol in der
  Adressleiste (bzw. Menü → „App installieren") die Installation an
  (`display: standalone`). Die App startet dann in einem eigenen Fenster mit
  `/mobile` als Startseite und funktioniert offline wie am Smartphone.
- Die Oberfläche ist für schmale Bildschirme gestaltet, läuft im
  Desktop-Fenster aber uneingeschränkt; für die volle Desktop-Oberfläche
  (Administration, Berichte) bleibt die normale Web-Ansicht (`/dashboard`)
  die bessere Wahl.

### Installierbarkeit

Installierbar auf Android, iOS, Windows, macOS und Linux über das Manifest
(`static/manifest.webmanifest`) mit `id`, `start_url`, `scope`, `display: standalone`
sowie Icons in 192px, 512px und SVG (maskable).

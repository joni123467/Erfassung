# Erfassung

Erfassung ist eine FastAPI-basierte Zeiterfassungsanwendung (Web-App) mit Benutzer-/Gruppenverwaltung, Arbeitszeitbuchungen, Urlaubsverwaltung, Feiertagssynchronisation und Exportfunktionen.

**Version:** `0.20.1`

> Seit 0.20.1: **„Remote" steht wieder in der Einsatzortauswahl** – und zwar
> für alle. Das alte Benutzerkennzeichen entfernte seit 0.14.1 nur noch einen
> Eintrag aus der Liste, versprach in seiner Beschriftung aber weiterhin die
> ganze Einsatzorterfassung; wer es deshalb ausließ, verlor „Remote"
> unbemerkt. Außerdem: **Wochentage erscheinen auf Deutsch** (die Locale
> `de_DE` fehlt in schlanken Container-Abbildern), der Sperrsatz auf der
> Anmeldeseite ist weg, „Anzurechnung" heißt jetzt „Angerechnete Zeit", die
> Schaltflächen in der App kleben nicht mehr aneinander, ein erfülltes
> Sonntagsminimum ist grün statt gelb, alle Kommentare sind auf Deutsch und
> rund 220 Zeilen toter CSS-Code samt einigen ungenutzten Funktionen sind
> entfernt. Details in
> [`docs/RELEASE_NOTES_0.20.1.md`](docs/RELEASE_NOTES_0.20.1.md).

> Seit 0.20.0 schöpft die Regelprüfung die technisch bestimmbaren Möglichkeiten
> für Sonn- und Nachtarbeit weiter aus: Die Administration zeigt pro Person
> freie und gearbeitete Sonntage, warnt revisionssicher, wenn die mindestens
> 15 freien Sonntage nicht mehr erreichbar sind, zählt Tage mit mindestens zwei
> Nachtstunden und kennzeichnet Nachtarbeit über acht Stunden. Rechte und
> Geltungsbereiche entsprechen der vorhandenen Compliance-Übersicht. Details in
> [`docs/RELEASE_NOTES_0.20.0.md`](docs/RELEASE_NOTES_0.20.0.md).

> Seit 0.19.1 liegt eine **erneute Rechts- und Standardsprüfung** vor. Ihr
> Ergebnis ist bewusst keine pauschale Konformitätszusage: Die Anwendung ist
> für den regulären Grundfall technisch weitgehend geeignet, Betreiberpflichten
> und Sonderregeln bleiben aber offen. Das betrifft insbesondere Nachtarbeit,
> 15 freie Sonntage, besondere Beschäftigtengruppen, Mitbestimmung,
> Datenschutzorganisation, externe Manipulationssicherung sowie formale
> Sicherheits- und Barrierefreiheitsnachweise. Siehe
> [`docs/LEGAL_COMPLIANCE_AUDIT_0.19.1.md`](docs/LEGAL_COMPLIANCE_AUDIT_0.19.1.md)
> und [`docs/RELEASE_NOTES_0.19.1.md`](docs/RELEASE_NOTES_0.19.1.md).

> Seit 0.19.0 werden Benutzerkonten aufbewahrungssicher deaktiviert und pseudonymisiert; Arbeitszeit- und Compliance-Nachweise bleiben erhalten. Sonntagsarbeit zählt vollständig zur Arbeitszeitprüfung, ohne den Werktagsnenner zu erhöhen, und die Zehn-Stunden-Grenze wird schichtbezogen über Mitternacht geprüft. Details stehen in [`docs/RELEASE_NOTES_0.19.0.md`](docs/RELEASE_NOTES_0.19.0.md).

> Seit 0.18.0: **Ausgleichsfeststellungen werden fortgeschrieben** – beim
> Start, vor der Compliance-Übersicht und nach Buchungsänderungen wechseln sie
> nachvollziehbar zwischen erforderlich, fällig, überfällig und erledigt.
> Tatsächlich geleistete Arbeit bleibt auch an Feiertagen, Urlaubstagen und
> geplanten Ersatzruhetagen Bestandteil der §-3-Rechnung. Ein Ersatzruhetag
> muss nach dem Arbeitstag liegen und wirklich arbeitsfrei sein. Die
> Wochenvariante des Ausgleichs ist auf höchstens 24 Wochen begrenzt. Details
> in [`docs/RELEASE_NOTES_0.18.0.md`](docs/RELEASE_NOTES_0.18.0.md).

> Seit 0.17.0: **Der §-3-Ausgleich rechnet über Werktage statt über
> Buchungstage** und bekommt eine **eigene Frist je Überschreitungstag** – ein
> einzelner Zehnstundentag ist ausgleichspflichtig, aber nicht sofort
> überfällig. Die arbeitsrechtliche Bewertung braucht das **neue Recht
> `Time.Compliance.Manage`**; `Time.View` ist nur noch ein Leserecht.
> Sonn-/Feiertagsausnahmen werden **geprüft** (Pflichtfelder, Fristen des
> § 11 Abs. 3 ArbZG, kein doppelter Ersatzruhetag), und jede Änderung landet in
> einer **append-only Historie**, die auch in der DSGVO-Auskunft steht.
> `Time.Edit` ist ein Korrekturrecht: Quelle, externe ID und UTC-Stempel bleiben
> dem **internen Terminal-/Importpfad** vorbehalten. Die **Betriebszeitzone**
> liegt jetzt persistent im config-Volume und wird bei jeder Änderung
> auditiert. Details in
> [`docs/RELEASE_NOTES_0.17.0.md`](docs/RELEASE_NOTES_0.17.0.md).

> Seit 0.16.0: **Selbstbedienung braucht jetzt auch über die API ein Recht.**
> 0.15.0 sicherte die Schnittstelle gegen Fremdzugriffe ab – für die eigene
> Person blieb sie offen. Eigene Buchungen brauchen `Own.Time.Edit`, eigene
> Stornierungen das **neue** `Own.Time.Cancel`, eigene Urlaubsanträge
> `Own.Vacation.Request`. Außerdem kann ein Beschäftigter bei einem eigenen
> Nachtrag **nicht mehr** Status, Quelle, externe ID oder UTC-Stempel
> bestimmen; die **Dauerberechnung liegt zentral** und rechnet überall in UTC
> (Zeitumstellung); **Feststellungen sind je Schicht eindeutig**; die
> **Schichtgrenze ist einstellbar**; der **Ausgleich nach § 3 ArbZG** wird über
> 24 Wochen ausgewertet; und zu **Sonn-/Feiertagsarbeit** lassen sich
> Ausnahmegrund, Rechtsgrundlage und Ersatzruhetag festhalten. Details in
> [`docs/RELEASE_NOTES_0.16.0.md`](docs/RELEASE_NOTES_0.16.0.md).

> Seit 0.15.0: **Die JSON-Schnittstelle ist abgesichert.** Neun `/api/*`-Endpunkte
> waren ohne jede Prüfung erreichbar – darunter das Anlegen von Benutzern und
> der vollständige Arbeitszeitexport jeder Person. Anonyme Aufrufe liefern jetzt
> **401**, fehlendes Recht oder fremder Team-Geltungsbereich **403**; eine
> Stornierung über die API braucht Akteur und Begründung. Außerdem: **Pausen
> werden über die ganze Schicht geprüft** statt je Buchung (ein Kunden- oder
> Auftragswechsel ist keine Pause), **UTC-Stempel werden tatsächlich benutzt**
> (Zeitumstellung), **Pausenereignisse stehen in der Historie** und
> **Regelverstöße werden fortgeschrieben statt gelöscht**. Details in
> [`docs/RELEASE_NOTES_0.15.0.md`](docs/RELEASE_NOTES_0.15.0.md).

> Seit 0.14.2: **Halbe Urlaubstage werden halb angerechnet.** In der
> Adminauswertung, im Excel- und PDF-Export sowie über `POST /api/vacations`
> zählten sie als ganze Tage – ein Antrag über zwei halbe Tage erschien mit
> 16:00 statt 8:00 Stunden, und beim Überstundenurlaub landete sogar ein
> falscher Wert in der Datenbank. Neu sind außerdem eine
> **Urlaubsübersicht** für die Administration (Anspruch, genommen, verplant,
> Resturlaub je Mitarbeitendem, eigenes Recht `Vacation.Overview`) und ein
> **Änderungsprotokoll** für alle Stempelungen. Details in
> [`docs/RELEASE_NOTES_0.14.2.md`](docs/RELEASE_NOTES_0.14.2.md).

> Seit 0.14.1: **Der Einsatzort ist zurück.** Die Standortauswahl hing am
> Benutzerkennzeichen „Remote/vor Ort" und verschwand ohne es komplett – ein
> Firmenstandort ist aber das Gegenteil von Remote-Arbeit. Standorte sind
> jetzt unabhängig davon wählbar, nur die Option „Remote" hängt weiter am
> Kennzeichen. Außerdem: **stornierte Buchungen** heißen jetzt „Storniert",
> haben einen eigenen Filter, zeigen Grund und Ersatzbuchung – und zählen in
> keiner Summe mehr mit (vorher stand die Zeit nach einer Korrektur doppelt in
> der Tages- und Wochensumme). **Ablehnen** funktioniert wieder: Das Formular
> hat das seit 0.14.0 verlangte Begründungsfeld. Details in
> [`docs/RELEASE_NOTES_0.14.1.md`](docs/RELEASE_NOTES_0.14.1.md).

> Seit 0.14.0: **Revisionssichere Erfassung.** Buchungen werden nicht mehr
> überschrieben oder gelöscht, sondern **storniert und ersetzt**; jede Änderung
> landet mit Vorher/Nachher, Zeitpunkt, Urheber und Begründung in einer
> Historie. Pausen werden als **einzelne Intervalle** mit Beginn und Ende
> geführt und nie ungenommen gebucht; gesetzliche Mindestpausen erscheinen
> getrennt davon als Hinweis. Verstöße gegen Höchstarbeitszeit, Ruhezeit,
> Pausen sowie Sonn-/Feiertagsarbeit werden **gekennzeichnet, nicht
> unterdrückt** – die tatsächliche Arbeitszeit bleibt gespeichert. Neu sind
> außerdem Abrechnungsperioden mit Freigabe/Widerspruch, ein Zugriffsprotokoll,
> Aufbewahrungsfristen und eine Selbstauskunft. **Eine rechtliche Garantie ist
> damit nicht verbunden** – Details und Grenzen in
> [`docs/RELEASE_NOTES_0.14.0.md`](docs/RELEASE_NOTES_0.14.0.md).

> Seit 0.13.1: **Standorte gehören zu ihrer Firma.** Schnell stempeln bietet
> wieder nur „Vor Ort" und „Remote"; im Auftragsdialog erscheinen ausschließlich
> die Standorte der gewählten Firma, und deren Hauptstandort ist vorausgewählt.
> Firmenfremde Standorte sind nicht mehr wählbar – der Server prüft das nach.
> Details in [`docs/RELEASE_NOTES_0.13.1.md`](docs/RELEASE_NOTES_0.13.1.md).

> Seit 0.13.0: **Standorte statt „Vor Ort“** – jede Firma kann beliebig viele
> Standorte mit Anschrift führen, und beim Stempeln lässt sich der Standort
> direkt wählen. Eine Firma kann als **eigener Betrieb** markiert werden, damit
> interne Zeit von Kundenzeit unterscheidbar bleibt. Ohne gepflegte
> Standorte bleibt es beim gewohnten Umschalter „Remote / Vor Ort“. Details in
> [`docs/RELEASE_NOTES_0.13.0.md`](docs/RELEASE_NOTES_0.13.0.md).

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
| Eigene Zeiterfassung | `Own.Time.Edit`, `Own.Time.Cancel`, `Own.Comment.Edit`, `Own.Vacation.Request` | – |
| Aufträge & Firmen | `Company.Create`, `Company.Manage` | – |
| Zeiten & Freigaben | `Time.Approve`, `Time.Edit`, `Time.View`, `Time.Compliance.Manage` | ✔ |
| Urlaub | `Vacation.Manage`, `Vacation.Overview` | ✔ |
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

## JSON-Schnittstelle (`/api/*`)

**Seit 0.15.0 ist jeder Endpunkt authentifiziert.** Bis 0.14.2 waren neun
Endpunkte ohne jede Prüfung erreichbar – das ist behoben.

### Authentifizierung

Es gibt **einen** Weg: die **Sitzung**. Ein API-Client meldet sich wie die
Oberfläche über `POST /login` an und schickt das Sitzungs-Cookie mit. Einen
API-Schlüssel oder Token gibt es bewusst nicht – ein zweiter Anmeldeweg wäre
eine zweite Angriffsfläche.

Für schreibende Aufrufe kommt der CSRF-Schutz hinzu: Token über `GET /api/csrf`
holen und als Kopfzeile `X-CSRF-Token` mitschicken.

```bash
# 1. Anmelden (Cookie merken)
curl -c cookies.txt -X POST https://host/login \
     -d "username=…&password=…&csrf_token=…"

# 2. Token holen und lesend zugreifen
curl -b cookies.txt https://host/api/users
```

### Antworten

| Lage | Antwort |
|------|---------|
| nicht angemeldet | **401** `Nicht angemeldet` |
| angemeldet, Recht fehlt | **403** `Keine Berechtigung` |
| Recht da, Person außerhalb des Geltungsbereichs | **403** `Außerhalb deines Geltungsbereichs` |
| gesperrte Abrechnungsperiode | **409** mit Klartextgrund |
| Benutzerlimit der Lizenz erreicht | **402** |

Der Unterschied zwischen 401 und 403 ist Absicht: „nicht angemeldet" und
„angemeldet, aber nicht berechtigt" sind verschiedene Dinge.

### Rechte je Endpunkt

| Endpunkt | Recht (mit Geltungsbereich) |
|----------|------------------------------|
| `GET /api/users` | `User.View` – die Liste ist auf den Geltungsbereich begrenzt |
| `POST /api/users` | `User.Create` |
| `GET`/`POST /api/groups` | `System.Groups` |
| `GET`/`POST /api/roles` | `System.Roles` |
| `POST /api/time-entries` | eigene Person `Own.Time.Edit`, sonst `Time.Edit` |
| `DELETE /api/time-entries/{id}` | eigene Person `Own.Time.Cancel`, sonst `Time.Edit` |
| `GET /api/users/{id}/excel` | eigene Person frei, sonst `Time.View` |
| `POST /api/vacations` | eigene Person `Own.Vacation.Request`, sonst `Vacation.Manage` |
| `POST /api/vacations/{id}/status` | `Vacation.Manage` |
| `GET /api/license` | `System.Settings` |
| `GET /api/me/export` | nur die eigene Person |
| `POST /admin/compliance/{id}/acknowledge` und `/exception` | `Time.Compliance.Manage` – `Time.View` genügt nicht |

Die eigene Person kommt immer ohne Sonderrecht an ihre **Daten** – Lesen ist
Selbstbedienung, kein Privileg. **Schreiben** braucht seit 0.16.0 auch für die
eigene Person das passende `Own.*`-Recht: Die Oberfläche prüfte das längst, die
Schnittstelle nicht. Ohne zugewiesene Rolle gelten diese Rechte wie bisher als
erlaubt, sodass sich Bestandsinstallationen nicht ändern.

### Was ein Beschäftigter selbst bestimmen darf

Ein eigener Nachtrag über `POST /api/time-entries` nimmt nur diese Felder an:
Datum, Beginn, Ende, Pause, Kunde, Standort, Einsatzort und Kommentar.

Alles andere setzt der Server:

| Feld | Wert |
|------|------|
| `status` | immer `pending` – ein Nachtrag geht in die Freigabe |
| `is_manual` / `is_open` | `true` / `false` |
| `source`, `external_id` | bleiben leer – diese Felder gehören Terminals |
| `started_at_utc`, `ended_at_utc`, `tz_name` | aus den Ortszeiten und der zentralen Betriebszeitzone |
| `location_id` | nur, wenn der Standort zur gebuchten Firma gehört |

Damit kann sich niemand selbst freigeben oder eine Buchung als
Terminalstempelung ausgeben.

### Was die Verwaltung bestimmen darf (seit 0.17.0)

`Time.Edit` ist ein **Korrekturrecht, kein Importrecht**. Bis 0.16.0 lief die
Verwaltung über dasselbe vollständige Schema wie der Terminalimport – wer
fremde Buchungen korrigieren durfte, konnte damit die Herkunft frei setzen und
eine Handbuchung als Terminalstempelung ausgeben.

| Feld | Verwaltung (`Time.Edit`) | interner Terminal-/Importpfad |
|------|--------------------------|-------------------------------|
| `status`, `is_manual` | setzbar | setzbar |
| `source` | fest `admin` | frei |
| `external_id` | immer leer | frei |
| `started_at_utc`, `ended_at_utc`, `tz_name` | vom Server aus Ortszeit und Betriebszeitzone | frei |

Der Terminalimport ruft `crud.create_time_entry` direkt auf und läuft nicht
über diese Schnittstelle; an der Treiberarchitektur ändert sich nichts.

### Stornieren

`DELETE /api/time-entries/{id}` **löscht nicht**, es storniert – und verlangt
eine Begründung:

```bash
curl -b cookies.txt -X DELETE \
     -H "X-CSRF-Token: $TOKEN" \
     "https://host/api/time-entries/42?reason=Doppelt+gestempelt"
```

Ohne `reason` antwortet der Server mit **400**. Akteur und Begründung landen in
der Revisionshistorie; eine Stornierung ohne Urheber wäre für die
Nachvollziehbarkeit wertlos.

### Protokollierung

Abgewiesene Zugriffe stehen in `logs/security.log`, erfolgreiche
administrative Aktionen zusätzlich in `logs/audit.log`. Protokolliert werden
Endpunkt, Recht und Zielperson – **keine** IP-Adresse (sie wäre ein
personenbezogenes Datum, das die Anwendung sonst nirgends festhält) und
niemals Passwörter, PINs oder Tokens. Lesende Zugriffe auf **fremde** Zeitdaten
erzeugen zusätzlich einen Eintrag im Zugriffsprotokoll.

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

## Einsatzort (Remote / vor Ort / Standort)

Feld je Buchung: Wo wurde gearbeitet? Es steht **allen Personen** offen und
braucht seit 0.20.1 keine Freischaltung mehr.

Bis 0.20.0 hing „Remote" an einem Benutzerkennzeichen. Das stammte aus 0.9.21,
als „Remote" die *gesamte* Einsatzorterfassung war. Seit 0.13.0 ist der
Einsatzort eine Liste von Arbeitsorten und wird seit 0.14.1 immer angezeigt –
das Kennzeichen entfernte damit nur noch **einen Eintrag** aus dieser Liste,
während seine Beschriftung „Einsatzort erfassen" weiterhin das Ganze versprach.
Wer das las, ließ den Haken weg, und „Remote" verschwand unbemerkt.

> **Offene Entscheidung:** Soll es eine personenbezogene Erlaubnis für
> Remote-Arbeit geben, gehört sie als `Own.Time.Remote` ins Rollenmodell und
> nicht als stiller Haken in die Stammdaten. Diese Umsetzung greift dem nicht
> vor. Ob jemand remote arbeiten darf, steht im Arbeitsvertrag; eine
> Zeiterfassung hält fest, wo gearbeitet wurde.

Ohne gepflegte Standorte steht ein **Umschalter** an den unten genannten
Stellen. Er wechselt Farbe und Beschriftung (seit 0.9.22, davor eine
Checkbox):

| Zustand | Darstellung |
|---------|-------------|
| Nicht gesetzt | grau – „Einsatzort · **Vor Ort**" |
| Gesetzt | blau – „Einsatzort · **Remote**" |

### Standorte (seit 0.13.0)

Sind an einer Firma **Standorte** hinterlegt, wird aus dem Umschalter eine
**Auswahlliste in derselben Pille** – gleicher Punkt, gleiche Beschriftung,
gleiche Farben:

```
Firma auswählen  [ Müller GmbH ▾ ]
● Einsatzort       [ Werk Nord · Kiel ▾ ]
                     Vor Ort
                     Remote
                     Werk Nord · Kiel
                     Werk Süd · Ulm
```

Gepflegt werden sie unter Administration → Firmen → *Firma bearbeiten*
(Bezeichnung, Straße, PLZ, Ort, Land). Der **erste Standort** einer Firma wird
automatisch **Hauptstandort** und ist vorausgewählt; ein Standort lässt sich
**schließen** statt löschen und bleibt dann in Auswertungen erhalten.

Ein Standort gehört zu **genau einer Firma**. Angeboten wird er deshalb nur
im Auftragsdialog, sobald die Firma gewählt ist – beim Wechsel der Firma
tauscht die Liste, und der **Hauptstandort** ist vorausgewählt. Beim
**Schnellstempeln** ohne Auftrag gibt es keine Firma und damit nur „Vor Ort"
und „Remote".

Der Standort hängt **nicht** am Benutzerkennzeichen „Einsatzort (Remote/vor
Ort)" (korrigiert in 0.14.1 – vorher verschwand ohne das Kennzeichen die ganze
Auswahl). Ein Firmenstandort ist das Gegenteil von Remote-Arbeit: Wer nie
remote arbeitet, muss trotzdem sagen können, wo er war. Nur die **Option
„Remote"** hängt am Kennzeichen und fehlt ohne es – auf der Seite wie im
Server.

Eine Firma kann als **eigener Betrieb** markiert werden. Das trennt interne
Zeit in Auswertungen von Kundenzeit; wer im eigenen Büro arbeitet, startet
einen Auftrag auf den eigenen Betrieb.

Der Server nimmt einen Standort nur an, wenn er zur gebuchten Firma gehört –
ein veraltetes oder manipuliertes Formular kann keinen fremden Standort
unterschieben.

Ohne gepflegte Standorte bleibt alles beim gewohnten Umschalter. Ein
unbekannter oder geschlossener Standort wird beim Stempeln verworfen und gilt
als „vor Ort" – abgewiesen wird nichts. Standorte gehören zum Lizenzbaustein
`orders`.

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
- **Anzeige**: Buchungslisten, Zeitübersichten und Freigaben tragen neben der
  Firma ein Kennzeichen – den **Standortnamen**, sonst „Remote". Das Dashboard
  zeigt bei laufender Buchung zusätzlich die Anschrift.
- **Exporte**: PDF und Excel zeigen eine zusätzliche Spalte **„Ort"** – aber
  nur, wenn im Zeitraum mindestens eine Buchung einen Einsatzort trägt
  (Standort oder Remote). Wer ihn nicht nutzt, bekommt unveränderte Exporte.
- **Bestandsdaten**: Alle vorhandenen Buchungen gelten als vor Ort und ohne
  Standort. Wird die Option für einen Benutzer wieder deaktiviert, bleiben
  bereits erfasste Angaben erhalten (sie werden nur nicht mehr neu vergeben).
- **Historie**: Wird ein Standort gelöscht, bleibt sein Name an den
  betroffenen Buchungen erhalten („Gelöscht (Werk Nord)") – wie bei Firmen.

## Revisionssichere Erfassung (seit 0.14.0)

> **Keine rechtliche Garantie.** Die folgenden Funktionen bilden gängige
> Anforderungen an eine nachvollziehbare Arbeitszeiterfassung ab. Ob eine
> konkrete Einrichtung den für sie geltenden Vorschriften genügt, entscheidet
> weder diese Software noch diese Dokumentation – das ist mit der eigenen
> Rechtsberatung und der Arbeitnehmervertretung zu klären.

### Nichts wird überschrieben

Originalbuchungen bleiben erhalten. Wird eine Buchung korrigiert, entsteht eine
**Stornierung plus Ersatzbuchung**; beide sind über `replaces_id` und
`replaced_by_id` miteinander verbunden. Auch das Löschen einer Buchung storniert
sie nur – sie verschwindet aus den Summen, nicht aus den Daten.

Jede Änderung, Freigabe, Ablehnung und Stornierung landet in der Tabelle
`time_entry_revisions` mit **Vorher- und Nachher-Stand, Zeitpunkt, Urheber und
Begründung**. Für Änderung, Ablehnung und Stornierung ist die Begründung
**Pflicht** – ohne sie lehnt der Server ab; das Formular unter *Freigaben* hat
dafür ein eigenes Feld. Historisiert werden auch das **Beenden** einer
laufenden Buchung („Beendet" – kein Korrekturvorgang, deshalb ohne
Begründung) und der **Kommentar-Nachtrag** aus der Stempelansicht. Die
Historie einer Buchung steht unter Administration → Auswertungen →
*Historie*.

### Wo stornierte Buchungen stehen

Eine stornierte Buchung ist zurückgenommen, nicht gelöscht. Sie zählt in
**keiner** Summe und in keinem Export mehr mit, bleibt aber sichtbar:

| Ort | Was zu sehen ist |
|-----|------------------|
| Administration → Auswertungen, Filter **Storniert** | alle Stornos des Zeitraums, gedämpft und durchgestrichen |
| Eigene Buchungen (`/records`) | Stand „Storniert" mit **Grund** und Hinweis auf die Ersatzbuchung |
| Historie der Buchung | Vorher/Nachher, Urheber, Begründung und der Verweis auf die Ersatzbuchung |

Bearbeiten lässt sich eine stornierte Buchung nicht mehr – der Weg führt über
die Historie zur Ersatzbuchung.

### Pausen: tatsächlich statt pauschal

Pausen werden als **einzelne Intervalle** mit Beginn und Ende geführt
(`break_intervals`). Eine nicht genommene Pause wird **nicht** als genommen
gebucht. Die gesetzlichen Mindestpausen erscheinen getrennt davon als Sollwert:

| Brutto-Arbeitszeit | Mindestpause |
|--------------------|--------------|
| über 6 Stunden | 30 Minuten |
| über 9 Stunden | 45 Minuten |

Anrechenbar sind nur Abschnitte von **mindestens 15 Minuten**. Bleibt die
tatsächliche Pause hinter dem Sollwert zurück, wird das **gekennzeichnet** – die
tatsächliche Arbeitszeit bleibt unverändert gespeichert.

Bestandsbuchungen behalten ihre alte Rechnung: Jede Buchung trägt in
`break_rule` fest, nach welcher Regel sie berechnet wurde (`legacy_auto` für
alles vor 0.14.0, `actual` ab 0.14.0). Alte Auswertungen ändern sich dadurch
nicht rückwirkend.

### Kunden sind keine Arbeitgeber

**Firmen und ihre Standorte sind Kunden beziehungsweise Auftragsorte.** Sie
dienen der Auftragszuordnung und sind **keine** Quelle für arbeitsrechtliche
Regeln:

| | Quelle |
|---|---|
| Feiertagsregion | zentrale Konfiguration (Administration → Feiertage) |
| Sollzeit, Pausenpflicht, Höchstarbeitszeit, Ruhezeit | Mitarbeiterstammdaten und Gesetz |
| Kunde, Auftrag, Kundenstandort | **nur** Zuordnung und Auswertung |

Wer für einen Kunden in einem anderen Bundesland arbeitet, bekommt deswegen
weder dessen Feiertage noch verliert er die eigenen. Ein Wechsel von Kunde,
Auftrag oder Standort ändert weder Sollzeit noch Pausen-, Höchstarbeitszeit-
oder Ruhezeitregeln. Die Arbeitszeiten **aller** Kunden eines Beschäftigten
werden für die Tages- und Ruhezeitprüfung gemeinsam betrachtet.

### Pausen über die ganze Schicht (seit 0.15.0)

Die Pausenprüfung betrachtet die **chronologische Schicht** über alle Kunden,
Aufträge und Einsatzorte hinweg – nicht die einzelne Buchung:

1. Jede Buchung wird um ihre gebuchten Pausen bereinigt.
2. Überlappende und unmittelbar aufeinanderfolgende Arbeitsintervalle werden
   zusammengeführt.
3. Lücken **unter 15 Minuten** sind Arbeitszeit, keine Ruhepause – ein
   Auftrags-, Kunden- oder Standortwechsel täuscht keine Pause vor.
4. Nur echte Unterbrechungen **ab 15 Minuten** werden angerechnet.
5. Eine Unterbrechung ab der **Schichtgrenze** beendet die Schicht und löst die
   Ruhezeitprüfung nach § 5 ArbZG aus.

Punkt 5 ist eine **betriebliche Festlegung**, keine Zahl aus dem Gesetz: Das
ArbZG kennt den Begriff „Schicht" nicht. Seit 0.16.0 ist der Wert deshalb unter
*Administration → System → Einstellungen* einstellbar (Voreinstellung 360
Minuten, zulässig 60–720). Er liegt persistent im config-Volume, wird beim
Import validiert, und jede Änderung erzeugt einen Audit-Eintrag – sie verändert
die Bewertung von Pausen und Ruhezeiten rückwirkend.

### Ausgleich nach § 3 ArbZG (überarbeitet in 0.17.0)

Mehr als acht Stunden werktäglich sind zulässig, wenn sie ausgeglichen werden.
§ 3 Satz 2 stellt dabei auf den **werktäglichen** Durchschnitt ab – und
Werktage sind Montag bis Samstag, ob gearbeitet wurde oder nicht.

Bis 0.16.0 lief der Durchschnitt über die **Tage mit Buchungen**. Wer an vier
Tagen je zehn Stunden arbeitete und sonst frei hatte, kam damit auf zehn
Stunden Durchschnitt und galt als überfällig, obwohl er über den Zeitraum weit
darunter lag. Seit 0.17.0 rechnet `app/compensation.py`:

- Der Nenner sind die **Werktage des Zeitraums**, nicht die Buchungstage.
  Sonntage zählen nie mit.
- **Feiertage, Urlaub und Ersatzruhetage** fallen aus dem Nenner – keiner von
  ihnen soll Mehrarbeit ausgleichen. Umschaltbar unter *Administration →
  System → Einstellungen*.
- Der Bericht nennt **Zeitraum, Nenner, Durchschnitt und jede Herausnahme**.
- Jeder Tag über acht Stunden ist ein **eigener Vorgang mit eigener Frist**:
  `compensation_required` (Frist läuft), `compensation_due` (Frist läuft ab),
  `compensation_overdue` (Frist verstrichen).
- Freie Kapazität wird **FIFO** zugeordnet – der älteste offene Vorgang hat die
  kürzeste Restlaufzeit. Das Gesetz schreibt keine Reihenfolge vor; diese ist
  die für die Beschäftigten günstigere.

**Offene Festlegung:** Das Gesetz nennt „sechs Kalendermonate **oder** 24
Wochen" gleichrangig. Diese Umsetzung wählt das Wochenraster; der Zeitraum ist
seit 0.17.0 einstellbar; seit 0.18.0 gilt für die Wochenvariante ausdrücklich
der Bereich 4–24 Wochen (Vorgabe 24). Sechs Kalendermonate sind keine pauschale
26-Wochen-Frist.

**Offene Entscheidung:** Krankheitstage bleiben im Nenner, weil die Anwendung
keine Arbeitsunfähigkeit erfasst. Das ist eine fehlende Datenquelle, keine
fachliche Festlegung.

### Sonn- und Feiertagsarbeit dokumentieren (geprüft seit 0.17.0)

Sonntagsarbeit ist nicht verboten, sondern erlaubnispflichtig (§ 10 ArbZG), und
§ 11 Abs. 3 verlangt einen Ersatzruhetag. Zu einer entsprechenden
Kennzeichnung lassen sich unter *Regelverstöße* festhalten:

- **Ausnahmegrund** (z. B. Notdienst, Instandhaltung),
- **Rechts-/Betriebsgrundlage** (Paragraf, Tarifvertrag, Betriebsvereinbarung),
- **Ersatzruhetag**,
- **Bearbeitungsstand** (offen, begründet, Ersatzruhetag gewährt, nicht nötig).

Das Bearbeiten braucht seit 0.17.0 das Recht **`Time.Compliance.Manage`** im
passenden Geltungsbereich – `Time.View` ist nur ein Leserecht.

Die Felder sind seit 0.17.0 nicht mehr beliebig. Pflicht je Bearbeitungsstand:

| Stand | verlangt |
|---|---|
| Offen | – |
| Begründet | Ausnahmegrund **und** Rechts-/Betriebsgrundlage |
| Ersatzruhetag gewährt | zusätzlich den Ersatzruhetag |
| Kein Ersatzruhetag nötig | eine Begründung |

Der Ersatzruhetag wird gegen § 11 Abs. 3 geprüft: nicht **vor** dem Arbeitstag,
**innerhalb der Frist** (zwei Wochen bei Sonntagsarbeit, acht Wochen bei einem
auf einen Werktag fallenden Feiertag, jeweils einschließlich des
Beschäftigungstages), **kein Sonntag und kein Feiertag**, und **nicht doppelt
verwendet** – ein Tag gleicht genau eine Beschäftigung aus.

Jede Änderung landet in einer **append-only Historie** (`compliance_logs`) mit
Vorher- und Nachher-Stand; über die Anwendung lässt sich davon nichts ändern
oder löschen. Einsehbar unter *Regelverstöße → Bewertungshistorie* und Teil
der Auskunft nach Art. 15 DSGVO.

Die geleistete Arbeit bleibt unberührt gespeichert und gekennzeichnet – die
Anwendung entscheidet nicht, ob eine Ausnahme greift (§ 7 und § 14 ArbZG,
Tarifverträge und Bewilligungen sind nicht maschinell entscheidbar), sie hält
fest, worauf sich der Betrieb beruft.

Nachtarbeit über Mitternacht bleibt eine Schicht. Gerechnet wird durchgehend
in UTC, damit die Zeitumstellung das Ergebnis nicht verschiebt.

### Verstöße kennzeichnen, nicht verhindern

Gespeichert wird immer die tatsächliche Zeit. Auffälligkeiten landen als
Kennzeichnung in `compliance_flags` und unter Administration → **Regelverstöße**:

| Kennzeichnung | Auslöser |
|---------------|----------|
| Tageshöchstarbeitszeit | über 8 Stunden (Hinweis) |
| Absolute Höchstgrenze | über 10 Stunden (kritisch) |
| Ruhezeit | unter 11 Stunden zwischen zwei Tagen |
| Pause | tatsächliche Pause unter dem Sollwert |
| Sonn-/Feiertagsarbeit | Buchung an einem Sonntag oder Feiertag |
| Ausgleich erforderlich | Tag über 8 Stunden, Frist nach § 3 Satz 2 läuft noch |
| Ausgleichsfrist läuft ab | Frist endet bald, der Überhang steht noch |
| Ausgleich überfällig | Frist verstrichen, ohne dass ausgeglichen wurde |

Kennzeichnungen lassen sich mit Notiz **zur Kenntnis nehmen**; gelöscht werden
sie nicht. Seit 0.15.0 haben sie einen Lebenszyklus:

| Zustand | Bedeutung |
|---------|-----------|
| Erkannt | neu aufgetreten |
| Geändert | besteht weiter, der bewertete Datenstand hat sich geändert |
| Erledigt | besteht nicht mehr – bleibt trotzdem erhalten |
| Eingeordnet | gesehen und mit Begründung bewertet |
| Wieder geöffnet | nach einer Bestätigung erneut aufgetreten |

**Eine Bestätigung gilt nur für den geprüften Datenstand.** Ändert sich danach
Arbeitszeit, Pause oder Schweregrad, öffnet sich die Feststellung automatisch
wieder – eine Einordnung von gestern deckt keinen Verstoß von heute zu.

Zum Einordnen genügt weder die Kenntnis der Kennzeichnung noch ein
Leserecht. Seit 0.17.0 verlangt jede Änderung an der Bewertung – einordnen,
Ausnahme begründen, Ersatzruhetag eintragen – das Recht
**`Time.Compliance.Manage`** *und* den passenden Geltungsbereich auf die
betroffene Person. Fehlt eines von beidem, antwortet der Server mit **403** und
schreibt einen Security- und einen Audit-Eintrag; die Formulare erscheinen
ohne das Recht gar nicht erst.

Jede Änderung landet zusätzlich in `compliance_logs` – siehe
[Sonn- und Feiertagsarbeit](#sonn--und-feiertagsarbeit-dokumentieren-geprüft-seit-0170).

### Abschluss- und Korrekturworkflow

Unter Administration → **Abrechnungsperioden** wird ein Zeitraum zur Prüfung
freigegeben. Beschäftigte bestätigen ihn oder legen **Widerspruch mit
Begründung** ein; die Arbeitgeberseite antwortet, gibt frei und **sperrt** die
Periode. In einer gesperrten Periode weist der Server neue Buchungen und
Änderungen ab. Ein **Wiederöffnen** ist möglich, verlangt aber eine Begründung
und wird protokolliert.

### Datenschutz

- **Zugriffsprotokoll**: Sieht jemand fremde Zeitdaten ein, wird das in
  `data_access_log` festgehalten. Der Blick auf die eigenen Daten wird nicht
  protokolliert.
- **Aufbewahrungsfristen**: einstellbar in `config/retention.json`
  (Voreinstellung 24 Monate für Buchungen und Historie, 12 Monate für das
  Zugriffsprotokoll). Der Bericht **zählt nur** – gelöscht wird ausschließlich
  auf ausdrückliche Anweisung.
- **Selbstauskunft**: `/api/me/export` liefert alle zur eigenen Person
  gespeicherten Daten als JSON (Person, Buchungen, Änderungshistorie,
  Kennzeichnungen samt **Bewertungshistorie**, Urlaub, Zugriffe auf diese
  Daten). Für die Verwaltung gibt es `/admin/users/{id}/export`.
- **Kein GPS**: Es wird **keine** Ortung durchgeführt und **kein**
  Bewegungsprofil geführt. Gespeichert wird nur der beim Stempeln bewusst
  gewählte Standort – und der gehört zu genau einer Firma.

### Zeitstempel und Nachtarbeit

Zeitstempel werden zusätzlich in **UTC** mit der **ursprünglichen Zeitzone**
(`tz_name`) gespeichert. Buchungen über Mitternacht werden korrekt als eine
Schicht gerechnet; gerechnet wird durchgehend in UTC, damit die Zeitumstellung
das Ergebnis nicht verschiebt (`app/worktime.py` ist seit 0.16.0 die einzige
Quelle für Dauern).

**Betriebszeitzone.** Seit 0.17.0 steht sie in der Systemkonfiguration im
config-Volume und ist unter *Administration → System → Einstellungen*
einstellbar. Reihenfolge: gespeicherte Konfiguration → `ERFASSUNG_TIMEZONE` →
Vorgabe `Europe/Berlin`. Die Umgebungsvariable ist damit nur noch eine
Vorbelegung bei der **Erstinstallation** – eine gespeicherte Konfiguration
überschreibt sie nie, wie bei der Datenbankkonfiguration auch.

Sie gilt für das ganze Unternehmen; ein Kundenstandort ändert sie nicht. Eine
Änderung wirkt **ausschließlich auf neue Buchungen**: Bestehende tragen ihr
`tz_name` mit sich und werden nicht umgeschrieben, sonst verschöben sich
vergangene Zeiten rückwirkend. Jede Änderung wird auditiert; eine unbekannte
Zone wird abgelehnt und die bisherige bleibt bestehen.

### Bestand bleibt

Migration 17 legt die neuen Tabellen und Spalten an, ohne bestehende Daten zu
verändern: Alle vorhandenen Buchungen erhalten `break_rule = legacy_auto` und
einen Eintrag „angelegt" in der Historie. Backups, Offline-PWA,
Terminal-Importe, Exporte und die Rollenrechte bleiben unverändert; die neuen
Tabellen wandern automatisch in das logische Backup und damit auch über
Datenbankgrenzen hinweg.

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

Seit 0.14.2 gilt das auch in der **Adminauswertung**, im **Excel-** und
**PDF-Export** sowie über `POST /api/vacations` – dort zählten halbe Tage
vorher als ganze.

### Urlaubsübersicht (seit 0.14.2)

Unter *Administration → Auswertungen → **Urlaubsübersicht*** steht der
Urlaubsstand aller Mitarbeitenden nebeneinander:

| Spalte | Bedeutung |
|--------|-----------|
| Anspruch | Jahresanspruch plus Übertrag aus dem Vorjahr |
| Genommen | genehmigte Anträge des Jahres |
| Beantragt | noch offene Anträge – bereits verplant |
| **Verbleibend** | Anspruch minus genommen minus beantragt |
| Überstundenabbau | getrennt ausgewiesen: zehrt vom Zeitkonto, nicht vom Urlaub |

Gerechnet wird mit derselben Funktion wie in der Ansicht der Person – zwei
Zahlen für dieselbe Sache dürfen nicht auseinanderlaufen.

Nötig ist das Recht **`Vacation.Overview`** („Urlaubsübersicht einsehen"). Es
hat einen eigenen Geltungsbereich (*alle* oder *eigenes Team*) und ist bewusst
von `Vacation.Manage` getrennt: Den Resturlaub eines Teams zu sehen ist etwas
anderes, als über Anträge zu entscheiden. **Bestehende Rollen bekommen es
nicht automatisch** – es ist in der Rollenverwaltung zu vergeben.

### Änderungsprotokoll (seit 0.14.2)

Unter *Administration → Auswertungen → **Änderungsprotokoll*** stehen alle
Vorgänge über alle Buchungen: Anlage, Beenden, Änderung, Freigabe, Ablehnung
und Stornierung – mit Vorher/Nachher, Bearbeiter, Zeitpunkt und Begründung.
Filter nach Vorgang und Zeitraum, aus jeder Zeile ein Weg in die Historie der
einzelnen Buchung.

Der Zeitraum bezieht sich auf das **Buchungsdatum**, nicht auf den Zeitpunkt
der Änderung: So bleibt eine späte Korrektur an einer alten Buchung dort, wo
man sie sucht. Sichtbar mit `Time.View`.

### Feiertage (seit 0.14.2)

Ein gesetzlicher Feiertag ist ein **bezahlter Ausfalltag** und wird mit der
individuellen Tagessollzeit gutgeschrieben – genau wie ein Urlaubstag:

```
Ist = gestempelte Zeit + Urlaub + Feiertag
Saldo = Ist − Soll
```

Die Sollzeit bleibt unverändert (jeder Werktag Mo–Fr); die Gutschrift kommt
auf der Habenseite dazu. Das ergibt denselben Saldo wie eine Kürzung der
Sollzeit, macht aber sichtbar, woher die Stunden kommen.

| Fall | Verhalten |
|------|-----------|
| Feiertag Mo–Fr | Gutschrift in Höhe der Tagessollzeit |
| Feiertag Sa/So | keine Gutschrift – kein Arbeitstag, kein Ausfall |
| Teilzeit | nach **individueller** Tagessollzeit (4 Std → 4 Std) |
| Feiertag **im Urlaub** | verbraucht **keinen** Urlaubstag, wird trotzdem gutgeschrieben |
| Feiertag im **Überstundenurlaub** | belastet das Zeitkonto nicht |
| **Arbeit** am Feiertag | zählt zusätzlich – und wird als Feiertagsarbeit gekennzeichnet (§9 ArbZG) |

Maßgeblich ist die eingestellte **Feiertagsregion** (Administration →
Feiertage). Die gesetzlichen Feiertage legt die Anwendung beim Start selbst
an. Die Gutschrift erscheint getrennt ausgewiesen in Dashboard, Wochen- und
Tagesansicht, eigenen Buchungen, Admin- und Benutzerauswertung, PDF- und
Excel-Export sowie im Offline-Snapshot der Stempel-App.

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
| `orders` | Aufträge, Firmen, Standorte, auftragsbezogenes Stempeln |
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

# Release Notes 0.11.0 – Lizenzierung

Diese Version verbindet die Zeiterfassung mit dem **Erfassung-Lizenzserver**
(eigenes Repository `joni123467/Erfassung_Lizenzserver`). Eine Installation
lässt sich damit einmalig aktivieren, prüft ihre Lizenz anschließend offline
und hält sich an die lizenzierte Benutzerzahl.

## Kurzfassung

| | |
|---|---|
| Neu | Administration → System → **Lizenz** |
| Neu | `GET /api/license` (Status als JSON, ohne Geheimnisse) |
| Neu | Protokollkanal `license.log` |
| Neu | `config/license.json` (Deployment-ID, Serveradresse, signiertes Dokument) |
| Durchgesetzt | Benutzerobergrenze `max_users`, Ablaufdatum |
| Nicht durchgesetzt | alles Übrige – eine Installation ohne Lizenz läuft weiter |
| Datenbank | **keine** Schemaänderung, keine Migration nötig |

## Ablauf

### 1. Deployment-ID

Beim ersten Start erzeugt die Anwendung eine dauerhafte Kennung im Format
`erfassung-<32 Hexzeichen>` und legt sie in `config/license.json` ab. Sie ist
reiner Zufall: **keine** Hardwaremerkmale, **keine** personenbezogenen Daten,
kein Hostname. Solange das `config`-Volume mitwandert, überlebt sie einen
Serverumzug – die Lizenz muss dann nicht erneut aktiviert werden.

### 2. Aktivierung

> Administration → System → Lizenz → *Installation aktivieren*

Serveradresse und Aktivierungsschlüssel eintragen, fertig. Die Anwendung ruft
`POST /v1/activations` auf und erhält ein **Ed25519-signiertes Lizenzdokument**
mit Lizenz-ID, Kunde, Edition, Merkmalen, `max_users` und Ablaufdatum.

Der Aufruf ist idempotent: Dieselbe Deployment-ID verbraucht keinen weiteren
Aktivierungsplatz. „Erneut prüfen“ holt deshalb jederzeit gefahrlos ein
frisches Dokument – nötig nach einer Verlängerung oder Erweiterung.

### 3. Offline-Prüfung

Bei jedem Start und bei jeder Statusabfrage wird das gespeicherte Dokument
gegen die in `app/licensing_keys.py` eingebetteten öffentlichen Schlüssel
geprüft. Der Lizenzserver muss dafür **nicht** erreichbar sein. Geprüft werden:

1. Version des Dokumentschemas,
2. Ed25519-Signatur über die kanonische JSON-Form (sortierte Schlüssel, keine
   Leerzeichen, kein ASCII-Escaping) ohne das Feld `signature`,
3. Produktkennung,
4. Deployment-ID – ein Dokument einer anderen Installation wird abgelehnt,
5. Ablaufdatum.

Schlägt einer der Punkte fehl, steht der Grund auf der Lizenzseite und in
`license.log`.

## Was durchgesetzt wird

| Zustand | Wirkung |
|---------|---------|
| **Nicht lizenziert** | Hinweis im Administrationsbereich. Sonst nichts – ein Update darf einen laufenden Betrieb nicht stilllegen. |
| **Lizenziert** | Neue Benutzer nur bis `max_users` (`0` = unbegrenzt). Ab 30 Tagen vor Ablauf erscheint eine Warnung. |
| **Abgelaufen / ungültig** | Keine neuen Benutzer. Alles Übrige – Stempeln, Auswertungen, Urlaub, Backups – bleibt uneingeschränkt nutzbar. |

Über die Oberfläche wird die Grenze mit Klartextmeldung abgewiesen, über
`POST /api/users` mit **HTTP 402** und derselben Begründung. Bestehende
Benutzer werden nie gesperrt oder gelöscht.

Optionale Merkmale aus dem Lizenzdokument stehen über
`licensing.has_feature("name")` bereit und werden auf der Lizenzseite
angezeigt; in dieser Version hängt noch keine Funktion daran.

## Umgang mit dem Aktivierungsschlüssel

Der Schlüssel liegt in `config/license.json`, damit die Installation ihre
Lizenz ohne erneute Eingabe nachprüfen kann. Abgesichert ist er so:

- Die Datei wird mit Dateirechten **0600** geschrieben.
- In der Oberfläche erscheint ausschließlich die maskierte Form (`••••-1234`).
- In `license.log` und jedem anderen Protokoll ebenfalls nur maskiert.
- Der Einstellungsexport (`/admin/system/settings/export`) enthält **keine**
  Lizenzdaten – die Datei ist installationsspezifisch und gehört nicht in eine
  Konfigurationsvorlage.
- `GET /api/license` liefert weder Schlüssel noch Signatur.

Wer den Schlüssel gar nicht speichern will, entfernt nach der Aktivierung das
Feld `activation_key` aus `config/license.json`. Die Lizenz bleibt gültig –
nur „Erneut prüfen“ verlangt dann wieder eine Eingabe.

## Grenzen des Kopierschutzes

Eine einmalige Aktivierung verhindert weitere **reguläre** Aktivierungen. Sie
verhindert **nicht** das vollständige Klonen einer bereits aktivierten
Installation: Wer `config`- und `data`-Volume kopiert, bekommt eine zweite
laufende Installation mit demselben Lizenzdokument. Das System ist damit kein
vollständiger Kopierschutz und wird auch nicht als solcher dargestellt.

Weitere Restrisiken:

- **Die Anwendung ist selbstgehostet.** Wer den Quellcode ändert, kann
  `app/licensing_keys.py` austauschen oder die Prüfung entfernen. Die
  Lizenzprüfung schützt vor versehentlicher Mehrfachnutzung, nicht vor
  bewusster Manipulation der eigenen Installation.
- **Widerruf wirkt verzögert.** Eine gesperrte Lizenz greift erst bei der
  nächsten Aktivierung bzw. erneuten Prüfung. Wer schnellere Wirkung braucht,
  vergibt kurze Laufzeiten (`expires_at`).
- **Die Ablaufprüfung nutzt die lokale Uhr** und lässt sich auf dem
  Kundensystem manipulieren.
- **Ohne eingebetteten Prüfschlüssel** (Auslieferung ohne
  `EMBEDDED_PUBLIC_KEYS`) läuft die Anwendung dauerhaft im Zustand „nicht
  lizenziert“. Die Lizenzseite weist darauf hin.

## Für Herausgeber: Prüfschlüssel einbetten

Im Lizenzserver-Repository:

```bash
python -m app.cli keygen --private-out /run/secrets/license_signing_key.pem
```

Der Befehl gibt das **öffentliche** PEM aus; der private Schlüssel verlässt den
Lizenzserver nie. Das PEM in `app/licensing_keys.py` eintragen:

```python
EMBEDDED_PUBLIC_KEYS = {
    "k1": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n",
}
```

Die `key_id` (hier `k1`) steht in jedem Lizenzdokument. Bei einer Rotation
bleibt der alte Eintrag stehen, bis alle Installationen ein neu signiertes
Dokument erhalten haben.

Für Entwicklung und Tests lässt sich die Zuordnung über die Umgebungsvariable
`ERFASSUNG_LICENSE_PUBLIC_KEYS` (JSON-Objekt `{"key_id": "<PEM>"}`)
überschreiben.

## Änderungen im Detail

**Neu**

- `app/licensing.py` – Deployment-ID, Persistenz, Signaturprüfung,
  Aktivierung/Deaktivierung, Durchsetzung.
- `app/licensing_keys.py` – eingebettete öffentliche Prüfschlüssel.
- `templates/admin/system_license.html` – Statusseite mit Aktivierungsformular.
- Routen `/admin/system/license`, `.../activate`, `.../recheck`,
  `.../deactivate` (alle unter `System.Settings`) und `GET /api/license`.
- Protokollkanal `license` inkl. Schalter „Lizenz-Logging“ in den
  Systemeinstellungen.
- `cryptography` als ausdrückliche Abhängigkeit (bisher nur transitiv über
  `smbprotocol`).

**Geändert**

- Jede Administrationsseite zeigt einen Hinweisbalken, solange die Lizenz
  fehlt, ungültig ist oder binnen 30 Tagen abläuft.
- Benutzeranlage prüft die Lizenzgrenze – in der Oberfläche und über die API.
- Beim Start wird der Lizenzstatus geprüft und protokolliert. Der Start
  scheitert nie an der Lizenz.

**Tests**

`tests/test_v0110.py` – 48 Tests: Deployment-ID (Stabilität, Zufall, keine
Hostdaten, Dateirechte, Verengung nach einem Restore), Offline-Prüfung (gültig,
manipuliert, fremder Schlüssel, fremde Installation, fremdes Produkt,
unbekannte Schemaversion, abgelaufen, Ablauffenster), kanonisches JSON,
Aktivierung (Speichern,
Ablehnung ohne Speichern, Fehlerübersetzung 403/429/422/500, unerreichbarer
Server, erneute Prüfung, Deaktivierung mit und ohne Server), Durchsetzung
(unlizenziert, Grenze, `max_users = 0`, abgelaufen, HTML- und API-Anlage),
Oberfläche (Status, maskierter Schlüssel, Navigation, Balken, Formular,
Berechtigungen) sowie Protokoll und Export.

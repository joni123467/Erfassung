# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.14.0] – 2026-07-31

### Added – Revisionssichere Erfassung nach ArbZG, MiLoG und DSGVO

**Keine rechtliche Garantie.** Diese Umsetzung erfüllt technische
Anforderungen; sie ist nicht zertifiziert und ersetzt keine Rechtsberatung.
Ausnahmen nach §7/§10 ArbZG und Tariföffnungen kann eine Software nicht
bewerten, und Revisionssicherheit endet an der Anwendungsgrenze. In Betrieben
mit Betriebsrat ist die Einführung nach §87 Abs. 1 Nr. 6 BetrVG
mitbestimmungspflichtig.

- **Revisionshistorie** (`time_entry_revisions`): Anlage, Änderung, Freigabe,
  Ablehnung und Stornierung mit Vorher/Nachher, Zeitpunkt, Bearbeiter, Quelle
  und Begründung. Ändern, Ablehnen und Stornieren **erfordern** eine
  Begründung; fehlt sie, wird der Vorgang abgewiesen. Ansicht unter
  `/admin/time-entries/<id>/history`.
- **Korrektur über Storno und Ersatzbuchung** (`crud.replace_time_entry`);
  beide Buchungen verweisen aufeinander. `delete_time_entry()` storniert
  jetzt. Auch das Überschreiben kollidierender Buchungen und der vollständig
  abdeckende Nachtrag stornieren statt zu löschen.
- **Pausenintervalle** (`break_intervals`) mit Beginn und Ende statt einer
  Summe. Grenzen korrigiert auf **mehr als** 6 Stunden = 30 Minuten und
  **mehr als** 9 Stunden = 45 Minuten (bisher schon *ab* sechs Stunden);
  Ruhepause erst ab 15 Minuten Abschnitt.
- **Nicht genommene Pausen werden nicht mehr abgezogen.** Die tatsächliche
  Zeit steht in der Buchung, der Fehlbetrag wird gekennzeichnet.
  Bestandsbuchungen behalten über `break_rule = legacy_auto` ihre bisherige
  Rechnung – abgerechnete Monate ändern sich nicht rückwirkend.
- **Regelverstöße** (`compliance_flags`): mehr als 8 bzw. 10 Stunden, Ruhezeit
  unter 11 Stunden, fehlende Pause, Sonn- und Feiertagsarbeit. Sie
  kennzeichnen und blockieren nichts; Einordnung mit Pflichtbegründung unter
  *Administration → Regelverstöße*.
- **Abschlussworkflow** (`payroll_periods`, `period_confirmations`): offen →
  Mitarbeiterprüfung → freigegeben → gesperrt. Bestätigung oder Widerspruch
  mit Begründung, Antwort des Arbeitgebers; eine gesperrte Periode weist jede
  Änderung ab. Entsperren nur mit Begründung, die vermerkt bleibt.
- **Zugriffsprotokoll** (`data_access_log`) für Lesezugriffe auf fremde
  Zeitdaten – ohne IP-Adresse, eigene Daten erzeugen keinen Eintrag.
- **Aufbewahrungsfristen** einstellbar (`config/retention.json`), Vorgabe 24
  Monate für Buchungen und 12 für das Zugriffsprotokoll. Automatisch gelöscht
  wird **nichts**; `privacy.retention_report()` zeigt nur, was die Frist
  überschritten hat.
- **Auskunftsexport** nach Art. 15 DSGVO: `/api/me/export` und – protokolliert
  – `/admin/users/<id>/export`, inklusive Historie und Zugriffen.
- **Vollständige Zeitstempel**: `started_at_utc`, `ended_at_utc` und `tz_name`
  an neuen Buchungen (`ERFASSUNG_TIMEZONE`, Vorgabe `Europe/Berlin`).
  Bestandsbuchungen werden nicht nachträglich umgerechnet. Nachtarbeit über
  Mitternacht ist zusätzlich durch Tests abgesichert.

**Keine GPS-Ortung, keine Bewegungsprofile** – und dieses Release führt auch
keine ein.

### Fixed

- `total_break_minutes` und `auto_break_enabled` lösten auf einer von ihrer
  Sitzung gelösten Buchung eine Ausnahme aus; beide prüfen jetzt vorher.
- Stornierte Buchungen blockierten die Überschneidungsprüfung. Sie zählen
  nicht mehr und belegen deshalb keinen Zeitraum.

### Datenbank

Migration **17** (`_add_compliance_and_revisions`) in beiden Mechanismen:
sechs neue Tabellen, neun neue Spalten an `time_entries`. Idempotent und
datenerhaltend; Bestandsbuchungen bekommen `legacy_auto`, eine laufende Pause
wird in ein Intervall überführt, und jede vorhandene Buchung erhält einen
Anlagevermerk. Portables DDL für SQLite, MySQL, MariaDB und PostgreSQL.

### Tests

`tests/test_v0140.py` – 42 Tests. Details in
[`docs/RELEASE_NOTES_0.14.0.md`](docs/RELEASE_NOTES_0.14.0.md).

## [0.13.1] – 2026-07-31

### Fixed – Standorte gehören zu ihrer Firma

0.13.0 hat die Standorte bewusst **nicht** an die gewählte Firma gebunden. Das
war in der Praxis falsch: Beim Schnellstempeln standen Firmenstandorte zur
Wahl, obwohl es dort keine Firma gibt; im Auftragsdialog blieb „Vor Ort"
vorausgewählt statt des Standorts der Firma; und es waren firmenfremde
Standorte wählbar.

- **Schnell stempeln** bietet wieder ausschließlich **Vor Ort** und **Remote**.
- Der **Auftragsdialog** zeigt neben Vor Ort und Remote nur die Standorte der
  **gewählten Firma**. Beim Wechsel der Firma tauscht die Liste, und der
  **Hauptstandort** ist vorausgewählt.
- Dasselbe gilt für den Nachtrag und die Buchungsbearbeitung.
- **Serverseitig geprüft**: Ein Standort wird nur angenommen, wenn er zur
  gebuchten Firma gehört. Ein veraltetes oder manipuliertes Formular kann
  keinen fremden Standort unterschieben; verworfen wird still („vor Ort"),
  abgewiesen wird nichts.
- Der Einsatzort wird bei `/punch` erst aufgelöst, wenn die Firma feststeht –
  bei `start_company` also nach dem eventuellen Anlegen einer neuen Firma.
- Auch die Standorte des **eigenen Betriebs** hängen jetzt an ihrer Firma; wer
  im eigenen Büro arbeitet, startet einen Auftrag darauf. Die Markierung
  behält ihren Zweck: interne Zeit bleibt in Auswertungen unterscheidbar.

Die Standorte liegen als JSON in der Seite (`#location-catalogue`), der
Wechsel läuft ohne Nachladen und damit auch offline; die Stempel-App zieht
dieselbe Liste aus dem Offline-Speicher.

### Datenbank

Keine Schemaänderung, keine Migration.

### Tests

`tests/test_v0130.py` – 27 Tests. Details in
[`docs/RELEASE_NOTES_0.13.1.md`](docs/RELEASE_NOTES_0.13.1.md).

## [0.13.0] – 2026-07-31

### Added – Standorte statt „Vor Ort“

Der Einsatzort war bisher ein Ja/Nein: Remote oder vor Ort. Jetzt hat jede
Firma beliebig viele Standorte mit Anschrift, und eine Buchung zeigt auf genau
einen davon.

- Neue Stammdaten je Firma: **Standorte** (Bezeichnung, Straße, PLZ, Ort,
  Land) unter Administration → Firmen → *Firma bearbeiten*. Der erste Standort
  wird automatisch **Hauptstandort** und ist beim Stempeln vorausgewählt;
  Standorte lassen sich **schließen** statt löschen und bleiben dann in
  Auswertungen erhalten.
- Eine Firma lässt sich als **eigener Betrieb** markieren (`is_internal`). Ihre
  Standorte stehen auch beim Stempeln **ohne Auftrag** zur Wahl – für die
  eigenen Büros – und stehen in der Auswahl oben. Damit braucht es keinen
  zweiten Katalog für eigene Adressen.
- Beim Stempeln wird aus dem Umschalter eine **Auswahlliste in derselben
  Pille**, sobald Standorte gepflegt sind: gleicher Punkt, gleiche
  Beschriftung „Einsatzort“, gleiche Farben. Ohne Standorte bleibt es exakt
  beim bisherigen Schalter. Bewusst ein Bedienelement statt Schalter *und*
  Liste.
- Der Einsatzort hängt **nicht** an der gewählten Firma: Wer für Kunde A
  arbeitet, kann im eigenen Büro sitzen. *(Nur 0.13.0 – seit 0.13.1 gehört ein
  Standort zu genau einer Firma.)*
- Laufende Buchung, Buchungslisten, Freigaben und Auswertungen zeigen den
  Standortnamen (mit Anschrift im Dashboard). Die Spalte „Ort“ in PDF und
  Excel erscheint jetzt auch, wenn nur Standorte und kein Remote genutzt wird.
- `GET /mobile/sync-data` liefert die Standorte samt Anschrift; die
  Offline-Shell schreibt sie beim Start in die Auswahllisten und nimmt den
  Standort in die Warteschlange mit.

**Bestandsdaten bleiben unberührt:** `location_id` ist bei allen vorhandenen
Buchungen `NULL` und damit weiterhin „Remote“ bzw. „Vor Ort“; jede vorhandene
Firma ist ein Kunde. Ein unbekannter oder geschlossener Standort wird beim
Stempeln verworfen statt abgewiesen – eine Stempelung darf nie an einer
Stammdatenfrage scheitern.

Standorte gehören zum Lizenzbaustein **`orders`**. Ohne ihn bleibt es beim
Umschalter.

### Changed – Stempelkarte aufgeräumt

Die Aktionsknöpfe lagen in einer einzigen umbrechenden Reihe; bei schmalem
Fenster stand „Arbeitszeit beenden“ zwischen den Pausenknöpfen. Jetzt
gruppiert: Pause, Auftrag, und die abschließende Aktion abgesetzt am rechten
Rand. Auf schmalen Schirmen stapeln die Gruppen mit Trennlinie untereinander.
Im Startzustand steht der Einsatzort in einer eigenen Zeile über den Knöpfen –
er gilt für die Buchung, nicht für einen einzelnen Knopf.

### Datenbank

Migration **16** (`_add_company_locations`), in beiden Mechanismen gepflegt:
neue Tabelle `company_locations`, `companies.is_internal` (Default `0`),
`time_entries.location_id` und `time_entries.deleted_location_name`. Geprüft
gegen eine 0.12.x-Datenbank – Spalten ergänzt, Tabelle angelegt, Buchungen
unverändert.

Wie bei Firmen bleibt der Name eines gelöschten Standorts an den betroffenen
Buchungen erhalten (`deleted_location_name`), auch beim Löschen der ganzen
Firma. War er der Hauptstandort, rückt der nächste nach.

### Tests

`tests/test_v0130.py` – 24 Tests. Details in
[`docs/RELEASE_NOTES_0.13.0.md`](docs/RELEASE_NOTES_0.13.0.md).

## [0.12.2] – 2026-07-31

### Added – Änderungen wirken schnell

- Die selbsttätige Nachfrage läuft **stündlich statt täglich** und zusätzlich
  **bei jedem Start**. Eine Änderung am Lizenzserver wirkt damit spätestens
  nach einer Stunde, nach einem Neustart des Containers sofort. Verstellbar
  über `ERFASSUNG_LICENSE_CHECK_MINUTES` (Untergrenze 5 Minuten; unbrauchbare
  Werte werden ignoriert statt den Start zu verhindern).
- Neuer Knopf **„Lizenz aktualisieren"** auf der Lizenzseite
  (`POST /admin/system/license/refresh`): holt den Stand sofort vom
  Lizenzserver und nennt in der Rückmeldung, **was sich geändert hat** –
  Zustand, Benutzerzahl, Laufzeit, hinzugekommene und entfallene Bausteine,
  aufgehobene Sperre. Der bisherige Knopf heißt jetzt **„Neu aktivieren"** und
  wiederholt weiterhin die vollständige Aktivierung.
- `licensing.refresh_now()` fällt auf die vollständige Aktivierung zurück,
  wenn ein älterer Lizenzserver die Zustandsabfrage nicht kennt.
- `licensing.describe_changes()` vergleicht zwei Lizenzzustände und benennt den
  Unterschied – Grundlage der Rückmeldung des Knopfes.

**Unverändert:** Ist der Lizenzserver nicht erreichbar, ändert sich nichts.
Weder die häufigere Nachfrage noch die Prüfung beim Start noch der neue Knopf
können etwas wegnehmen – die hinterlegte Lizenz bleibt in vollem Umfang gültig,
bis sie abläuft. Nur eine ausdrückliche Sperrmeldung startet die
Übergangsfrist.

### Fixed

- **Auftragsbezogenes Stempeln lief ohne Lizenz weiter.** Firmen- und
  Auftragsauswahl gehören zum Baustein `orders`, `/punch` war aber bewusst
  ganz von der Middleware ausgenommen, damit Stempeln nie blockiert. Jetzt
  entfällt ohne `orders` der ganze Auftragsteil in Dashboard, Mobilansicht und
  Synchronisation, und `start_company` sowie ein Nachtrag mit Firma werden
  serverseitig abgewiesen. **„Auftrag beenden" bleibt erlaubt** – läuft eine
  Lizenz mitten im Auftrag aus, muss sich die Buchung schließen lassen, sonst
  ginge Arbeitszeit verloren. Das reine Stempeln ist unverändert offen.

### Datenbank

Keine Schemaänderung, keine Migration.

### Tests

`tests/test_v0121.py` wächst auf 41 Tests. Neu: Auftragsstart gesperrt und
Auftragsende offen, Firmenliste und `create_companies` in
`/mobile/sync-data`, Nachtrag mit Firma abgewiesen, stündliches Intervall samt
Grenzen der Umgebungsvariablen, Nachfrage beim Start, und „Lizenz
aktualisieren“ – wirkt sofort, nennt die Änderung, lässt bei unerreichbarem
Server alles unangetastet.

Details in [`docs/RELEASE_NOTES_0.12.2.md`](docs/RELEASE_NOTES_0.12.2.md).

## [0.12.1] – 2026-07-30

### Changed – Ohne Lizenz keine zubuchbare Funktion

0.12.0 hat die Funktionsbausteine eingeführt, eine unlizenzierte Installation
aber offen gelassen. Das war widersprüchlich: Wer **keine** Lizenz hatte,
konnte mehr als wer eine ohne Bausteine hatte – die Lizenz war damit folgenlos.
Ab sofort entscheidet ausschließlich das Lizenzdokument.

- `LicenseStatus.has_feature()` liefert nur noch `True`, wenn eine **gültige**
  Lizenz den Baustein nennt. „Nicht lizenziert“, „abgelaufen“ und „ungültig“
  schalten nichts mehr frei; nach abgelaufener Übergangsfrist einer Sperre
  bleibt es wie bisher bei `False`.
- Neu: `LicenseStatus.add_ons_available` ersetzt `features_enforced` – die
  Frage lautet jetzt „kann diese Lizenz überhaupt etwas freischalten?“ statt
  „wird überhaupt durchgesetzt?“.
- `user_limit_error()` weist auch ohne hinterlegte Lizenz ab: Ohne Aktivierung
  lassen sich keine neuen Benutzer anlegen. Über die Oberfläche mit
  Klartextmeldung, über `POST /api/users` mit **HTTP 402**.
- Auch außerhalb des Administrationsbereichs verschwindet Gesperrtes aus der
  Oberfläche: der Urlaubsreiter unter „Buchungen“, die Urlaubsübersicht auf
  dem Dashboard und Reiter samt Antragsformular in der Mobilansicht. Diese
  Vorlagen haben keinen gemeinsamen Kontextaufbau und fragen über die neue
  Jinja-Funktion `has_license_feature('vacation')` einzeln nach. Auch
  `GET /mobile/sync-data` liefert ohne Lizenz keine Urlaubsanträge, kein
  Urlaubskonto und `request_vacations: false` – die Offline-Shell stellt einen
  gesperrten Antrag damit gar nicht erst in die Warteschlange.
- `GET /api/license` liefert zusätzlich `feature_access` – was tatsächlich
  nutzbar ist, im Unterschied zu `features` aus dem Dokument. Beides fällt
  etwa nach einer Sperre auseinander.
- Der Hinweisbalken nennt die Folge beim Namen, statt nur den Status zu
  melden; die Lizenzseite erklärt, was offen bleibt und warum.
- Der Startlauf protokolliert „nicht lizenziert“ als Warnung.

### Fixed

- `GET /api/users/{id}/excel` war nicht lizenzpflichtig, obwohl es eine
  Auswertung ist: Am Pfadpräfix ließ es sich nicht von der Benutzer-API
  unterscheiden, die zur Basis gehört. Die Middleware kennt dafür jetzt
  zusätzlich Muster (`LicenseFeatureMiddleware.PATTERNS`).

**Unverändert offen bleibt die Basis** – Stempeln, eigene Zeitübersicht, die
bereits angelegten Benutzer, Sicherungen, Systemeinstellungen und die
Lizenzseite selbst. Wer nicht stempeln kann, verliert Arbeitszeit, die sich
nicht nachholen lässt; wer nicht sichern kann, verliert sie endgültig. Eine
Lizenzfrage darf keine Daten kosten und niemanden aus seinen eigenen Daten
aussperren. Die Grundausstattung einer frischen Installation entsteht beim
ersten Start und geht nicht durch die Lizenzprüfung – eine noch nicht
aktivierte Installation lässt sich also einrichten und aktivieren.

> **Wirkung auf Bestandsinstallationen:** Eine Installation ohne Lizenz
> verliert mit diesem Update Aufträge, Urlaubsplanung, Auswertungen und
> Terminals sowie die Möglichkeit, neue Benutzer anzulegen. Vorhandene Daten
> bleiben unangetastet und werden nach einer Aktivierung wieder erreichbar.

### Tests

`tests/test_v0121.py` – 27 Tests: jeder zubuchbare Bereich ohne Lizenz zu
(Oberfläche und API), Basis offen, Navigation ohne die gesperrten Punkte,
Benutzeranlage abgewiesen, Stempeln und Anmelden weiterhin möglich,
abgelaufene und ungültige Lizenz schalten nichts frei, gültige Lizenz öffnet
weiterhin genau das Genannte, `feature_access` in der API.
Neu ist außerdem `tests/licensed_env.py`: Die Fachtests der zubuchbaren
Bereiche liefen bisher ohne Lizenz, weil ohne Lizenz alles offen war. Sie
aktivieren ihre Testinstanz jetzt mit einem selbst signierten Dokument mit
allen Bausteinen und prüfen damit weiterhin Fachlogik statt Lizenzierung.

Angepasst: `test_has_feature_follows_the_license` und
`test_without_a_license_no_new_users` in `tests/test_v0110.py` sowie
`test_without_a_license_no_module_is_reachable` in `tests/test_v0120.py`.

## [0.12.0] – 2026-07-30

### Added – Funktionsbausteine

Eine Lizenz schaltet Bereiche frei. **Immer enthalten**: Stempeln, eigene
Zeitübersicht, Benutzer-/Gruppen-/Rollenverwaltung, Sicherungen,
Systemeinstellungen. Zubuchbar:

| Baustein | Schaltet frei |
|---|---|
| `orders` | Aufträge, Firmen, auftragsbezogenes Stempeln |
| `vacation` | Urlaubsanträge, Urlaubskonten, Urlaubsfreigaben |
| `reports` | PDF-/Excel-Exporte, Benutzer- und Team-Auswertungen |
| `terminals` | RFID-Terminals und Geräte-Synchronisation |

Eine Lizenz ohne jeden Baustein ist eine reine Stempel-Lizenz. Gesperrte
Bereiche verschwinden aus der Navigation; ein direkter Aufruf landet mit
Hinweis auf dem Dashboard, die API antwortet mit **HTTP 402**. Durchgesetzt
wird das über eine Middleware (`LicenseFeatureMiddleware`) statt Route für
Route – so kann kein Endpunkt versehentlich offen bleiben.

**Ohne hinterlegte Lizenz bleibt alles offen.** Ein Update darf einen
laufenden Betrieb nicht beschneiden.

### Added – Regelmäßige Prüfung beim Lizenzserver

- Ein Hintergrundthread (`app/license_scheduler.py`) fragt einmal täglich
  nach (`POST /v1/activations/state`) und erhält ein frisch signiertes
  Dokument. Änderungen an Benutzerzahl, Laufzeit und Bausteinen wirken damit
  ohne Zutun des Kunden.
- **Ein unerreichbarer Lizenzserver sperrt nie.** Störung, Netzausfall oder
  abgeschalteter Server lassen die gespeicherte Lizenz unverändert
  weiterlaufen; der Vorfall landet nur in `license.log`. Auch ein älterer
  Lizenzserver ohne diesen Endpunkt ist unschädlich.
- Auch das frische Dokument wird vor der Übernahme geprüft: Signatur,
  Deployment-ID, Produkt und Schemaversion. Ein gefälschtes Dokument ersetzt
  nie das gespeicherte.

### Added – Übergangsfrist bei Sperrung

Meldet der Server `suspended`, `revoked` oder `expired`, beginnt eine
**Übergangsfrist von 14 Tagen**:

- Tag 0–14: deutlicher Hinweis mit Restfrist auf jeder Administrationsseite,
  sonst arbeitet alles weiter.
- Ab Tag 15: Aufträge, Urlaubsplanung, Auswertungen und Terminals sind
  gesperrt.
- Immer offen: Stempeln, eigene Zeitübersicht, Benutzerverwaltung,
  Sicherungen – eine Lizenzfrage darf keine Arbeitszeitdaten kosten.

Eine Freigabe durch den Herausgeber beendet die Frist bei der nächsten
Nachfrage sofort.

### Changed

- Die Lizenzseite zeigt jeden Baustein mit seinem Zustand, den letzten
  Serverkontakt und bei einer Sperre die Restfrist.
- `GET /api/license` liefert zusätzlich `blocked_status`, `blocked_reason`,
  `grace_days_left`, `grace_expired` und `last_contact_at`.
- `config/license.json` merkt sich Sperrzustand, Beginn der Frist und den
  letzten Serverkontakt.

### Datenbank

Keine Schemaänderung.

## [0.11.1] – 2026-07-30

### Fixed

- **Freigaben waren vollständig gesperrt.** Beim Umstieg auf Rollen (0.10.0)
  blieben an drei Stellen die alten Gruppenrechte-Namen stehen
  (`can_edit_time_entries`, `can_approve_manual_entries`,
  `can_manage_vacations`). Ein unbekannter Berechtigungsschlüssel ergibt den
  Geltungsbereich „keiner“ – dadurch wurde **jede** Freigabe von Buchungen und
  Urlaubsanträgen abgewiesen, mit der Meldung „gehört nicht zu deinem Team“,
  selbst für den Superadministrator. Betroffen waren das Freigeben und
  Ablehnen manueller Buchungen, das Genehmigen und Ablehnen von Urlaub sowie
  das Bearbeiten fremder Buchungen über die Zeitübersicht.
  `_user_in_permission_scope` wirft jetzt bei einem unbekannten Schlüssel einen
  Fehler, statt stillschweigend alles zu verbieten.

### Added

- **Halbe Urlaubstage.** Erster und letzter Tag eines Antrags lassen sich
  einzeln halbieren; bei einem eintägigen Antrag genügt ein Häkchen. Halbe
  Tage zählen mit 0,5 Urlaubstagen und der halben Tagessollzeit – in der
  Urlaubsübersicht, der Tagesgutschrift, den Auswertungen und beim
  Überstundenurlaub. In den Listen erscheinen sie als „½“. Bestandsanträge
  bleiben unverändert ganze Tage.
- **Lizenz beantragen oder erweitern.** Auf der Lizenzseite führt ein Knopf
  zum Lizenzserver und nimmt Deployment-ID, Version, aktuelle Lizenz und die
  Zahl der belegten Benutzerplätze mit. Weder Aktivierungsschlüssel noch
  personenbezogene Daten werden übertragen. Sind alle Benutzerplätze belegt,
  weist der Text ausdrücklich darauf hin.
- Der Lizenzserver des Herausgebers (`https://lic.dh-cloud.de`) ist im
  Aktivierungsformular vorbelegt.

### Datenbank

Migration 15 ergänzt `vacation_requests.half_day_start` und `.half_day_end`
(beide `BOOLEAN DEFAULT 0`). Datenerhaltend: Bestandsanträge zählen weiterhin
als ganze Tage.

## [0.11.0] – 2026-07-29

### Added – Lizenzierung gegen den Erfassung-Lizenzserver

Eine Installation lässt sich einmalig gegen den **Erfassung-Lizenzserver**
(eigenes Repository `joni123467/Erfassung_Lizenzserver`) aktivieren, prüft ihre
Lizenz anschließend **offline** und hält sich an die lizenzierte Benutzerzahl.

- **Neue Seite** Administration → System → **Lizenz**: Status, Lizenz-ID, Kunde,
  Edition, Merkmale, Benutzerbelegung, Ablaufdatum, Deployment-ID. Dazu
  Aktivieren, „Erneut prüfen" und „Lizenz entfernen" (gibt den
  Aktivierungsplatz beim Server wieder frei).
- **Deployment-ID**: Beim ersten Start wird eine dauerhafte Zufallskennung
  (`erfassung-<32 Hexzeichen>`) in `config/license.json` erzeugt – **keine**
  Hardwaremerkmale, **keine** personenbezogenen Daten, kein Hostname. Sie
  überlebt einen Serverumzug, solange das `config`-Volume mitwandert.
- **Offline-Prüfung** bei jedem Start und jeder Statusabfrage: Schemaversion,
  Ed25519-Signatur über die kanonische JSON-Form ohne das Feld `signature`,
  Produktkennung, Deployment-ID und Ablaufdatum. Der Lizenzserver muss dafür
  nicht erreichbar sein.
- **Prüfschlüssel wird automatisch übernommen.** Bei der ersten Aktivierung
  holt die Installation den öffentlichen Schlüssel des Lizenzservers
  (`GET /v1/instance/public-key`) und merkt ihn sich dauerhaft. Danach ist er
  je `key_id` unveränderlich: Ein gewechselter Schlüssel führt zum Abbruch,
  ohne etwas zu überschreiben; eine Rotation über eine neue `key_id` wird
  ergänzt. Ein in `app/licensing_keys.py` eingebetteter Schlüssel hat Vorrang.
  Auf der Lizenzseite steht ein Fingerprint (`SHA256:…`) zum Abgleich mit dem
  Lizenzserver.
- **Durchsetzung**: `max_users` (`0` = unbegrenzt) und Ablaufdatum. Über die
  Oberfläche mit Klartextmeldung, über `POST /api/users` mit **HTTP 402**.
  Bestehende Benutzer werden nie gesperrt oder gelöscht.
- **Neu**: `GET /api/license` liefert den Status als JSON – ohne
  Aktivierungsschlüssel und ohne Signatur, nur mit `System.Settings`.
- **Neuer Protokollkanal** `license.log` samt Schalter „Lizenz-Logging" in den
  Systemeinstellungen. Aktivierungsschlüssel erscheinen dort ausschließlich
  maskiert (`••••-1234`).
- **Hinweisbalken** auf jeder Administrationsseite, solange die Lizenz fehlt,
  ungültig ist oder binnen 30 Tagen abläuft.
- `cryptography` ist jetzt eine ausdrückliche Abhängigkeit (bisher nur transitiv
  über `smbprotocol`).

**Bewusst nicht durchgesetzt:** Eine Installation **ohne** Lizenz läuft
unverändert weiter und zeigt nur einen Hinweis – ein Update darf einen
laufenden Betrieb nicht stilllegen. Ist die Lizenz abgelaufen oder ungültig,
entfällt nur das Anlegen neuer Benutzer; Stempeln, Auswertungen, Urlaub und
Sicherungen bleiben nutzbar.

**Grenze des Kopierschutzes:** Die einmalige Aktivierung verhindert weitere
reguläre Aktivierungen, aber **nicht** das vollständige Klonen einer bereits
aktivierten Installation. Das System ist damit kein vollständiger Kopierschutz.
Weitere Restrisiken stehen in `docs/RELEASE_NOTES_0.11.0.md`.

**Datenbank:** keine Schemaänderung, keine Migration erforderlich.

## [0.10.1] – 2026-07-29

### Fixed

- **Mobil ließ sich kein Auftrag mehr starten, sobald die Arbeitszeit lief.**
  Die Schaltfläche „Auftrag starten“ stand in der mobilen App ausschließlich im
  Start-Block. Bis 0.9.21 blieb dieser Block trotz `hidden` sichtbar, weil
  `display: grid` das Attribut überstimmte – der Knopf war dadurch zufällig auch
  bei laufender Arbeitszeit erreichbar. Mit der korrekten Ausblendung in 0.9.22
  verschwand er, und es ließ sich nur noch Arbeitszeit stempeln.
  „Auftrag starten“ steht jetzt **in beiden Zuständen** zur Verfügung (mobile
  App und Offline-Shell) – wie auf dem Desktop, wo der Knopf schon immer in
  beiden Zuständen vorhanden war. Fachlich unverändert: Bei laufender
  Arbeitszeit wird diese beendet und der Auftrag läuft weiter.

## [0.10.0] – 2026-07-29

### Changed – Rollenbasierte Rechteverwaltung (RBAC)

Berechtigungen kommen ab sofort **ausschließlich über Rollen**. Gruppen sind
reine Organisationseinheiten. Ein Benutzer kann in **mehreren** Gruppen und
**mehreren** Rollen sein.

- **Neues Datenmodell**: `roles`, `role_permissions`, `user_roles`,
  `user_groups`. Die Rechte-Spalten und `is_admin` entfallen aus `groups`.
- **Berechtigungen im Code** (`app/permissions.py`) mit Key, Kategorie,
  Anzeigename und Beschreibung – neue Rechte brauchen keine Migration mehr:
  `Own.Time.Edit`, `Own.Comment.Edit`, `Own.Vacation.Request`, `Company.Create`,
  `Company.Manage`, `Time.Approve`, `Time.Edit`, `Time.View`, `Vacation.Manage`,
  `User.View`, `User.Create`, `User.Edit`, `User.Delete`, `System.Groups`,
  `System.Terminals`, `System.Roles`, `System.Settings`, `System.Backup`.
- **Geltungsbereiche** je Recht: *Nicht erlaubt / Nur eigene / Eigene Gruppen /
  Alle Benutzer*. „Eigene Gruppen“ prüft jetzt die **Schnittmenge der Gruppen**
  statt einer einzelnen Gruppen-ID; bei mehreren Rollen gilt der weiteste
  Bereich.
- **Zentrale Prüfung** in `app/permission_service.py` (`has`, `scope`,
  `allowed_user_ids`, `can_access_user`, `area_permissions`). Keine Route greift
  mehr auf Gruppenrechte zu.
- **Systemrollen**: **Superadministrator** (alles) und **Administrator** (alles
  außer `System.Roles`, `System.Settings`, `System.Backup`). Beide sind nicht
  änderbar und werden bei Updates automatisch um neue Rechte ergänzt.
- **Schutz vor Rechteausweitung**: Rollen zuweisen erfordert `System.Roles`;
  Systemrollen darf nur ein Superadministrator vergeben, und die
  Superadministrator-Vorbehalte lassen sich nicht über eine selbst angelegte
  Rolle weitergeben. Gruppen sind nur im eigenen Geltungsbereich zuweisbar.
- **Oberfläche**: neue Bereiche **Rollen** (Berechtigungsmatrix mit
  Bereichsauswahl) und **Berechtigungen** (nur lesend); der Gruppeneditor führt
  nur noch Name, Beschreibung und Mitglieder; das Benutzerformular bietet
  Mehrfachauswahl für Gruppen und Rollen.
- **API**: neu `/api/roles` (Liste, Anlegen, Ändern). `/api/groups` bleibt
  bestehen und ignoriert mitgesendete Rechte-Felder; `/api/users` akzeptiert
  weiterhin `group_id` und zusätzlich `group_ids` / `role_ids`.
- **CLI**: neuer Befehl `list-roles`, `create-user --role`, und `list-users`
  zeigt Gruppen und Rollen.
- **Systembereich getrennt**: Feiertage/Terminals hängen an `System.Terminals`,
  Sicherung/Wiederherstellung an `System.Backup`, der restliche Systembereich an
  `System.Settings`.

### Migration

Migration 14 läuft beim ersten Start automatisch und ist datenerhaltend:

1. Bisherige Gruppenzugehörigkeit → `user_groups`.
2. Mitglieder von Administratorgruppen → Systemrolle **Superadministrator**
   (sie durften bisher alles und verlieren dadurch nichts).
3. Jede Gruppe mit Rechten → Rolle **„Migration – &lt;Gruppenname&gt;“** mit
   identischem Rechteumfang; Mitglieder erhalten sie zugewiesen.
4. Rechte-Spalten der Gruppen werden geleert.

Migrationen laufen jetzt **vor** dem Seeding der Stammdaten, damit das Rollen-
modell steht, bevor Systemrollen ergänzt werden. Details:
[`docs/RBAC_MIGRATIONSPLAN.md`](docs/RBAC_MIGRATIONSPLAN.md).

### Notes

- Benutzer **ohne Rolle** behalten die `Own.*`-Rechte (Bestandsverhalten); neue
  Rollen bringen sie voreingestellt mit.
- Die Regressionssuiten zu den alten Gruppenberechtigungen (0.9.11/0.9.12)
  wurden durch `tests/test_rbac.py` ersetzt; die Suiten 0.9.19/0.9.20 nutzen
  jetzt Rollen.

## [0.9.22] – 2026-07-29

### Changed – Einsatzort als Umschalter statt Checkbox

- Der Einsatzort aus 0.9.21 wurde als kleine Checkbox angeboten – auf dem
  Handy zu klein zum Treffen. Jetzt ist es eine **Schaltfläche, die Farbe und
  Beschriftung wechselt**: grau **„Einsatzort · Vor Ort"** ⇄ blau
  **„Einsatzort · Remote"**. In der mobilen App füllt sie die volle Breite und
  hat dieselbe Höhe wie die Stempel-Schaltflächen.
- Der Umschalter wird an allen Stellen verwendet: mobile App, Offline-Shell,
  Dashboard (Schnell stempeln, Auftrags-Dialog, manuelle Buchung) und die
  Buchungsbearbeitung in der Administration.
- **Technisch unverändert**: Das Formularfeld bleibt eine Checkbox
  (`is_remote`), die Umschaltung passiert per CSS. Damit funktionieren
  Offline-Warteschlange, Synchronisation und das Absenden ohne JavaScript wie
  bisher – auch in der statischen Offline-Shell.
- **Barrierefrei**: Die Schaltfläche ist per Tastatur bedienbar (Leertaste),
  hat einen Fokusrahmen und einen eigenen Screenreader-Namen; die farbige
  Darstellung ist `aria-hidden`.
- Neu: gemeinsames Makro `templates/_components.html` (`location_toggle`),
  damit alle Stellen identisch aussehen.

### Fixed

- **Mobile App zeigte Start- und Aktiv-Bereich gleichzeitig**: Ausgeblendete
  Bereiche (`hidden`) blieben sichtbar, weil die Komponentenregeln
  (`display: flex` / `display: grid`) die Browser-Standardregel für das
  `hidden`-Attribut überstimmten. Bei laufender Arbeitszeit standen dadurch
  „Beginne deine Arbeitszeit …" samt (deaktiviertem) Start-Knopf neben den
  aktiven Aktionen. Jetzt gilt `[hidden] { display: none !important; }`
  global.

## [0.9.21] – 2026-07-28

### Added – Einsatzort einer Buchung (Remote / vor Ort)

- **Optionales Feld je Buchung**: Eine Stempelung kann jetzt als **Remote**
  (z. B. Telefon) gekennzeichnet werden; ohne Haken gilt sie als **vor Ort**.
- **Freischaltung je Benutzer** – wie das Zeitkonto: In der Benutzerverwaltung
  unter „Zeitkonto & Buchungen" die Option **„Einsatzort erfassen (Remote /
  vor Ort)"** aktivieren. Ohne Freischaltung erscheint das Feld nirgends, und
  ein trotzdem mitgesendeter Wert wird serverseitig ignoriert.
- **Überall dort, wo gestempelt wird**: Arbeitszeit starten und Auftrag starten
  (Web und mobil), manuelle Buchungen, die nachträgliche Kommentar-Bearbeitung
  der letzten Buchung (mobil) sowie die Buchungsbearbeitung in der
  Administration.
- **Offline-fähig**: Der Haken wandert mit der Stempelung in die
  Offline-Warteschlange der PWA und wird beim Synchronisieren übertragen; die
  laufende Buchung zeigt das Kennzeichen auch ohne Netz an.
- **Teilen bleibt konsistent**: Wird eine Buchung durch einen Nachtrag geteilt
  oder beim Überschreiben zerlegt, übernehmen alle Abschnitte den Einsatzort
  der Ursprungsbuchung.
- **Anzeige**: Buchungslisten, Zeitübersichten und Freigaben zeigen ein
  Kennzeichen „Remote" neben der Firma.
- **Exporte**: PDF und Excel enthalten eine zusätzliche Spalte **„Ort"** –
  aber nur, wenn im Zeitraum mindestens eine Buchung remote erfasst wurde.
  Wer den Einsatzort nicht nutzt, bekommt unveränderte Exporte.

### Changed

- Die Buchungstabelle der persönlichen Arbeitszeitübersicht und die
  Stempelzeiten des Administrations-Exports nutzen jetzt dieselbe Funktion
  (`_entry_table`) – dadurch bleibt die neue Spalte in beiden gleich.

### Datenbank

Migration 13 (idempotent, datenerhaltend):

| Tabelle | Spalte | Default |
|---------|--------|---------|
| `users` | `remote_flag_enabled` | `0` |
| `time_entries` | `is_remote` | `0` |

Der Default erhält das Bestandsverhalten: Alle vorhandenen Buchungen gelten als
vor Ort, und das Feld erscheint erst nach bewusster Freischaltung.

## [0.9.20] – 2026-07-27

### Added – Stempelzeiten im PDF der Benutzerauswertung

- **Optionale Einzelbuchungen im Administrations-Export**: Die
  Benutzerauswertung (`/admin/reports/users`) lieferte im PDF bisher nur die
  Summen je Benutzer. Neben dem PDF-Export gibt es jetzt die Option
  **„Stempelzeiten"**; ist sie gesetzt, enthält das PDF zusätzlich je Benutzer
  eine Tabelle mit allen freigegebenen Einzelbuchungen des Zeitraums –
  Datum, Firma, Start, Ende, Arbeitszeit, Status und Kommentar samt Summenzeile.
  Damit steht Administratoren dieselbe Detailtiefe zur Verfügung, die Benutzer
  aus ihrer eigenen Arbeitszeitübersicht (`/records`) kennen.
- **Gleiches Layout wie die persönliche Übersicht**: Die Tabelle nutzt das
  gemeinsame Stilsystem (`_entry_table`), sodass persönliche Übersicht und
  Administrations-Export identisch aussehen.
- **Dateiname erkennbar**: Der Export heißt mit Stempelzeiten
  `benutzer_zeit_<von>_<bis>_stempelzeiten.pdf`.

### Notes

- Der Geltungsbereich von „Zeitübersichten einsehen" gilt unverändert: Ein
  Abteilungsadministrator erhält ausschließlich Buchungen des eigenen Teams.
- Der Excel-Export der Benutzerauswertung bleibt unverändert die reine
  Summenauswertung.
- Keine Datenbankänderung.

## [0.9.19] – 2026-07-24

### Added – Abteilungsadministration (Gruppenadmins)

- **Administrationsbereich für Abteilungsadministratoren**: Der
  Administration-Link und der Bereich `/admin` waren an volle Adminrechte
  (`is_admin`) gebunden – Gruppen mit Team-Rechten kamen gar nicht hinein.
  Jetzt genügt **eine beliebige Administrationsberechtigung**; `/admin` landet
  automatisch auf der ersten erlaubten Seite (Benutzer → Freigaben →
  Zeitübersichten → …). Die Navigation zeigt weiterhin nur die freigegebenen
  Bereiche.
- **„Benutzer verwalten“ mit Geltungsbereich**: Das Recht ist jetzt – wie die
  Team-Rechte aus 0.9.12 – dreistufig (Nicht erlaubt / Eigenes Team / Alle
  Benutzer). Bei „Eigenes Team“ sieht und bearbeitet ein Abteilungsadmin nur
  Benutzer der eigenen Gruppe; die Benutzerliste, die Detailseite sowie
  Anlegen/Ändern/Löschen sind entsprechend begrenzt.
- **Schutz vor Rechteausweitung**: Im Bereich „Eigenes Team“ lässt sich nur die
  eigene Gruppe zuweisen – insbesondere keine Administratorgruppe. Das
  Gruppen-Auswahlfeld bietet nur zulässige Gruppen an, und der Server lehnt
  abweichende Zuweisungen ab.
- **Benutzer-Detailseite**: verlangte bisher volle Adminrechte und ist jetzt
  für Berechtigte mit „Benutzer verwalten“ (im Geltungsbereich) erreichbar.

### Added – Buchungen überschreiben mit Bestätigung

- Führt das Bearbeiten einer Buchung zu einer **neuen** Überschneidung, wird
  die Änderung nicht mehr abgelehnt. Stattdessen erscheint eine
  **Bestätigungsseite**, die auflistet, welche Buchungen betroffen sind
  (Datum, Zeitraum, Mitarbeiter, Firma) und **was mit ihnen passiert**:
  - vollständig überdeckt → wird gelöscht,
  - teilweise überlappt → wird gekürzt (mit Angabe der neuen Zeiten),
  - neue Zeiten liegen mittendrin → wird geteilt (beide Abschnitte werden
    genannt).
- Erst „Überschreiben und speichern“ führt die Änderung aus; „Zurück zum
  Bearbeiten“ und „Abbrechen“ lassen alles unverändert.
- **Laufende Buchungen werden nie gelöscht**, sondern ab dem Ende der neuen
  Buchung fortgeführt – eine laufende Zeiterfassung bricht durch eine
  Korrektur nicht ab.

### Datenbank

- Neue Spalte `groups.can_manage_users_scope` (VARCHAR(10), Default `'all'`).
  Migration 12 bzw. `ensure_schema()` ergänzen sie idempotent; Bestandsgruppen
  behalten mit `'all'` ihr bisheriges Verhalten.

## [0.9.18] – 2026-07-24

### Fixed – Falsche Überschneidung zwischen direkt angrenzenden Buchungen (Sekunden)

- **Ursache gefunden**: Direkt aneinandergrenzende Buchungen teilen sich bei
  Terminal-Importen denselben Stempel-Zeitpunkt **inklusive Sekunden** (z. B.
  Ende der einen `14:18:45` = Beginn der nächsten `14:18:45`). Das
  Bearbeiten-Formular arbeitet nur mit Minuten (`HH:MM`): Beim Speichern wurde
  die Startzeit auf `14:18:00` abgerundet und „überlappte" dadurch die
  Vorbuchung um bis zu 59 Sekunden. Folge: „Zeiten überschneiden sich mit
  einer bestehenden Buchung" beim reinen Verkürzen einer Buchung, obwohl gar
  kein echter Konflikt vorliegt.
- **Behebung**: Die Überschneidungsprüfung (Anlegen, Bearbeiten, Nachtrag/
  Teilen) vergleicht jetzt **minutengenau**. Sekunden-Grenzfälle direkt
  angrenzender Buchungen gelten damit korrekt als *nicht* überlappend; echte
  Überschneidungen von mindestens einer Minute werden weiterhin erkannt und
  abgelehnt.

### Datenbank

- Keine Schemaänderungen; keine Migration erforderlich.

## [0.9.17] – 2026-07-24

### Changed – Aussagekräftige Überschneidungs-Meldung beim Bearbeiten

- Wird das Bearbeiten einer Buchung durch eine **tatsächlich neu entstehende**
  Überschneidung blockiert, nennt die Fehlermeldung jetzt die **konkret
  kollidierende Buchung** (Datum + Start–Ende), z. B. „Zeiten überschneiden
  sich mit einer bestehenden Buchung: 22.07.2026 16:00–19:20". So ist sofort
  erkennbar, welche Buchung im Weg ist.
- Der eigentliche Fix aus 0.9.16 bleibt unverändert: Eine bereits mit dem
  ursprünglichen Zeitraum bestehende Überschneidung (z. B. eine noch laufende
  Buchung) blockiert eine Korrektur weiterhin **nicht**.

> Hinweis: Sollte die Meldung „Zeiten überschneiden sich …" beim reinen
> Verkürzen einer Buchung weiterhin **ohne** Detailangabe erscheinen, läuft die
> Instanz noch nicht auf 0.9.16/0.9.17 – bitte das aktuelle Image ausrollen
> (die laufende Version steht im Footer bzw. unter Administration → System).

### Datenbank

- Keine Schemaänderungen; keine Migration erforderlich.

## [0.9.16] – 2026-07-23

### Fixed – Bearbeiten scheiterte an bereits bestehenden Überschneidungen

- **Korrektur einer Buchung wurde durch fremde Überlappung blockiert**: Eine
  Buchung (z. B. automatisch „14:18–19:20") ließ sich nicht auf „16:00"
  verkürzen – es kam „Zeiten überschneiden sich mit einer bestehenden
  Buchung", obwohl der Zeitraum kleiner wird. Ursache: Die
  Überschneidungsprüfung beim Bearbeiten zählte auch Überlappungen mit, die
  bereits mit dem *bisherigen* Zeitraum bestanden – etwa eine noch laufende
  (offene) Buchung, deren Fenster bis „jetzt" reicht, oder eine bereits
  vorhandene Doppelbuchung. Dadurch ließ sich eine fehlerhafte Buchung nicht
  einmal verkürzen.
- **Neu**: Beim Bearbeiten werden nur noch **neu entstehende** Überschneidungen
  abgelehnt. Eine Überschneidung, die schon mit dem ursprünglichen Zeitraum
  bestand, blockiert die Korrektur nicht mehr. Das Verschieben auf einen bisher
  freien, aber belegten Zeitraum wird weiterhin abgelehnt. Das Anlegen neuer
  Buchungen (inkl. Nachträge/Teilen) bleibt unverändert streng geprüft.

### Datenbank

- Keine Schemaänderungen; keine Migration erforderlich.

## [0.9.15] – 2026-07-16

### Added – Nachtrag zwischen bestehenden Buchungen & Bearbeiten aus den Berichten

- **Nachtrag in eine abgeschlossene Buchung**: Fällt eine manuelle Buchung
  (z. B. ein Telefonat) in eine bereits abgeschlossene Buchung, wird diese –
  wie bisher schon die laufende Buchung – automatisch geteilt: Abschnitt
  davor und danach behalten Firma, Kommentar, Status und Quelle der
  Bestandsbuchung, dazwischen wird der Nachtrag eingefügt. Randfälle
  (Beginn = Start, Ende = Ende, exakte Deckung) werden korrekt behandelt;
  die erfassten Pausenminuten bleiben beim führenden Abschnitt. So lassen
  sich neue Stempelungen zwischen bestehenden manuellen Buchungen einfügen,
  ohne dass Zeiten doppelt zählen.
- **Zeitbuchungen aus den Berichten bearbeiten**: Die Einzelbuchungs-Tabelle
  unter Administration → Zeiterfassung → Zeitübersichten hat für Berechtigte
  (Administratoren bzw. Gruppen mit „Zeitbuchungen bearbeiten") eine Spalte
  „Aktionen" mit Bearbeiten-Link zum bestehenden Bearbeitungsformular.
  Bisher war das Formular nur aus den Freigaben (offene manuelle Buchungen)
  erreichbar; jetzt lassen sich auch freigegebene/automatische Buchungen
  direkt aus der Übersicht korrigieren. Der Geltungsbereich (eigenes Team /
  alle Benutzer) aus 0.9.12 gilt unverändert.

### Datenbank

- Keine Schemaänderungen; keine Migration erforderlich.

## [0.9.14] – 2026-07-16

### Added – Nachtrag bei laufender Arbeitszeit (laufende Buchung wird geteilt)

- **Manuelle Buchung innerhalb der laufenden Arbeitszeit**: Ein Nachtrag
  (z. B. ein Telefonat), der in die aktuell laufende Buchung fällt, wurde
  bisher pauschal als Überschneidung abgelehnt. Jetzt wird die laufende
  Buchung geteilt – exakt das Ergebnis, das beim Live-Stempeln entstanden
  wäre: Der bereits gearbeitete Teil wird bis zum Beginn des Nachtrags
  abgeschlossen (bisherige Pausenminuten bleiben dort), der Nachtrag wird
  eingefügt (wartet wie gehabt auf Freigabe), und die Arbeitszeit läuft ab
  dem Ende des Nachtrags mit Firma/Kommentar unverändert weiter. Es
  entstehen keine doppelt gezählten Zeiten.
- **Randfälle**: Beginnt der Nachtrag exakt mit der laufenden Buchung,
  entfällt der erste Teil (Pausenminuten bleiben an der weiterlaufenden
  Buchung). Bei laufender Pause kommt die klare Meldung, zuerst die Pause
  zu beenden. Nur teilweise Überlappungen (Beginn vor der laufenden
  Buchung, Ende in der Zukunft) und Kollisionen mit anderen Buchungen
  werden weiterhin abgelehnt.
- Erfolgsmeldung weist auf die Teilung hin („… die laufende Arbeitszeit
  wurde entsprechend geteilt und läuft weiter").

### Datenbank

- Keine Schemaänderungen; keine Migration erforderlich.

## [0.9.13] – 2026-07-15

### Fixed – PWA-Updates erreichen installierte Geräte zuverlässig (iOS)

- **Version in `/sw.js` eingebrannt**: Die Route stempelt die App-Version in
  den Skriptinhalt (`self.__ERFASSUNG_VERSION`). Bisher steckte die Version
  nur in der Registrierungs-URL (`?v=`) – eine installierte PWA lädt `/mobile`
  aber aus dem Service-Worker-Cache, die alte Seite registrierte wieder die
  alte URL mit unverändertem Skript, und der Browser sah **nie** ein Update.
  Die PWA blieb dauerhaft auf dem alten Stand (Synchronisation brach, bis die
  App neu installiert wurde). Mit eingebrannter Version ändert jedes Release
  die Skript-Bytes und der Update-Check des Browsers greift immer.
- **Aktive Update-Prüfung**: Registrierung mit `updateViaCache: 'none'`;
  `registration.update()` läuft bei jedem Start, beim Zurückholen der App in
  den Vordergrund (App-Resume, wichtig für iOS) und sobald ein Sync eine
  geänderte Server-Version meldet (`/mobile/sync-data` → `version`).
- **Einmaliger Auto-Reload nach Update**: Übernimmt ein neuer Worker die
  Kontrolle (`controllerchange`), lädt sich die Seite einmalig neu, damit
  sofort die frischen Assets aktiv sind. Kein Reload bei Erstinstallation,
  kein Reload-Loop; die Offline-Queue bleibt erhalten (IndexedDB).
- **Kein staler HTTP-Cache bei der Installation**: Der Worker lädt seine
  Assets beim `install` mit `cache: 'no-cache'`, damit die neue Cache-Version
  nicht mit alten Dateien gefüllt wird.
- **Konstante Registrierungs-URL (`/sw.js` ohne `?v=`)**: Wird `app.js` vom
  Service Worker aus dem Cache bedient, verliert `import.meta.url` seinen
  `?v=`-Parameter – die Registrierung flatterte dadurch zwischen
  `/sw.js?v=<version>` und `/sw.js?v=dev` und erzeugte Worker mit
  Cache-Namen `erfassung-mobile-vdev`, wodurch die versionsbasierte
  Cache-Rotation auf installierten Geräten vollständig ausgehebelt war.
  Die Version kommt jetzt ausschließlich aus dem eingebrannten Skriptinhalt.

### Added – Synchronisation bei App-Resume

- Beim Wechsel der (iOS-)PWA in den Vordergrund wird automatisch
  synchronisiert (`visibilitychange`) – zuvor nur beim Seitenstart und beim
  `online`-Ereignis, wodurch lange im Hintergrund geparkte Apps nicht mehr
  synchronisierten.

### Dokumentation

- README: neuer Abschnitt „PWA am Desktop/PC verwenden" (Nutzung im
  Desktop-Browser und Installation über Chrome/Edge) sowie aktualisierte
  Beschreibung des Update-Mechanismus.

### Datenbank

- Keine Schemaänderungen; keine Migration erforderlich.

## [0.9.12] – 2026-07-08

### Added – Geltungsbereich für Team-Rechte (eigenes Team oder alle Benutzer)

- **Dreistufige Vergabe**: Die Rechte der Kategorie „Team & Freigaben"
  (Manuelle Buchungen freigeben, Urlaubsanträge verwalten, Zeitübersichten
  einsehen, Zeitbuchungen bearbeiten) werden im Gruppenformular jetzt als
  Bereichsauswahl vergeben: **Nicht erlaubt**, **Eigenes Team (Gruppe)**
  oder **Alle Benutzer**.
- **Durchsetzung überall**: Bei „Eigenes Team" sehen Berechtigte in den
  Freigaben nur Buchungen/Urlaubsanträge von Benutzern der eigenen Gruppe,
  Berichte/Exporte (Team- und Benutzerauswertung, PDF/Excel) enthalten nur
  Gruppenmitglieder, und die Bearbeitung fremder Buchungen (Seite, Update,
  Löschen, Freigabe-POSTs) wird serverseitig mit klarer Meldung abgelehnt –
  auch das Umbuchen einer Buchung auf einen Benutzer außerhalb des Teams.
- **Übersicht**: Die Gruppenliste kennzeichnet Team-beschränkte Rechte im
  Badge-Tooltip mit „(eigenes Team)".
- Administratorrechte wirken unverändert immer auf alle Benutzer.

### Datenbank

- Neue Spalten in `groups`: `can_approve_manual_entries_scope`,
  `can_manage_vacations_scope`, `can_view_time_reports_scope`,
  `can_edit_time_entries_scope` (VARCHAR(10), Default `'all'`).
  Migration 11 bzw. `ensure_schema()` ergänzen sie idempotent; Bestands-
  gruppen behalten mit `'all'` exakt ihr bisheriges Verhalten.

## [0.9.11] – 2026-07-08

### Changed – Gruppenberechtigungen überarbeitet

- **Kategorisierte Berechtigungsmatrix**: Das Gruppenformular zeigt alle
  Berechtigungen – angelehnt an bekannte Rollen-/Rechteverwaltungen – nach
  Kategorien gegliedert (Eigene Zeiterfassung, Aufträge & Firmen, Team &
  Freigaben, Verwaltung) mit Titel und Beschreibung je Recht.
  Administratorrechte umfassen automatisch alle Rechte; die Einzelrechte
  werden dann gesperrt (aber sichtbar) dargestellt.
- **Zentrales Berechtigungs-Register** (`app/permissions.py`): Formular,
  Formular-Parsing und Gruppenübersicht speisen sich aus einer Quelle –
  neue Rechte erfordern keine UI-Änderung mehr.
- **Gruppenübersicht**: zeigt vergebene Rechte kompakt als Badges je
  Kategorie (z. B. „Team & Freigaben: 2/4", Details per Tooltip).

### Added – Neue Berechtigungen

- **Eigene Kommentare nachträglich bearbeiten** (`can_edit_own_notes`,
  Standard: erlaubt): steuert die Kommentar-Nachbearbeitung nach dem
  Beenden (mobil und Web). Ohne das Recht verschwinden Dialog und Button,
  und `/punch update_notes` wird serverseitig abgelehnt (auch für
  Offline-Aktionen).
- **Manuelle Zeitbuchungen nachtragen** (`can_manual_time_entries`,
  Standard: erlaubt): steuert das Formular „Manuelle Buchung" und
  `POST /time`.
- **Urlaubsanträge stellen** (`can_request_vacations`, Standard: erlaubt):
  steuert die Antragsformulare (Web und mobil) und `POST /vacations`.
- **Firmen verwalten** (`can_manage_companies`, Standard: nur Admin):
  Zugriff auf Administration → Firmen ist jetzt delegierbar und nicht mehr
  ausschließlich Administratoren vorbehalten.
- Die mobile App/Offline-Shell erhält die Rechte über `/mobile/sync-data`
  (`permissions`) und blendet nicht erlaubte Aktionen aus.

### Datenbank

- Neue Spalten in `groups`: `can_manage_companies` (Default 0, für
  Admin-Gruppen 1), `can_manual_time_entries`, `can_edit_own_notes`,
  `can_request_vacations` (jeweils Default 1 – Bestandsverhalten bleibt
  erhalten). Migration 10 (`schema_migrations`) bzw. `ensure_schema()`
  ergänzen die Spalten idempotent und datenerhaltend.

## [0.9.10] – 2026-07-07

### Fixed – Mobiles Stempeln nach Firmensuche

- **Suchvorschlag startet den Auftrag zuverlässig**: Wurde in der mobilen App
  eine Firma über das Suchfeld gefunden und der Vorschlag (Datalist)
  übernommen, blieb das Dropdown „Firma auswählen" leer und der Server lehnte
  die Buchung mit „Bitte eine Firma auswählen oder neu anlegen." ab. Die
  Firmensuche wählt jetzt – wie auf dem Desktop – bei exakter Übereinstimmung
  die Firma automatisch im Dropdown aus (zusätzlich auf das `change`-Ereignis
  der Vorschlagsübernahme reagierend).
- **Client-seitige Namensauflösung**: Vor dem Einreihen einer
  `start_company`-Aktion wird eine fehlende `company_id` aus dem Suchtext gegen
  die Firmenliste aufgelöst.
- **Server-Fallback über den Firmennamen**: `/punch` akzeptiert bei
  `start_company` jetzt zusätzlich `company_name` und löst die Firma über den
  Namen auf (exakt, dann ohne Beachtung der Groß-/Kleinschreibung), wenn keine
  `company_id` übermittelt wurde – das repariert auch bereits offline
  eingereihte Aktionen älterer Clients.
- **Offline-Vorschlagsliste**: Die Firmen-Datalist wird nun ebenfalls aus dem
  lokalen Cache befüllt (die Offline-Shell startete bisher mit leerer
  Vorschlagsliste).

### Added – Kommentar nach dem Beenden bearbeiten

- **Optionaler Kommentar-Dialog**: Nach „Auftrag beenden" bzw. „Arbeitszeit
  beenden" öffnet die mobile App einen optionalen Dialog, um den Kommentar der
  soeben beendeten Buchung anzupassen („Überspringen" möglich). Funktioniert
  offline über die bestehende Queue (`update_notes` wird in Reihenfolge nach
  der Beenden-Aktion synchronisiert).
- **„Kommentar der letzten Buchung bearbeiten"**: Neuer Button unter den
  Stempel-Aktionen (sichtbar, wenn am aktuellen Tag bereits eine Buchung
  beendet wurde), der denselben Dialog öffnet.
- **Neue `/punch`-Aktion `update_notes`**: Aktualisiert den Kommentar einer
  eigenen Buchung – bevorzugt über `entry_id`, sonst die zuletzt beendete
  Buchung des Benutzers. Idempotent über `client_action_id` wie alle
  Stempelaktionen.

### Datenbank

- Keine Schemaänderungen; keine Migration erforderlich.

## [0.9.9] – 2026-06-15

### Added – Docker-Erstinitialisierung der Datenbank (ENV)

- **`DB_*`-ENV-Variablen für Neuinstallationen**: Ist beim Start noch keine
  `config/database.json` vorhanden, wird die Datenbankkonfiguration aus
  `DB_TYPE`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSL`
  (und `DB_PATH` für SQLite) erzeugt, **persistiert**, getestet und migriert.
  Unterstützt: SQLite, MySQL, MariaDB, PostgreSQL.
- **ENV nur zur Erstinitialisierung**: Existiert bereits eine Konfiguration, wird
  sie verwendet und die ENV-Variablen werden ignoriert – vorhandene
  Konfigurationen werden **niemals** überschrieben.
- **Herkunft sichtbar**: Administration → System → Datenbank zeigt an, ob die
  Konfiguration über *Docker ENV Erstinitialisierung* oder das *Webinterface*
  erstellt wurde (`created_by`).

### Added – Datenbankunabhängige (logische) Backups & Cross-Database Restore

- **Logische Backups** (`app/data_transfer.py`): Backups enthalten die Daten als
  JSON je Tabelle (`data/database.json`) statt einer rohen Datenbankdatei oder
  eines vendor-spezifischen Dumps. Backups sind damit vollständig
  datenbankunabhängig.
- **Erweiterte Metadaten** in jedem Archiv: `app_version`,
  `backup_format_version`, `database_type`, `schema_version`, `created_at` sowie
  Datensatzanzahlen. Diese sind ausschließlich informativ (Analyse,
  Kompatibilität, Vorschau) und lösen niemals einen automatischen
  Datenbankwechsel aus.
- **Cross-Database Restore**: Ein Backup kann unabhängig vom ursprünglichen
  Datenbanktyp in die **aktuell konfigurierte** Datenbank wiederhergestellt
  werden (z. B. SQLite → PostgreSQL, MariaDB → PostgreSQL, PostgreSQL → SQLite).
  Ablauf: Backup analysieren → Daten extrahieren → ORM-Import in einer
  Transaktion → Migrationen → Integritätsprüfung.
- **Restore-Vorschau** (`/admin/system/restore/preview`): zeigt vor der
  Wiederherstellung Backup-Informationen (Version, Datum, Format, ursprünglicher
  Datenbanktyp, Datensatzanzahlen) und das aktuelle System samt Hinweis, dass die
  Datenbankkonfiguration unverändert bleibt.
- **Sicherheitsbackup vor jedem Restore** (`pre_restore_*.zip`) für Rollback.

### Changed

- **Restore-Engine logisch** überarbeitet (`app/restore_manager.py`): Restore
  importiert ausschließlich Daten über den ORM-/Repository-Layer und verändert
  **niemals** den aktiven Datenbanktyp, die Datenbankkonfiguration oder die
  ENV-/Docker-Einstellungen. Ältere Datei-Backups (vor 0.9.9) werden weiterhin
  typgleich wiederhergestellt (Abwärtskompatibilität).
- **Migration nach Restore**: Nach dem Import wird das Schema geprüft und auf den
  aktuellen Stand gebracht (Restore eines 0.8.x-Backups auf 0.9.9 inklusive).
- **README** um einen ausführlichen Abschnitt *Docker Deployment* mit
  Stack-Vorlagen für PostgreSQL (Referenz), MariaDB, MySQL und SQLite erweitert.
- Version auf **0.9.9** angehoben (Frontend, Backend, Footer, Loginseite,
  Systemstatus, API-Version, Release- und Buildinformationen).

### Database

- Keine Schemaänderung. Backups/Restore sind logisch und damit dialektunabhängig;
  beim Cross-Database Restore werden PostgreSQL-Sequenzen nach dem Import
  nachgezogen.

### Logging

- `database.log` um ENV-Initialisierung erweitert (erkannt, Konfiguration
  erstellt, Verbindung erfolgreich/fehlgeschlagen, Migration gestartet/
  erfolgreich/fehlgeschlagen).
- Restore-Protokoll um Cross-Database-Ereignisse erweitert (Backup analysiert/
  Metadaten gelesen, Quell-/Ziel-Datenbank erkannt, Cross-Database Restore
  gestartet/erfolgreich/fehlgeschlagen, Migration nach Restore). Passwörter,
  Tokens, API-Keys und Secrets werden niemals protokolliert.

### Migrationshinweise

- Upgradepfade `0.8.x → 0.9.9`, `0.9.0 → 0.9.9`, `0.9.5 → 0.9.9` und
  `0.9.8 → 0.9.9` werden unterstützt. Bestehende Installationen behalten ihre
  Datenbankkonfiguration; ENV-Variablen greifen ausschließlich bei
  Neuinstallationen ohne vorhandene `config/database.json`.

## [0.9.8] – 2026-06-14

### Added – Generische Terminalverwaltung (ersetzt TimeMoto)

- **Neuer Bereich Administration → Zeiterfassung → Terminals**
  (`/admin/terminals`): Zeiterfassungsterminals werden jetzt über eine
  generische Terminalverwaltung gepflegt – optisch und funktional analog zu den
  Backup-Jobs und der Benutzerverwaltung (Kartenlayout, Tabelle, Modal,
  Dark-Mode-kompatibel, responsive).
- **Tabellenansicht** mit Name, Typ, Status, letzter Verbindung, letzter
  Synchronisation sowie Aktionen (Bearbeiten, Synchronisieren, Aktivieren/
  Deaktivieren, Löschen). Über „Neues Terminal“ (oben rechts) öffnet sich ein
  kompaktes Modal analog zu „Neuer Backup-Job“.
- **Treiber-/Plugin-Architektur** (`app/integrations/terminals/`): Jeder
  Terminaltyp ist ein Treiber, der sich in einer Registry registriert. Die UI
  enthält **keine hartkodierte TimeMoto-Logik** mehr; weitere Typen (ZKTeco,
  Suprema, generische REST-/CSV-Terminals) lassen sich ohne Umbauten ergänzen.
- **Terminaltyp TimeMoto** als erster Treiber: Anlegen, Bearbeiten, Verbindung
  testen, Synchronisieren, Aktivieren/Deaktivieren. Felder: Name, Host/IP, Port,
  Benutzer, Passwort/API-Key, Zeitzone, Synchronisationsintervall, SSL und
  Aktiv-Status.
- **Statusanzeige je Terminal**: Online (erreichbar), Warnung (instabil),
  Offline (nicht erreichbar) und Fehler (Authentifizierung fehlgeschlagen).
- **Synchronisationsergebnis**: letzte Synchronisation, Anzahl importierter
  Buchungen und Anzahl Fehler – je Lauf in der Historie (`terminal_sync_history`).
- **Neuer Logkanal `terminal`** → `logs/terminal.log` (in Administration → Logs
  filter-/such-/downloadbar). Erfasst Terminal erstellt/geändert/gelöscht,
  Verbindungstest, Synchronisation gestartet/erfolgreich/fehlgeschlagen sowie
  Aktivierung/Deaktivierung. Über das neue Logging-Setting „Terminal-Logging“
  steuerbar.
- **Systemstatus erweitert**: Anzahl Terminals, Online-/Offline-Terminals,
  letzte Synchronisation und letzter Synchronisationsfehler.
- **REST-Endpunkt** `POST /api/terminals/{id}/sync` für automatisierte
  Synchronisation einzelner Terminals.

### Changed

- **TimeMoto-Konfigurationspunkt entfernt**: Der bisherige Menüpunkt
  „TimeMoto TM-616“ unter Einstellungen entfällt. Die alte URL
  `/admin/integrations/timemoto` leitet dauerhaft auf `/admin/terminals` um.
- **Navigationsgruppe „Zeitverwaltung“ → „Zeiterfassung“** umbenannt; der neue
  Punkt „Terminals“ liegt darunter.
- **Datenbank-Konfiguration korrigiert**: Beim Wechsel des Datenbanktyps werden
  die Eingabefelder jetzt korrekt aktualisiert. SQLite zeigt nur den
  Datenbankpfad; MySQL/MariaDB/PostgreSQL zeigen Host, Port, Datenbankname,
  Benutzer, Passwort und SSL. Der Standardport wird beim Wechsel automatisch
  gesetzt (MySQL/MariaDB 3306, PostgreSQL 5432) und der Platzhalter aktualisiert
  – ein selbst eingetragener Port bleibt jedoch erhalten, ebenso bereits
  gespeicherte Werte (z. B. der Host). Der Verbindungstest läuft stets gegen die
  aktuell eingestellte Konfiguration.
- Version auf **0.9.8** angehoben (Frontend, Backend, Footer, Loginseite,
  Systemstatus, API-Version, Release- und Buildinformationen).

### Database

- Neue Tabellen `terminals` und `terminal_sync_history` (Migration 9,
  automatisch, idempotent, ohne Datenverlust).
- **Automatische Übernahme** einer vorhandenen `config/timemoto.json` in die
  Terminalverwaltung beim Upgrade – bestehende TimeMoto-Installationen
  funktionieren ohne Neukonfiguration weiter.

### Migrationshinweise

- Upgradepfade `0.9.5 → 0.9.8`, `0.9.6 → 0.9.8` und `0.9.7 → 0.9.8` werden
  unterstützt. Die Migrationen laufen beim Start automatisch und sind idempotent.
  Eine vorhandene TimeMoto-Konfiguration wird einmalig als Terminal angelegt.

## [0.9.7] – 2026-06-14

### Added – Datenbankverwaltung & -migration über die Oberfläche

- **Neuer Bereich Administration → System → Datenbank** (`/admin/system/database`):
  Das aktive Datenbanksystem lässt sich jetzt direkt über die Weboberfläche
  verwalten. Unterstützt werden **SQLite, MySQL, MariaDB und PostgreSQL**.
  MariaDB und PostgreSQL sind als empfohlene Produktivdatenbanken
  gekennzeichnet (⭐ Empfohlen); SQLite bleibt für Einzelplatz-, Test- und
  Entwicklungsumgebungen verfügbar.
- **Datenbankauswahl & -konfiguration**: Dropdown „Aktive Datenbank“ mit
  Empfehlungskarten (Einsatzzwecke, Hinweise) sowie ein kompaktes Modal
  („Datenbank konfigurieren“). SQLite zeigt den Datenbankpfad, die Server-
  backends Host, Port, Datenbankname, Benutzer, Passwort, SSL und Verbindungs-
  Timeout. Ein Info-Symbol (ⓘ) zeigt empfohlene und unterstützte Versionen.
  Konfiguration wird persistent als `config/database.json` im config-Volume
  gespeichert und hat Vorrang vor `DATABASE_URL`.
- **Verlustfreie Datenbankmigration** (`app/db_migrator.py`): Wechsel zwischen
  allen vier Systemen ohne Datenverlust. Ablauf: Zielverbindung prüfen →
  automatisches Sicherheitsbackup (`pre_db_migration_*.zip`) → Zielschema
  erzeugen → Daten exportieren/importieren → Integritätsprüfung →
  Anwendung umstellen → `post_db_migration_*.zip` als sofortiger
  Wiederherstellungspunkt. Übernommen werden Benutzer, Rollen, Arbeitszeiten,
  Stempelungen, Urlaub, Feiertage, Logs, Backup-/Restore-Historie,
  Offline-Synchronisationsdaten und alle weiteren Tabellen. Einstellungen liegen
  im config-Volume und bleiben unberührt.
- **Integritätsprüfung** nach jeder Migration: Tabellenanzahl, Datensatzanzahl
  je Tabelle, Schlüsselentitäten (Benutzer, Rollen, Historien). Bei Abweichung
  schlägt die Migration fehl.
- **Rollback ohne Downtime**: Da nur in die Zieldatenbank geschrieben wird,
  bleibt die bisherige Datenbank bei jedem Fehler unverändert aktiv. Eine nicht
  leere Zieldatenbank bricht die Migration ab (Datenverlust-Schutz).
- **Asynchroner Migrations-Worker** (`app/db_migration_jobs.py`) analog zum
  Restore: Der Request validiert und queued nur, der Hintergrund-Thread führt
  die Migration aus; Fortschritt über `data/db_migration_status.json` und
  `GET /api/database/migration/status` mit eigener Fortschrittsseite.
- **Neuer Logkanal `database`** → `logs/database.log` (in Administration → Logs
  filter-/such-/downloadbar). Erfasst Migration gestartet/erfolgreich/
  fehlgeschlagen, Rollback und Verbindungstests (Zeitpunkt, Benutzer, Quelle,
  Ziel, Datensatzanzahl, Dauer, Ergebnis) – nie Zugangsdaten. Über das neue
  Logging-Setting „Datenbank-Logging“ steuerbar.

### Changed

- **Systemstatus erweitert**: zeigt aktive Datenbank, Datenbankversion, Host,
  Datenbankname, Tabellenanzahl, letzte Migration, letzte erfolgreiche Migration
  und letzten Fehler.
- **PostgreSQL-Treiber** (`psycopg2-binary`) ergänzt; `app/database.py` erkennt
  und bedient SQLite, MySQL/MariaDB (PyMySQL) und PostgreSQL über eine
  abstrahierte URL-/Engine-Schicht mit Laufzeit-Reconfigure.
- Version auf **0.9.7** angehoben (Frontend, Backend, Footer, Loginseite,
  Systemstatus, API-Version, Release- und Buildinformationen).

## [0.9.6] – 2026-06-14

### Changed – Administration UI/UX überarbeitet

- **Navigation im Reiter-Design**: Die Administrationsnavigation
  (`templates/admin/_nav.html`) entspricht jetzt optisch den Reitern unter
  „Buchungen“/„Urlaub“ (`.timetac-subnav`): flache, kantige Reiter mit gemeinsamer
  Unterkante, gleicher Höhe, Schriftgröße, Hover-/Active-/Focus-States und
  Abständen – keine klassischen Dropdown-Menüs/Bootstrap-Optik mehr.
  Verhalten unverändert: Desktop öffnet beim Hover ein Dropdown und schließt
  beim Verlassen, Mobile klappt als Accordion, es ist immer nur **eine**
  Hauptgruppe geöffnet.
- **Systemeinstellungen aufgeräumt**: `admin/system_settings.html` ist in klare
  Sektionen mit Kartenlayout gegliedert (Allgemein, Logging, Log-Rotation,
  Synchronisation, Import) mit einheitlichen Feldbreiten, -höhen und Abständen.

### Added – QR-Code im Benutzerdialog

- „Benutzer bearbeiten“ zeigt den Anmelde-QR-Code jetzt direkt im Dialog
  (rechte Seitenspalte auf dem Desktop, unterhalb der Benutzerdaten auf Mobil)
  mit Kurzbeschreibung, Download und „Neu generieren“.

### Fixed – Backup-Historie als eigene Ansicht

- Die Backup-Historie hatte bisher dieselbe Seite wie die Backup-Jobs
  (`/admin/system/backups#history`). Sie besitzt nun eine **eigene Route**
  (`GET /admin/system/backups/history`), ein eigenes Template
  (`admin/system_backups_history.html`) und eine eigene Datenabfrage. Spalten:
  Backup, Start, Ende, Dauer, Größe, Ziel, Status sowie Aktionen (Download,
  Details, Wiederherstellen). Die Backup-Jobs-Seite zeigt nur noch geplante Jobs.

### Fixed – Navigation schließt bei Dialogen

- Beim Öffnen eines Bearbeitungs-/Erstellungsdialogs (Benutzer, Rollen, Firmen,
  Systemeinstellungen, Backup-/Restore-Dialoge u. a.) bleibt keine
  Navigationsgruppe mehr dauerhaft geöffnet: Formularseiten setzen
  `admin_nav_collapse`, Modals lösen ein automatisches Schließen aus
  (Beobachtung der `body.modal-open`-Klasse).

### Docs

- `AGENTS.md`: neue Pflichtprüfung für Administrationsänderungen (Navigation,
  Responsive, Dropdown-Verhalten, Formularausrichtung, Design-Konsistenz).

## [0.9.5] – 2026-06-14

### Fixed – „Internal Server Error" bei der Wiederherstellung

- **Ursache**: Die Wiederherstellung lief synchron im HTTP-Request und tauschte
  die SQLite-Datei aus bzw. verwarf den Engine-Pool (`engine.dispose()`) –
  dadurch wurde genau die Verbindung zerstört, die der laufende Request nutzte,
  und die Antwort endete als 500, obwohl der Restore teils/ganz erfolgreich war.
- **Lösung**: Restore läuft jetzt **asynchron** in einem Hintergrund-Worker. Der
  Request validiert nur (Berechtigung, Datei, Integrität, Kompatibilität),
  erzeugt einen Restore-Job und antwortet sofort mit Weiterleitung auf eine
  Fortschrittsseite.

### Added – Asynchrones Restore mit Statusüberwachung

- Hintergrund-Worker (`app/restore_jobs.py`) mit persistenter Status-Datei im
  `data`-Volume (übersteht DB-Tausch und Neustarts).
- **Status-API** `GET /api/restore/status` (nur Session-basiert, ohne
  Datenbankzugriff) mit Zuständen `queued`, `creating_backup`, `restoring`,
  `restarting`, `running_migrations`, `completed`, `failed` inkl. Fortschritt,
  Meldung, Start-/Endzeit.
- **Fortschrittsseite** mit Fortschrittsbalken, Statusschritten,
  **Neustarterkennung** (bei kurzzeitig nicht erreichbarem Backend wird „Anwendung
  wird neu gestartet, Verbindung wird wiederhergestellt …" angezeigt und weiter
  gepollt) sowie **Countdown (5→1)** und automatischer Weiterleitung zu `/login`.
- **Fehleranzeige** mit Ursache, Zeitpunkt und Log-ID statt nacktem 500.
- Sauberes Schließen/Neuinitialisieren der DB-Verbindungen vor/nach dem Restore
  (SQLite & MySQL).

### Added – Logging, Historie & Systemstatus

- `backup.log` um detaillierte Restore-Schritte erweitert (Restore gestartet,
  Sicherheitsbackup erstellt, Migration gestartet/erfolgreich/fehlgeschlagen,
  Anwendung wird neu gestartet/wieder verfügbar, Restore erfolgreich/fehlgeschlagen).
- Restore-Historie um **Dauer** und **Log-ID** erweitert.
- Systemstatus zeigt zusätzlich letzte erfolgreiche/fehlgeschlagene
  Wiederherstellung, aktiven Restore-Job und letzte Migrationsausführung.

### Notes

- Schemaänderung: `restore_runs.duration_seconds` und `restore_runs.log_token`
  (Migration 8, idempotent, dialect-aware). Upgradepfade 0.6.x–0.9.4 → 0.9.5
  (SQLite & MySQL) verifiziert; keine Datenverluste.

## [0.9.4] – 2026-06-13

### Added – Enterprise Backup & Restore

- **Wiederherstellung** (`Administration → Sicherung → Wiederherstellung`):
  Backups prüfen, herunterladen, hochladen und wiederherstellen. Listet lokale
  und hochgeladene Backups mit Dateiname, Größe, Datum, Anwendungsversion,
  Datenbanktyp, Schema-Version und Quelle.
- **Restore-Dialog** mit Pflicht-Bestätigung („WIEDERHERSTELLEN" eingeben) und
  deutlicher Warnung. Vor jeder Wiederherstellung wird automatisch ein
  **Sicherheitsbackup** (`pre_restore_*.zip`) erzeugt.
- **Versionsübergreifender Restore**: Ältere Backups (0.6.x–0.9.3) werden
  unterstützt; nach dem Einspielen werden fehlende Tabellen angelegt und alle
  ausstehenden Migrationen automatisch ausgeführt (SQLite & MySQL). Kein
  manueller Eingriff nötig.
- **Backup-Download** als Streaming/Chunked-Transfer (auch große Dateien, nicht
  komplett im RAM). **Upload** großer Backups in 1-MiB-Chunks, isoliert
  gespeichert, erst nach Integritätsprüfung übernommen.
- **Backup-Prüfung** (verify) mit Ampel: grün (verwendbar), gelb (verwendbar
  mit Hinweisen), rot (nicht verwendbar).
- **Backup-Metadaten** in jedem Archiv (`backup_meta.json`): Anwendungsversion,
  Datenbanktyp, Schema-Version, Erstellungsdatum, Backup-Typ – für
  Kompatibilitätsprüfungen.
- **Restore-Historie** (`restore_runs`): Zeitpunkt, Benutzer, Datei, Version,
  DB-Typ, Sicherheitsbackup, ausgeführte Migrationen, Ergebnis.

### Added – Eigenes Backup-Logging

- Neuer Logkanal **`logs/backup.log`** für alle Backup-/Restore-/Upload-/
  Verbindungstest-/Aufbewahrungs-/Integritätsvorgänge (Zeitpunkt, Benutzer,
  Jobname, Ziel, Dateiname, Größe, Dauer, Ergebnis). Passwörter/Zugangsdaten
  werden niemals protokolliert. In `Administration → Logs` filter-, such- und
  herunterladbar.
- Logging-Konfiguration um **Backup-Logging** und **Restore-Logging** erweitert
  (persistent im config-Volume).
- Audit-Log um Backup-Ereignisse erweitert (manuell gestartet, gelöscht,
  hochgeladen, wiederhergestellt, Job erstellt/geändert, Ziel geändert).

### Changed

- Systemstatus zeigt zusätzlich letztes erfolgreiches Backup, letzten
  Backupfehler, letzte Wiederherstellung und letzte Backupprüfung.
- Navigation „Sicherung" um **Wiederherstellung** und **Restore-Historie**
  erweitert.

### Notes

- Schemaänderung: neue Tabelle `restore_runs` (Migration 7, idempotent,
  dialect-aware). Upgradepfade 0.6.x–0.9.3 → 0.9.4 (SQLite & MySQL) verifiziert;
  keine Datenverluste. Uploads werden auf Dateityp, Archiv-Integrität und
  Path-Traversal geprüft und isoliert gespeichert.

## [0.9.3] – 2026-06-13

### Fixed – Backup-Job-Modal vollständig bedienbar

- Das Modal „Neuer Backup-Job" wird nie höher als der Viewport (`max-height:
  90vh`). Kopfzeile (Titel) und Fußzeile (Abbrechen, Verbindung testen,
  Speichern) bleiben immer sichtbar; nur der Inhaltsbereich scrollt. Damit
  werden die unteren Buttons auf Notebook-/Tablet-Auflösungen nicht mehr
  abgeschnitten.
- Kompakteres Layout (geringere Abstände, gruppierte Felder); dynamische Felder
  je Typ (Lokal/FTP/SMB) ohne Leerflächen. Zusätzlicher „Abbrechen"-Button.

### Changed – Administration-Navigation als echtes Akkordeon

- Es ist immer **maximal eine** Hauptgruppe geöffnet: Beim Öffnen einer Gruppe
  schließen sich die übrigen automatisch.
- **Desktop**: Gruppen öffnen per Hover und schließen automatisch, wenn der
  Mauszeiger die Navigation verlässt; Klick funktioniert weiterhin.
- **Mobile/Touch**: Accordion per Klick (kein Hover); das Öffnen einer Gruppe
  schließt die vorherige.
- Überarbeitete Hover-, Fokus- und Active-States; Dropdown-Panels ohne Lücke
  (kein Flackern beim Hover).

## [0.9.2] – 2026-06-13

### Added – Job-basierte Backup-Verwaltung

- Backups laufen jetzt als verwaltete **Backup-Jobs** (Tabelle `backup_jobs`):
  Liste aller Jobs mit Name, Typ, Aktiv, Zeitplan, Aufbewahrung, letzter
  Ausführung und letztem Ergebnis; Aktionen Bearbeiten, Sofort ausführen,
  Aktivieren/Deaktivieren, Löschen.
- **Neuer Backup-Job** öffnet ein Modal mit dynamischen Feldern je Typ:
  - Lokal: Zielpfad
  - FTP/FTPS: Server, Port, Benutzer, Passwort (maskiert), Zielpfad
  - SMB3: **ein** UNC-Pfad-Feld (`\\\\server\\share\\sub`) und **ein**
    Benutzerfeld (`benutzer`, `DOMAIN\\benutzer` oder `benutzer@domain.local`).
- **Verbindung testen** direkt im Modal (lokal/FTP/SMB), mit Ergebnis-/Fehlertext.
- **Backup-Inhalt** wählbar (Datenbank, Konfiguration, Logs – Mehrfachauswahl).
- **Zeitplan** je Job: manuell, täglich, wöchentlich, monatlich; ein
  In-Process-Scheduler führt fällige Jobs automatisch aus.
- **Aufbewahrung** je Job (Anzahl und/oder Tage), alte Backups werden
  automatisch entfernt (lokal vollständig, FTP/SMB best-effort).
- **Backup-Historie** (Tabelle `backup_runs`): Start, Ende, Dauer, Größe, Ziel,
  Status (Erfolg/Warnung/Fehler); Download lokaler Sicherungen.
- **Engine**: konsistente Datenbank-Sicherung (SQLite Online-Backup-API,
  MySQL via `mysqldump`), Integritätsprüfung nach jeder Sicherung
  (Datei vorhanden, plausible Größe, Archiv lesbar). Passwörter werden nie
  im Klartext geloggt. Eine vorhandene 0.9.0/0.9.1-Backup-Konfiguration wird
  beim Start in einen (inaktiven) Job übernommen.

### Changed – Administration-Navigation gruppiert

- Neue, gruppierte und einklappbare Navigation (`<details>`-Accordion) mit den
  Gruppen **Benutzer**, **Zeitverwaltung**, **Sicherung**, **System** und
  **Einstellungen**. Desktop als Dropdown-Panels, Mobile als Accordion; der
  offene/geschlossene Zustand wird pro Gruppe gemerkt (localStorage). Die Gruppe
  der aktiven Seite öffnet automatisch.

### Notes

- Schemaänderung: neue Tabellen `backup_jobs` und `backup_runs`
  (Migration 6, idempotent, dialect-aware via `create_all`). Upgradepfade
  0.6.x–0.9.1 → 0.9.2 für SQLite und MySQL verifiziert; keine Datenverluste.

## [0.9.1] – 2026-06-13

### Fixed

- „Schnell stempeln": Das Info-Symbol zeigte fälschlich den Freigabe-Hinweis
  der manuellen Buchung. Es wird wieder der Arbeitsschutz-Hinweis nach ArbZG
  angezeigt (Pausen: nach 6 Std mind. 30 Min, nach 9 Std mind. 45 Min) – bei
  aktiver automatischer Pausenkorrektur ergänzt um den Abzugs-Hinweis. Gilt für
  Web und Mobile.

## [0.9.0] – 2026-06-13

### Added – Professionelles Logging-System

- Dateibasiertes Logging (`app/logging_setup.py`) mit sechs rotierenden
  Kanälen im `logs`-Volume: `application.log`, `api.log`, `sync.log`,
  `security.log`, `error.log`, `audit.log`. Strukturiertes Format mit
  Zeitstempel, Log-Level, Kanal und Benutzerbezug.
- Größenbasierte Log-Rotation (max. Dateigröße + Generationen),
  konfigurierbar und persistent im `config`-Volume (`logging.json`).
- Optionale automatische Bereinigung rotierter Logs nach Alter.

### Added – Administration → System

- **Logs** (`/admin/system/logs`): Anzeige aller Kanäle mit Filter
  (Suchtext, Log-Level, Zeitraum), Einzel-Download, ZIP-Download mehrerer
  Logs, Leeren einzelner/aller Logs (mit Sicherheitsabfrage, nur Admins)
  sowie optionalem Auto-Refresh.
- **Systemstatus** (`/admin/system/status`): Version, Datenbankstatus/-typ,
  Benutzer-/Urlaubs-/Auftrags-Zahlen, Speicherinformationen (DB-, config-,
  logs-Größe, freier Speicher), Synchronisation, PWA-Status und Volume-Übersicht
  (Pfad, Größe, Dateianzahl, letzte Änderung).
- **Fehlerübersicht** (`/admin/system/errors`): Fehler 24 h / 7 Tage,
  häufigste Fehler, Fehler nach Kategorie, Direktsprung zu den Logs.
- **Systemeinstellungen** (`/admin/system/settings`): Log-Level, Logging-Toggles,
  Rotation und Synchronisationsparameter; persistent im `config`-Volume.
- **Backups** (`/admin/system/backups`): Übersicht (letzte Sicherung, Datum,
  Größe, Speicherort) und manuelles Erstellen einer ZIP-Sicherung von
  Datenbank + Konfiguration.

### Added – Audit-Logging, Health, Import/Export

- Audit-Protokollierung für Login/Logout, Passwort-, Benutzer-, Rollen-,
  Urlaubs-, Feiertags- und Systemeinstellungsänderungen sowie Log-Aktionen.
- `/health` liefert nun einen detaillierten Statusbericht (Datenbank,
  Konfiguration, Volumes, Schreibrechte) inkl. korrektem HTTP-Status.
- Export/Import der Systemeinstellungen und der Feiertagskonfiguration als JSON
  (mit Validierung vor der Übernahme).

### Added – Persistente Volumes & Start-up-Prüfung

- Zentrale Volume-Auflösung (`app/paths.py`) für `config`, `data`, `logs`
  inkl. Umgebungsvariablen-Overrides. Beim Start werden fehlende Verzeichnisse
  angelegt und das Ergebnis im `application.log` dokumentiert.

### Changed – Dashboard & Arbeitsschutz-Hinweis

- Dashboard-Reihenfolge: Mein Soll-/Ist-Stunden → Urlaubsübersicht →
  Feiertagsübersicht. Die doppelte Feiertagsanzeige im unteren Bereich
  wurde entfernt – Feiertage erscheinen nur noch einmal.
- Arbeitsschutz-Hinweis ist nun kontextabhängig: Der Freigabe-Hinweis wird
  immer angezeigt; der Hinweis zu automatischen gesetzlichen Pausen nur, wenn
  `auto_break_deduction` aktiv ist (Web und Mobile, inkl. Info-Tooltip).

### Added – Feiertagsverwaltung überarbeitet (§22)

- Jahres-Dropdown entfernt; es gilt automatisch das aktuelle Kalenderjahr.
- Einzige Auswahl ist das Bundesland; Aktion „**Feiertage übernehmen**" lädt,
  speichert und übernimmt die gesetzlichen Feiertage des aktuellen Jahres.
- Neues Feld `Holiday.source` (`statutory`/`custom`): Eigene Feiertage werden
  beim Übernehmen nie überschrieben, es entstehen keine Duplikate. Bestehende
  Einträge gelten als `custom` (Default), bleiben also erhalten.

### Added – Optionale MySQL-Unterstützung (§23)

- Datenbankwahl über `DATABASE_URL` (Standard bleibt SQLite); MySQL 8+/MariaDB
  via PyMySQL. Engine dialect-aware (Pool-Pre-Ping für MySQL).
- Alle `String`-Spalten haben jetzt explizite Längen (MySQL-kompatibel).
- Migrationen sind dialect-aware: Versionsstand wird in der portablen Tabelle
  `schema_migrations` geführt (statt SQLite-`PRAGMA user_version`), bestehende
  SQLite-Installationen werden transparent übernommen. Migrationen laufen
  automatisch beim Start, sind idempotent und datenerhaltend.

### Fixed – Offline-Aktionszähler (§24)

- „Offene Offline-Aktionen" im Systemstatus zählte fälschlich den
  Idempotenz-/Dedup-Log bereits verarbeiteter Aktionen (`mobile_sync_actions`).
  Der Server verarbeitet Offline-Aktionen synchron und hat keine serverseitige
  Warteschlange – der Wert ist nun korrekt 0. Verarbeitete Aktionen werden
  separat als Gesamtzahl ausgewiesen.

### Added – Synchronisationsdiagnose & Systemstatus (§24/§26)

- Neuer Bereich **Administration → Synchronisation** (`/admin/system/sync`):
  offene Aktionen, laufende/fehlerhafte Synchronisationen, Retry-Versuche,
  letzte erfolgreiche Synchronisation, verarbeitete Offline-Aktionen.
- Systemstatus zeigt Datenbanktyp, DB-Version, letzte und ausstehende
  Migrationen.

### Added – Backup-Ziele & -Verwaltung (§25/§26)

- Backup-Ziele **lokal**, **FTP/FTPS** und **SMB3** (Windows-kompatible Pfade,
  Auth mit Benutzer/Passwort/Domäne). Konfiguration persistent im
  config-Volume; Passwörter werden nie im Klartext geloggt.
- „Verbindung testen", konfigurierbare Aufbewahrung (Anzahl/Dauer),
  Integritätsprüfung nach jeder Sicherung (Datei/Größe/Archiv lesbar),
  Backup-Historie mit Ergebnis, optionales Einschließen der Logs.

### Notes

- Schemaänderung in dieser Version: `holidays.source` (Migration 5,
  idempotent, dialect-aware, Default `custom`). Upgradepfade
  0.6.x/0.7.x/0.8.x → 0.9.0 für SQLite und MySQL über `schema_migrations`
  verifiziert (Daten bleiben erhalten). Neue Abhängigkeiten: `PyMySQL`,
  `smbprotocol`.

## [0.8.1] – 2026-06-13

### Added – Benutzerauswertung (Zeitübersicht je Benutzer)

- Neue Auswertung unter **Administration → Benutzerauswertung**
  (`/admin/reports/users`): frei wählbarer Zeitraum, Auswahl einzelner
  oder mehrerer Benutzer (ohne Auswahl: alle). Je Benutzer werden
  Buchungen, Arbeitszeit, Pausen, Soll, Urlaub, Überstundenabbau und
  Über-/Minusstunden ausgewiesen, inkl. Summenzeile.
  (Krankheit ist im Datenmodell nicht vorhanden und daher nicht enthalten.)
- **PDF-Export** im bestehenden Report-Layout
  (`/admin/reports/users/pdf`).
- **Excel-Export** (`/admin/reports/users/excel`): ein Benutzer pro
  Zeile, Dezimalstunden mit Zahlenformat, fixierte Kopfzeile – geeignet
  für Weiterverarbeitung.

### Added – Konfigurierbare gesetzliche Pausen

- Neues Benutzerfeld `auto_break_deduction` (Standard: aktiviert).
  Checkbox „Automatische gesetzliche Pausen anwenden (ArbZG)" unter
  Benutzer bearbeiten → Zeitkonto & Buchungen.
- Deaktiviert: keine automatische Pausenkorrektur mehr – es zählen nur
  tatsächlich gestempelte Pausen. Aktiviert: bisheriges Verhalten.
- Migrationssicher: `ensure_schema()` ergänzt die Spalte mit Default 1
  beim Start, zusätzlich versionierte Migration 4 in
  `app/db_migrations.py`. Bestehende Benutzer behalten das bisherige
  Verhalten.

### Changed – Feiertagsverwaltung vereinfacht

- „Jahr synchronisieren"-Formular und „Feiertage laden"-Button entfernt;
  die Endpunkte `POST /admin/holidays/sync` und `POST /api/holidays/sync`
  wurden ersatzlos gestrichen.
- Feiertage werden jetzt automatisch verwaltet: beim Anwendungsstart
  werden aktuelles und nächstes Jahr für die konfigurierte Region
  sichergestellt; die Verwaltungsseite lädt fehlende Jahre weiterhin
  automatisch beim Aufruf. Manuelles Anlegen/Löschen bleibt erhalten.

### Added – Feiertage im Dashboard

- Neue kompakte Sektion „Nächste Feiertage" in der Dashboard-Seitenleiste
  direkt unter „Meine Soll-/Ist-Stunden" (bis zu 5 kommende Feiertage,
  token-basiert und damit Dark-Mode-kompatibel).

### Added – AGENTS.md

- Neuer Leitfaden für Entwicklungsagenten mit verpflichtenden Regeln für
  Datenbankschema-Prüfung, idempotente Migrationen, versionsübergreifende
  Upgrades (0.6.x/0.7.x/0.8.0 → 0.8.1) und Vor-Deployment-Checks.

### Grund der Versionsanhebung

Patch-/Minor-Mischung bewusst als 0.8.1 gemäß Vorgabe: neue Auswertung und
Benutzereinstellung, vereinfachte Feiertagsverwaltung, keine Breaking
Changes; Migrationen halten alle Bestandsdaten.

## [0.8.0] – 2026-06-13

### Changed – PDF-Reports grundlegend überarbeitet (`app/pdf_export.py`)

- **Keine Überlappungen mehr:** jede Tabellenzelle wird als umbruchfähiger
  `Paragraph` gerendert (inkl. XML-Escaping von Nutzereingaben). Lange
  Firmennamen, Kommentare oder Status brechen sauber innerhalb ihrer Spalte
  um, statt in Nachbarspalten zu laufen oder abgeschnitten zu werden.
- **Bessere Seitennutzung:** kompakter Kopf (Titel 15pt linksbündig + eine
  Metazeile statt großem zentriertem Titel mit Doppel-Spacern), Ränder
  20mm → 14mm seitlich / 12mm oben, kompakte Zellenpaddings und 8pt-Schrift
  in Tabellen, Kennzahlen + Urlaubskonto bzw. Zusammenfassung +
  Statusverteilung nebeneinander statt untereinander.
- **Einheitliches Tabellen-Stilsystem** für beide Reports (Kopfzeile,
  Zebra-Streifen, Gitter, rechtsbündige Zahlenspalten, wiederholte
  Kopfzeile bei Seitenumbruch, Summenzeile) statt sechsfach kopierter
  Einzel-Styles.
- **Fußzeile mit Seitenzahl** auf jeder Seite (auch im Team-Report, der
  zuvor gar keine Fußzeile hatte).
- **Fix:** Im Team-Report stand die Summe der Einzelbuchungen in der
  Spalte „Ende" statt „Arbeitszeit".

### Added – Urlaubsübersicht im PDF

- Beide Reports enthalten eine Tabelle „Urlaubsübersicht" mit Zeitraum,
  Typ (Urlaub/Überstundenabbau), Status (Genehmigt, Offen, Abgelehnt,
  Storniert, Rücknahme angefragt), Arbeitstagen, Stunden-Anrechnung (nur
  bei genehmigten Anträgen) und Kommentar – für dieselbe Periode wie der
  Report. Die Kennzahlen-Berechnung nutzt unverändert nur genehmigte
  Anträge.

### Changed – Arbeitsschutz-Hinweis als Info-Tooltip

- Der dauerhaft sichtbare ArbZG-Hinweis (Desktop-Dashboard, Mobile-App,
  Offline-Shell) ist jetzt ein kleines (i)-Symbol neben „Schnell stempeln":
  Hover/Fokus zeigt den Tooltip (Desktop), Tippen öffnet/schließt ihn
  (Mobile), Escape schließt. Token-basiert, Dark-Mode-kompatibel, absolut
  positioniert (keine Layoutverschiebung).

### Grund der Versionsanhebung

Minor (`0.7.0` → `0.8.0`): neue Reportinhalte (Urlaubsübersicht) plus
Layout-/Usability-Überarbeitung ohne Änderung bestehender Geschäftslogik.

## [0.7.0] – 2026-06-13

### Added – Dark Mode (vollständig, umschaltbar)

- **Umschalter Hell/Dunkel** im Desktop-Header und im Mobile-Footer
  (auch in der Offline-Shell der PWA). Die Wahl wird in `localStorage`
  (`erfassung-theme`) gespeichert und bleibt beim Neuladen erhalten; ohne
  gespeicherte Wahl folgt die App der Systemeinstellung
  (`prefers-color-scheme`).
- **Kein Flackern:** ein Inline-Snippet im `<head>` wendet das gespeicherte
  Theme vor dem ersten Paint an; `static/theme.js` (neu, im Service-Worker-
  Precache) verdrahtet die Toggle-Buttons und hält `theme-color` synchron.
- **Dunkle Palette** (kein reines Schwarz): Hintergrund `#0f172a`, Flächen
  `#111827`, Karten `#1e293b`, Rahmen `#334155`, Text `#f8fafc`, gedämpfter
  Text `#94a3b8`, Primärfarbe `#3b82f6`. Umgesetzt ausschließlich als
  Token-Overrides unter `:root[data-theme="dark"]` – keine komponentenweisen
  Sonderfälle.

### Changed – Design-System konsequent durchgezogen

- **Radius-Skala als einzige Quelle:** `--radius-xs` 3px (Tabs, Badges,
  Chips), `--radius-sm` 5px (Buttons, Inputs, Selects), `--radius-md` 6px,
  `--radius-lg` 8px (Karten, Dialoge). Alle fest codierten `border-radius`-
  Werte (inkl. `50%` beim Mobile-Einstellungsbutton) entfernt; nichts ist
  mehr runder als 8px.
- **Einheitliche Control-Höhen:** `--control-h` (2.5rem) für Inputs, Selects
  und Buttons; `--control-h-sm` (2rem) nur für kompakte Tabellen-Buttons.
  Filterleisten (u. a. „Feiertage verwalten", Buchungen, Zeitübersichten)
  haben jetzt durchgehend gleiche Höhen in einer Zeile.
- **Navigation modernisiert:** kompakter Sticky-Header (3.5rem), SVG-Icons
  statt Emojis, ruhige Hover-Zustände (neutraler Wash), klarer aktiver
  Zustand; Bereichs-Tabs (Admin, Buchungen/Urlaub) als Underline-Tabs statt
  Pill-Container; Footer als dezente Trennlinie statt blauem Balken.
- **Alle Farben tokenisiert:** sämtliche hartcodierten Hex-/RGBA-Werte in
  `styles.css` (Modals, Login, Alerts, Formulare, Tabellen-Streifen,
  Status-Badges, Mobile-Listen …) durch Design-Tokens ersetzt – Voraussetzung
  dafür, dass der Dark Mode überall greift. Einzige Ausnahme: der QR-Code
  behält bewusst einen weißen Hintergrund (Scanbarkeit).
- **Manifest/Theme-Color** auf die aktuelle Palette aktualisiert
  (`#2563eb`, Hintergrund `#f8fafc`).

### Grund der Versionsanhebung

Minor (`0.6.0` → `0.7.0`): neues Feature (umschaltbarer Dark Mode) plus
sichtbares, aber rein darstellungsbezogenes Design-Refactoring.

## [0.6.0] – 2026-06-12

### Changed – UI-Redesign (modernes SaaS-/Business-Erscheinungsbild)

Reines Design-/UX-Update – **keine** Änderung an Funktionen, APIs, Datenmodell,
Synchronisation, Offline-Funktion oder Geschäftslogik. Betroffen ist
ausschließlich `static/styles.css`.

- **Design-System / Tokens:** zentrale `:root`-Token-Ebene (Farben, Radien,
  Schatten, Status, Focus-Ring). Alle Komponenten konsumieren diese Tokens, wodurch
  Desktop und Mobile durchgängig wie ein Produkt wirken.
- **Farbpalette:** tiefes Blau als Primärfarbe (`#2563eb` / Hover `#1d4ed8`),
  Slate-Neutraltöne, ruhiger Hintergrund (`#f8fafc`), weiße Karten. Statusfarben
  vereinheitlicht: Grün (aktiv), Amber (Pause), Blau (Urlaub/Info), Rot (Fehler).
- **Kanten statt Pillen:** kleine Border-Radien (Buttons/Inputs/Badges 6px, Karten
  /Dialoge 8px); alle `999px`-Pillen entfernt.
- **Buttons:** Primary (klare Fläche, dezenter Schatten, Hover, Focus-Ring),
  Secondary (zurückhaltender Neutral-Outline), Danger (klar rot).
- **Karten:** 1px-Rahmen + dezente Schatten statt starker Schlagschatten; mehr
  Ruhe, klare Trennung. KPI-Karten vereinheitlicht.
- **Tabellen:** ruhige Kopfzeile (Uppercase, gedämpft), Zeilen-Hover, bessere
  Lesbarkeit.
- **Mobile (`/mobile`):** Header, Tabs, Stempelbuttons, Auftrags- und
  Urlaubsansicht auf dasselbe Token-System umgestellt – wirkt wie eine
  installierbare Business-App, nicht wie eine Website.
- **Dark Mode:** vorbereitet (Token-Overrides unter `html[data-theme="dark"]`),
  bewusst **nicht** automatisch aktiv – Standard bleibt Hell.

### Grund der Versionsanhebung

Minor (`0.5.2` → `0.6.0`): umfassendes, sichtbares Redesign (nur Darstellung),
ohne funktionale Änderungen.

## [0.5.2] – 2026-06-12

### Fixed – Mobile-/PWA-Funktionen

- **Auftragsstart-Dialog blieb geöffnet:** `handleOfflineSubmission` setzte das
  Formular zwar zurück, schloss aber das Modal nicht. Nach erfolgreichem Start
  (queue-first, also immer erfolgreich) wird das umgebende Modal jetzt
  automatisch geschlossen; der Nutzer sieht wieder die normale Ansicht.
- **Urlaubsanträge verschwanden nach der Synchronisation:** Die mobile Urlaubsliste
  wurde nur serverseitig (beim Online-Laden) bzw. für Offline-Entwürfe befüllt –
  es gab **keine** clientseitige Darstellung aus dem gecachten Snapshot. Nach
  Sync/Reload waren synchronisierte Anträge daher nicht mehr sichtbar. Neu:
  `renderVacations()` zeigt **alle Anträge des laufenden Jahres** (offen,
  genehmigt, abgelehnt, storniert, Rücknahme angefragt sowie noch nicht
  synchronisierte Offline-Anträge) mit Zeitraum, Typ und Status. Backend:
  `/mobile/sync-data` liefert Urlaubsanträge nun für das **gesamte laufende Jahr**
  (zuvor nur das `days`-Fenster).
- **Synchronisationsanzeige zeigte Phantom-Aktionen („4 Offline-Aktionen warten"
  trotz Sync):** In der Queue konnten Aktionen dauerhaft hängen bleiben – etwa
  ein verwaister Stempel-Stopp (`end_*`), dessen Buchung serverseitig längst
  geschlossen ist und der mit `retryable` beantwortet wurde (das blockierte zudem
  die übrige Queue). `flushOfflineQueue` entfernt eine Aktion jetzt bei **jeder
  eindeutigen Server-Antwort** (Erfolg, Duplikat oder definitive Ablehnung);
  nur bei echten Transport-/Auth-Fehlern bleibt sie erhalten. Echte
  Reihenfolge-Abhängigkeiten bleiben über den Transientfehler-Pfad gewahrt.
  Ergebnis: Der Zähler entspricht exakt dem Queue-Zustand – keine Phantom-Einträge.

### Nicht verändert (Offline-Architektur erhalten)

- Offline-Start, Service Worker, IndexedDB-Speicherung, Offline-Stempelungen,
  Sync-Queue, Wiederanlauf, Idempotenz/Duplikatvermeidung und automatische
  Synchronisation bleiben unverändert (per Regressionstest bestätigt).

### Grund der Versionsanhebung

Patch (`0.5.1` → `0.5.2`): gezielte Korrekturen dreier Mobile-Funktionen ohne
Eingriff in die Offline-Architektur, Datenmodell oder Geschäftslogik.

## [0.5.1] – 2026-06-11

### Fixed – Regressionen nach dem 0.5.0-Offline-Refactoring

- **Navigation reagierte erst beim zweiten Klick & Administration nicht
  erreichbar (gleiche Ursache):** Mit 0.5.0 wurde der Service Worker erstmals im
  Scope `/` aktiv. Sein `offlineFirstNavigation` bediente daraufhin **jede**
  Navigation cache-first aus dem einen `/mobile`-Cache-Eintrag. Folge: andere
  Seiten (`/dashboard`, `/admin`, `/records/*`) zeigten beim ersten Klick den
  zuvor gecachten Inhalt und erst der zweite Klick die richtige Seite; der
  legitime `303`-Redirect von `/admin` → `/admin/users` wurde nie befolgt
  („Administration nicht erreichbar"). Der Worker bedient nun **ausschließlich
  die `/mobile`-Route** offline-first; alle übrigen Navigationen gehen direkt
  ans Netzwerk und funktionieren beim ersten Klick. Offline-Verhalten von
  `/mobile`, Caching statischer Assets und die Sync-Logik bleiben unverändert.
- **Arbeitszeitverlauf falsch sortiert:** Zwei Ansichten sortierten aufsteigend
  (ältester Eintrag oben). Sie zeigen jetzt **neueste Einträge zuerst**:
  - Desktop-Dashboard „Heute" (`_build_daily_overview`).
  - Administration → Zeitberichte inkl. PDF-/Excel-Export (`entries_sorted`;
    Datum/Startzeit absteigend, Name aufsteigend als Tiebreaker).
  Geändert wurde ausschließlich die Anzeige-/Export-Reihenfolge – Zeitstempel,
  Arbeits-/Pausenzeiten, Summen, Datenbank und Synchronisation bleiben unberührt.
  (Mobile Tages-/Wochenansicht, Buchungsliste und Freigaben waren bereits
  absteigend bzw. Kalenderraster und blieben unverändert.)

### Grund der Versionsanhebung

Patch (`0.5.0` → `0.5.1`): gezielte Regressionsbehebung, keine Änderung an den
Offline-Komponenten (Start, Service-Worker-Caching, IndexedDB, Queue, Sync,
Duplikatvermeidung).

## [0.5.0] – 2026-06-11

### Fixed – Offline-PWA zuverlässig gemacht

- **Offline-Start scheiterte (Safari/iOS: „Seite nicht gefunden"):**
  Der Service Worker wurde unter `/static/sw.js` ausgeliefert, aber mit
  `{scope: '/'}` registriert. Der maximal erlaubte Scope eines Workers ist sein
  eigener Pfad (`/static/`); ein breiterer Scope erfordert den Header
  `Service-Worker-Allowed`, den `StaticFiles` nicht sendet. Dadurch wurde die
  **Registrierung vom Browser abgelehnt**, das `install`-Event lief nie, nichts
  wurde vorab gecacht – die App konnte offline nicht starten. Der Worker wird nun
  von der Wurzel (`GET /sw.js`) mit `Service-Worker-Allowed: /` ausgeliefert und
  als `/sw.js` registriert, sodass Scope `/` gültig ist und `/mobile` offline
  bedient wird.
- **Offline-Stempelungen wurden nicht vollständig synchronisiert (v. a.
  Arbeitsende):** Mehrere zusammenwirkende Ursachen behoben:
  1. `postQueuedAction` nutzte `redirect: 'manual'` und wertete **jede**
     303-Antwort als „Sitzung abgelaufen". Da `/punch` bei Erfolg immer per 303
     antwortete, schlug jede erfolgreiche Buchung clientseitig fehl. Die
     Endpunkte liefern bei `Accept: application/json` nun eine **maschinenlesbare
     JSON-Antwort** (`{ok, duplicate, retryable, message}`).
  2. `processPunchSubmission` **verwarf** Ereignisse vor dem Speichern anhand
     einer clientseitigen Zustandsprüfung. In Kombination mit einem eingefrorenen
     Lade-Zustand führte das dazu, dass das **Arbeitsende verworfen** wurde. Jede
     Buchung wird jetzt **immer** zuerst in IndexedDB gespeichert.
  3. `flushOfflineQueue` löschte nicht gesendete Aktionen aufgrund clientseitiger
     Vermutung (Datenverlust). Es wird nun **jede** Aktion in Erstellungsreihenfolge
     an den Server gesendet; entfernt wird sie nur bei eindeutiger Server-Antwort
     (Erfolg/duplikat). Server-Idempotenz (`client_action_id`) verhindert Dubletten.
  4. Der effektive Zustand wird nach jeder Synchronisation aus dem frischen
     Server-Snapshot aktualisiert (statt am eingefrorenen Lade-Zustand zu hängen).
- **Offline-Zeiten waren falsch (Sync-Zeit statt Ereigniszeit):** Der Server
  stempelte jede Buchung mit `datetime.now()`. Offline erfasste Ereignisse
  bekamen damit die (spätere) Synchronisationszeit – ein um 8 h versetzter
  Arbeitstag wurde z. B. mit Dauer 0 erfasst. Der Client sendet nun die echte
  lokale Ereigniszeit (`event_time`), die der Server verwendet (mit Plausibilitäts-
  Grenzen). Online-Buchungen verhalten sich unverändert.
- **Robustheit:** Eine `start_work`-Buchung, deren Intervall sich mit einer
  vorhandenen Buchung überschneidet, liefert jetzt eine saubere, endgültige
  Fehlerantwort statt eines HTTP 500 (das ein Offline-Client endlos wiederholt
  hätte).

### Unverändert / kompatibel

- Normale Browser-Formular-POSTs (`Accept: text/html`) erhalten weiterhin die
  klassische 303-Weiterleitung – die Desktop-Web-Oberfläche ist nicht betroffen.
- CSRF-Schutz, Datenmodell und Geschäftslogik bleiben unverändert.

### Grund der Versionsanhebung

Minor (`0.4.0` → `0.5.0`): überarbeitete Offline-Synchronisations-Engine inkl.
neuem JSON-Sync-Vertrag und client-seitigen Ereigniszeitstempeln.

## [0.4.0] – 2026-06-11

### Added

- **Konsolen-Benutzerverwaltung (`app/manage.py`):** Neues CLI-Werkzeug zur
  Administration ohne Web-Oberfläche – ideal für Notfälle (z. B. verlorener
  Admin-Zugang) und Erstinbetriebnahme.
  - `list-users` – alle Benutzer auflisten (ID, Benutzername, Name, E-Mail,
    Gruppe, Admin, Passwortwechsel-Flag).
  - `list-groups` – Gruppen inkl. Admin-Kennzeichen auflisten.
  - `create-user` – Benutzer anlegen (Passwort interaktiv, per `--password`
    oder `--random`; Gruppenzuordnung per ID/Name; `--weekly-hours`;
    `--no-force-change`).
  - `reset-password` – Passwort per `--username` oder `--id` zurücksetzen
    (interaktiv, `--password` oder `--random`; `--force-change/--no-force-change`).
  - Aufruf im Container: `docker exec -it erfassung python -m app.manage <befehl>`.
  - Nutzt dieselbe DB (`DATABASE_URL`), Passwort-Hashing (PBKDF2) und
    Stärke-Prüfung wie die Web-App; PIN-Vergabe erfolgt automatisch.
- **README:** Abschnitt „Benutzerverwaltung über die Konsole (CLI)" mit Anleitung
  und Beispielen ergänzt.

### Grund der Versionsanhebung

Minor (`0.3.8` → `0.4.0`): additive neue Funktionalität (Administrations-CLI). Keine
Änderung an bestehender Web-/Geschäftslogik, am Datenmodell oder an Endpunkten.

## [0.3.8] – 2026-06-11

### Fixed

- **Anmeldung mit „403 – Ungültige Sitzung" repariert (zwei zusammenhängende
  Fehler in der CSRF-Absicherung):**
  1. **Middleware-Reihenfolge:** Starlette wendet Middleware in umgekehrter
     Registrierungsreihenfolge an – die zuletzt registrierte läuft *außen*. Die
     `CSRFMiddleware` war nach der `SessionMiddleware` registriert und lief damit
     *vor* ihr. Beim CSRF-Check war die Session daher noch nicht geladen
     (`scope["session"]` fehlte), sodass **jeder** POST – inklusive `/login` –
     mit `403` abgewiesen wurde. Reihenfolge korrigiert (CSRF zuerst, Session
     zuletzt registriert ⇒ Session läuft außen).
  2. **Request-Body wurde verbraucht:** Die `CSRFMiddleware` (vormals
     `BaseHTTPMiddleware`) las das Formular per `await request.form()`, wodurch
     der Body-Stream geleert wurde und der `/login`-Handler keine Felder mehr
     erhielt (`422 Field required`). Die Middleware ist nun eine **reine
     ASGI-Middleware**, die den Body puffert und über ein frisches
     `receive`-Callable an die Anwendung **weiterreicht**.
  Ergebnis: Anmeldung funktioniert wieder; falsche Zugangsdaten liefern wieder
  die reguläre Fehlermeldung (HTTP 400) statt eines 403, und fehlende/ungültige
  CSRF-Token werden weiterhin korrekt mit 403 abgelehnt.

### Grund der Versionsanhebung

Patch (`0.3.7` → `0.3.8`): Behebung eines kritischen Fehlers, der die Anmeldung
vollständig blockierte. Keine Änderung an Datenmodell oder Geschäftslogik.

## [0.3.7] – 2026-06-11

### Fixed

- **Docker-Image in Portainer deploybar (behebt „error 500" beim Deploy):**
  Der Build (`docker/build-push-action@v6`) hängte standardmäßig
  Provenance-/SBOM-Attestations an das Image. Dadurch wurde das Image als
  **OCI Image Index** veröffentlicht, der zusätzlich ein Attestation-Manifest mit
  `platform: unknown/unknown` enthält. Dieser Zusatz-Eintrag bringt Portainer und
  ältere Docker-/Registry-Tooling beim Deploy zum Fehler („no matching manifest" /
  HTTP 500). Der Workflow erzeugt nun mit `provenance: false`, `sbom: false` und
  explizitem `platforms: linux/amd64` ein **schlankes Single-Platform-Manifest**
  (identisch zu `docker build && docker push`). Das Image `:0.3.7` ist damit ohne
  Sonderbehandlung deploybar.

### Grund der Versionsanhebung

Patch (`0.3.6` → `0.3.7`): reiner Build-/Auslieferungs-Fix. Es wurde kein
Anwendungscode geändert. Eigene Version (statt Überschreiben von `0.3.6`), damit
Portainer/Docker garantiert ein frisches, sauberes Manifest ziehen und kein zuvor
gecachter `0.3.6`-Index verwendet wird.

## [0.3.6] – 2026-06-11

### Hintergrund

Die mobile Oberfläche (`/mobile`) ist bereits seit `0.3.5` eine offline-first PWA
(Service Worker, IndexedDB-Datenhaltung, Offline-Aktionsqueue mit Idempotenz und
Reconnect-Synchronisation). Mit `0.3.6` wird diese PWA produktionshärtend
vervollständigt – minimal-invasiv, ohne Eingriff in die Business-Logik.

### Changed / Fixed

- **Automatische Service-Worker-Versionierung (behebt Stale-Cache-Risiko):**
  Der Cache-Name in `static/sw.js` war fest auf `erfassung-mobile-v0.3.5`
  verdrahtet. Wurde `VERSION` erhöht, ohne die Datei manuell anzupassen, blieb der
  alte Cache aktiv und Clients konnten auf veralteten Assets „hängen bleiben".
  Der Cache-Name wird nun zur Laufzeit aus dem `?v=`-Parameter der
  SW-Registrierung abgeleitet (`new URLSearchParams(self.location.search)`), der
  wiederum aus `app_version` / `VERSION` stammt. Damit erzeugt jede Versionsanhebung
  automatisch einen neuen Cache; der alte wird beim `activate`-Event entfernt.
- **`static/app.js`** registriert den Service Worker jetzt mit der aus
  `import.meta.url` (`?v=…`) ermittelten Version statt mit einer hartcodierten
  Versionsnummer (`?v=0.3.5`).

### Added

- **Manifest vervollständigt** (`static/manifest.webmanifest`): Felder `id`
  (`"/mobile"`), `dir` (`"ltr"`) und `categories` (`["business", "productivity"]`)
  ergänzt. Das verbessert die eindeutige App-Identität (Installierbarkeit/Updates)
  und die Einordnung bei App-Store-/Launcher-Integrationen.
- **Dokumentation:** README um Abschnitte „Updates & Service-Worker-Versionierung"
  und „Installierbarkeit" erweitert; Versionsangabe von `0.1.7` auf `0.3.6`
  korrigiert. Diese Changelog-Datei sowie Release Notes
  (`docs/RELEASE_NOTES_0.3.6.md`) neu angelegt.

### Grund der Versionsanhebung

Patch-Release (`0.3.5` → `0.3.6`): Es handelt sich um Härtung und Vervollständigung
einer bestehenden Funktion (PWA/Offline), nicht um eine neue, brechende oder
umfangreiche Feature-Erweiterung. Es wurden keine bestehenden Endpunkte, Datenmodelle
oder die Business-Logik verändert.

## [0.3.5]

- Offline-first-PWA-Architektur der mobilen Oberfläche (Service Worker,
  IndexedDB, Offline-Queue mit `client_action_id`-Idempotenz,
  Reconnect-Synchronisation, Konfliktbehandlung per State-Replay).

## [0.3.4]

- Fix: HTTP-500 bei `/mobile/sync-data` behoben.

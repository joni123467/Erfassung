# Release Notes 0.17.0

Nimmt sich die fachlichen Punkte vor, die 0.16.0 zwar angefasst, aber nicht
zu Ende gebracht hat: Der Ausgleich nach § 3 ArbZG bekommt einen tragfähigen
Nenner und Fristen je Überschreitungstag, die arbeitsrechtliche Bewertung ein
eigenes Recht und eine unveränderliche Historie, Sonn- und Feiertagsausnahmen
eine echte Prüfung, `Time.Edit` seine Grenze gegenüber dem Importpfad, und die
Betriebszeitzone einen dauerhaften, nachvollziehbaren Platz.

> **Keine rechtliche Garantie.** Es gilt unverändert, was in
> [`RELEASE_NOTES_0.14.0.md`](RELEASE_NOTES_0.14.0.md) steht: Die Umsetzung
> erfüllt technische Anforderungen, ist nicht zertifiziert und ersetzt keine
> Rechtsberatung. In Betrieben mit Betriebsrat ist die Einführung nach
> § 87 Abs. 1 Nr. 6 BetrVG mitbestimmungspflichtig.

## 1. Der Ausgleich nach § 3 ArbZG rechnete mit dem falschen Nenner

§ 3 Satz 2 ArbZG erlaubt zehn Stunden werktäglich, „wenn innerhalb von sechs
Kalendermonaten oder innerhalb von 24 Wochen im Durchschnitt acht Stunden
werktäglich nicht überschritten werden". Der Bezugspunkt ist der **Werktag** –
und Werktage sind Montag bis Samstag, unabhängig davon, ob an ihnen gearbeitet
wurde.

0.16.0 mittelte über die **Tage mit Buchungen**. Wer an vier Tagen je zehn
Stunden arbeitete und sonst frei hatte, kam damit auf einen Durchschnitt von
zehn Stunden und galt als überfällig – obwohl er über den Zeitraum weit unter
acht Stunden werktäglich lag. Die Anwendung meldete einen Verstoß, den es
nicht gab.

Die Rechnung liegt jetzt in einem eigenen Modul, `app/compensation.py`, und
zählt jeden Werktag des Fensters:

| | 0.16.0 | 0.17.0 |
|---|---|---|
| Nenner | Tage mit Buchungen | Werktage (Mo–Sa) des Zeitraums |
| Sonntage | zählten mit, wenn gebucht | nie im Nenner |
| Feiertage, Urlaub, Ersatzruhetage | zählten mit | konfigurierbar ausgenommen |
| Herleitung | eine Zahl | `describe()` nennt Zeitraum, Nenner, Schnitt und jede Ausnahme |

**Ausfalltage.** Das Gesetz sagt nicht, wie Feiertage, Urlaub oder
Ersatzruhetage im Nenner zu behandeln sind. Die Vorgabe nimmt sie heraus –
keiner von ihnen soll Mehrarbeit ausgleichen –, und die Einstellung ist unter
*Administration → System → Einstellungen* umschaltbar. Die getroffene Wahl
steht im Bericht, sie wird nicht stillschweigend angewendet.

**Offene Entscheidung: Krankheitstage.** Sie werden nicht ausgenommen, weil
die Anwendung keine Arbeitsunfähigkeit erfasst. Das ist keine fachliche
Festlegung, sondern eine fehlende Datenquelle; die Einstellung dazu ist
vorhanden und dokumentiert, aber ohne Wirkung. Wer Krankheitstage
berücksichtigen will, braucht zuerst ein Modell dafür.

## 2. Ausgleichsfristen hängen jetzt am Überschreitungstag

Bis 0.16.0 gab es eine Gesamtbetrachtung mit einer Restlaufzeit, die
rechnerisch immer null war: Das rollierende Fenster ist stets gleich lang,
also blieb nie etwas übrig. Aus „der Durchschnitt liegt über acht Stunden"
ließ sich nicht ablesen, **was** bis **wann** auszugleichen ist.

Jeder Tag über acht Stunden ist jetzt ein eigener Vorgang mit eigenem Fenster
und eigener Frist (`CompensationCase`). Ein einzelner Zehnstundentag ist damit
**ausgleichspflichtig**, aber nicht sofort überfällig – überfällig wird er
erst, wenn seine Frist verstrichen ist, ohne dass die zwei Stunden abgebaut
wurden. Drei Kennzeichnungen unterscheiden das:

- `compensation_required` – Ausgleich nötig, Frist läuft.
- `compensation_due` – die Frist läuft ab, der Überhang steht noch.
- `compensation_overdue` – die Frist ist verstrichen.

**Zuordnungsregel (FIFO, ausdrücklich festgelegt).** Freie Kapazität eines
Werktags – die Minuten, um die er unter acht Stunden bleibt – wird dem
**ältesten** noch offenen Vorgang zugeschlagen, dessen Fenster den Tag umfasst.
Das Gesetz schreibt keine Reihenfolge vor. FIFO ist die für die Beschäftigten
günstigere: Der älteste Vorgang hat die kürzeste Restlaufzeit; würde zuerst der
jüngste bedient, liefe der älteste ab, obwohl Ausgleich stattgefunden hat.

Blockiert oder gekürzt wird nie etwas. Die geleistete Arbeitszeit bleibt
unverändert gespeichert.

## 3. Neues Recht `Time.Compliance.Manage`

`Time.View` genügte, um die arbeitsrechtliche Bewertung zu **verändern**: einen
Verstoß einzuordnen, eine Ausnahme zu begründen, einen Ersatzruhetag
einzutragen. Das sind Entscheidungen des Arbeitgebers – sie gehören nicht in
ein Leserecht.

- **`Time.View`** ist ab jetzt ausschließlich ein Leserecht: Zeitkonten,
  Berichte, Exporte, Regelverstöße und deren Historie einsehen.
- **`Time.Compliance.Manage`** (scoped) ist nötig, um Verstöße einzuordnen,
  Sonn-/Feiertagsausnahmen zu begründen, Ersatzruhetage einzutragen oder zu
  ändern und Ausgleichsdokumentationen zu bearbeiten.

Beide Hürden gelten: das Recht **und** der Geltungsbereich auf die betroffene
Person. Ein direkter `POST` ohne beides liefert **403** und schreibt einen
Security- **und** einen Audit-Eintrag. Auf der Übersichtsseite verschwinden die
Formulare ganz, wenn das Recht fehlt – der Server prüft trotzdem noch einmal.

Systemrollen (Administrator, Superadministrator) bekommen das Recht beim
Start automatisch. Eigene Rollen bleiben unangetastet: Wer es vergeben will,
entscheidet das bewusst.

## 4. Sonn- und Feiertagsausnahmen werden geprüft

Sonntagsarbeit ist nicht verboten, sondern erlaubnispflichtig (§§ 9–11 ArbZG).
Ob eine Ausnahme greift, kann die Anwendung nicht entscheiden – aber sie kann
prüfen, ob die Angabe in sich stimmig ist. Bis 0.16.0 tat sie das nicht.

**Pflichtfelder je Bearbeitungsstand:**

| Stand | verlangt |
|---|---|
| Offen | – |
| Begründet | Ausnahmegrund **und** Rechts-/Betriebsgrundlage |
| Ersatzruhetag gewährt | zusätzlich den Ersatzruhetag |
| Kein Ersatzruhetag nötig | eine Begründung |

Der letzte Fall verlangt bewusst eine Begründung: Die Behauptung, § 11 Abs. 3
greife nicht, ist die weitreichendste von allen und darf nicht unbegründet
dastehen.

**Prüfungen des Ersatzruhetags** (§ 11 Abs. 3 ArbZG, „innerhalb eines den
Beschäftigungstag einschließenden Zeitraums von …"):

- nicht **vor** dem Arbeitstag – ein Ruhetag, der vorher lag, ersetzt nichts;
- **innerhalb der Frist**: zwei Wochen bei Sonntagsarbeit, acht Wochen bei
  einem auf einen Werktag fallenden Feiertag;
- **kein Sonntag und kein Feiertag** – beide sind ohnehin frei;
- **nicht doppelt verwendet** – ein Tag gleicht genau eine Beschäftigung aus.

Feiertage kommen dabei ausschließlich aus der zentralen Region des eigenen
Unternehmens. Ein Kundenstandort ändert den Feiertagskalender nicht.

Verstößt eine Eingabe gegen eine dieser Regeln, wird sie abgelehnt und der
konkrete Grund im Klartext angezeigt – nicht eine pauschale Fehlermeldung.

**Was die Anwendung weiterhin nicht kann:** Ausnahmen nach § 7 oder § 14 ArbZG,
Tarifverträge und behördliche Bewilligungen sind nicht maschinell entscheidbar.
Sie werden dokumentiert, nicht bewertet.

## 5. Die Bewertung hat jetzt eine unveränderliche Historie

Ausnahmegrund, Rechtsgrundlage, Ersatzruhetag und Bearbeitungsstand wurden an
der Feststellung **überschrieben**. Wer eine Begründung nachträglich
austauschte, hinterließ keine Spur – bei einer arbeitsrechtlichen Bewertung
genau das falsche Verhalten.

Neue Tabelle `compliance_logs`, **append-only**: Über die Anwendung gibt es
keinen Weg, einen Eintrag zu ändern oder zu löschen. Festgehalten werden
Vorgang, Zeitpunkt, bearbeitende Person, Quelle, Begründung sowie der
Vorher- und Nachher-Stand als JSON.

Protokollierte Vorgänge: `detected`, `changed`, `resolved`, `reopened`,
`acknowledged`, `exception_documented`, `rest_day_set`,
`compensation_assigned`, `migrated`.

Die Historie ist unter *Administration → Regelverstöße → Bewertungshistorie*
einsehbar (Leserecht `Time.View` im passenden Geltungsbereich, mit
Zugriffsprotokoll) und Teil der Auskunft nach Art. 15 DSGVO: Wer eine
Sonntagsarbeit als zulässig eingestuft hat und worauf er sich dabei berief,
gehört zu den Daten über diese Person.

**Bestand.** Migration 20 schreibt je vorhandener Feststellung genau einen
`migrated`-Vermerk. Er behauptet nicht, die frühere Historie zu kennen – er
hält den Stand bei der Umstellung fest und macht sichtbar, ab wann die
Historie lückenlos ist.

## 6. `Time.Edit` ist ein Korrekturrecht, kein Importrecht

Bis 0.16.0 lief die Verwaltung über dasselbe vollständige Eingabeschema wie der
Terminalimport. Wer fremde Buchungen korrigieren durfte, konnte damit `source`,
`external_id` und die UTC-Originalstempel frei setzen – eine von Hand angelegte
Buchung ließ sich als Terminalstempelung ausgeben. Die Herkunft ist bei einer
Prüfung das erste, worauf man schaut.

Neues Schema `AdministrativeTimeEntryCreate` für `POST /api/time-entries` bei
fremden Personen:

| Feld | Verwaltung (`Time.Edit`) | interner Terminal-/Importpfad |
|---|---|---|
| `status`, `is_manual` | setzbar | setzbar |
| `source` | fest `admin` | frei |
| `external_id` | immer leer | frei |
| `started_at_utc`, `ended_at_utc`, `tz_name` | vom Server aus Ortszeit und Betriebszeitzone | frei |

Ein Ausschluss per Positivliste hält länger als einer per Negativliste: Was im
Schema nicht steht, kann auch nicht versehentlich durchgereicht werden – wie
schon bei `SelfServiceTimeEntryCreate` seit 0.16.0.

Der Terminalimport ruft `crud.create_time_entry` direkt auf und ist davon nicht
berührt. An der Treiberarchitektur ändert sich nichts; es gibt weiterhin keine
terminaltyp-spezifische Routing- oder UI-Logik.

## 7. Die Betriebszeitzone wird gespeichert und protokolliert

Sie stand nur in `ERFASSUNG_TIMEZONE` – weder gespeichert noch ihre Änderung
nachvollziehbar. Dabei entscheidet sie, welchem Kalendertag eine Buchung
zugerechnet wird, und damit über jede Tages-, Wochen- und Ausgleichsauswertung.

- Neu in der Systemkonfiguration im **config-Volume**, einstellbar unter
  *Administration → System → Einstellungen*.
- Reihenfolge: gespeicherte Konfiguration → `ERFASSUNG_TIMEZONE` → Vorgabe
  `Europe/Berlin`. Die Umgebungsvariable ist damit nur noch eine Vorbelegung
  bei der **Erstinstallation** – wie bei der Datenbankkonfiguration.
- Geprüft über `zoneinfo`, nicht über eine gepflegte Liste; eine unbekannte
  Zone wird abgelehnt, die bisherige bleibt bestehen, und die Ablehnung steht
  im Audit-Protokoll.
- Jede Änderung wird auditiert – mit altem und neuem Wert.

**Eine Änderung wirkt ausschließlich auf neue Buchungen.** Bestehende tragen
ihr `tz_name` mit sich und werden nicht umgeschrieben; sonst verschöben sich
vergangene Zeiten rückwirkend. Der Hinweis steht auch im Formular.

Ebenfalls neu im Formular und ebenfalls auditiert: der Ausgleichszeitraum in
Wochen (4–26, Vorgabe 24) und die Behandlung der Ausfalltage. Nebenbei
behoben: Das Speichern setzte bislang jeden Wert zurück, den das Formular nicht
selbst mitschickte.

## Upgrade

Aus **0.14.2**, **0.15.0** und **0.16.0** geprüft. Beide Wege richten das
Schema ein – die versionierte Migration 20 und `ensure_schema()`.

- **Migration 20** legt `compliance_logs` an und schreibt die
  Bestandsvermerke. Idempotent (Tabelle mit `checkfirst`, Vermerk nur ohne
  vorhandenen Eintrag), datenerhaltend, portabel über SQLite, MySQL/MariaDB
  und PostgreSQL – der Zeitstempel kommt als Parameter, nicht als
  dialektabhängige Zeitfunktion.
- **Keine Migration nötig** für die neuen Konfigurationswerte: Sie liegen im
  config-Volume und bekommen beim ersten Laden ihre Vorgaben.
- **Neues Recht.** Systemrollen synchronisieren sich beim Start; eigene Rollen
  bleiben unverändert. Wer bisher mit `Time.View` Verstöße eingeordnet hat,
  braucht jetzt zusätzlich `Time.Compliance.Manage`.
- **Volumes** bleiben getrennt: Konfiguration im config-Volume, Geschäftsdaten
  im data-Volume, Protokolle im logs-Volume. Pfade ausschließlich über
  `app/paths.py`.
- Sicherung und Rücksicherung, Offline-PWA, Terminalimport und Exporte laufen
  unverändert.

## Datenschutz

Unverändert: keine Passwörter, PINs, Tokens, API-Schlüssel oder exakten
Standortdaten in Protokollen, keine dauerhafte GPS-Ortung und keine
Bewegungsprofile. Die Compliance-Historie erweitert die Auskunft nach Art. 15
DSGVO um die arbeitsrechtliche Bewertung samt Verlauf.

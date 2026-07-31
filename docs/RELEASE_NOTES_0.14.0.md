# Release Notes 0.14.0 – Revisionssichere Arbeitszeiterfassung

Dieses Release richtet die Erfassung an ArbZG, ArbSchG, MiLoG und DSGVO aus.
Der Grundsatz, aus dem sich fast alles Weitere ergibt:

> **Die tatsächlich geleistete Arbeitszeit wird immer gespeichert, und nichts
> verschwindet.**

## Keine rechtliche Garantie

Diese Software setzt technische Anforderungen um. Sie ist **nicht** zertifiziert
und ersetzt keine Rechtsberatung. Ob eine konkrete Nutzung den gesetzlichen
Pflichten genügt, hängt von Tarifverträgen, Betriebsvereinbarungen, der
Arbeitsorganisation und dem Betrieb der Anlage ab. Insbesondere:

- Ausnahmen nach §7 und §10 ArbZG, Bereitschaftsdienste und Tariföffnungen kann
  eine Software nicht bewerten. Sie kennzeichnet Auffälligkeiten; entscheiden
  müssen Menschen.
- Revisionssicherheit endet an der Anwendungsgrenze. Wer direkten Datenbank-
  oder Dateizugriff hat, kann Einträge verändern. Dagegen helfen Rechte-,
  Backup- und Betriebsmaßnahmen, keine Anwendungslogik.
- Nach **§87 Abs. 1 Nr. 6 BetrVG** ist die Einführung einer Zeiterfassung in
  Betrieben mit Betriebsrat mitbestimmungspflichtig. Das Zugriffsprotokoll
  dieses Release ist eine technische Einrichtung im Sinne der Vorschrift.

## 1. Revisionssicherheit

Jede Anlage, Änderung, Freigabe, Ablehnung und Stornierung landet in
`time_entry_revisions` – mit **Vorher- und Nachher-Stand**, Zeitpunkt (UTC),
Bearbeiter, Quelle und Begründung. Einträge dieser Tabelle werden nie geändert
oder gelöscht.

| Vorgang | Begründung |
|---|---|
| Anlegen | nicht nötig |
| Ändern | **Pflicht** |
| Freigeben | nicht nötig |
| Ablehnen | **Pflicht** |
| Stornieren | **Pflicht** |

Fehlt eine Pflichtbegründung, wird der Vorgang **abgelehnt** – lieber das als
eine Historie, in der „wurde geändert" steht und sonst nichts.

**Korrektur = Storno + Ersatzbuchung.** `crud.replace_time_entry()` storniert
das Original und legt die Ersatzbuchung an; beide verweisen aufeinander
(`replaced_by_id` / `replaces_id`). Das Original bleibt vollständig sichtbar.

**Löschen gibt es nicht mehr.** `crud.delete_time_entry()` storniert. Auch die
Pfade, die bisher still Buchungen entfernten, stornieren jetzt: das
Überschreiben kollidierender Buchungen und der Nachtrag, der eine Buchung
vollständig abdeckt.

Die Historie steht unter *Administration → Buchung bearbeiten → Historie*
(`/admin/time-entries/<id>/history`).

## 2. Pausen

Pausen liegen jetzt als **einzelne Intervalle** mit Beginn und Ende in
`break_intervals`. Bis 0.13.x gab es nur eine Summe – damit ließ sich nicht
nachweisen, *wann* eine Pause lag.

Die Grenzen sind korrigiert:

| Anwesenheit | Mindestpause |
|---|---|
| bis einschließlich 6:00 Std | keine |
| **mehr als** 6 Std | 30 Minuten |
| **mehr als** 9 Std | 45 Minuten |

Bis 0.13.x verlangte die Anwendung schon *ab* sechs Stunden eine Pause – bei
glatt sechs Stunden also zu früh. Ein Pausenabschnitt zählt als Ruhepause erst
**ab 15 Minuten**; kürzere Unterbrechungen werden gespeichert und von der
Arbeitszeit abgezogen, erfüllen die Pausenpflicht aber nicht.

**Eine nicht genommene Pause wird nicht mehr als genommen verbucht.** Das ist
die wichtigste Verhaltensänderung: Wer neun Stunden ohne Pause arbeitet, hat
neun Stunden gearbeitet. Der Fehlbetrag erscheint als Kennzeichnung.

### Was das für Bestandsdaten heißt

Die alte Rechnung zog die gesetzliche Pause auch dann ab, wenn sie nicht
gestempelt war. Würde die neue Regel rückwirkend gelten, änderten sich
abgerechnete Monate. Deshalb trägt **jede Buchung ihre Regel bei sich**
(`break_rule`):

- Bestandsbuchungen: `legacy_auto` – rechnen exakt wie bisher.
- Neue Buchungen: `actual`.

## 3. Regelverstöße: kennzeichnen, nicht verhindern

Geprüft werden mehr als 8 Stunden (§3, Hinweis), mehr als 10 Stunden (§3,
kritisch), fehlende Ruhepause (§4), Ruhezeit unter 11 Stunden (§5) sowie Sonn-
und Feiertagsarbeit (§9). Die Kennzeichnungen stehen in `compliance_flags` und
unter *Administration → Regelverstöße*.

Eine Kennzeichnung **blockiert nichts**. Die Buchung wird gespeichert wie
gestempelt. Alles andere würde den Nachweis verfälschen – und genau den
verlangen §16 Abs. 2 ArbZG und §17 MiLoG.

Eine Kennzeichnung lässt sich mit Pflichtbegründung **einordnen**; der Verstoß
selbst bleibt für jede Prüfung erhalten. Stornierte Buchungen lösen keine
Verstöße aus.

## 4. Abschluss- und Korrekturworkflow

Abrechnungsperioden (`payroll_periods`) durchlaufen vier Zustände:

**offen** → **Mitarbeiterprüfung** → **freigegeben** → **gesperrt**

In der Mitarbeiterprüfung bestätigt jede Person ihre Zeiten oder widerspricht –
ein Widerspruch **braucht** eine Begründung, der Arbeitgeber antwortet darauf.
Erst die **Sperre** macht Buchungen des Zeitraums unveränderlich: Jeder Versuch,
darin zu ändern, zu stornieren oder neu anzulegen, wird abgewiesen.

Zwischen Freigabe und Sperre liegt bewusst ein Schritt: Wer sofort sperrt, macht
jede berechtigte Nachfrage unmöglich; wer nie sperrt, hat keinen Abschluss. Das
Aufheben einer Sperre ist möglich, braucht eine Begründung und bleibt an der
Periode vermerkt.

Verwaltung unter *Administration → Abrechnungsperioden*.

## 5. Datenschutz

**Zugriffsprotokoll** (`data_access_log`): Lesezugriffe auf **fremde**
Zeitdaten werden protokolliert – wer, wessen Daten, wann, wofür. Die eigenen
Daten einzusehen erzeugt keinen Eintrag; sonst bestünde das Protokoll aus
Rauschen. Bewusst **ohne IP-Adresse**: für den Zweck nicht erforderlich.

**Aufbewahrungsfristen** sind einstellbar (`config/retention.json`), mit
Vorgaben an den Mindestfristen (24 Monate für Buchungen nach §16 ArbZG /
§17 MiLoG, 12 Monate für das Zugriffsprotokoll). **Gelöscht wird nichts
automatisch** – eine Zeiterfassung, die von sich aus Daten entfernt, kann einen
Nachweis vernichten, den jemand noch braucht. `privacy.retention_report()`
zeigt, was die Frist überschritten hat; die Entscheidung bleibt bei Menschen.
Nur das Zugriffsprotokoll lässt sich auf Wunsch bereinigen.

**Auskunftsexport** nach Art. 15 DSGVO: `/api/me/export` liefert die eigenen
Daten, `/admin/users/<id>/export` den Prüfexport (protokolliert). Enthalten
sind Stammdaten, Buchungen, Pausenintervalle, vollständige Änderungshistorie,
Kennzeichnungen, Urlaub **und die Zugriffe auf diese Daten**.

RBAC bleibt unverändert: Rollen und Geltungsbereiche entscheiden weiterhin,
wer was sieht.

## 6. Standorte und Ortung

Standorte gehören zu genau einer Firma – unverändert seit 0.13.1.

**Es gibt keine GPS-Ortung und keine Bewegungsprofile**, und dieses Release
führt auch keine ein. Das ist eine bewusste Entscheidung: Standortüberwachung
von Beschäftigten ist mitbestimmungspflichtig und macht aus einer
Zeiterfassung ein Kontrollinstrument. Der Einsatzort ist die **Angabe der
Person**, nicht eine Messung.

Sollte Geofencing später gewünscht sein, wäre die Vorgabe: Standort nur beim
bewussten Stempeln prüfen und dauerhaft **nur das Prüfergebnis** speichern
(„innerhalb"/„außerhalb"), nie die Koordinaten.

## 7. Zeitstempel und Nachtarbeit

Neue Buchungen tragen zusätzlich `started_at_utc`, `ended_at_utc` und
`tz_name` (z. B. `Europe/Berlin`, einstellbar über `ERFASSUNG_TIMEZONE`).
Ortszeit bleibt für Anzeige und Auswertung führend; die UTC-Stempel machen die
Angabe eindeutig – etwa in der Nacht der Zeitumstellung, in der eine Ortszeit
zweimal vorkommt.

Bestandsbuchungen bleiben ohne UTC-Stempel. Sie werden **nicht** nachträglich
umgerechnet: Ohne bekannte Zeitzone der Vergangenheit wäre jede Umrechnung eine
Behauptung.

Nachtarbeit über Mitternacht wird wie bisher korrekt gerechnet (Ende vor
Beginn ⇒ Folgetag) und ist jetzt zusätzlich durch Tests abgesichert.

## 8. Verträglichkeit

- **Bestandsdaten**: unverändert lesbar, unveränderte Rechnung (`legacy_auto`).
- **Backups und Cross-Database-Restore**: Der logische Export läuft über
  `Base.metadata`; die neuen Tabellen sind automatisch enthalten. Ein Test
  sichert das ab.
- **Offline-PWA**: unverändert. Pausen aus der Warteschlange erzeugen
  Intervalle.
- **Terminalimporte**: laufen ohne Bearbeiter; die Historie hält „System" und
  die Quelle fest. Die Idempotenz über `source`/`external_id` bleibt.
- **Exporte und Auswertungen**: unverändert.
- **SQLite, MySQL, MariaDB, PostgreSQL**: portables DDL, keine
  dialektspezifischen Typen.

## Datenbank

Migration **17** (`_add_compliance_and_revisions`), in beiden Mechanismen
gepflegt. Neue Tabellen: `break_intervals`, `time_entry_revisions`,
`compliance_flags`, `payroll_periods`, `period_confirmations`,
`data_access_log`. Neue Spalten an `time_entries`: `started_at_utc`,
`ended_at_utc`, `tz_name`, `break_rule`, `cancelled_at`, `cancelled_by_id`,
`cancel_reason`, `replaced_by_id`, `replaces_id`.

Die Migration ist idempotent und datenerhaltend. Sie setzt Bestandsbuchungen
auf `legacy_auto`, überführt eine laufende Pause in ein Intervall und legt für
jede vorhandene Buchung einen Anlagevermerk an, damit die Historie lückenlos
bei der Bestandsaufnahme beginnt.

## Nebenbefunde

Beim Umbau aufgefallen und mit behoben:

- `total_break_minutes` und `auto_break_enabled` lösten auf einer von ihrer
  Sitzung gelösten Buchung eine Ausnahme aus (Lazy Load). Beide prüfen jetzt
  vorher.
- Stornierte Buchungen blockierten die Überschneidungsprüfung. Sie zählen nicht
  mehr und belegen deshalb auch keinen Zeitraum.

## Tests

`tests/test_v0140.py` – 42 Tests: Migration gegen eine 0.13.x-Datenbank samt
Datenerhalt, unveränderte Rechnung für Bestandsbuchungen, Pausengrenzen
(parametrisiert um 6 und 9 Stunden), Mindestabschnitt, einzelne Intervalle,
nicht verbuchte Pausen, Nachtarbeit, UTC-Stempel und Zeitzone, alle fünf
Verstoßarten samt Nachweis der gespeicherten Zeit, Revisionshistorie mit
Vorher/Nachher, Pflichtbegründung, Storno statt Löschen, Storno plus
Ersatzbuchung, gesperrte Periode, Bestätigung und Widerspruch,
Zugriffsprotokoll (fremd ja, eigen nein), Auskunftsexport, Aufbewahrungs­
fristen, Berechtigungen, Offline-Synchronisation, Terminalimport samt
Idempotenz und der logische Export der neuen Tabellen.

Angepasst wurden Tests, die das alte Verhalten festhielten: Änderungen brauchen
jetzt eine Begründung, und verdrängte Buchungen werden storniert statt
gelöscht.

Die gesamte Suite läuft mit **495 Tests** grün durch.

Nebenbei ist dabei ein Problem der Testinfrastruktur aufgefallen: Jeder Test
lädt die Anwendung frisch und legt dabei eine eigene Engine an, deren
Verbindungspool bisher offen blieb. Über die volle Suite lief der Prozess
dadurch in das Limit für offene Dateien – und zwar erst beim Aufräumen am
Ende, sodass pytest gar keine Zusammenfassung mehr schrieb. Ein grüner Lauf
war so nicht von einem roten zu unterscheiden. `tests/conftest.py` schließt
den Pool jetzt nach jedem Test; an der Anwendung ändert das nichts.

# AGENTS.md – Leitfaden für Entwicklungsagenten

Dieser Leitfaden gilt für alle automatisierten Änderungen an diesem
Repository. Er ergänzt `README.md` und `CHANGELOG.md`.

## Projektüberblick

- FastAPI-Anwendung (`app/`), Jinja2-Templates (`templates/`),
  statische Assets inkl. Offline-PWA (`static/`).
- SQLite-Datenbank (`erfassung.db`), SQLAlchemy-Modelle in `app/models.py`.
- Versionsquelle ist ausschließlich die Datei `VERSION` im Repo-Root;
  `app/__init__.py` liest sie und versorgt FastAPI (`version=`), Footer,
  Health-API und Asset-Cache-Busting (`?v=`). Bei Releases nur `VERSION`
  und `CHANGELOG.md` pflegen – nirgendwo Versionsnummern hartkodieren.

## Datenbankschema prüfen (verpflichtend)

Bei **jeder** Änderung analysieren, ob sie das Datenbankschema berührt:

- neue Felder (Spalten)
- neue Tabellen
- geänderte Datentypen
- neue Beziehungen (Foreign Keys)
- neue Indizes (inkl. Unique-Indizes)

Berührt eine Änderung `app/models.py`, ist IMMER ein Migrationspfad
erforderlich (siehe unten). `Base.metadata.create_all()` legt nur fehlende
Tabellen an – **keine** fehlenden Spalten in bestehenden Tabellen.

## Migrationen

Es gibt zwei Mechanismen, die beide gepflegt werden müssen:

1. **`app/main.py` → `ensure_schema()`**
   Läuft bei jedem Anwendungsstart. Ergänzt fehlende Spalten/Indizes per
   `ALTER TABLE` idempotent (erst `PRAGMA table_info` prüfen, dann ändern).
   Neue Spalten hier mit sinnvollem `DEFAULT` hinzufügen, damit bestehende
   Zeilen sofort gültige Werte haben.

2. **`app/db_migrations.py` → `MIGRATIONS`**
   Versionierter Runner auf Basis von `PRAGMA user_version`. Für jede
   Schemaänderung einen neuen Eintrag `(n, funktion)` mit der nächsten
   freien Nummer anhängen. Bestehende Einträge niemals ändern oder
   umnummerieren. Downgrades werden nicht unterstützt – Migrationen müssen
   deshalb vorwärts immer sicher sein.

### Anforderungen an jede Migration

- **idempotent**: mehrfaches Ausführen darf nichts beschädigen
  (Spalten-/Tabellen-/Index-Existenz vorher prüfen).
- **datenerhaltend**: bestehende Daten dürfen nie verloren gehen.
- **fehlende Spalten automatisch ergänzen** (`ALTER TABLE … ADD COLUMN`
  mit Default + `UPDATE … WHERE … IS NULL` als Absicherung).
- **fehlende Tabellen automatisch anlegen** (über `create_all` bzw.
  explizites `CREATE TABLE IF NOT EXISTS`).
- **Verhalten erhalten**: Defaults so wählen, dass sich das Verhalten für
  Bestandsdaten nicht ändert (Beispiel: `auto_break_deduction DEFAULT 1`,
  damit gesetzliche Pausen weiterhin angewendet werden).

### Versionsübergreifende Updates

Benutzer aktualisieren von **beliebigen** älteren Versionen
(z. B. 0.6.x → 0.8.1, 0.7.x → 0.8.1, 0.8.0 → 0.8.1). Deshalb:

- Migrationen bauen aufeinander auf und laufen lückenlos von jedem Stand.
- Keine Migration darf voraussetzen, dass eine bestimmte App-Version
  vorher lief; nur der tatsächliche Schemazustand zählt.
- `ensure_schema()` fängt zusätzlich Installationen ab, deren
  `user_version` nicht gepflegt wurde.

## Pflichtprüfung vor jedem Abschluss/Deployment

1. Sind Datenbankänderungen enthalten? (`git diff app/models.py`)
2. Existiert dafür eine Migration (beide Mechanismen aktualisiert)?
3. Funktioniert das Upgrade einer bestehenden Installation?
   Test: Datenbank mit altem Schema erzeugen → App starten bzw.
   `python -m app.db_migrations --database <pfad>` ausführen →
   Spalten/Daten prüfen.
4. Bleiben vorhandene Daten erhalten? (Stichproben vor/nach Migration)
5. Werden Logs geschrieben und liegen sie im `logs`-Volume?
6. Bleiben Konfigurationsänderungen über Neustarts erhalten (`config`-Volume)?
7. Werden config/data/logs jeweils korrekt verwendet?

## Logging prüfen (verpflichtend)

Seit 0.9.0 existiert ein dateibasiertes Logging-System
(`app/logging_setup.py`) mit sechs rotierenden Kanälen im `logs`-Volume:
`application`, `api`, `sync`, `security`, `error`, `audit`.

- **Neue Logs registrieren**: zusätzliche Kanäle ausschließlich über
  `logging_setup.CHANNELS` einführen; keine eigenen Dateipfade hartkodieren.
- **Persistenz geprüft**: Logdateien liegen unter `paths.LOGS_DIR`. Keine
  Logs ins data- oder config-Volume schreiben.
- **Audit-Pflicht**: administrative Aktionen (Login/Logout, Passwort-,
  Benutzer-, Rollenänderungen, Urlaubsfreigaben, Feiertags- und
  Systemeinstellungsänderungen, Log-Level-Änderungen) müssen
  `logging_setup.log_audit` auslösen – möglichst bevor eine neue
  Logging-Policy aktiv wird.

## Konfiguration prüfen (verpflichtend)

Persistente Einstellungen liegen als JSON im `config`-Volume
(`app/app_config.py`: `logging.json`, `system.json`).

- **Einstellungen persistent**: neue konfigurierbare Werte über `app_config`
  (Dataclass + `from_dict`/`to_dict`) ergänzen, nie nur im Speicher halten.
- Validierung für Importe in `app_config.validate_import` ergänzen.

## Volumes prüfen (verpflichtend)

`app/paths.py` löst die drei Volumes zentral auf:

- **config**: nur Konfiguration (System, Logging, UI, Mail, Sync, PWA).
- **data**: nur Geschäftsdaten (Datenbank, Benutzer, Urlaub, Zeiterfassung,
  Aufträge, Feiertage, Backups).
- **logs**: nur Protokolle.
- Pfade immer über `paths.*` beziehen, nichts relativ zum Arbeitsverzeichnis
  ablegen und keine Datei im falschen Volume speichern.

## Weitere Konventionen

- **Offline-PWA**: `static/sw.js` cached Assets versioniert über `?v=`;
  neue statische Dateien in `CORE_ASSETS` aufnehmen. Funktionsänderungen
  an `static/mobile.js`/Service Worker immer gegen den Offline-Modus
  testen.
- **Design-System**: Farben/Radien/Abstände ausschließlich über die
  CSS-Tokens in `static/styles.css` (`:root` / `:root[data-theme="dark"]`).
  Keine hartkodierten Hex-Werte in Komponenten; Dark Mode muss ohne
  komponentenspezifische Overrides funktionieren.
- **Reports**: PDF-Layouts über das gemeinsame Stilsystem in
  `app/pdf_export.py` (`_data_table`, `_kv_table`, …) – Zellen immer als
  umbruchfähige Paragraphs mit Escaping.
- **Changelog**: jede nutzersichtbare Änderung in `CHANGELOG.md`
  dokumentieren (Keep-a-Changelog-Format, deutsch).

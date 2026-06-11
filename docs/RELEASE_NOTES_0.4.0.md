# Release Notes – Erfassung 0.4.0

**Alte Version:** 0.3.8
**Neue Version:** 0.4.0
**Datum:** 2026-06-11
**Typ:** Minor (neue Funktion – Konsolen-Benutzerverwaltung)

---

## Neu: Benutzerverwaltung über die Konsole

Ein neues CLI-Werkzeug `app/manage.py` ermöglicht die Verwaltung von Benutzern
direkt über die Konsole – ohne Web-Oberfläche. Das ist besonders nützlich bei
verlorenem Admin-Zugang oder zur Erstinbetriebnahme.

Es verwendet dieselbe Datenbank (`DATABASE_URL`), dasselbe Passwort-Hashing (PBKDF2)
und dieselbe Passwort-Stärke-Prüfung wie die Web-App. Die interne PIN wird wie im
Web-Flow automatisch vergeben.

### Aufruf

```bash
# Im laufenden Docker-Container (Produktivbetrieb)
docker exec -it erfassung python -m app.manage <befehl> [optionen]

# Lokal (Entwicklung)
python -m app.manage <befehl> [optionen]
```

### Befehle

| Befehl | Zweck |
| --- | --- |
| `list-users` | Alle Benutzer auflisten (ID, Benutzername, Name, E-Mail, Gruppe, Admin, PW-Wechsel) |
| `list-groups` | Gruppen inkl. Admin-Kennzeichen auflisten |
| `create-user` | Neuen Benutzer anlegen |
| `reset-password` | Passwort eines Benutzers zurücksetzen |

### Beispiele

```bash
# Benutzer auflisten
docker exec -it erfassung python -m app.manage list-users

# Benutzer anlegen (Passwort wird verdeckt abgefragt)
docker exec -it erfassung python -m app.manage create-user \
  --username mmustermann --full-name "Max Mustermann" \
  --email max@example.com --group Administration

# Passwort zurücksetzen mit Zufallspasswort
docker exec -it erfassung python -m app.manage reset-password --username admin --random
```

### Optionen (Kurzüberblick)

- `--password "…"` – Passwort direkt setzen (sonst interaktive, verdeckte Abfrage).
- `--random` – sicheres Zufallspasswort erzeugen und einmalig ausgeben.
- `--group <ID|Name>` – Gruppenzuordnung (Admin-Rechte hängen an der Gruppe).
- `--weekly-hours <h>` – Wochenarbeitszeit (Standard 40).
- `--force-change / --no-force-change` – Passwortwechsel bei nächster Anmeldung
  erzwingen (Standard: ja).
- `reset-password` wählt den Benutzer per `--username` **oder** `--id`.

## Verifikation (getestet)

- Anlegen mit explizitem Passwort, `--random` und `--no-force-change`.
- Zurücksetzen per Benutzername und per ID.
- Ablehnung von: zu schwachem Passwort, doppeltem Benutzernamen/E-Mail,
  unbekanntem Benutzer (jeweils verständliche Meldung, Exit-Code 1).
- Das zurückgesetzte Passwort authentifiziert anschließend erfolgreich
  (gegen `security.verify_password` geprüft); `must_change_password` wird korrekt
  gesetzt.

## Auswirkungen

- Rein additive Funktion. Web-Oberfläche, Endpunkte, Datenmodell und
  Geschäftslogik bleiben unverändert.

## Deployment

Nach Merge baut der Workflow `ghcr.io/joni123467/erfassung:0.4.0`. Das CLI ist im
Image enthalten und sofort per `docker exec` nutzbar.

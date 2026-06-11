# Release Notes – Erfassung 0.3.8

**Alte Version:** 0.3.7
**Neue Version:** 0.3.8
**Datum:** 2026-06-11
**Typ:** Patch (kritischer Bugfix – Anmeldung)

---

## Symptom

Beim Anmelden erschien:

> **403 – Ungültige Sitzung**
> Das Sicherheitstoken ist abgelaufen oder ungültig. Bitte lade die Seite neu.

Das trat **unabhängig vom Passwort** auf – auch bei korrekten Zugangsdaten. Es war
also kein falsches Passwort, sondern ein Programmfehler in der CSRF-Absicherung.

## Ursache (zwei zusammenhängende Fehler)

1. **Falsche Middleware-Reihenfolge**
   Starlette wendet Middleware in **umgekehrter** Registrierungsreihenfolge an: die
   zuletzt mit `add_middleware` registrierte Middleware läuft am weitesten **außen**.
   Die `CSRFMiddleware` war *nach* der `SessionMiddleware` registriert und lief daher
   **vor** ihr. Zum Zeitpunkt der CSRF-Prüfung war die Session noch nicht geladen
   (`scope["session"]` fehlte) → `session_token = None` → **jeder** POST (auch
   `/login`) wurde mit `403` abgewiesen.

2. **Verbrauchter Request-Body**
   Die `CSRFMiddleware` war eine `BaseHTTPMiddleware` und las das Formular via
   `await request.form()`, um das `csrf_token`-Feld zu prüfen. Dadurch wurde der
   Body-Stream geleert; der nachgelagerte `/login`-Handler erhielt keine
   `username`/`password`-Felder mehr (`422 Field required`). Dieser Fehler war zuvor
   durch Fehler 1 verdeckt, weil es nie bis zum Handler kam.

## Fix

- **Reihenfolge korrigiert** (`app/main.py`): `CSRFMiddleware` wird **zuerst**,
  `SessionMiddleware` **zuletzt** registriert. Dadurch läuft die Session außen und
  ist beim CSRF-Check bereits geladen.
- **CSRFMiddleware als reine ASGI-Middleware** neu implementiert: Der Request-Body
  wird gepuffert, das `csrf_token` daraus (oder aus dem `X-CSRF-Token`-Header)
  gelesen und der Body anschließend über ein frisches `receive`-Callable **an die
  Anwendung weitergereicht**. Der Handler erhält seine Formularfelder wieder.

## Verifikation (automatisiert reproduziert)

| Fall | Vorher | Nachher |
| --- | --- | --- |
| Korrekte Zugangsdaten + gültiges Token | 403 ❌ | **303 Redirect (eingeloggt)** ✅ |
| Falsche Zugangsdaten + gültiges Token | 403 ❌ | **400 (reguläre Fehlermeldung)** ✅ |
| Fehlendes CSRF-Token | 403 | **403** (Schutz erhalten) ✅ |
| Manipuliertes CSRF-Token | 403 | **403** (Schutz erhalten) ✅ |
| Token via `X-CSRF-Token`-Header | – | **akzeptiert** ✅ |

## Sicherheit

Der CSRF-Schutz bleibt vollständig erhalten: State-Changing-Requests ohne gültiges,
zur Session passendes Token werden weiterhin mit `403` abgelehnt. Geändert wurde nur,
*dass* der Token jetzt korrekt geprüft werden kann, ohne den Request zu zerstören.

## Auswirkungen

- Betrifft die gesamte Anmeldung und alle Formular-POSTs (Buchungen,
  Urlaubsanträge, Admin-Formulare, mobile Aktionen).
- Keine Änderung an Datenmodell, Endpunkten oder Geschäftslogik.

## Deployment

Nach Merge baut der Workflow `ghcr.io/joni123467/erfassung:0.3.8`. In Portainer den
Image-Tag auf `0.3.8` setzen und neu deployen.

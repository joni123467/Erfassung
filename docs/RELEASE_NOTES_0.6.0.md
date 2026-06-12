# Release Notes – Erfassung 0.6.0

**Alte Version:** 0.5.2
**Neue Version:** 0.6.0
**Datum:** 2026-06-12
**Typ:** Minor – UI-Redesign (nur Design/UX, keine Funktionsänderung)

> **Technische Vorgabe eingehalten:** keine Änderung an APIs, Datenbank,
> Synchronisation, Offline-Funktion oder Geschäftslogik. Geändert wurde
> ausschließlich `static/styles.css`. Da die Datei vom Service Worker vorab
> gecacht wird, sorgt die Versionsanhebung dafür, dass der neue Stil ausgeliefert
> wird (neuer Cache-Name → alter Cache wird ersetzt).

---

## 1. Designanalyse (vorher)

- Generische „Standard-Webapp"-Optik: viele große Radien (`12–16px`) und
  pillenförmige Elemente (`border-radius: 999px`).
- Kräftige, gefärbte Schlagschatten (z. B. `0 12px 35px rgba(...)`) → „verspielt".
- Uneinheitliche, teils zufällige Farben (zahlreiche hartcodierte Hex-/RGBA-Werte).
- Mittelblauer Brand-Ton (`#1d7ed0`); Hintergrund leicht bläulich.
- Mobile und Desktop mit abweichenden Schatten-/Form-Sprachen.

## 2. Neues Design-System

Zentrale **Design-Tokens** in `:root` – jede Komponente konsumiert sie, daher
durchgängige Konsistenz über Desktop und Mobile:

- **Form:** `--radius-sm: 6px` (Buttons, Inputs, Badges), `--radius: 8px`
  (Karten, Dialoge). Keine Pillen mehr.
- **Elevation:** `--shadow-sm/-/-md` – bewusst dezent (geringe Deckkraft,
  neutrales Slate statt blauer Glow). Kein Glassmorphism, keine starken Schatten.
- **Focus:** einheitlicher `--ring` (zugänglicher Fokus-Zustand).

## 3. Farbpalette

| Rolle | Token | Wert |
| --- | --- | --- |
| Primär | `--brand` / `--brand-dark` | `#2563eb` / `#1d4ed8` |
| App-Hintergrund | `--bg` | `#f8fafc` (Slate-50) |
| Karten | `--surface` / `--surface-muted` | `#ffffff` / `#f9fafb` |
| Rahmen | `--border` / `--border-strong` | `#e2e8f0` / `#cbd5e1` |
| Text | `--text` / `--text-muted` / `--text-subtle` | `#0f172a` / `#64748b` / `#94a3b8` |
| Aktiv/Erfolg | `--success` | `#16a34a` |
| Pause/Warnung | `--warning` | `#d97706` (Amber) |
| Urlaub/Info | `--info` | `#2563eb` |
| Krank/Fehler | `--danger` | `#dc2626` |

Status-„soft"-Varianten (`--*-soft`) für dezent getönte Flächen/Badges.

## 4. Komponentenrichtlinien

- **Buttons:** Primary = volle Brand-Fläche, dezenter Schatten, Hover dunkler,
  Focus-Ring. Secondary (`.ghost`) = zurückhaltender Neutral-Outline. Danger = rot.
  Kantige Form (6px), nie pillenförmig.
- **Karten/Sections:** weiße Fläche, 1px-Rahmen (`--border`), `--shadow-sm`, 8px.
- **KPI-/Metric-Karten:** vereinheitlicht (weiß, Rahmen, dezenter Schatten).
- **Tabellen:** gedämpfte Kopfzeile (Uppercase, klein, `--text-muted`),
  Zeilen-Hover (`--surface-muted`), luftigere Zellen.
- **Inputs:** 6px, `--border-strong`, Fokus mit `--ring`.
- **Mobile:** Header/Karten mit Rahmen + dezentem Schatten; Tabs als kantige
  Segmente (aktiv = Brand-Fläche, kein Glow); Badges in Status-Soft-Tönen.

## 5. Betroffene Dateien

| Datei | Änderung |
| --- | --- |
| `static/styles.css` | Komplettes Re-Tokenizing + Komponenten-Feinschliff (Palette, Radien, Schatten, Buttons, Karten, Tabellen, Mobile, Dark-Mode-Vorbereitung). |
| `VERSION`, `README.md`, `CHANGELOG.md`, `docs/RELEASE_NOTES_0.6.0.md` | Version 0.6.0 + Doku. |

**Keine** Änderungen an Templates, JavaScript, Python-Backend, APIs oder DB.

## 6. Dark Mode (vorbereitet, nicht aktiv)

Token-Overrides unter `:root[data-theme="dark"]`. Aktivierbar künftig über ein
`data-theme="dark"` am `<html>`-Element (z. B. via Umschalter). Bewusst **opt-in**,
damit das Standard-Erscheinungsbild (Hell) unverändert bleibt.

## 7. Qualitätssicherung

- CSS strukturell valide (ausgeglichene Klammerbilanz).
- Alle `var(--token)`-Referenzen sind definiert (keine toten Tokens).
- Keine Alt-Brand-Hexwerte und keine `999px`-Pillen mehr im Stylesheet.
- Keine Selektor-/Klassennamen geändert → Templates unverändert kompatibel.

## 8. Auswirkungen / Rollout

Nach Merge baut der Workflow `ghcr.io/joni123467/erfassung:0.6.0`. Beim nächsten
Online-Aufruf lädt der Service Worker das neue `styles.css` (Cache-Erneuerung über
die Versionsnummer). Offline-Funktion, Stempelungen und Synchronisation bleiben
unverändert.

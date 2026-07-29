# Release Notes 0.9.22

## Überblick

Der Einsatzort aus 0.9.21 war eine kleine Checkbox – auf dem Handy fummelig zu
treffen. Ersetzt durch eine **Schaltfläche, die Farbe und Beschriftung
wechselt**.

## Der Umschalter

| Zustand | Darstellung |
|---------|-------------|
| Nicht gesetzt | grau, gedämpfter Punkt, **„Einsatzort · Vor Ort"** |
| Gesetzt | blau hinterlegt, kräftiger Punkt, **„Einsatzort · Remote"** |

Ein Tipp genügt zum Wechseln. In der mobilen App füllt der Umschalter die volle
Breite und hat dieselbe Höhe wie die Stempel-Schaltflächen darunter – auf dem
Desktop steht er kompakt neben bzw. über der jeweiligen Aktion.

Verwendet an allen Stellen aus 0.9.21:

- mobile App: Arbeitszeit starten, Auftrags-Dialog, Kommentar-Nachbearbeitung
- Offline-Shell (ohne Netz)
- Dashboard: Schnell stempeln, Auftrags-Dialog, manuelle Buchung
- Administration: Zeitbuchung bearbeiten

## Technisch

- Das **Formularfeld bleibt eine Checkbox** (`is_remote`); sichtbar ist eine
  gestylte Beschriftung, umgeschaltet wird per CSS. Dadurch funktionieren
  Offline-Warteschlange, Synchronisation und das Absenden **ohne JavaScript**
  unverändert – wichtig für die statische Offline-Shell.
- **Barrierefreiheit**: per Tastatur bedienbar (Leertaste), eigener Fokusrahmen,
  eigener Screenreader-Name („Remote (z. B. Telefon)"); die farbige Darstellung
  ist `aria-hidden`.
- Neues gemeinsames Makro `templates/_components.html` → `location_toggle()`,
  damit alle Stellen identisch bleiben.

## Nebenbei behoben

In der mobilen App waren bei laufender Arbeitszeit **beide** Bereiche sichtbar:
der aktive („Arbeitszeit läuft", Pause/Beenden) *und* der Start-Bereich
(„Beginne deine Arbeitszeit …" mit deaktiviertem Start-Knopf). Ursache: Die
Layoutregeln (`display: flex` / `display: grid`) überstimmten die
Browser-Standardregel für das `hidden`-Attribut. Ausgeblendete Bereiche sind
jetzt tatsächlich ausgeblendet – die Stempelansicht zeigt nur noch die
Aktionen, die im aktuellen Zustand sinnvoll sind.

## Datenbank

Keine Migration; reine Darstellungsänderung.

## Upgrade-Hinweise

Standard-Update genügt. Mobile Geräte holen die neue Oberfläche über die
übliche PWA-Aktualisierung (siehe 0.9.13).

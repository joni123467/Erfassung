# Release Notes 0.9.21

## Überblick

Eine Buchung kann jetzt optional festhalten, ob der Termin **vor Ort** oder
**remote** (z. B. per Telefon) stattgefunden hat. Umgesetzt als schlichter
Haken „Remote" beim Stempeln – freigeschaltet je Benutzer, genau wie das
Zeitkonto.

## Freischaltung

> Administration → Benutzer → *Benutzer* → **Zeitkonto & Buchungen** →
> „Einsatzort erfassen (Remote / vor Ort)"

- **Aus (Standard)**: Das Feld erscheint nirgends, alle Buchungen gelten als
  vor Ort. Für Installationen, die den Einsatzort nicht brauchen, ändert sich
  nichts – auch nicht in den Exporten.
- **An**: Der Haken „Remote" erscheint an allen Stempelstellen.

## Wo der Haken erscheint

| Stelle | Wirkung |
|--------|---------|
| Arbeitszeit starten (Web & mobil) | die gestartete Buchung wird als Remote erfasst |
| Auftrag starten (Web & mobil) | die gestartete Auftragsbuchung wird als Remote erfasst |
| Manuelle Buchung / Nachtrag | der Nachtrag wird als Remote erfasst |
| „Kommentar der letzten Buchung bearbeiten" (mobil) | Einsatzort nachträglich korrigieren |
| Administration → Zeitbuchung bearbeiten | Einsatzort korrigieren |

Der Nachbearbeitungsschritt aus 0.9.10 dient damit doppelt: Wer beim Stempeln
den Haken vergessen hat, korrigiert ihn direkt nach dem Beenden mit.

## Verhalten im Detail

- **Offline**: Der Haken wird zusammen mit der Stempelung in die
  Offline-Warteschlange gelegt und beim Synchronisieren übertragen. Die
  laufende Buchung zeigt das Kennzeichen „Remote" auch ohne Netz.
- **Teilen**: Wird eine Buchung durch einen Nachtrag geteilt (0.9.14/0.9.15)
  oder beim Überschreiben zerlegt (0.9.19), übernehmen alle entstehenden
  Abschnitte den Einsatzort der Ursprungsbuchung.
- **Schutz**: Ohne Freischaltung ignoriert der Server ein mitgesendetes
  Remote-Kennzeichen. Wird die Option später wieder deaktiviert, bleiben
  bereits erfasste Kennzeichen erhalten – sie werden nur nicht mehr neu
  vergeben.

## Anzeige und Exporte

- Buchungslisten (`/records`), Zeitübersichten und Freigaben zeigen neben der
  Firma ein Kennzeichen **Remote**.
- PDF- und Excel-Exporte erhalten eine zusätzliche Spalte **„Ort"**
  (Remote / Vor Ort) – **nur**, wenn im Zeitraum mindestens eine Buchung remote
  erfasst wurde. Andernfalls bleiben die Exporte unverändert.

## Datenbank

Migration 13 (idempotent, datenerhaltend):

| Tabelle | Spalte | Default |
|---------|--------|---------|
| `users` | `remote_flag_enabled` | `0` |
| `time_entries` | `is_remote` | `0` |

## Upgrade-Hinweise

Standard-Update genügt; die Migration läuft beim Start automatisch. Um den
Einsatzort zu nutzen, ihn bei den gewünschten Benutzern aktivieren. Mobile
Geräte holen die neue Oberfläche über die übliche PWA-Aktualisierung
(siehe 0.9.13).

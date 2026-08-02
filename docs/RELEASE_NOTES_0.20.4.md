# Release Notes 0.20.4

Version 0.20.4 erweitert Erfassung um eine historisch korrekte Arbeitszeit- und
Abwesenheitsplanung und beseitigt den einzigen QR-Drittanbieteraufruf.

## Arbeitszeitmodelle

Arbeitszeitpläne speichern ein Gültigkeitsdatum und eigene Sollminuten für alle
sieben Wochentage. Monatssoll, Urlaubs- und Feiertagsgutschrift verwenden den am
jeweiligen Tag gültigen Plan. Ohne Plan bleibt die bisherige Mo–Fr-Logik erhalten.
Die Wochenarbeitszeit wird daraus abgeleitet; Anlage und Historie liegen in
einem eigenen Modal.

## Kalender und Abwesenheiten

- persönlicher Kalender und Teamkalender,
- grafische Monats-/Wochenansicht, Feiertage und Listenalternative,
- eigenes Bereichsrecht `Vacation.TeamCalendar` im normalen Urlaubsreiter,
- allgemeine, konfigurierbare Abwesenheitsarten,
- vertrauliche Arten erscheinen teamweit nur als „Abwesend",
- persönliche und Team-iCalendar-Feeds über `calendar_sync`,
- ausschließlich genehmigte Vorgänge im Feed, keine Kommentare,
- zufällige Feed-Tokens; gespeichert wird nur SHA-256.

## Urlaubskonto

Begründete Zu- und Abbuchungen ergänzen den Jahresanspruch append-only. Optional
verfallende Buchungen werden nach ihrem Verfallsdatum nicht mehr angerechnet.
Bei aktiviertem Übertrag wird der Rest zum Jahreswechsel automatisch und
idempotent ins Folgejahr gebucht. Endgültiger Verfall bleibt eine begründete
Betreiberentscheidung.

## Lokale QR-Codes

Die Anwendung erzeugt mobile Login-QR-Codes mit `qrcode`/Pillow lokal als PNG.
Weder die Login-URL noch ihr 30 Tage gültiges Token werden an einen externen
QR-Dienst übertragen. Die Endpunkte verlangen Anmeldung und `User.View` im
passenden Geltungsbereich und liefern `Cache-Control: no-store`.

## Datenbank und Upgrade

Migration 23 legt `work_schedules`, `absence_types`,
`vacation_entitlement_entries` und `calendar_feeds` an und ergänzt
`vacation_requests.absence_type_key`. Bestehende Anträge bleiben als Urlaub
erhalten. Die Migration läuft idempotent auf SQLite, MySQL/MariaDB und
PostgreSQL. Bestehende logische Backups bleiben kompatibel; nach einem Restore
werden die neuen Strukturen automatisch ergänzt.
Migration 24 ergänzt `vacation_entitlement_entries.source_key` und einen
portablen Unique-Index gegen Doppelüberträge.

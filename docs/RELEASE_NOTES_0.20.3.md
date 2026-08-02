# Release Notes 0.20.3

Version 0.20.3 erweitert Erfassung um eine historisch korrekte Arbeitszeit- und
Abwesenheitsplanung und beseitigt den einzigen QR-Drittanbieteraufruf.

## Arbeitszeitmodelle

Arbeitszeitpläne speichern ein Gültigkeitsdatum und eigene Sollminuten für alle
sieben Wochentage. Monatssoll, Urlaubs- und Feiertagsgutschrift verwenden den am
jeweiligen Tag gültigen Plan. Ohne Plan bleibt die bisherige Mo–Fr-Logik erhalten.

## Kalender und Abwesenheiten

- persönlicher Jahreskalender und Teamkalender,
- allgemeine, konfigurierbare Abwesenheitsarten,
- vertrauliche Arten erscheinen teamweit nur als „Abwesend",
- persönliche und Team-iCalendar-Feeds über `calendar_sync`,
- ausschließlich genehmigte Vorgänge im Feed, keine Kommentare,
- zufällige Feed-Tokens; gespeichert wird nur SHA-256.

## Urlaubskonto

Begründete Zu- und Abbuchungen ergänzen den Jahresanspruch append-only. Optional
verfallende Buchungen werden nach ihrem Verfallsdatum nicht mehr angerechnet.

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

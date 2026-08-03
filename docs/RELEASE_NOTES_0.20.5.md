# Erfassung 0.20.5

## Persönlicher Kalender und Teamplanung

Unter **Buchungen & Urlaub → Urlaub** stehen jetzt ein grafischer persönlicher
Kalender und, mit `Vacation.TeamCalendar`, ein Teamkalender bereit. Beide bieten
Monats-, Wochen- und Listenansicht, direkte Monatswahl und Vor-/Zurücknavigation.
Feiertage, offene eigene Anträge, genehmigte Abwesenheiten und halbe Tage sind
klar gekennzeichnet. Die responsive Oberfläche verwendet ausschließlich das
bestehende Designsystem und benötigt weder CDN noch externe Kalenderdienste.

Der Teamkalender folgt dem Scope der Rolle. Normale Planer sehen keine offenen
Anträge anderer Personen. Nur Benutzer mit `Vacation.Manage` sehen diese im
eigenen Verwaltungs-Scope. Vertrauliche Arten heißen stets „Abwesend“;
Kommentare und Freigabeinformationen werden nicht ausgegeben. Ein geschützter
JSON-Endpunkt meldet beim Antrag lediglich genehmigte Überschneidungen.

## iCalendar und Datenschutz

Der optionale Baustein `calendar_sync` (zusätzlich zu `vacation`) stellt
persönliche und berechtigte Teamfeeds bereit. Feed-Adressen werden nur einmal
angezeigt. Gespeichert wird ausschließlich der SHA-256-Hash eines starken
Zufallstokens. Feeds sind widerrufbar, enthalten nur genehmigte Ereignisse,
verwenden stabile UIDs, CRLF, korrektes Escaping und exklusive Enddaten. Rechte
und Lizenz werden bei jedem Abruf erneut geprüft.

## Aktualisierung und Datenbank

Es gibt keine neue Schemaänderung. Die portable und idempotente Migration 23
aus 0.20.3 stellt `calendar_feeds` für SQLite, MySQL/MariaDB und PostgreSQL
weiterhin bereit. Backup-/Restore-Archive und logische Cross-Database-Transfers
bleiben kompatibel.

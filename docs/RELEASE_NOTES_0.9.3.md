# Release Notes – 0.9.3

UI/UX-Korrekturen an den 0.9.2-Funktionen.

## Backup-Job-Modal
- Maximalhöhe `90vh`; Kopf- und Fußzeile bleiben fixiert, nur der Inhalt
  scrollt. Speichern/Abbrechen/Verbindung testen sind immer sichtbar – auch auf
  Notebook-, Tablet- und Mobilauflösungen.
- Kompakteres Layout, dynamische Felder je Backup-Typ (Lokal/FTP/SMB) ohne
  überflüssige Leerflächen.

## Administration-Navigation
- Echtes Akkordeon: maximal eine geöffnete Hauptgruppe.
- Desktop: Hover öffnet, Verlassen schließt; Klick funktioniert ebenfalls.
- Mobile: Klick öffnet, eine andere Gruppe schließt die vorherige.
- Verbesserte Hover-/Fokus-/Active-States, kein Flackern der Dropdowns.

## Sonstiges
- Version durchgängig auf 0.9.3 angehoben (Frontend, Backend, Footer, Login,
  Systemstatus, Health-API, Cache-Busting, Docker-Tag).
- Keine Schema- oder API-Änderungen; bestehende Funktionen unverändert.

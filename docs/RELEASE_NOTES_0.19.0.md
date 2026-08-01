# Release Notes 0.19.0

## Aufbewahrungssichere Kontodeaktivierung

Benutzer werden nicht mehr physisch gelöscht. Die Deaktivierung sperrt Login und bestehende Sitzungen, pseudonymisiert Benutzername und E-Mail, entfernt Zugangsdaten, RFID, Rollen und Gruppen und vergibt eine freie Archiv-PIN. Der vollständige Name sowie Arbeitszeiten, Pausen, Revisionen und die vollständige Compliance-Historie bleiben als minimale Zuordnung zum gesetzlichen Nachweis erhalten. Die Aktion und Pseudonymisierung werden im Audit-Log dokumentiert.

## Arbeitszeitprüfung

Sonntage bleiben außerhalb des Werktagsnenners. Tatsächlich geleistete Sonntagsminuten bleiben jedoch in `total_minutes` und in der Arbeitszeit- und Ausgleichsprüfung nach § 11 Abs. 2 in Verbindung mit §§ 3–8 ArbZG. Zusammenhängende Schichten werden für die absolute Zehn-Stunden-Grenze auch über Mitternacht bewertet; Kunden-, Auftrags- und Standortwechsel trennen keine Schicht. Erfasste Zeit wird niemals gekürzt oder blockiert.

Die Zustände `compensation_required`, `compensation_due` und `compensation_overdue` bilden einen Vorgang mit stabilem `finding_key`. Bestehende Feststellungen aus 0.17/0.18 werden beim ersten Refresh am bestehenden Datensatz fortgeschrieben; ihre Historie bleibt erhalten.

## Migration 21

Migration 21 ergänzt portabel und idempotent:

- `users.is_active BOOLEAN NOT NULL DEFAULT 1`
- `users.deactivated_at DATETIME NULL`
- `users.deactivation_reason VARCHAR(500) NULL`

Bestandsbenutzer werden aktiv übernommen. Die Migration verändert oder löscht keine Geschäfts- oder Nachweisdaten und unterstützt SQLite, MySQL, MariaDB und PostgreSQL.

## Organisatorische und juristische Grenze

Tarifabweichungen, §§ 7/10/14 ArbZG, Betriebsvereinbarungen und Legal Holds benötigen eine betriebliche beziehungsweise juristische Festlegung. Die Software kann diese organisationsspezifischen Entscheidungen nicht automatisch ersetzen.

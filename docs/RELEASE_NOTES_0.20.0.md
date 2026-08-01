# Release Notes 0.20.0

## Jahresprüfung für Sonn- und Nachtarbeit

Die Regelübersicht berechnet nun je Person und Kalenderjahr:

- beschäftigungsfreie und gearbeitete Sonntage,
- das gesetzliche Minimum von 15 freien Sonntagen nach § 11 Abs. 1 ArbZG,
- ob das Minimum mit den verbleibenden Sonntagen noch erreichbar ist,
- Tage mit mindestens zwei Stunden Arbeit in der Nachtzeit von 23:00 bis
  06:00 Uhr sowie das 48-Tage-Indiz für Nachtarbeitnehmer nach § 2 Abs. 5
  ArbZG.

Sobald 15 freie Sonntage rechnerisch nicht mehr erreichbar sind, entsteht eine
kritische, revisionssicher fortgeschriebene Compliance-Feststellung. Arbeitstage
mit mindestens zwei Nachtstunden und mehr als acht Gesamtstunden erhalten eine
zusätzliche Kennzeichnung nach § 6 Abs. 2 ArbZG. Zeitumstellungen und Pausen
werden über die vorhandene UTC-/Intervallrechnung berücksichtigt.

Die Übersicht folgt dem bestehenden Rechtekonzept: `Time.View` und der
Geltungsbereich bestimmen, welche Personen sichtbar sind;
`Time.Compliance.Manage` bleibt für Einordnungen erforderlich. Tatsächliche
Arbeitszeit wird weiterhin weder blockiert noch gekürzt.

## Rechtliche Grenze

Wechselschicht, die Bäckerei-/Konditorei-Nachtzeit, tarifliche oder behördliche
Abweichungen, arbeitsmedizinische Vorsorge und Zuschlags-/Freizeitausgleich
lassen sich ohne zusätzliche Betriebs-, Vertrags- oder Branchendaten nicht
automatisch entscheiden. Die neue Berechnung macht die technisch feststellbaren
Sachverhalte sichtbar und benennt die verbleibende menschliche Einordnung.

## Datenbank und Migration

Keine Schemaänderung und keine Migration. Neue Regelcodes werden in der
vorhandenen portablen `compliance_flags.code`-Spalte gespeichert.

# Rechtliche und normative Prüfung 0.19.1

> **Fortschreibung in 0.20.0:** Die damals offenen technischen Punkte
> „15 freie Sonntage“ und „Nachtarbeit erkennen“ sind inzwischen in der
> Jahres- und Regelübersicht umgesetzt. Nicht maschinell ableitbare
> Wechselschicht-, Branchen-, Vorsorge-, Tarif- und Ausgleichsentscheidungen
> bleiben Betreiberaufgabe; siehe [Release Notes 0.20.0](RELEASE_NOTES_0.20.0.md).

**Prüfstand:** 1. August 2026 · **Geltungsbereich:** Deutschland · reguläre
volljährige Beschäftigte. Diese technische Prüfung ist keine Rechtsberatung und
keine Zertifizierung. Tarifverträge, Betriebsvereinbarungen, Branchenregeln und
der konkrete Verarbeitungszweck müssen je Betrieb gesondert geprüft werden.

## Ergebnis

**Die Anwendung erfüllt wichtige technische Grundanforderungen, aber nicht
„alle rechtlichen Grundlagen und Standards“ ohne organisatorische Maßnahmen und
betriebliche Konfiguration.** Für reguläre Beschäftigte kann sie als Grundlage
eines objektiven, verlässlichen und zugänglichen Zeiterfassungssystems dienen.
Eine pauschale Rechtskonformitätszusage wäre trotzdem falsch.

| Bereich | Technischer Stand | Ergebnis / offene Maßnahme |
|---|---|---|
| Vollständige Erfassung | Beginn, Ende, Pausen, UTC-Zeitpunkt und Zeitzone; Offline-Nachlieferung | **Erfüllt als Funktion.** Arbeitgeber muss die tatsächliche Nutzung anordnen, kontrollieren und Offline-Konflikte bearbeiten. |
| ArbZG §§ 3–5 | 8-/10-Stunden-, Pausen- und 11-Stunden-Ruhezeitprüfung; Verstöße bleiben als tatsächliche Zeit erhalten | **Für den Grundfall abgedeckt.** Ausnahmen nach §§ 5 Abs. 2, 7 und 14 werden nicht automatisch entschieden. |
| ArbZG §§ 9–11 | Sonn-/Feiertagskennzeichnung, Grundlage, Ersatzruhetag und Fristen | **Dokumentierbar, nicht automatisch erlaubt.** Zulässigkeit nach § 10/Bewilligung bleibt Arbeitgeberentscheidung. Mindestens 15 beschäftigungsfreie Sonntage (§ 11 Abs. 1) werden derzeit nicht als Jahresregel geprüft. |
| ArbZG § 16 Abs. 2 / MiLoG § 17 | Nachweise und Historien, Vorgabe 24 Monate; Deaktivierung statt Löschung | **Technisch abgedeckt.** MiLoG-Dokumentationspflicht gilt nur für den gesetzlichen Personenkreis; Beginn, Ende und Dauer müssen fristgerecht tatsächlich erfasst werden. Legal Holds und längere steuer-/prozessrechtliche Fristen sind betrieblich zu konfigurieren. |
| BAG 1 ABR 22/21 / EuGH C-55/18 | objektive Zeitpunkte, Mitarbeiteransicht, Exporte, Korrekturhistorie | **Geeignete Grundlage.** Zugänglichkeit, Einführung, Unterweisung und Kontrolle sind organisatorisch sicherzustellen. |
| Nachweis-/Beweiswert | Storno plus Ersatz, Begründung, Vorher/Nachher, Audit | **Anwendungsseitig nachvollziehbar, nicht unveränderbar gegen DB-/Host-Administratoren.** Für erhöhten Beweiswert externe manipulationsgeschützte Archivierung, signierte Exporte, restriktive Adminrechte und unabhängige Backups vorsehen. |
| DSGVO / BDSG § 26 | Rollen/Geltungsbereiche, Zugriffshistorie, Selbstauskunft, einstellbare Aufbewahrung, keine GPS-Ortung | **Privacy-Funktionen vorhanden, Compliance nicht allein durch Software erfüllt.** Rechtsgrundlage, Transparenzinformation, Verzeichnis der Verarbeitungstätigkeiten, Löschkonzept, TOMs, Auftragsverarbeitungsverträge, Betroffenenprozesse und gegebenenfalls Datenschutz-Folgenabschätzung bleiben Betreiberpflicht. Datenminimierung und Zweckbindung sind je Konfiguration zu prüfen. |
| BetrVG | Rechte und Audit für Administration | **Organisatorisch offen.** Mitbestimmung, insbesondere § 87 Abs. 1 Nr. 6 und ggf. Nr. 2/3, vor Einführung/Änderung klären; das BAG verneint kein Mitbestimmungsrecht an der Ausgestaltung. |
| Besondere Personengruppen | keine eigenen Regelwerke | **Nicht abgedeckt:** Jugendliche (JArbSchG), schwangere/stillende Personen (MuSchG), mobile Beschäftigte/Fahrpersonal, See-/Luftfahrt, Bereitschaftsdienst und weitere branchenspezifische Regeln. |
| Nachtarbeit (§ 6 ArbZG) | Nachtstunden werden zeitlich korrekt erfasst | **Nicht vollständig:** Definition als Nachtarbeitnehmer, besonderer Ausgleich über einen Monat/vier Wochen, arbeitsmedizinische Vorsorge und Zuschlag/Freizeitausgleich werden nicht automatisiert. |
| Entgelt-/Überstundenrecht | Zeitkonto, Freigabe, Periodenabschluss und Exporte | **Nachweis unterstützt, Anspruch nicht entschieden.** Vergütung, Anordnung/Duldung, Rundung, Kappung, Zuschläge und Tarifregeln müssen außerhalb bzw. betrieblich geregelt werden. Keine Rundung darf die Rohdaten ersetzen. |
| Informationssicherheit | Authentifizierung, Rollen, Logs, Backups | **Keine Zertifizierung.** ISO/IEC 27001, BSI IT-Grundschutz oder SOC 2 werden nicht behauptet; dafür fehlen organisationsweite ISMS-Nachweise, unabhängige Audits und Zertifizierung. |
| Barrierefreiheit | Weboberfläche vorhanden | **Nicht zertifiziert.** WCAG 2.2 / EN 301 549 / BITV- oder BFSG-Konformität ist nicht durch einen vollständigen Audit nachgewiesen; Anwendbarkeit ist je Betreiber und Angebot zu klären. |

## Verbindliche Rechtsquellen der Prüfung

- [Arbeitszeitgesetz](https://www.gesetze-im-internet.de/arbzg/) – insbesondere
  §§ 2–7, 9–11, 14, 16 und branchenspezifisch § 21a.
- [Mindestlohngesetz](https://www.gesetze-im-internet.de/milog/) – insbesondere
  § 17 (Personenkreis, Inhalt, Frist und zweijährige Aufbewahrung).
- [BAG, Beschluss vom 13.09.2022 – 1 ABR 22/21](https://www.bundesarbeitsgericht.de/entscheidung/1-abr-22-21/)
  zur Pflicht, ein System zur Erfassung der geleisteten Arbeitszeit einzuführen.
- [EuGH, C-55/18](https://curia.europa.eu/juris/liste.jsf?num=C-55/18&language=de)
  zum objektiven, verlässlichen und zugänglichen System.
- [DSGVO](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=de), insbesondere
  Art. 5, 6, 12–22, 24–25, 28, 30, 32 und gegebenenfalls 35; ergänzend
  [BDSG § 26](https://www.gesetze-im-internet.de/bdsg_2018/__26.html).
- [Betriebsverfassungsgesetz](https://www.gesetze-im-internet.de/betrvg/),
  insbesondere § 87 Abs. 1 Nr. 2, 3 und 6.

Standards wie ISO/IEC 27001, ISO 8601, WCAG 2.2 und EN 301 549 sind nicht
pauschal gesetzliche Zulassungsvoraussetzungen für jedes interne
Zeiterfassungssystem. Wo Vertrag, Vergabe, Betreiberstatus oder Gesetz sie
verbindlich macht, ist eine gesonderte Konformitätsprüfung erforderlich.

## Technische Stichprobe

Geprüft wurden die zentrale Dauerberechnung (`app/worktime.py`), die
Regelbewertung (`app/compliance.py`), Modelle und Löschbeziehungen
(`app/models.py`), Datenschutz/Retention (`app/privacy.py`), Berechtigungen,
Exporte, Korrektur- und Abschlussworkflow sowie die Regressionstests für
0.14.0–0.19.0. Die Version 0.19.1 ändert **kein Datenbankschema** und keine
fachliche Berechnung; sie dokumentiert den erneuten Soll-Ist-Abgleich.

## Vor Produktivbetrieb zwingend

1. Beschäftigtengruppen, Tarif-/Branchenrecht, Nachtarbeit und Ausnahmen mit
   Arbeitsrecht/Fachkraft für Arbeitssicherheit bestimmen.
2. Betriebs-/Personalrat beteiligen und Betriebsvereinbarung zu Zweck,
   Auswertung, Korrektur, Kontrolle und Löschung schließen.
3. Datenschutzunterlagen, Rollen, Löschfristen, AV-Verträge, TOMs und
   gegebenenfalls DSFA fertigstellen; Zugriff auf das erforderliche Minimum
   beschränken.
4. Zeitzone, Feiertagsregion, Sollzeiten, Ausgleichszeitraum und betriebliche
   Schichtgrenze dokumentiert konfigurieren; Regelverstöße regelmäßig durch
   zuständige Personen bearbeiten.
5. Unveränderte Rohdaten, Audit-Logs und Backups extern absichern, Restore
   testen, Systemzeit synchronisieren und privilegierte Zugriffe überwachen.
6. Vollständigkeit praktisch prüfen: Web, Mobil, Offline, Korrektur, Export,
   Austritt, Auskunft und Lösch-/Legal-Hold-Prozess mit realistischen Fällen.

## Schlussurteil

Für den dokumentierten Grundfall lautet das Ergebnis **„technisch weitgehend
geeignet, mit offenen organisatorischen und spezialgesetzlichen Anforderungen“**.
Es lautet ausdrücklich nicht „vollständig rechtskonform“. Besonders Nachtarbeit,
15 freie Sonntage, besondere Beschäftigtengruppen, Betreiber-Datenschutz,
Mitbestimmung, manipulationsgeschützte externe Archivierung und eine formale
Barrierefreiheits-/Informationssicherheitszertifizierung bleiben offen.

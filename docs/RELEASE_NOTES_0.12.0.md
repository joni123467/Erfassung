# Release Notes 0.12.0 – Funktionsbausteine und regelmäßige Lizenzprüfung

Eine Lizenz schaltet ab sofort einzelne Bereiche frei. Die Installation fragt
täglich beim Lizenzserver nach, und eine gesperrte Lizenz wirkt erst nach einer
Übergangsfrist.

## Funktionsbausteine

### Immer enthalten

Diese Bereiche werden **nie** gesperrt – auch nicht bei abgelaufener Lizenz
oder nach einer Sperre:

- Stempeln: Arbeitszeit, Pausen, Kommentare, Einsatzort
- eigene Zeitübersicht und eigene Buchungen
- Benutzer-, Gruppen- und Rollenverwaltung
- Sicherung und Wiederherstellung
- Systemeinstellungen, Logs, Datenbankverwaltung

Der Grund ist einfach: **Eine Lizenzfrage darf keine Arbeitszeitdaten kosten.**
Wer nicht stempeln kann, verliert Daten, die sich nicht nachholen lassen.

### Zubuchbar

| Baustein | Schaltet frei |
|---|---|
| `orders` | Aufträge, Firmen, auftragsbezogenes Stempeln |
| `vacation` | Urlaubsanträge, Urlaubskonten, Urlaubsfreigaben |
| `reports` | PDF-/Excel-Exporte, Benutzer- und Team-Auswertungen |
| `terminals` | RFID-Terminals und Geräte-Synchronisation |

Eine Lizenz ohne jeden Baustein ist damit eine reine **Stempel-Lizenz**.

### Wie gesperrt wird

Gesperrte Bereiche verschwinden aus der Navigation. Wer die Adresse direkt
aufruft, landet mit einer Klartextmeldung auf dem Dashboard; die API antwortet
mit **HTTP 402** und nennt den fehlenden Baustein.

Durchgesetzt wird das über eine **Middleware** und nicht Route für Route.
Damit kann kein Endpunkt versehentlich offen bleiben, und neue Unterseiten
eines Bereichs sind automatisch mit abgedeckt – `/admin/reports/users/pdf`
gehört ohne weiteres Zutun zu `reports`.

> **Ohne hinterlegte Lizenz ist alles offen.** Ein Update darf einen laufenden
> Betrieb nicht beschneiden. Erst eine gültige Lizenz entscheidet.

## Regelmäßige Prüfung

Ein Hintergrundthread fragt einmal täglich beim Lizenzserver nach
(`POST /v1/activations/state`) und bekommt bei gültiger Lizenz ein **frisch
signiertes Dokument**. Änderungen an Benutzerzahl, Laufzeit oder Bausteinen
wirken damit ohne Zutun des Kunden, in der Regel binnen eines Tages.

Der Zeitpunkt des letzten Kontakts steht auf der Lizenzseite. „Erneut prüfen"
stößt die Abfrage sofort an.

Auch das frische Dokument durchläuft die volle Prüfung: Signatur,
Deployment-ID, Produktkennung und Schemaversion. Ein gefälschtes Dokument
ersetzt nie das gespeicherte – dann gilt weiter, was schon da war.

## Wenn der Lizenzserver ausfällt

**Nichts passiert.** Störung, Netzausfall, abgeschalteter Server, Wartung – die
gespeicherte Lizenz läuft unverändert weiter. Die Prüfung ist ohnehin offline;
der Server wird nur für Aktualisierungen gebraucht.

Der Vorfall landet in `license.log`, sonst merkt niemand etwas. Auch ein
älterer Lizenzserver, der den Endpunkt noch nicht kennt, ist unschädlich.

Das ist die wichtigste Eigenschaft des ganzen Verfahrens: Ein Ausfall auf
Herausgeberseite darf niemals beim Kunden zu Ausfall führen.

## Wenn eine Lizenz gesperrt wird

Nur eine **ausdrückliche** Sperrmeldung des Servers (`suspended`, `revoked`
oder `expired`) startet die Übergangsfrist von **14 Tagen**:

| Zeitraum | Wirkung |
|---|---|
| Tag 0–14 | Deutlicher Hinweis mit Restfrist auf jeder Administrationsseite. Alles arbeitet weiter. |
| ab Tag 15 | Aufträge, Urlaubsplanung, Auswertungen und Terminals sind gesperrt. |
| immer | Stempeln, eigene Zeitübersicht, Benutzerverwaltung und Sicherungen bleiben offen. |

Gibt der Herausgeber die Lizenz wieder frei, endet die Frist bei der nächsten
Nachfrage sofort – oder direkt über „Erneut prüfen".

Warum überhaupt eine Frist? Eine Sperre trifft oft nicht die Person, die sie
verursacht hat. Zwei Wochen reichen, um eine Rechnung zu klären, ohne dass ein
Betrieb stillsteht.

## Neu auf der Lizenzseite

- **Funktionsbausteine** mit Zustand je Baustein („nutzbar" / „nicht enthalten")
- **Letzter Serverkontakt** samt Prüfintervall
- Bei einer Sperre: Begründung des Servers und verbleibende Frist
- `GET /api/license` liefert zusätzlich `blocked_status`, `blocked_reason`,
  `grace_days_left`, `grace_expired` und `last_contact_at`

## Lizenzserver

Passend dazu **Lizenzserver 1.4.0**:

- Lizenzen lassen sich **bearbeiten** – Benutzerzahl, Aktivierungen, Laufzeit
  und Bausteine, ohne neuen Aktivierungsschlüssel. Jede Änderung landet mit
  Vorher/Nachher in der Historie.
- Funktionsbausteine als Ankreuzfelder beim Anlegen und Bearbeiten.
- Neuer Endpunkt `POST /v1/activations/state` für die Nachfrage. Er antwortet
  **differenziert** (`active`/`suspended`/`revoked`/`expired`), damit die
  Zeiterfassung eine Sperre von einem Ausfall unterscheiden kann. Ein falscher
  Aktivierungsschlüssel wird weiterhin gleichförmig abgewiesen.
- Das Aktivierungslimit lässt sich nicht unter die Zahl der belegten Plätze
  senken.

## Datenbank

Keine Schemaänderung in Erfassung. `config/license.json` merkt sich
zusätzlich Sperrzustand, Beginn der Frist und den letzten Serverkontakt.

## Tests

`tests/test_v0120.py` – 34 Tests:

- **Bausteine**: ohne Lizenz alles offen, lizenzierter Baustein öffnet seinen
  Bereich, fehlender schließt ihn, Stempeln immer erreichbar, Navigation
  blendet aus, API antwortet 402, Pfadzuordnung inklusive Unterseiten und
  ähnlich lautender Präfixe.
- **Nachfrage**: unerreichbarer Server sperrt nie, alter Server ohne Endpunkt
  ist harmlos, `active` erneuert das Dokument, ein gefälschtes wird abgelehnt.
- **Übergangsfrist**: Sperre startet die Frist, währenddessen arbeitet alles
  weiter, danach sind die Bausteine zu, eine Freigabe beendet die Frist,
  Hinweisbalken mit Restfrist.
- **Fälligkeit**: Intervall wird eingehalten, ohne Lizenz nichts zu tun, der
  Scheduler überlebt einen Fehler.

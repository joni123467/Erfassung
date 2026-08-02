# Release Notes 0.20.3

**Datum:** 2026-08-02
**Art:** Fehlerbehebung (Patch)

0.20.3 repariert einen Folgefehler aus 0.20.1: Im Browser verschwand „Remote"
aus der Einsatzortauswahl, sobald eine Firma gewählt wurde. Betroffen waren
*Auftrag starten* und das Bearbeiten bestehender Zeitbuchungen im Web.

---

## Behoben – „Remote" verschwand nach der Firmenauswahl

### Was passierte

Die Einsatzortauswahl wird zweimal befüllt:

1. **Serverseitig** beim Rendern der Seite – über das Makro `location_picker`
   in `templates/_components.html`.
2. **Im Browser**, sobald eine Firma gewählt oder gewechselt wird – über
   `fillPicker()` in `static/app.js`. Die Funktion baut die Liste komplett neu
   auf, weil sich die firmengebundenen Standorte ändern.

0.20.1 hat das Benutzerkennzeichen `remote_flag_enabled` außer Dienst gestellt
und dabei das Attribut `data-allow-remote` aus der Vorlage entfernt. In
`fillPicker()` blieb die zugehörige Abfrage jedoch stehen:

```js
const allowRemote = picker.hasAttribute('data-allow-remote');
```

Da das Attribut niemand mehr setzt, lieferte `hasAttribute` **immer** `false`.
Der erste Seitenaufbau war noch korrekt – die Optionen kamen vom Server. Erst
beim Wechsel der Firma warf das Skript die Serverliste weg und baute sie ohne
„Remote" neu auf.

Das erklärt auch, warum die Regressionstests aus 0.20.1 nicht angeschlagen
haben: Sie prüften ausschließlich das vom Server gelieferte HTML, und das war
zu jedem Zeitpunkt richtig. Verloren ging die Option erst im Browser.

### Was jetzt gilt

„Vor Ort" und „Remote" stehen **immer** in der Liste – server- wie
clientseitig, unabhängig von der gewählten Firma:

```js
const fixed = [['onsite', 'Vor Ort'], ['remote', 'Remote']];
```

Darunter folgen wie bisher die Standorte der gewählten Firma. Ein
firmengebundener Standort, der bereits an der Buchung hängt, bleibt beim
Neuaufbau ausgewählt.

### Betroffene Stellen

| Stelle | Vorher | Jetzt |
| --- | --- | --- |
| Auftrag starten (Dialog, Web) | nach Firmenwahl ohne „Remote" | „Vor Ort", „Remote", Standorte |
| Zeitbuchung bearbeiten (Web) | nach Firmenwahl ohne „Remote" | „Vor Ort", „Remote", Standorte |
| Schnellstempeln ohne Firma | korrekt | unverändert korrekt |
| App/Offline-Shell (`/mobile`) | korrekt | unverändert korrekt |

Die Offline-Shell war nie betroffen: Sie rendert ihre Auswahl selbst und ist
nie über `fillPicker()` gelaufen.

---

## Tests

`tests/test_v0203.py` (13 Tests) prüft die Reparatur auf beiden Ebenen und
schließt damit die Lücke, durch die der Fehler gerutscht ist:

**Serverseitig** – das gerenderte HTML enthält „Remote" im Auftragsdialog und
im Bearbeitungsformular; eine Buchung mit Firma **und** `remote` wird
angenommen; ein firmengebundener Standort gewinnt weiterhin gegen „Remote".

**Clientseitig** – `static/app.js` wird als Quelltext geprüft:

- `test_script_has_no_attribute_gate_for_remote` – es existiert keine
  Attributabfrage mehr, die „Remote" ausblenden könnte.
- `test_script_always_offers_onsite_and_remote` – die Literalliste `fixed`
  wird ausgelesen und muss beide Werte enthalten.
- `test_template_and_script_agree` – Vorlage und Skript bieten dieselben
  festen Optionen an.

Die drei Skripttests wurden gegen den alten Stand gegengeprüft: Mit dem Code
von 0.20.2 schlagen sie fehl. Zusätzlich wurde die Auswahl in einem echten
Browser (Chromium/Playwright) nach der Firmenwahl ausgelesen:

```
Auftrag starten – nach Firmenwahl:      ['Vor Ort', 'Remote', 'Werk Nord · Kiel', 'Werk Süd · Ulm']
Buchung bearbeiten – nach Firmenwahl:   ['Vor Ort', 'Remote', 'Werk Nord · Kiel', 'Werk Süd · Ulm']
```

---

## Migration

Keine. 0.20.3 ändert weder Datenbankschema noch gespeicherte Daten; die
Schemaversion bleibt bei 22. Bereits erfasste Buchungen sind nicht betroffen –
verloren ging nur die *Auswahlmöglichkeit*, nicht ein gespeicherter Wert.

Der Versionssprung genügt, damit das korrigierte `app.js` auch installierte
Instanzen erreicht: Der Server stellt `static/sw.js` die Anwendungsversion
voran, aus der der Cache-Name `erfassung-mobile-v<Version>` entsteht. Mit
0.20.3 legt der Service Worker also einen neuen Cache an und räumt den alten
ab – ohne Zutun der Anwenderinnen und Anwender.

---

## Bekannte, nicht in dieser Version behobene Punkte

Beide Punkte bestehen unabhängig von 0.20.1–0.20.3 und wurden bei der Prüfung
der übrigen Funktionen gefunden. Sie sind hier festgehalten, nicht behoben,
weil ihre Behebung über eine Fehlerkorrektur hinausgeht.

- **QR-Code der mobilen Anmeldung kommt von einem Fremddienst.** Das Bild unter
  Administration → Benutzer → *Mobile Anmeldung* wird von `api.qrserver.com`
  geladen, wobei der Anmelde-Link **mitsamt seinem 30 Tage gültigen Token** als
  URL-Parameter an diesen Dienst übertragen wird. In abgeschotteten Netzen
  (die typische Betriebsform dieser Anwendung) lädt das Bild nicht. Die
  Abhilfe – Erzeugung des Codes in der Anwendung selbst – bedeutet eine neue
  Abhängigkeit und damit eine Entscheidung, die nicht in einen Patch gehört.
  Vorhanden seit 0.9.6.
- **Waagerechter Überlauf auf schmalen Displays.** Die Hinweisblasen
  (`.info-tip__bubble`) sind links am Fragezeichen verankert und ragen bei
  einer Breite von 390 px über den rechten Rand hinaus; die Seite lässt sich
  dadurch seitlich schieben (Dashboard 532 px statt 390 px). Gegengeprüft mit
  dem Stylesheet aus 0.20.0 – identische Werte, also kein Rückschritt aus den
  Änderungen der letzten drei Versionen. Eine saubere Behebung muss die Blase
  je nach Platz nach links **oder** rechts ausrichten und ist eine
  Gestaltungsentscheidung.

---

## Hinweis

Diese Fehlerbehebung stellt eine Auswahlmöglichkeit wieder her. Sie ist weder
eine Aussage über die vollständige Rechtskonformität der Anwendung noch eine
Zertifizierung.

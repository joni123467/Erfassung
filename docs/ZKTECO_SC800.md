# ZKTeco SC800 anbinden

## Zweck und Sicherheitsstatus

Das SC800 ist eine **optionale Eingabequelle**. Web, API und Offline-PWA bleiben ohne Gerät unverändert. Eingehende Ereignisse verwenden dieselben `crud.start_running_entry`-/`finish_running_entry`-Primitive wie `/punch`; Arbeitszeitberechnung, Pausenregeln und Auswertungen bleiben zentral. Beachte vor Produktion den [Kompatibilitätsbericht](ZKTECO_SC800_COMPATIBILITY.md).

## Hardware/Firmware

Benötigt werden SC800, Ethernet oder WLAN sowie eine Firmware mit aktivierbarem T&A PUSH/ADMS (gegebenenfalls der vom Hersteller beschriebenen A&C→T&A-Konvertierung). Firmware-Version und das dazu passende offizielle Protokollhandbuch dokumentieren. Keine hier nicht genannten Menüwerte aus ähnlichen ZKTeco-Geräten übernehmen.

## Terminalkonfiguration (am realen Gerät verifizieren)

1. Statische IP/DHCP, Gateway, DNS und NTP konfigurieren.
2. Zeitzone `Europe/Berlin`, Uhrzeit und Sommerzeit kontrollieren.
3. T&A PUSH/ADMS aktivieren; falls nur A&C PUSH angeboten wird, die herstellerseitige T&A-Konvertierung einsetzen.
4. Als Server den internen DNS-Namen des Reverse Proxys und dessen HTTPS-Port eintragen.
5. Der erwartete Pfad ist die PUSH-Familie `/iclock/cdata`; das Gerät ergänzt Seriennummer und Tabellenparameter. Ob die SC800-Firmware einen Basispfad erlaubt, ist am Gerät zu prüfen.
6. HTTPS aktivieren und eine vom Gerät vertraute Zertifikatskette verwenden. Nur falls die konkrete Firmware es nicht unterstützt, HTTP ausschließlich in einem isolierten VLAN bis zu einem TLS-terminierenden Gateway verwenden.
7. Ein nativer Communication-Key-Transport ist noch nicht nachgewiesen. `X-Terminal-Key` funktioniert nur mit Firmware/Gateway, die/das diesen Header setzt.
8. Ersten Kontakt auslösen. Das Gerät erscheint **inaktiv/pending** als „Nicht registriertes Terminal“ und muss in *Administration → Zeiterfassung → Terminals* freigegeben werden.

## Server, Docker und Reverse Proxy

```yaml
environment:
  TERMINAL_SUPPORT: "true"
  # bestehend: SESSION_SECRET_KEY, DB_*, ERFASSUNG_*_DIR
```

Es ist kein zusätzlicher Containerport nötig: intern `8000`, nach außen ausschließlich der bestehende HTTPS-Reverse-Proxy. Firewall: SC800-VLAN darf TCP 443 zum Proxy; kein eingehender Internetzugriff und kein direkter Datenbankzugriff. Proxy-Limit für `/iclock/` höchstens 256 KiB setzen, Rate-Limit pro Geräte-IP vorsehen, Request-Body unverändert weiterreichen und Zugriffslogs ohne Query-Secrets betreiben.

Optional wird in `terminals.config_json` nur `communication_key_sha256` gespeichert. Erzeugen: `printf %s 'GEHEIM' | sha256sum`. Das Klartextgeheimnis gehört nicht in Datenbank oder Logs. Da der native SC800-Header nicht bestätigt ist, sind mTLS am Gateway, IP-Allowlist und ein separates Geräte-VLAN die bevorzugte zusätzliche Absicherung.

## Mitarbeiter und RFID

Im Abschnitt **Mitarbeiter-Zuordnung** je Terminal einen aktiven Mitarbeiter, dessen SC800 User ID und optional eine RFID-Kartennummer hinterlegen. Mehrere Geräte können verschiedene User IDs besitzen; mehrere Karten werden vom Schema unterstützt. Die Web-PIN wird nicht an das Gerät übertragen. Automatisches Provisioning/Löschen ist mangels verifizierter SC800-Command-Dokumentation nicht aktiv.

## Datenfluss und Zustände

`ATTLOG → Parser → TerminalEvent (einmalig) → Zuordnung → start/finish running entry`. Der Schlüssel ist ein SHA-256-Fingerprint aus Terminal, externer ID beziehungsweise stabilen Eventfeldern; zusätzlich erzwingt die Datenbank dessen Eindeutigkeit je Terminal. Ereigniszeit und Empfangszeit werden getrennt gespeichert. Ein Batch wird nach Ereigniszeit sortiert. Ein einfaches Karten-Vorhalten toggelt *Kommen/Gehen*. Pause/Work Codes werden beweissicher gespeichert, aber ohne bestätigte Firmware-Zuordnung nicht als Pause interpretiert.

Unbekannte/deaktivierte Geräte, unbekannte/deaktivierte Mitarbeiter und Parsefehler erzeugen keine Buchung. Rohdaten sind auf eine einzelne, maximal 2.000 Zeichen lange ATTLOG-Zeile begrenzt; PINs und Schlüssel werden nicht angenommen oder protokolliert. Der gesamte Request ist auf 256 KiB begrenzt.

## Emulator

Nur das bestätigte konservative ATTLOG-Grundformat wird erzeugt:

```bash
TERMINAL_SUPPORT=true uvicorn app.main:app --host 0.0.0.0 --port 8000
python tools/sc800_emulator.py --serial TEST001 --user 17 --timestamp '2026-09-07 08:00:00'
```

Danach Gerät freigeben, Mitarbeiter-ID `17` zuordnen und erneut mit einem neuen Zeitstempel senden. Der Emulator beansprucht nicht, die vollständige SC800-Firmware nachzubilden.

## Fehlersuche

- **404:** `TERMINAL_SUPPORT` ist nicht `true` oder Proxy routet `/iclock/` nicht.
- **pending/unbekannt:** Seriennummer im Adminbereich freigeben.
- **Unbekannter Benutzer/Karte:** Terminal User ID exakt zuordnen; Kartenfeld ist im SC800-ATTLOG noch zu verifizieren.
- **Doppelt:** Normal bei Retry; nur ein `TerminalEvent` und eine fachliche Zustandsänderung entstehen.
- **Uhrzeit falsch:** Gerät, NTP und `Europe/Berlin` prüfen. Rückgestellte DST-Stunde am echten Gerät testen; ohne eindeutigen Offset/Eventzähler kann eine lokale Zeit prinzipbedingt mehrdeutig sein.
- **Offline:** DNS/Route/Firewall/Zertifikatskette prüfen. Nachlieferung erscheint mit alter Ereigniszeit und neuer Empfangszeit.
- **Nicht verarbeitet:** `terminal.log` und „Letzte Terminalereignisse“ prüfen; keine Roh-PINs/Schlüssel in Tickets kopieren.

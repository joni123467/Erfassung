# Release Notes 0.10.1

## Behobener Fehler

**Mobil ließ sich kein Auftrag mehr starten, sobald die Arbeitszeit lief.**

In der mobilen App stand die Schaltfläche „Auftrag starten“ nur im Start-Block
(Zustand „nichts läuft“). Bis 0.9.21 blieb dieser Block trotz `hidden` sichtbar,
weil die Layoutregel `display: grid` das HTML-Attribut überstimmte – der Knopf
war dadurch **zufällig** auch bei laufender Arbeitszeit erreichbar. Die
Korrektur dieser Anzeige in 0.9.22 blendete den Block richtigerweise aus und
nahm damit die einzige mobile Möglichkeit mit, einen Auftrag zu starten oder zu
wechseln, während die Arbeitszeit läuft.

„Auftrag starten“ steht jetzt in **beiden** Zuständen zur Verfügung – in der
mobilen App und in der Offline-Shell. Auf dem Desktop war der Knopf schon immer
in beiden Zuständen vorhanden; dort ändert sich nichts.

## Verhalten

Unverändert: Wird bei laufender allgemeiner Arbeitszeit ein Auftrag gestartet,
wird die laufende Buchung beendet und der Auftrag läuft weiter. Ein bereits
laufender Auftrag lässt sich auf demselben Weg wechseln.

## Datenbank

Keine Migration.

## Upgrade-Hinweise

Standard-Update genügt. Mobile Geräte holen die neue Oberfläche über die übliche
PWA-Aktualisierung (siehe 0.9.13).

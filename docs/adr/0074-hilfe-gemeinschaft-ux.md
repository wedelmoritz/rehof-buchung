# 0074 – UX-Feinschliff: Karma-Erklärung, Hilfe-Gliederung, „unbegrenzte Wünsche", Quartals-Kurve, PIN-Platzierung

## Status

Accepted (2026-06-29)

> Verfeinert ADR 0073 (Losung-UX/Karma), 0063 (Gemeinschafts-Spiegel) und 0053
> (Terminal-PIN im Profil).

## Kontext

Praxis-Feedback zu Verständlichkeit und Auffindbarkeit:

1. Die Karma-Erklärung auf der Wunschliste suggerierte einen Anstieg **je nicht
   erfülltem Wunsch**. Tatsächlich steigt der Faktor **einmal je Auslosung** um
   0,1 (sobald mindestens ein echter Verlust vorlag; `had_genuine_loss` ist ein
   Boolean, `lottery.py`). Die Formulierung war also fachlich ungenau.
2. Auf der **Hilfeseite** stand unter „Gemeinschaft & Transparenz" einiges zum
   **Losverfahren** (Karma, Entzerren, Verifizierbarkeit) – thematisch vermischt.
3. Es fehlte eine Erklärung, **warum** es im Sinne der Gemeinschaft ist, dass alle
   beliebig viele Wünsche eintragen dürfen – inkl. der Kehrseite (viele Rückfall-
   Wünsche lassen den Kalender überall „beliebt" wirken, obwohl nur die halbe
   Tagezahl tatsächlich vergeben wird).
4. Der **Gemeinschafts-Spiegel** zeigte nur die nächsten zwei Monate Auslastung.
5. Im **Profil** war die Hofladen-PIN oberhalb der eingeklappten „Anmeldedaten"
   platziert – gewünscht: PIN **darunter**, dauerhaft sichtbar (nicht eingeklappt).

## Entscheidung

**1) Karma-Erklärung präzise & positiv.** Auf der Wunschliste: „Geht dir in einer
Auslosung ein sehr beliebter Wunsch nicht auf, steigt dein Faktor fürs nächste Jahr
um 0,1 (**je Auslosung**, höchstens 1,5) … Nach dem Gewinn eines sehr beliebten
Wunsches geht er wieder auf 1,0." Kein „je Wunsch", kein „Pech" (ADR 0073). Der
veraltete Profil-Link für den eigenen Faktor zeigt jetzt auf die **Wunschliste**.

**2) Hilfe nach Tätigkeiten gegliedert.** Die Losung-Themen (Karma, Entzerren,
Verifizierbarkeit) stehen vollständig unter **„Wunschliste & Auslosung"**; der
Abschnitt **„Gemeinschaft & Transparenz"** führt nur noch die Gemeinschafts-
Funktionen (Spiegel, Solidaritäts-Pool, Danke sagen) und verweist für die Losung
dorthin.

**3) „Warum beliebig viele Wünsche?" erklärt (mit Beispiel).** Neuer Aufklapp-
Abschnitt unter „Wunschliste & Auslosung": Zusatzwünsche sind ehrlicher Rückfall,
das Verfahren ist strategiesicher (Reihenfolge hängt nur an Karma+Zufall) → mehr
Wünsche drängen niemanden zurück, nutzen aber freie Zeiten. **Beispiel** (20×
Pfingsten + Sommerwoche). **Analyse-Ergebnis**: Den Kalender auf die „obersten 25
Tage je Person" zu filtern wäre **falsch** – ein nachgeordneter Wunsch konkurriert
real, sobald ein höherer belegt ist; und welche Wünsche am Ende zählen, hängt vom
Ausgang der ganzen Ziehung ab (keine feste Top-Liste). Darum zeigt der Kalender
bewusst **alle** eingereichten Wünsche (ehrlichstes Nachfrage-Bild). **Kein
Algorithmus-Eingriff.**

**4) Gemeinschafts-Spiegel: Quartals-Auslastungskurve.** Neuer Service
`services.quarter_occupancy_curve(year)` aggregiert die Auslastung des Kalender-
jahres je Quartal und liefert fertige SVG-Koordinaten (viewBox 0 0 320 120). Die
`community.html` zeichnet daraus eine schlanke **Inline-SVG-Kurve** (Fläche + Linie
+ Punkte, **kein JS**, CSP-konform). Der frühere Zwei-Monats-Blick bleibt als
eingeklapptes Detail erhalten.

**5) Hofladen-PIN unter „Anmeldedaten".** Im Profil steht die Terminal-/PIN-Karte
nun **unter** dem eingeklappten Abschnitt „Anmeldedaten" und bleibt **nicht
eingeklappt**.

Betroffen: `booking/templates/booking/wishlist.html` (Karma-Text, `.explain`
leicht abgehoben), `help.html` (Gliederung + neuer Abschnitt), `community.html`
(Kurve + Detail), `profile.html` (PIN-Reihenfolge), `booking/services/dashboard.py`
(`quarter_occupancy_curve`).

## Konsequenzen

**Positiv** – die Karma-Aussage stimmt jetzt mit dem Code überein; die Hilfe ist
klar nach „was kann ich tun" gegliedert; die offene Wunsch-Politik ist begründet
und mit Beispiel belegt; die Jahres-Auslastung ist auf einen Blick als Kurve
sichtbar; die PIN ist dauerhaft auffindbar. **Grenzen** – die Quartals-Kurve nutzt
weiterhin `_month_occupancy` je Monat (12 Aufrufe), getragen vom 10-Minuten-Cache
des Gemeinschafts-Spiegels (ADR 0064). Die Wahl „alle Wünsche zeigen" bleibt eine
bewusste Transparenz-Entscheidung (keine Filterung).

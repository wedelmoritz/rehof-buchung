# 0098 – Übersicht: Belegungsplan höher, Legende entfernt

## Status

Accepted (2026-07-05)

## Kontext

Auf der Übersichtsseite ist der **Belegungsplan** (Tape-Chart) der Held (ADR 0083),
stand aber unter der voll ausgeklappten **„Diese Woche"-Agenda** und einer **Legende**,
die die Balken-Farben den Mitgliedsnamen zuordnete. Beides drückte den Plan nach unten;
die Farb-Legende war zudem redundant.

## Entscheidung

1. **„Diese Woche" standardmäßig eingeklappt** (`<details>`, wie die Benachrichtigungen):
   der Schnell-Überblick bleibt einen Tap entfernt, nimmt aber nur eine Zeile ein –
   der Belegungsplan steht damit weiter oben. Reine Reihenfolge/Progressive-Disclosure,
   kein JS, DOM-/A11y-Reihenfolge unverändert.

2. **Legende entfernt.** Jeder Balken trägt den **Namen** (+ Tooltip mit Zeitraum/
   Personen + Klick öffnet das Tagesdetail); Schulferien-Spalten haben bereits einen
   `title`-Tooltip, „heute" ist selbsterklärend markiert. Die Farb-Zuordnung war damit
   überflüssig. Die **Balken-Farbe bleibt** (dekorativer Gemeinschaftsaspekt,
   `color_map` in `views.overview`), nur die separate `legend`-Liste + `.who-legend`
   entfallen – minimal effizienter und deutlich aufgeräumter.

## Konsequenzen

**Positiv** – der Plan ist sofort sichtbar (weniger Scrollen), die Seite ruhiger; eine
redundante Erklärfläche weniger. Gilt für Mitglieder- **und** Verwaltungs-Ansicht.

**Grenzen** – die Farbe ist ohne Legende nicht mehr „lesbar" als Namens-Code; das ist
gewollt (sie war nie der Identifikator – der Name auf dem Balken ist es).

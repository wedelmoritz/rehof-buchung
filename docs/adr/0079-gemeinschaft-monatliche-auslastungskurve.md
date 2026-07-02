# 0079 – Gemeinschafts-Spiegel: monatliche Auslastungskurve statt Quartals-Kurve + Monatsliste

## Status

Accepted (2026-07-01)

> Verfeinert die Auslastungs-Anzeige aus ADR 0074/0076 (Gemeinschafts-Spiegel).

## Kontext

Die Auslastung der Quartiere wurde im Gemeinschafts-Spiegel doppelt gezeigt:

- eine **Quartals-Kurve** (`quarter_occupancy_curve`, 4 Punkte Q1–Q4) als Inline-SVG,
- **darunter** eingeklappt eine **Monatsliste** (`_year_months_occupancy`, 12 CSS-Balken).

Das war unschön und redundant:

- Die Quartals-Kurve zeigte je Punkt den Prozentwert **über oder unter** dem Punkt.
  Bei niedriger Auslastung rutschte das Wert-Label **unter** den Punkt und landete
  **auf der Quartals-Beschriftung** („Q1"…„Q4") – die Ziffer wurde überdeckt, sichtbar
  blieb oft nur das „Q". Der Graph wirkte kaputt.
- Vier Quartals-Punkte sind grob; die interessante Verteilung übers Jahr (Sommer-
  Spitze, Winter-Täler) war nur im eingeklappten Detail ablesbar.
- Beide Funktionen riefen je **12×** `_month_occupancy` auf → **24 Monatsabfragen**
  pro Seitenaufbau.

## Entscheidung

**Eine monatliche Kurve ersetzt beides** (`services.year_occupancy_curve`).

1. **12 Monatspunkte** (Jan–Dez) als Inline-SVG-Fläche+Linie. Monats-Kürzel unten
   (`Jan`…`Dez`, klein), der **genaue Prozentwert** steht als kleines Label **immer
   über** dem Punkt (nie darunter) und zusätzlich als **`<title>`-Hover/Tap** am
   Punkt (`Mär: 58 % (…Nächte)`) – kein JS, CSP-konform.
2. **Wert-Label kollidiert nie mehr** mit der Monatsleiste, weil es konsequent
   oberhalb des Punktes sitzt (am oberen Rand leicht eingeklemmt). Damit ist der
   „nur Q lesbar"-Fehler strukturell ausgeschlossen.
3. **Der separate, eingeklappte Monats-Detailblock entfällt** – die Kurve zeigt die
   Monatsauflösung ohnehin, das exakte Ergebnis liefert der Hover-Titel.
4. **Effizient:** die Kurve lädt die Belegungen des Jahres **einmal** (Mitglieder +
   bestätigte externe Gäste) und verteilt die Nächte in Python auf die Monate –
   **2 Abfragen** statt 24 (durch `assertNumQueries` abgesichert).

## Betrachtete Alternativen

- **Quartals-Kurve reparieren** (Wert-Label immer oben): behebt den Anzeigefehler,
  bleibt aber grob und lässt die redundante Monatsliste bestehen → verworfen.
- **Nur die Monatsliste, keine Kurve**: weniger „auf einen Blick"; die Kurve zeigt
  Verlauf/Spitzen besser → verworfen.

## Konsequenzen

**Positiv** – eine klare, feinere Darstellung; der Anzeigefehler ist strukturell weg;
weniger Redundanz; deutlich weniger DB-Abfragen. `quarter_occupancy_curve` und
`_year_months_occupancy` sind entfernt; `community_stats` liefert `occ_curve` statt
`occ_quarters`/`occ_months`.

**Grenzen** – 12 kleine Wert-Labels sind kompakt; die exakten Zahlen liest man am
bequemsten über den Hover-/Tap-Titel. Für Screenreader nennt das `aria-label` der
Grafik weiterhin alle Monate mit Prozentwert.

## Nachtrag (Safari-Fix)

Die Schriftgröße der SVG-`<text>`-Elemente wird als **Präsentationsattribut**
(`font-size="…"`) direkt am Element gesetzt, **nicht** über die CSS-`font`-Kurzform.
Grund: **Safari (macOS/iOS) ignoriert die `font`-Kurzform auf SVG-Text** – die Größe
fiel dann auf den Default von 16px (in Nutzer-Einheiten des `viewBox`) zurück, was den
Text riesig, überlappend und unlesbar machte (Achsen-/Wert-Labels „verschmolzen“).
Präsentationsattribute werden von allen SVG-Renderern zuverlässig beachtet; Farbe und
Schriftfamilie bleiben per CSS (beides greift auch in Safari). Die Prozent-Labels
tragen zusätzlich ein „%“ für Klarheit.

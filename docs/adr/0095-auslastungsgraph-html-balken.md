# 0095 – Auslastungsgraph als reines HTML/CSS-Balkendiagramm (kein SVG)

## Status

Accepted (2026-07-05) · ersetzt die SVG-Kurve aus ADR 0079/0074/0076

## Kontext

Der Auslastungsgraph im Gemeinschafts-Spiegel (`community`) war als Inline-**SVG**
umgesetzt. Über mehrere Anläufe blieb er auf **iOS-/macOS-Safari unlesbar**: mal
zeigte WebKit nur den ersten Buchstaben je `<text>`-Label (SVG-Text-Rendering im
skalierten `viewBox`), mal – nach dem Umbau auf HTML-Beschriftungen, die absolut
über der SVG lagen – fehlten die Labels ganz. Die Ursachen sind engine-spezifische
SVG-Eigenheiten, die sich ohne WebKit-Testumgebung nicht zuverlässig ausräumen
lassen.

## Entscheidung

Den Graphen **komplett ohne SVG** neu bauen – als **reines HTML/CSS-Balkendiagramm**:
12 Monatsbalken, deren Höhe per `height: <pct>%` gesetzt wird, mit HTML-Beschriftungen
(Prozent über dem Balken, Monat darunter, Y-Achse 0/50/100 % + gestrichelte
Gitterlinien). Kein `<svg>`, kein `<text>`, keine absolute Positionierung über einer
SVG – nur `<div>`s mit Prozenthöhen. Solche Boxen rendern in **Blink, WebKit und Gecko
identisch**; es gibt keine SVG-Text- oder viewBox-Fallstricke mehr.

**Verifiziert** vor dem Ausliefern per Headless-Chromium-Screenshot (Desktop **und**
Mobil, echte Daten): lesbar, ausgerichtet, mit Kopf-Freiraum für die Werte über hohen
Balken. Auf schmalen Screens werden die 12 Prozent-Labels ausgeblendet (sie würden
überlappen) – Balkenhöhe, Gitterlinien und der Hover-/Tap-Titel je Balken liefern den
Wert weiter; die Kopfzeile nennt zusätzlich **Schnitt** und **Spitze**.

**Effizienz unverändert:** `services.year_occupancy_curve` lädt die Belegungen des
Jahres **einmal** (Mitglieder-`Allocation` + bestätigte `ExternalBooking`) und verteilt
die Nächte in Python auf die Monate – 3 Abfragen (Quarter-Count + 2×) statt 24. Rückgabe
je Monat: `label`, `pct`, `booked`, `possible`; dazu `peak`/`avg` für die Kopfzeile. Die
frühere SVG-Geometrie (`x/y/vy/line/area/axis`) entfällt.

**Konvention (neu):** Für Diagramme im Frontend ist ein HTML/CSS-Balken-/Meter-Ansatz
die Voreinstellung. SVG nur, wo es echte Kurven/Flächen braucht (z. B. Fairness-
Grafik) – und dann Text nach Möglichkeit **nicht** im SVG.

## Konsequenzen

**Positiv** – der Graph ist auf allen Engines lesbar und identisch, schön (Marken-
Terrakotta, gerundete Balken, Gitter) und barrierefrei (`aria-label` mit allen Werten,
`title` je Balken). Weniger Code als die SVG-Variante, keine engine-spezifischen
Sonderfälle mehr.

**Grenzen** – ein Balkendiagramm zeigt Monatswerte diskret statt als fließende Kurve;
für „Auslastung je Monat" ist das sogar die klarere Darstellung. Feiner aufgelöste
Verläufe (z. B. täglich) bräuchten wieder eine echte Kurve – dann SVG-Pfad ohne Text.

# 0067 – Backend-Layout: EINE gestapelte Spalte (ersetzt Float/Flex)

## Status

Accepted (2026-06-28)

> Ersetzt die Layout-Entscheidung **c** aus ADR 0065 (Flexbox auf `#content.colMS`).
> Theme/Farben (ADR 0054/0065), Navigator (ADR 0055/0057) bleiben unverändert.

## Kontext

Das Backend wirkte – per Screenshot auf Desktop **und** Smartphone geprüft –
unaufgeräumt, vor allem auf der **Startseite**:

- Der in ADR 0065 (c) eingeführte Flexbox-Kniff (`@media (min-width:1024px)
  #content.colMS { display:flex }`) machte **jedes** direkte Kind von `#content`
  zum Flex-Element – also auch den von Django gerenderten Seitentitel `<h1>`
  („Verwaltung") und sonstige Blöcke. Folge: Titel, Erklär-Kasten und „Neue
  Benutzer"-Kasten standen **nebeneinander**, „Neueste Aktionen" rutschte als
  schmaler Block nach unten links.
- Zusätzlich verengt Djangos `dashboard.css` den `#content` der Startseite fest
  auf `width:600px; margin-right:300px` (Reste der alten zweispaltigen App-Liste,
  die wir längst durch den Navigator ersetzt haben) – die Seite nutzte nur den
  linken Drittel-Streifen.

Die Unterseiten (Listen/Formulare) waren bereits brauchbar, aber **uneinheitlich
breit** gegenüber der Startseite.

## Entscheidung

**Ein einziges, simples Layout für ALLE Seiten – eine Spalte, von oben nach unten
gestapelt, identisch auf Desktop und Mobil.** Best practice für einen schlanken
Admin: keine fragilen Float-/Flex-Spalten, sondern ein vorhersagbarer Block-Stapel.

- Djangos Float-Spalten werden aufgehoben: `#content-main` und `#content-related`
  sind `float:none; width:auto` → sie stapeln sich (Navigator → Titel → Inhalt →
  Seitenspalte mit Filter bzw. „Neueste Aktionen"). Die Reihenfolge ist auf jeder
  Seite gleich; nichts überlappt, nichts verstreut sich.
- Der Flexbox-Kniff aus ADR 0065 (c) entfällt ersatzlos – damit kann der
  Seitentitel nicht mehr zum Flex-Element verkommen.
- Die Startseite bekommt **volle Breite** (`#content` `width:auto; margin-right:0`
  statt 600px/300px) – konsistent mit Listen und Formularen.
- Die redundante Startseiten-Überschrift „Verwaltung" wird ausgeblendet (die Marke
  steht schon in der Kopfzeile, der Navigator zeigt die Bereiche).
- „Neueste Aktionen"/Filter erscheinen als ruhige, klar begrenzte **Karte** unter
  dem Inhalt – volle Breite, statt schmal angeflanscht.

Die changelist-Filter (`#changelist-filter`) bleiben als eigene, von Django
responsiv gehandhabte Spalte rechts auf breiten Schirmen (auf dem Handy stapeln sie
ohnehin) – das funktionierte und ist eine bewährte, gut lesbare Anordnung.

## Betrachtete Alternativen

- **Flexbox/Float reparieren** (jedes Streukind einzeln platzieren): bleibt
  fragil, sobald Django neue Blöcke rendert – verworfen.
- **CSS-Grid mit zwei Spalten:** mächtiger, aber Streukinder (Titel/Navigator)
  müssten explizit verankert werden – mehr Komplexität ohne Mehrwert für die
  kleinen Datenmengen hier. Einspaltig ist robuster und mobil-first.
- **Feste max-Breite/zentriert:** bewusst nicht – Listen/Tabellen profitieren von
  voller Breite; die Kopfzeile bleibt randlos, der Inhalt füllt den Rahmen.

## Konsequenzen

**Positiv** – Start-, Listen- und Formularseiten sehen auf Desktop UND Handy gleich
ruhig und aufgeräumt aus (per Screenshot verifiziert); kein verrutschter Kasten,
keine Nebeneinander-Stapel, einheitliche Breite. Das Layout ist vorhersagbar und
kann nicht mehr durch zusätzliche Django-Blöcke „auseinanderfallen". **Grenzen** –
„Neueste Aktionen" steht nun unter (statt neben) dem Inhalt; bei sehr breiten
Tabellen scrollen Inline-/Listen-Tabellen wie gehabt innerhalb ihres Containers
(kein Seiten-Scrollen).

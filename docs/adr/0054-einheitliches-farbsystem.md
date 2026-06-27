# 0054 – Einheitliches Farbsystem (warmes Papier-Neutral + Terrakotta-Akzent)

## Status

Accepted (2026-06-27)

## Kontext

Die App hatte die zwei Re:hof-Markenfarben (Terrakotta `#BE3E23`, Salbei `#7F8F8C`)
übernommen, aber **ohne klare Rollen**: Terrakotta füllte viele große Flächen
(Objekt-Tool-Leisten, Header, viele Knöpfe) und „schrie“ dadurch; Salbei wurde
stellenweise als **Text auf hellen/pastelligen Flächen** benutzt (`#7F8F8C` auf
Creme ≈ 2,5–3:1 Kontrast → **unter** der WCAG-AA-Schwelle 4,5:1, schlecht lesbar).
Dazu kamen vereinzelte Fremdfarben (Grüns `#4f7344`/`#6fa45f`, ein Pfirsich-Knopf
`#c9805d`, ein grüner Terminal-Akzent `#3f7d4f`), die zu keinem System gehörten.
Ergebnis: uneinheitliches, teils unlesbares Bild.

## Entscheidung

**Ein** durchgängiges Token-System mit **klaren Rollen**, identisch in Web-App und
Backend, orientiert an gut lesbaren, aufgeräumten Daten-UIs (Stripe/Linear/Primer/
Tailwind): **ruhige neutrale Grundfläche, near-black Text, der Akzent rar.**

**Foundation (warmes Papier-Neutral, gewählt vom Auftraggeber):**
`--bg #F6F4F1` (Seite) · `--card #FFFFFF` · `--line #E4DFD8` · `--ink #23201D`
(Text ≈ 15:1) · `--muted #6B6259` (Sekundärtext, ≈ 5,3:1 → AA ✓).

**Akzent Terrakotta – BEWUSST sparsam:** `--accent #BE3E23` nur für
**Aktionen/aktiven Zustand/Fokus** (Primär-Knöpfe, Links, aktive Nav, „Heute“,
Auswahl-Outline), `--accent-deep #9E3119` (Hover), `--accent-soft #FBE9E4`
(Auswahl-/Badge-Tönung). **Nie** als großflächige Füllung.

**Sekundär Salbei – ruhige Stütze:** `--sage #7F8F8C` für Flächen/Chips/Sekundär-
Knopf (weiße Schrift darauf ist ok). **Salbei NIE als Text auf Hell** – dafür
`--sage-deep #566C68` (lesbar) oder `--muted`.

**Semantik harmonisiert (ersetzt die Streufarben):** `--good #2E7D55`,
`--warn #B07314`, `--bad #B23A2A` (jeweils + `*-soft`).

**Funktionale Daten-Farben bleiben absichtlich eigen** (kein Marken-Akzent):
der **Ampel-Kalender** (grün=frei … rot=belegt) signalisiert Verfügbarkeit, die
**Mitglieder-Kategoriefarben** der Übersicht unterscheiden Personen – beides
Daten-Visualisierung mit eigener Semantik, die nicht „auf Marke“ gezogen wird.

**Durchweg angewandt:** `booking/templates/booking/base.html :root` (Quelle der
Tokens), gespiegelt im Backend-Theme `templates/admin/base_site.html`; ebenso
Terminal-Kiosk (`terminal.html` – grüner Akzent → Terrakotta; Abbrechen bleibt
neutraler Ghost-Knopf, **kein** Go/Stop-Konflikt für ältere Nutzer), Offline-Seite
(`offline.html` + Inline-HTML im `sw.js`, Cache `rehof-v4`), Externen-Widget
(`external_embed.html` – Verfügbarkeits-Grün bleibt, die **Buchen-CTA** wird
Terrakotta), `manifest.webmanifest` + `<meta name="theme-color">`.

## Konsequenzen

**Positiv**
- Lesbar (alle Texte ≥ AA), ruhig, modern; der Marken-Akzent wirkt, weil er rar ist.
- Ein einziger Satz Tokens → eine Stelle zum Ändern, konsistent über App + Backend.
- Keine Streufarben mehr; Semantik einheitlich.

**Negativ / Grenzen**
- Statische Seiten mit eigenem `:root`/Inline-Style (Terminal, Offline, Embed)
  müssen bei künftigen Token-Änderungen **mitgezogen** werden (sie erben die
  `base.html`-Variablen nicht).
- Service-Worker-Cache wurde auf `rehof-v4` erhöht, damit Clients die neue
  Offline-HTML bekommen.
- Dark-Mode ist (wie bisher) nicht umgesetzt.

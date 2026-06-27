# 0035 – PWA: installierbar, offline-fähig, responsive Navigation

## Status

Accepted (2026-06-26)

## Kontext

Mitglieder nutzen die App überwiegend am Smartphone, oft mit wackeligem Netz (Hof,
ländliche Lage). Eine App-Store-App wäre teurer Eigenbau und Pflegeaufwand für ein
kleines Projekt. Die Bedienung soll am Handy app-artig und auch offline robust sein.

## Entscheidung

Die Web-App ist eine **Progressive Web App** – installierbar und offline-tauglich,
ohne native App.

- **Installierbar:** Manifest `booking/static/booking/manifest.webmanifest` + Icons;
  „Zum Home-Bildschirm hinzufügen“ (iOS/Android).
- **Offline:** Service Worker (`/sw.js`, Root-Scope) mit **network-first** +
  Offline-Fallback (`/offline/`); Registrierung am Ende von
  `booking/templates/booking/base.html` (`navigator.serviceWorker.register("/sw.js")`,
  `base.html:450-452`). `sw`/`offline` sind von der Aktivierungs-Sperre (ADR 0015)
  ausgenommen.
- **Responsive Navigation:** Desktop = einklappbare Seitenleiste (`.sidenav`,
  Zustand in `localStorage`, im `<head>` gesetzt → kein FOUC); Smartphone = feste
  untere Tab-Leiste (`.tabbar`) + Bottom-Sheet „Mehr“. Icons als einmaliges
  SVG-Sprite.
- **Kein seitliches Seiten-Scrollen am Handy:** Horizontales Scrollen der ganzen
  Seite ließ den sticky-Banner nur über die ursprüngliche Breite spannen und
  „abbrechen“. Lösung: `html`/`body` mit `overflow-x:clip` (statt `hidden`, damit
  `position:sticky` erhalten bleibt); am Handy ist die `.shell` ein **Block** statt
  Flex-Spalte (die Sidebar ist aus, die Tab-Leiste `position:fixed`), damit ein
  breiter Inhalt den Hauptbereich nicht über die Bildschirmbreite dehnt. Breite
  Inhalte (Belegungs-Zeitstrahl `.occ`, Datentabellen `.table-wrap`) scrollen in
  **ihrem eigenen** Wrapper; lange Zeichenketten brechen um (`overflow-wrap:anywhere`).
- **Erreichbarer Warenkorb am Handy:** Da der Hofladen-Korb am Handy unter den
  ganzen Katalog rutscht, gibt es einen **schwebenden Warenkorb-Knopf** (`.cart-fab`)
  mit Symbol, Artikel-Anzahl und Summe, der zum Korb springt (am Desktop ausgeblendet,
  dort steht der Korb sichtbar in der rechten Spalte).

## Betrachtete Alternativen

- **Native App (iOS/Android):** zwei zusätzliche Codebasen, App-Store-Prozesse,
  laufende Pflege – unverhältnismäßig.
- **Nur responsive Website ohne Service Worker:** keine Installierbarkeit, kein
  Offline-Verhalten.
- **Cache-first-Strategie:** Risiko veralteter Inhalte; network-first hält die
  Daten aktuell und nutzt den Cache nur als Fallback.
- **`overflow-x:hidden` gegen Seiten-Überlauf:** macht den Wurzelknoten zum
  Scroll-Container und kann `position:sticky` brechen – deshalb `clip`.
- **Warenkorb-Knopf direkt zur Kasse:** verworfen zugunsten „springt zum Korb“,
  damit Mengen vor dem Checkout noch prüf-/änderbar bleiben.

## Konsequenzen

**Positiv**
- App-artige Nutzung am Handy ohne App-Store; robuster bei schlechtem Netz.
- Eine Codebasis (Django) für Web und „App“.

**Negativ**
- Service-Worker-Caching kann tückisch sein (Update-/Invalidierung); network-first
  mildert das.
- PWA-Fähigkeiten/Installations-UX variieren je Browser/OS (v. a. iOS).

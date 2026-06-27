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
- **Sichtbare Bestätigungen (Toasts) + AJAX-Navigation:** Früher landeten Meldungen
  als Zeile **oben** im Inhalt; nach dem Redirect sprang die Seite nach oben und der
  Hinweis wurde leicht übersehen. Jetzt werden **Django-`messages`** (Feedback auf
  eine aktive Aktion) als **fixierte Toasts** angezeigt (sichtbar unabhängig von der
  Scrollposition, kurz eingeblendet, in `base.html`). **Abgrenzung:** Nur die
  Framework-`messages` tragen das Attribut `data-toast` und werden eingesammelt –
  **fest im Template stehende `.msg`-Banner** (Status-/Hinweis-Banner wie
  „Losverfahren offen“) und die **Benachrichtigungs-Karte** (`.notif`, „Aktuelle
  Nachrichten“ auf der Übersicht: Losergebnis, Wartelisten-Platz, Rechnung etc.)
  bleiben bewusst **an Ort und Stelle** (`harvest('.msg[data-toast]')`).
- **AJAX-Navigation ohne Neuladen:** **POST-Formulare** werden progressiv per `fetch`
  abgeschickt (Antwort nach Redirect geparst, `<main>` getauscht inkl. Re-Ausführung
  der Inline-Skripte, **Scrollposition gehalten**, Meldung als Toast). Zusätzlich
  werden **GET-Navigationen im Kalender** (Tag wählen Anreise→Abreise, Monat blättern,
  Auswahl zurücksetzen) ohne Neuladen ausgeführt: `window.__nav(url)` holt die Seite
  per `fetch`, tauscht `<main>` und **hält die Scrollposition** – kein Sprung nach
  oben mehr beim Datums-Klick. Opt-in über `data-ajax` an Links/GET-Formularen
  (`book`/`wishlist`/`external_home`-Kalender + gemeinsame Monats-Navigation
  `_calnav.html`, Monat/Jahr-Selects über `__nav`). Reine Progressive Enhancement –
  ohne JS, bei Fehlern oder Modifier-Klick (neuer Tab) greift das normale Laden;
  ausgenommen sind `multipart`-Uploads und die Auth-Formulare (`data-no-ajax`).

## Betrachtete Alternativen

- **Native App (iOS/Android):** zwei zusätzliche Codebasen, App-Store-Prozesse,
  laufende Pflege – unverhältnismäßig.
- **Nur responsive Website ohne Service Worker:** keine Installierbarkeit, kein
  Offline-Verhalten.
- **Cache-first-Strategie:** Risiko veralteter Inhalte; network-first hält die
  Daten aktuell und nutzt den Cache nur als Fallback.
- **`overflow-x:hidden` gegen Seiten-Überlauf:** macht den Wurzelknoten zum
  Scroll-Container und kann `position:sticky` brechen – deshalb `clip`.
- **Voll-SPA / htmx-Abhängigkeit für die AJAX-Formulare:** verworfen zugunsten eines
  kleinen, abhängigkeitsfreien Progressive-Enhancement-Layers, der mit den bestehenden
  server-gerenderten Views (Redirect-nach-POST) arbeitet.
- **Meldung nur ans Seitenende verschieben / hochscrollen:** löst die Sichtbarkeit
  nicht zuverlässig; fixierte Toasts sind scrollunabhängig.
- **Alle `.msg`-Banner als Toasts einsammeln:** verworfen – dauerhafte Status-Banner
  und die Benachrichtigungs-Karte („Aktuelle Nachrichten“) sollen sichtbar **stehen
  bleiben**; nur das aktive Aktions-Feedback (`messages`) blitzt als Toast. Daher die
  `data-toast`-Markierung statt „alles, was `.msg` ist“.
- **Auch Tagesdetail/Ansicht-Umschalter der Übersicht per AJAX:** vorerst nicht –
  deren `#tag`-Anker leben vom Sprung zum Detail; die scrollerhaltende AJAX-Naht
  passt dort nicht ohne Zusatzlogik. Bewusst auf die Kalender-Auswahl beschränkt.
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

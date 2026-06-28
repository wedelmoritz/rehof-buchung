# 0065 – Backend-Theme-Konsolidierung & UX-Fixes (Selbsttest-Findings)

## Status

Accepted (2026-06-28)

> Verfeinert ADR 0054 (einheitliches Farbsystem), 0055/0057 (Navigator) nach
> Selbsttest-Findings aus dem laufenden Betrieb (Desktop **und** Smartphone).

## Kontext

Beim Selbsttest fielen mehrere Backend-/Verwaltungs-Probleme auf:
- **Farben (f):** Djangos Admin hat **drei** Theme-Modi (Hell/Dunkel/Auto). Das
  warme Re:hof-Theme war nur in `:root` definiert; Djangos Dunkel-/Auto-Werte
  (höhere Spezifität via `[data-theme]`/`prefers-color-scheme`) überschrieben es →
  unlesbare graue Überschriften im Hellmodus, Blau-/Gelb-Mix im Auto-Modus,
  weiß-auf-weiß im Dunkelmodus.
- **„Neueste Aktionen" (c):** rutschte im Float-Layout unter den Inhalt statt oben
  rechts anzudocken.
- **Navigator mobil (d):** war per Default **eingeklappt** – man sah als Admin gar
  nicht, was man tun kann, nur den „Neue Benutzer"-Kasten.
- **Static devices (e):** ein englischer, ungenutzter OTP-Backup-Eintrag.
- **Onboarding (g):** das Feld „Bezeichnung (nur bei neuem Anteil)" stand verwirrend
  immer da.
- **Dashboard-Sprungleiste (b):** auf dem Handy nicht klebend (zwei Zeilen Umbruch).

## Entscheidung

**f) EIN warmes Hell-Theme in allen Modi.** Die Theme-Variablen werden mit
`!important` gesetzt (schlagen Djangos Dunkel-/Auto-Werte zuverlässig, unabhängig von
Spezifität/Media-Query); Flächen/Eingabefelder, die der Dunkelmodus dunkel färbt,
werden hell erzwungen. Der **Modus-Umschalter wird ausgeblendet** (`.theme-toggle`),
da das Backend bewusst – wie das Frontend – **ein** Theme hat. Onboarding-Überschriften
explizit dunkel.

**c) „Neueste Aktionen" oben rechts** via Flexbox: `#content.colMS` wird ab 1024 px
Flex; der Navigator nimmt die ganze erste Zeile (`flex 1 1 100%`), darunter Inhalt
links + „Neueste Aktionen" rechts (`sticky`), beide oben ausgerichtet – ersetzt das
fragile Django-Float-Layout.

**d) Navigator per Default AUF** (Desktop **und** mobil; reine Klassen-Steuerung, die
Mobile-Default-Collapse-Media-Query entfällt). **Kehrt die mobile Default-Entscheidung
aus ADR 0057 um**: Sichtbarkeit („was kann ich tun?") wiegt schwerer als die paar
gesparten Pixel; manuelles Einklappen wird weiterhin gemerkt. Der **„Neue Benutzer"-
Kasten** ist nun ein per Default **eingeklapptes** `<details>` mit **Anzahl-Badge** im
Summary – Dringlichkeit sichtbar, ohne den Blick auf den Navigator zu verstellen.

**e) Static devices entfernt:** `RehofAdminConfig.ready()` meldet `StaticDevice` nach
dem Autodiscover ab (wir nutzen nur TOTP). Das **TOTP-Gerät** wandert in die Sektion
„Administratives & Logs".

**g) Onboarding zweistufig:** Im Anteil-Select stehen bestehende Anteile zuerst, „Neuen
Anteil anlegen …" zuletzt. Die **„Bezeichnung des neuen Anteils"** erscheint **nur**,
wenn „neu" gewählt ist – **rein per CSS** (`:has(select … option[value=new]:checked)`),
ohne JS (CSP-konform; Browser ohne `:has` zeigen es als harmlosen Fallback immer).

**b) Dashboard-Sprungleiste mobil klebend:** Auf dem Handy klebt sie **direkt unter dem
(sticky) Header** (`top: calc(48px + env(safe-area-inset-top))`) und scrollt **einzeilig
horizontal** statt auf zwei Zeilen umzubrechen.

## Betrachtete Alternativen

- **Drei Theme-Modi sauber unterstützen** (eigene Dunkel-Palette): verworfen – das
  Frontend hat bewusst nur ein warmes Hell-Theme; Konsistenz schlägt Dark-Mode.
- **Navigator-Höhe per JS messen für die Sprungleiste:** verworfen – `env()`-CSS ist
  ausreichend robust und ohne JS/CSP-Aufwand.

## Konsequenzen

**Positiv** – Backend wirkt aufgeräumt, lesbar und konsistent zum Frontend; mobil sieht
man sofort die Bereiche; Onboarding ist selbsterklärend; keine verwirrenden Fremd-
Einträge. **Negativ/Grenzen** – der Dark-Mode entfällt bewusst; bei sehr schmalen
Geräten mit umbrechendem Header kann die Sprungleiste minimal überlappen (vertretbar).

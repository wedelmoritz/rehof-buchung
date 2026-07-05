# 0085 – Verwaltung: echte Unterseiten (Menü-Einträge) statt Dashboard-Tabs

## Status

Accepted (2026-07-05) · ersetzt Punkt 2 („Dashboard-Tabs", #59) aus ADR 0084

> Tester-Feedback der Betriebsleitung (Sophie), Folge zu ADR 0084.

## Kontext

ADR 0084 hatte die vier langen operativen Abschnitte des Dashboards
(Reinigung · Buchungen · Rechnungen · Kontoabgleich) in **Client-nahe Tabs**
(`?tab=` + `data-ajax`) gebündelt. Das Feedback dazu:

- Tabs auf **einer** URL sind weniger übersichtlich als **eigene Navigations-
  Einträge** – man sieht nicht auf einen Blick, was es gibt, und kann nicht direkt
  verlinken/als Lesezeichen speichern.
- Der **Überpunkt „Verwaltung"** sollte nicht selbst eine der Listen sein, sondern
  **zusammenfassen, was jetzt zu tun ist** (neue/geänderte Buchungen, offene
  Endreinigungs-Anfragen, überfällige Rechnungen, Kennzahlen).
- „Endreinigung nachträglich ändern" war **zu breit** (horizontaler Scroll).
- **Kein** getrennter Menüpunkt „Reinigung" vs. „Endreinigung": nach **jeder**
  Abreise wird (unbezahlt) gereinigt; die gebuchte, bezahlpflichtige **Endreinigung**
  ist nur ein Zusatz und gehört fachlich in **dieselbe** Reinigungs-Seite.
- Der **Hofladen-Katalog** soll ein eigener Verwaltungs-Menüpunkt sein.
- Der **Beds24-Import** ist ein **einmaliger, admin-seitiger Umzugs-Task** und gehört
  ins **Backend**, nicht ins Verwaltungs-Dashboard.

## Entscheidung

**Aus den Tabs werden echte, geroutete Unterseiten mit eigenen Menü-Einträgen; das
Dashboard wird zur Handlungsbedarf-Übersicht.**

1. **Eigene Seiten/URLs + Menü-Einträge.** Jede Sektion ist eine eigene View/URL
   unter `/verwaltung/…` und ein eigener Nav-Link (Seitenleiste + „Mehr"-Sheet),
   sichtbar für `is_verwaltung`, als eingerückte Unterpunkte unter „Verwaltung":
   - `verw_buchungen` (`/verwaltung/buchungen/`) – anstehende Buchungen
   - `verw_reinigung` (`/verwaltung/reinigung/`) – **Reinigung inkl. Endreinigung**
   - `verw_rechnungen` (`/verwaltung/rechnungen/`) – Rechnungen + Erinnerungen
   - `verw_konto` (`/verwaltung/kontoabgleich/`) – Kontoabgleich
   - `verw_auslastung` (`/verwaltung/auslastung/`) – Statistik + Auslastungs-Ampel
   - `dashboard_products` (`/verwaltung/produkte/`) – Hofladen-Katalog

2. **„Verwaltung" (`/verwaltung/`) = Handlungsbedarf.** Das Dashboard zeigt nur
   noch „jetzt handeln": Kompakt-Kennzahlen (Monat) + drei Karten – offene
   **Endreinigungs-Anfragen** (mit Inline-Bestätigen/Ablehnen), **überfällige
   Rechnungen**, **neue & geänderte Buchungen** der letzten 7 Tage
   (`services.recent_booking_activity`: neue `Allocation` + `CancellationLog`).
   Jede Karte verlinkt auf die volle Unterseite.

3. **Reinigung + Endreinigung auf EINER Seite.** `verw_reinigung` trägt die
   Reinigungsliste (alle Abreisen = Reinigungstage, Spalte „Endreinigung gebucht") und
   darunter „Endreinigung freigeben" (#28) samt „Nachträglich ändern" (#45). Der
   frühere separate Menüpunkt/`verw_endreinigung`-View entfällt. Die Freigabe-Liste
   ist als **kompakte, umbrechende Karten** (`.er-item`, flex-wrap) statt breiter
   Tabelle gebaut – **kein horizontaler Scroll** mehr.

4. **Gemeinsame Bausteine.** `verw_base.html` hält das Layout + das gesamte CSS;
   jede Unterseite füllt `verw_h1`/`verw_body`. `_verw_monthbar.html` ist die
   gemeinsame Monatswahl (GET, `data-ajax`). Ein zentraler POST-Dispatcher
   (`views._verw_post`) verarbeitet alle Aktionen und leitet auf die passende
   Unterseite zurück (Monat/Filter erhalten) – so bleibt die Logik an einer Stelle.

5. **Beds24-Import ins Backend.** Der Assistent ist aus dem Dashboard entfernt und
   erscheint als Kasten auf der **Backend-Startseite** (`custom_index.html`) – nur für
   Superuser und solange in den Betriebs-Einstellungen freigeschaltet
   (`admin_site.index` liefert `beds24_import_enabled`). Die URL/View bleibt
   unverändert (`/verwaltung/beds24-import/`, admin-geschützt).

## Konsequenzen

**Positiv** – jede Sektion hat eine eigene, verlinkbare URL und einen Menü-Eintrag;
das Dashboard ist ein scanbares Cockpit statt einer Tab-Leiste; die Reinigung ist
fachlich zusammengeführt und mobil-tauglich; der einmalige Beds24-Task liegt dort,
wo er hingehört (Backend/Admin). Weiterhin **server-getrieben + CSP-treu** (GET-Nav
via `data-ajax`, keine Client-Tabs), rein View-/Template-seitig (keine Migration).

**Grenzen** – mehr Menü-Einträge in der Verwaltungs-Nav (bewusst, als eingerückte
Unterpunkte gruppiert; im eingeklappten Icon-Modus ausgeblendet). Der bisherige
`?tab=`-Deeplink-Stil aus ADR 0084 entfällt (durch echte URLs ersetzt).

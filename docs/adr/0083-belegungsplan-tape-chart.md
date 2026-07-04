# 0083 – Belegungsplan als Tape-Chart (Option A): Datums-Anker, Halbtags-Wechsel, rollen-abhängiges Tagesdetail, Druck

## Status

Accepted (2026-07-04)

> Erweitert den Belegungs-Zeitstrahl der Übersicht (ADR 0059) zum vollwertigen
> Betriebs-Werkzeug. Aus Tester-Feedback der Betriebsleitung (Sophie): #38, #39,
> #40, #41, #42, #46, #47.

## Kontext

Der bisherige Belegungs-Zeitstrahl war **monats-gebunden** (`build_occupancy_timeline(
member, year, month)`), alphabetisch sortiert und stellte Buchungen als volle
Tages-Balken dar. Für die tägliche Arbeit der Betriebsleitung (BL) reichte das nicht:

- **#38** Reihenfolge/Vollständigkeit: Die BL ist an die **beds24-Sortierung** (nach
  Gebäude) gewöhnt; alphabetisch verrutscht das Auge, und Sonder-Einheiten fehlten.
- **#40** Ein sauberer **Belegungswechsel** (A reist ab, B reist am selben Tag an)
  sah wie eine **Doppelbelegung** aus – volle Tages-Balken stoßen hart aneinander.
- **#41** Nur Monats-Dropdown; kein **konkretes Startdatum** wählbar („MG reist am
  6.7. an" → Plan soll dort beginnen).
- **#42** Quartiers-Zeilen schlecht unterscheidbar.
- **#46b/#47** Externe nur als „extern" ohne Kontakt; das Tag-Popup zeigte
  mitglieds-orientiert „freie Quartiere / hier buchen" statt BL-Belegungsdetails.
- **#39** Die BL **druckt** den Plan täglich fürs Team.

Der Nutzer hat **Option A** (dicht, beds24-nah) aus einem bebilderten Zwei-Optionen-
Konzept gewählt – **ein** responsiver Plan (kein Web/Handy-Split, kein Umschalter),
Zebra bewusst **weggelassen** (kollidiert mit der Gebäude-Tönung).

## Entscheidung

**Belegungsplan als klassischer Tape-Chart** (Industriestandard: beds24, Cloudbeds,
Mews) – Unterkünfte als Zeilen, durchgehende Datumsachse als Spalten, Buchungen als
Balken. Ein Plan für **beide Rollen**; die Verwaltung bekommt Zusatzinfos
**eingeblendet** (serverseitig entschieden, nicht per CSS versteckt).

1. **Reihenfolge & Gruppen (#38/#42):** neues Feld `Quarter.sort_order`
   (Default 0 = wie bisher alphabetisch; die BL vergibt im Backend die
   beds24-Reihenfolge). `Quarter.Meta.ordering = ["sort_order", "name"]` (bei
   Default 0 ein No-op). Zeilen werden nach `building` in **Gebäude-Bänder**
   gruppiert (fortlaufende Läufe nach `sort_order`) – ruhige Trennung **ohne Zebra**.
   Die Sonder-Einheiten (Zelt/Bully/Kaminlounge …) legt die Verwaltung als
   `Quarter` an; der Plan zeigt sie automatisch – **nicht** hartkodiert.

2. **Halbtags-Wechsel (#40):** je Tag ZWEI Sub-Spalten (`n_sub = span_days*2`).
   Ein Balken beginnt an der **PM-Kante** des Anreisetags (`col_start = 2·a+2`) und
   endet an der **AM-Kante** des Abreisetags (`col_end = 2·c+1`, checkout-exklusiv).
   Ab- und Anreise am selben Tag treffen sich so an der **Tagesmitte** statt sich zu
   überlappen – die Schein-Doppelbelegung verschwindet. Balken, die vor/nach dem
   Fenster liegen, werden geklammert und offen dargestellt (`open_left/right`).

3. **Datums-Anker & Bereich (#41):** `build_occupancy_timeline(member, anchor,
   span_days, management)` statt Monat. Steuerleiste: **„Ab" (Datum)** + **1/2/4
   Wochen** + ‹ Heute › + (Verwaltung) **Drucken**. GET-Parameter `from`/`weeks`,
   AJAX-navigiert (kein Reload, Position bleibt). Default-Anker = heute.

4. **Rollen-abhängig (#46b/#47):** `management=True` (Verwaltung/BL) zeigt externe
   Gäste mit **Klartext-Name + Personen** im Balken und im **Tagesdetail** zusätzlich
   Kontakt (E-Mail); Mitglieder sehen nur „extern". Das **Tagesdetail** ist klar
   getrennt nach **Anreise / Abreise / Anwesenheit** (Arrivals/Departures/Stayovers,
   Standard professioneller PMS) – behebt die widersprüchliche „Wer ist da"-Liste.
   Endreinigung als **dezentes 🧹-Symbol** am Balken/an der Abreise (#46c), keine
   laute Farbe. Pro Tag zeigt der Kopf die **Zahl freier Unterkünfte**.

5. **Druck als PDF (#39):** Der **Drucken**-Knopf (nur Verwaltung) verlinkt auf
   `plan_pdf` (`/verwaltung/belegungsplan.pdf?from=&weeks=`) und erzeugt ein
   **Querformat-PDF** (A4 quer) via WeasyPrint – dieselbe Infrastruktur wie das
   Rechnungs-PDF (`booking/plan_pdf.py`, HTML-Bau von Render getrennt, SSRF-sicherer
   `_no_remote_fetcher`). Best Practice professioneller PMS: **Querformat-Raster +
   operative Listen**. Das Druck-Raster ist bewusst **nacht-basiert**
   (`services.build_plan_print`: jede Spalte = eine Nacht → ein Wechsel sind
   benachbarte Zellen, robust als Tabelle mit `colspan`-Balken in WeasyPrint) und
   wird ergänzt um tabellarische **Anreisen / Abreisen / Endreinigungen**. Emoji
   werden im PDF durch font-sichere Kürzel ersetzt (DejaVu Sans). Das `@media print`
   der Bildschirmseite bleibt als schlichter Fallback (Ctrl+P).

6. **Ein responsiver Plan:** dieselbe Darstellung überall; eine Media-Query
   (`max-width:680px`) vergrößert am Handy Zeilenhöhe und Tap-Flächen. Der Plan
   scrollt in seinem eigenen Container (`.tape { overflow-x:auto }`) – die Seite
   scrollt nie seitlich. **Kein** Web/Handy-Split, **kein** Umschalter.

7. **Ziel-Auslastung (Fundament):** neues optionales Feld `Quarter.target_occupancy`
   (%) für die spätere statische Dashboard-Ampel (🔴/🟡/🟢).

## Effizienz / Sicherheit

- **Wenige Queries:** eine Query je Quelle (`Allocation`/`ExternalBooking`) über das
  Fenster, `select_related` auf Quartier/Mitglied/Gast, `_annotate_cleaning`
  (Exists-Subquery) für das 🧹 – kein N+1, auch bei 4-Wochen-Fenster.
- **Sicherheit:** Die Gast-Klartext-/Kontakt-Einblendung ist **serverseitig** an
  `is_verwaltung(request.user)` gebunden (nicht per CSS versteckt). Der Belegungsplan
  selbst zeigt ohnehin nur allgemein sichtbare Belegungsdaten.
- **Parallelität:** rein lesend; keine Schreibpfade berührt.

## Konsequenzen

**Positiv** – die BL bekommt das gewohnte beds24-Bild (Reihenfolge, Wechseltag,
Druck), Mitglieder eine klar lesbare Belegung; ein Plan, eine Codebasis. Die
`day_detail`-Trennung An-/Abreise/Anwesenheit ist auch außerhalb des Plans nützlich.

**Migration** `0050` (`sort_order`, `target_occupancy`, Meta-ordering).

**Grenzen / offen** – Zusatzbett/interne Notiz je Buchung (#62/#84) und die
statische Auslastungs-Ampel (#63/#64) sind eigene, spätere Schritte; die Ampel-
Feld-Grundlage (`target_occupancy`) ist hier schon gelegt. Sonder-Einheiten
(Zelt×n, Bully, Kaminlounge/Event) werden als normale `Quarter` gepflegt; ob sie in
Losung/Buchung mitlaufen bzw. „nur Mitglieder"/„Event" sind, ist eine Daten-/
Regel-Entscheidung der Verwaltung (bewusst nicht hartkodiert).

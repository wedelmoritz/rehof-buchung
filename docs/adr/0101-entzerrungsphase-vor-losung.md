# 0101 – Entzerrungs-/Review-Phase vor der Losung (Freeze, Absprachen, Export)

## Status

Proposed (2026-07-10) · erweitert [ADR 0003](0003-losverfahren-weighted-rsd.md)/
[ADR 0007](0007-nur-eingereichte-wuensche.md) (Losverfahren) · nutzt
[ADR 0062](0062-verifizierbare-auslosung-commit-reveal.md) (Commit-Reveal),
[ADR 0064](0064-kooperative-transparenz-features.md) (Entzerrung P2.4), [ADR 0072](0072-positive-wortwahl-frontend.md)
(Wortwahl), [ADR 0080](0080-wunsch-frist-anzeige-und-erinnerung.md) (Wunsch-Erinnerung),
[ADR 0089](0089-benachrichtigungs-framework.md) (Benachrichtigungen),
[ADR 0095](0095-auslastungsgraph-html-balken.md) (HTML/CSS-Diagramme),
[ADR 0063](0063-gemeinschafts-spiegel-karma-transparenz.md) (Anonymität) · Verwaltungsrechte über
[ADR 0100](0100-granulare-verwaltungsrollen-rbac.md). **In Umsetzung (batchweise).**

> **Umsetzungsstand.** **Batch A (Lebenszyklus-Fundament) umgesetzt (2026-07):** die
> Phase `wishes_review`, `review_days` (Richtlinie + je Periode), die abgeleiteten
> Fristen `review_open`/`freeze_start` und der `display_frozen`-Zustand, `compute_status`/
> Scheduler, `submission_deadline = review_open`, der Phasen-Hinweis mit den zwei Marken
> (Übersicht + Wunschliste) und der serverseitige Wunsch-Guard (`wishes_editable`).
> **Batch B (Prognose) umgesetzt (2026-07):** reine Logik
> `lottery.simulate_win_probabilities` (Monte-Carlo-Trockenlauf der echten RSD, nur
> Zufalls-Seeds) + `lottery.win_band`; Service `wish_prognosis(period)` (kurz gecacht,
> Cache-Schlüssel aus dem Wunsch-Stand, Seed daraus abgeleitet – **nie** der committete
> Seed); Anzeige des Chancen-Bandes je eingereichtem Wunsch auf der Wunschliste
> (positiv: „Gute Chance/Offen/Knapp“ + ≈ %).
> **Batch C–F umgesetzt (2026-07):**
> * **C – Nachfrage-Heatmap** (`wish_demand_grid`): anonyme Quartier×Monat-Heatmap auf
>   der Wunschliste (HTML/CSS).
> * **D – Absprachen + Opt-out** (`Member.coordination_hide_phone/_email`,
>   `wish_coordination`): überlappende Wunsch-Nachbarn je Wunsch mit Name (immer sichtbar,
>   Begegnung) + Kontaktkanälen; Default sichtbar, **je Kanal (Telefon/E-Mail) einzeln
>   verbergbar** im Profil, DSGVO-Hinweise. Governance-Entscheidung (Kontakt by default)
>   bewusst so. *(Batch 2, 2026-07: aus der Einzel-Sichtbarkeit `coordination_opt_out`
>   wurde per-Kanal-Opt-out; die Nachbarn stehen jetzt je Wunsch unter „Details &
>   Aktionen" statt in einem eigenen Abschnitt, samt Chancen-Begründung = Zahl der
>   Überlappungen + eigene Priorität.)*
> * **E – Wunsch-Export + Admin-Nachtrag**: Capability `wuensche`/Unterseite
>   `verw_wuensche` (`export_wishes`) mit xlsx/CSV-Export; `add_wish_for_member`
>   (auditiert, `Wish.created_by`).
> * **F – Snapshots + Hilfe**: `demand_snapshot` (Freeze-Anzeige + „vor"-Export),
>   `capture_wish_snapshots`/Kommando `capture_demand_snapshots` (Scheduler);
>   ausführliche, prosa-geprüfte Hilfeseite `help_content/entzerrung.md` + HTML/CSS-
>   Ablauf-Zeitleiste.
> * **Dringende Erinnerung:** bereits durch Batch A abgedeckt – `submission_deadline =
>   review_open` lässt die bestehenden zweistufigen Wunsch-Erinnerungen (ADR 0080)
>   automatisch auf die Einreiche-Frist greifen (kein separater Mechanismus nötig).
>
> Damit ist ADR 0101 **vollständig umgesetzt.**
>
> **Präzisierung zu Abschnitt 2 (Edits in der Phase).** In der Entzerrungsphase bleibt
> die Wunschliste **bearbeitbar** (Anpassen/Zurückziehen+Neu-Einreichen), ohne **harte**
> Teilnehmer-Sperre: Das RSD-Losverfahren ist strategiesicher (späte Anpassungen bringen
> keinen Vorteil), und ein harter Riegel würde mit dem bestehenden Einreichen/
> Zurückziehen-Ablauf kollidieren (wer zum Anpassen zurückzieht, wäre sonst plötzlich
> „raus“). Die Frist wird klar **kommuniziert** (Chip/Banner + Erinnerung). Eine
> strengere Cutoff-Variante bleibt später nachrüstbar (`wishes_editable` trägt die
> Mitglieds-Signatur bereits).

> **Nachtrag (2026-07): „Einreichen“ abgeschafft.** Der frühere Zwischenschritt
> „Wünsche einreichen/zurückziehen“ (Entwurf `submitted=False` → Lostopf
> `submitted=True`) entfällt. Wünsche sind jetzt **ab dem Eintragen verbindlich** und
> nehmen sofort an der Losung teil – genau wie eine Buchung ab dem Anlegen gilt. Grund:
> Der Submit-Schritt war vor allem eine **Fußangel** („Wunsch eingetragen, aber
> vergessen einzureichen → nicht dabei“); mechanisch braucht die Losung nur den
> **finalen** Wunsch-Stand zum Ziehungszeitpunkt, und die Entzerrungsphase erlaubt
> Anpassen ohnehin bis zur Ziehung. Umsetzung: Feld `Wish.submitted` entfernt,
> `submitted_at`→`added_at` umbenannt (Migration 0072); Services `submit_wishlist`/
> `withdraw_wishlist` gestrichen; `add_wish` setzt `added_at`; alle Zähler/Prognosen/
> Heatmap/Nachbarn/Erinnerungen zählen **alle eingetragenen** Wünsche. Die zweistufige
> Wunsch-Erinnerung (ADR 0080) geht nun an Mitglieder **ohne eingetragenen Wunsch**.
> [ADR 0007](0007-nur-eingereichte-wuensche.md) („nur eingereichte Wünsche“) ist damit
> überholt: es nehmen **alle eingetragenen** Wünsche teil (der Schutz gegen versehentliche
> Teilnahme liegt jetzt im bewussten Eintrag-Schritt, nicht in einem separaten Submit).

> **Nachtrag (2026-07): Wunschlisten-UX aufgeräumt.** Feedback aus der Genossenschaft:
> * **Aufgeräumte Wunsch-Karten:** je Wunsch nur Quartier/Zeitraum + Aufklapper „Details
>   & Aktionen“; **Chance und alle Aktionen** (Priorität, **Zeitraum/Unterkunft ändern**
>   via neuem Service `adjust_wish`, entfernen) stehen **erst dort**.
> * **Ampel statt Prozent:** Die missverständliche Gewinn-Prozentzahl (100 % trotz
>   Mitbewerbern durch gleichwertige Ausweichquartiere) ist raus. Je Wunsch nun eine
>   **Nachfrage-/Beliebtheits-Ampel** aus überlappenden Fremd-Wünschen
>   (`wish_demand_band`: keine/wenige/beliebt/sehr beliebt) **plus** die Los-Chance nur
>   noch **qualitativ** (gut/offen/knapp, ohne %).
> * **Eigen-Überlappung sichtbar:** je Wunsch **ganz oben** im Detail + ein Sammel-Hinweis
>   über der Liste („Einige deiner Wünsche überlappen sich …“).
> * **Zwei Reiter auf einer Seite** (`?view=`, data-ajax): „Meine Wünsche“ (Default) und
>   „Nachfrage & Heatmap“ – Letzterer trägt die Heatmap **und** tabellarische Ranglisten
>   der beliebtesten Unterkünfte/Zeiträume (`wish_demand_ranking`). Das entlastet die
>   Wunsch-Ansicht.
> * **Hilfe:** Ablauf-Zeitleiste als moderner **Stepper** (durchgehende Schiene, `flow-timeline`),
>   und das „Ablauf als Diagramm“ zeigt die **Entzerrungsphase** jetzt als eigenen Schritt.

> **Fachlicher Bezug:** Der Perioden-Lebenszyklus und die Losregeln stehen im
> [Fachkonzept](../FACHKONZEPT.md); dieser ADR ergänzt eine **Phase** darin. Die
> Regelwerte (Vorlauf, Freeze) werden bei der Umsetzung dort nachgezogen.

## Kontext

Heute laufen Wünsche bis zu einem Termin, danach wird gezogen ([ADR 0007](0007-nur-eingereichte-wuensche.md)).
Mitglieder sehen die **Nachfrage** zwar als Ampel und Entzerrungs-Hinweise
([ADR 0064](0064-kooperative-transparenz-features.md)), aber es fehlt eine **klar abgegrenzte Phase**, in der
alle die umkämpften Zeiträume und ihre **realistische Chance** sehen und ihre Wünsche
gezielt **entzerren** können. Ziel: weniger unnötige Losungen, höhere Zufriedenheit,
mehr Transparenz – **ohne** die Strategiesicherheit (RSD/Commit-Reveal) zu verletzen.

## Entscheidung

### 1. Neue Phase im Lebenszyklus + Freeze

Zwischen „Wünsche eintragen" und „Losung" tritt die Phase **`wishes_review`**:

```
Wünsche eintragen        Entzerrungsphase           Freeze (24 h)       Losung
& EINREICHEN             (Nachfrage sichtbar,        (editierbar,        (Ziehung →
                          editierbar)                 Ansicht fix)        Bestätigung)
 │                        │                           │                   │
 ▼                        ▼                           ▼                   ▼
[wishlist_open] ────► [review_open] ─────────► [freeze_start] ─────► [draw_at] ─► Ergebnis
                       = Einreiche-Frist          = draw − 24 h              + Rückblick (ADR 0102)
   ▲ Erinnerungen           ▲ dringende Erinnerung
   (ADR 0080)                 an Nicht-Eingereichte
```

- **Dauer konfigurierbar:** `review_days` (Default **7**) in `BookingPolicy`, je Periode
  über `BookingPeriod.review_days` überschreibbar. Abgeleitet: `review_open = draw_at −
  review_days`.
- **Freeze fest 24 h** (`FREEZE_HOURS = 24`, Konstante, nicht pro Nutzer konfigurierbar):
  ab `freeze_start = draw_at − 24 h` wird die **angezeigte** Nachfrage/Prognose
  eingefroren (Stand von `freeze_start`). **Edits bleiben bis `draw_at` möglich und
  zählen** – nur die *Sichtbarkeit* endet früher (verhindert Last-Minute-Ansturm/
  Oszillation). Zwei kommunizierte Marken: „Nachfrage sichtbar bis …" (Freeze-Start) und
  „Änderungen möglich bis …" (`draw_at`).
- **Modellierung:** `wishes_review` als Status; Freeze als **abgeleiteter Zustand**
  (`display_frozen = now ≥ freeze_start`) – im Ablaufdiagramm ein eigener Schritt, intern
  ein Flag (keine Status-Explosion). `compute_status`/`run_due_lotteries` erweitert; nie
  rückwärts, nie automatisch aus `lottery_review` heraus (wie bisher).

### 2. Einreiche-Frist, fixer Teilnehmerkreis, Admin-Nachtrag

- **Einreiche-Frist = `review_open`.** Wer teilnimmt, muss bis dahin `submitted=True`.
- **Erinnerungen:** die zweistufige Vorlauf-Erinnerung ([ADR 0080](0080-wunsch-frist-anzeige-und-erinnerung.md))
  bleibt; **neu** eine **dringende** Stufe **kurz vor `review_open`** an alle ohne
  eingereichten Wunsch (neues Ereignis im Framework [ADR 0089](0089-benachrichtigungs-framework.md),
  idempotent je Periode).
- **In der Review-Phase: nur Bearbeiten.** Der Lostopf-Teilnehmerkreis ist fix; Mitglieder
  dürfen eingereichte Wünsche **anpassen/zurückziehen**, aber **keine neuen** anlegen
  (serverseitig in `add_wish` am Status geprüft).
- **Admin-Nachtrag:** `add_wish_for_member` (Rolle *Buchungs-Verwaltung-Erweitert*,
  [ADR 0100](0100-granulare-verwaltungsrollen-rbac.md)) trägt Vergessenen auch in der
  Review-Phase Wünsche nach – **auditiert** (`created_by`, analog `book_for_member`).

### 3. Konflikt-/Prognose-Ansicht

- **Nachfrage-Heatmap** je Quartier × Zeit: **absolute Wunschzahl** je Zeitraum
  (anonyme Aggregate), Farbheat. Erweiterung von `quarter_wish_counts` auf ein
  zeitaufgelöstes Raster.
- **Prognose je Wunsch** – *„wo kommt es zur Losung"*: per **Monte-Carlo-Trockenlauf**
  der echten RSD über die eingereichten Wünsche (Fairness-Engine, [ADR 0062](0062-verifizierbare-auslosung-commit-reveal.md))
  → Gewinnwahrscheinlichkeit, dargestellt als **qualitatives Band** („gute Chance /
  offen / knapp", positiv [ADR 0072](0072-positive-wortwahl-frontend.md)) **plus absolute
  Wunschzahl** im Zeitraum. Berücksichtigt Karma, Ausweich-Äquivalenzklassen, Budget,
  Saison – wie die echte Ziehung. **Wichtig:** die Simulation nutzt **Zufalls-Seeds**,
  **nie** den committeten Seed (bleibt bis nach der Ziehung geheim).
- **Persönlich** (Meine Wünsche): Prognose-Band + Entzerrungs-Alternativen
  ([ADR 0064](0064-kooperative-transparenz-features.md)) als Ein-Klick-Chips.
- **Gemeinschaftsweit** (Übersicht/Gemeinschaftsspiegel): anonyme Heat der beliebten
  Zeiträume.

### 4. Absprachen zwischen „Wunsch-Nachbarn"

Damit Mitglieder sich **privat, außerhalb der App** abstimmen können:

- Wer einen mit *meinem* Wunsch **überlappenden** Zeitraum wünscht, ist mir als
  **Anzeigename + Telefonnummer** sichtbar – **nur** überlappende Wünsche, **nur** während
  der Phase.
- **Opt-out, Default AN** (bewusste Gemeinschafts-Entscheidung): jederzeit **1-Klick-Opt-out**
  im Profil (`Member`-Feld, Default sichtbar). Wer opt-out wählt, erscheint nicht.
- **DSGVO-Rahmen (Art. 5/13/25):** klarer Hinweis in der Phase *und* im Profil,
  Zweckbindung (nur Absprache), Datenminimierung (nur die zwei Felder), Ergänzung der
  **Datenschutzerklärung** (`ShopConfig`). Kontakt läuft **außerhalb** der App.
- **Mechanik-sicher:** Absprachen ändern nur eigene Wünsche; der RSD-Kern bleibt
  strategiesicher.

### 5. Verwaltungs-Export

- **`export_wishes`** (Rolle *Buchungs-Verwaltung*, [ADR 0100](0100-granulare-verwaltungsrollen-rbac.md)):
  xlsx **und** CSV aller Wünsche über `booking/exports.py` (inkl. Formel-Injektions-Schutz)
  – als **zwei Snapshots „vor" (`review_open`) und „nach" (`draw_at`)**, damit beliebte
  Zeiträume **und** die Wirkung der Entzerrung sichtbar werden.

### 6. Snapshot-Strategie (dreifach genutzt)

Ein **Nachfrage-Snapshot** wird vom Scheduler festgehalten und dient dreifach:
`review_open`-Snapshot = „vor"-Export **+** Basis der anonymen Community-Grafik;
`freeze_start`-Snapshot (draw − 24 h) = **eingefrorene Anzeige**. Speicherung schlank
(aggregierte Nachfrage + für den Export die Wunschzeilen), gepflegt im
`run_scheduler`-Lauf.

## Architektur / Sicherheit / Performanz

- **Reine Logik** (Django-frei, [ADR 0002](0002-drei-schichten-architektur.md)):
  `lottery.simulate_win_probabilities(parties, wishes, n_runs)` (Fairness-Engine
  wiederverwenden) – testbar ohne DB.
- **Service** `wish_prognosis(period)` → Bänder je Wunsch + Nachfrage-Raster;
  **precompute im Scheduler** während der Phase + Cache (Redis falls aktiv), invalidiert
  bei Wunsch-Änderung → Requests O(1). Für ~50 Mitglieder/~100 Wünsche ist der
  Monte-Carlo günstig.
- **Security by Design:** Commit-Reveal-Seed unangetastet (Prognose nur Zufalls-Seeds);
  gemeinschaftsweite Heat strikt anonym; Identitäten nur opt-out-gefiltert; CSP-nonce,
  CSRF, `django-ratelimit` auf die Wunsch-Endpunkte; serverseitige Status-/Rechte-Checks.
- **UI/UX:** Phasen-Status-Chip mit den zwei Marken; Prognose-Chip (positiv); Heat als
  **HTML/CSS-Zellen** ([ADR 0095](0095-auslastungsgraph-html-balken.md), kein SVG);
  **ausführliche Hilfeseite mit Ablaufdiagramm** (die zwei Fristen klar erklärt);
  mobil-first, AJAX, Toasts.

## Datenmodell (Umsetzungs-Skizze)

- `BookingPolicy.review_days` (Default 7); `BookingPeriod.review_days` (null = Default).
- Abgeleitet: `review_open`, `freeze_start` (`FREEZE_HOURS=24`), `display_frozen`.
- `BookingPeriod.status`-Choice `WISHES_REVIEW`.
- `Member`-Opt-out-Feld für die Absprachen-Sichtbarkeit (Default sichtbar).
- Schlanker Nachfrage-Snapshot (Modell **oder** JSON am `BookingPeriod`).
- Notify-Ereignisse (Katalog [ADR 0089](0089-benachrichtigungs-framework.md)):
  „Entzerrungsphase offen", „dringende Wunsch-Erinnerung".

## Betrachtete Alternativen

- **Keine eigene Phase, nur Ampel** (Status quo): zu schwach – keine klare Frist, keine
  Chancen-Prognose.
- **Heuristik „Überschneidungen zählen"** statt Monte-Carlo: billiger, aber ungenau
  (ignoriert Karma/Ausweich/Budget) – verworfen zugunsten des ehrlichen Trockenlaufs.
- **Live-Nachfrage ohne Freeze**: einfacher, aber Last-Minute-Oszillation/Gaming –
  Freeze gewählt (fest 24 h).
- **Anonyme Nachfrage ohne Identitäten**: datensparsamer, aber verhindert Absprachen –
  bewusst zugunsten opt-out-Sichtbarkeit verworfen (Gemeinschafts-Entscheidung).

## Konsequenzen

**Positiv** – Mitglieder sehen Nachfrage **und** realistische Chancen und können gezielt
entzerren; weniger unnötige Losungen; Absprachen möglich; Verwaltung sieht Wirkung per
Export; Strategiesicherheit + Seed-Geheimnis bleiben gewahrt; viel Wiederverwendung
(Fairness-Engine, `quarter_wish_counts`, Export, Notify-Framework).

**Negativ / Grenzen** – zusätzliche Phase erhöht die Erklärbedürftigkeit → **starke Hilfe/
Diagramm** nötig (bewusst eingeplant); der Monte-Carlo ist eine Schätzung (Bänder statt
Scheingenauigkeit); Telefonnummer-by-default ist eine **bewusste Datenexposition**
(opt-out + DSGVO-Hinweise mildern, bleibt Governance-Entscheidung); der Freeze macht die
Anzeige in den letzten 24 h leicht veraltet (gewollt: Stabilität vor Aktualität).

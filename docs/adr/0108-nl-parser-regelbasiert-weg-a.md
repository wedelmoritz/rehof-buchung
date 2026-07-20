# 0108 – Natürlichsprachliche Kurz-Eingabe: regelbasierter Parser (Weg A)

## Status

Proposed (2026-07-20) · **setzt [ADR 0103](0103-wunsch-situationsbild-beliebtheit-und-vorschlaege.md)
P2 „Weg A" um** · reine Logik/Injektion wie [ADR 0002](0002-drei-schichten-architektur.md)/
`beds24.py` · Eingabe-Härtung [ADR 0039](0039-eingabe-validierung-und-xss-haertung.md) ·
Datensparsamkeit [ADR 0043](0043-dsgvo-datensparsamkeit-aufbewahrung-loeschung.md).
**Teil 1 (reine Logik) umgesetzt (2026-07); Einbindung in Wunsch-/Buchungs-Flow folgt.**

## Kontext

ADR 0103 (P2) skizziert eine optionale natürlichsprachliche Eingabe – „ruhige Woche im
Juli, barrierefrei, mit Hund" → sinnvolle Vorbelegung. Von den drei Wegen ist **Weg A
(regelbasiert)** empfohlen: billig, sofort, **kein neuer Betrieb**, DSGVO-neutral. Weg B
(lokales LLM) und Weg C (externe API) bleiben abgelehnt/zurückgestellt (RAM bzw. PII-Abfluss).

## Entscheidung

**Reine Logik `booking/wish_nl.py` (Django-frei):** `parse_wish_text` / `parse_booking_text`
übersetzen deutsche Kurz-Eingaben in **strukturierte Constraints** (`WishIntent`), die das
normale Formular **vorausfüllen** – *parse-and-confirm*: best-effort, **nie blockierend**,
das Mitglied prüft/korrigiert. Der Parser **entscheidet nie**.

**Stammdaten werden injiziert** (wie `beds24.py`), **nichts hartcodiert:**
- `quarters`/`eq_classes` als `[(key, name)]` → unscharfer Sliding-Window-Abgleich über
  `beds24.name_score` (nur ein **sicherer** Treffer wird gesetzt; ein Fehltreffer wäre
  schlimmer als keiner).
- `seasons`/`holidays` als `[(name, start, end)]`, **materialisiert** aus den konfigurierten
  `SeasonRule`/`SchoolHoliday` fürs Zieljahr → benannte Zeiträume („Herbstferien",
  „Hochsaison") folgen automatisch der Backend-Konfiguration.

**Erkannt werden:** konkreter Zeitraum (Datums-Regex + Dauer-Wortliste), benannter Zeitraum
(konfigurierte Ferien/Saison), Personenzahl, barrierefrei → `Quarter.accessible`,
Flexibilität, sowie **Besonderheiten** mit/ohne **Endreinigung**, **Hund**, **Beistellbett**,
**Kinder** (fürs Buchen; beim Wunsch mitgeführt). Nicht Zugeordnetes landet in
`unresolved` – der Nutzer sieht **ehrlich**, was nicht verstanden wurde.

## Security by Design

- Eingabe wird mit `validation.strip_controls` gesäubert und **hart längenbegrenzt**
  (`MAX_LEN=400`) **vor** jeder Verarbeitung.
- Nur **einfache, gebundene** Regex (keine verschachtelten Quantoren) → **kein ReDoS**;
  alle Schleifen sind durch Länge/Kandidatenzahl begrenzt.
- **Kein** `eval`/`exec`, **kein** Template-Rendering von Eingaben → **SSTI-frei**.
- Ausgabe ist ausschließlich strukturierte Data (IDs/Daten/Flags/kurze Labels), **nie HTML**;
  die spätere Anzeige escapt ohnehin.
- **Django-frei/DSGVO-neutral:** nichts verlässt den Server, keine externe/KI-Abhängigkeit;
  isoliert in `tests/` prüfbar (inkl. Missbrauchs-/Robustheits-Eingaben).

## Grenzen (ehrlich, ADR-konform)

Vage Eingaben ohne fassbaren Zeitraum, Verneinung/Entweder-oder jenseits weniger fester
Muster, **Tippfehler/Dialekt**, lange erzählende Bedingungssätze und **nicht modellierte**
Präferenzen („ruhig", „mit Sauna" – kein Feld) werden **nicht** verstanden – und dürfen
nichts Falsches setzen. Alles fällt sauber auf die Formularauswahl zurück.

## Betrachtete Alternativen

- **Weg B (lokales kleines LLM):** zurückgestellt – ~1–4 GB RAM resident, eigener Dienst
  (ADR 0103).
- **Weg C (externe LLM-API):** abgelehnt – PII-Abfluss/AV-Vertrag/Determinismus.
- **Ganze-Text-Namensabgleich statt Sliding-Window:** verworfen – kurze Quartiersnamen in
  langen Sätzen erreichen die Schwelle nicht; Fenster-Abgleich trifft eingebettete Namen.

## Konsequenzen

**Positiv** – billige, sofort verfügbare, deterministische und auditierbare Vorbelegung ohne
neue Infrastruktur/PII-Risiko; folgt den konfigurierten Stammdaten; klar getestet.

**Negativ / Grenzen** – deckt nur Kurz-Eingaben ab (s. o.); die Match-Schwelle ist bewusst
konservativ (lieber kein als ein falscher Treffer); die Einbindung ins UI (zwei getrennte
Freitextfelder, escaped/CSP-treu, Vorschau-zum-Bestätigen) erfolgt in einem Folge-Batch.

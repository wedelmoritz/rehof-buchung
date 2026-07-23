# 0108 – Natürlichsprachliche Kurz-Eingabe: regelbasierter Parser (Weg A)

## Status

Proposed (2026-07-20) · **setzt [ADR 0103](0103-wunsch-situationsbild-beliebtheit-und-vorschlaege.md)
P2 „Weg A" um** · reine Logik/Injektion wie [ADR 0002](0002-drei-schichten-architektur.md)/
`beds24.py` · Eingabe-Härtung [ADR 0039](0039-eingabe-validierung-und-xss-haertung.md) ·
Datensparsamkeit [ADR 0043](0043-dsgvo-datensparsamkeit-aufbewahrung-loeschung.md).
**Umgesetzt (2026-07): reine Logik + Einbindung in Wunsch- und Buchungs-Flow.**

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

## Einbindung (zwei getrennte Felder)

Die Naht `services.nl.py` (`nl_parse_wish`/`nl_parse_booking`) baut die injizierten
Stammdaten aus der DB (aktive Quartiere/Klassen + materialisierte `SchoolHoliday`/
`SeasonRule` des Zieljahrs) und ruft die reine Logik. **Zwei getrennte Freitextfelder:**
- **Wunsch** („Neue Wünsche eintragen"): `nlq` → füllt Zeitraum als Auswahl vor, stellt
  den Kalender auf den Monat, markiert die vorgeschlagene Unterkunft (💬); der Nutzer
  trägt wie gewohnt selbst ein.
- **Buchung** (`book`): `nlq` → füllt **Personen/barrierefrei/Zeitraum** vor und markiert
  die vorgeschlagene Unterkunft; gebucht wird wie gewohnt über den Bestätigungsschritt.
Ein **Vorschau-Banner** zeigt escaped, was verstanden (`matched`) bzw. **nicht**
übernommen (`unresolved`) wurde. Alles `data-ajax`/CSP-treu, nur GET (kein Schreibpfad).

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

## Nachtrag (2026-07): grober Monatswunsch → erstes (freies) Datum

Ein **grober Zeitwunsch ohne konkretes Startdatum** („eine Woche im Juli") lief bisher in
die Meldung „Dauer erkannt, aber kein Startdatum" – widersprüchlich zum vorgeschlagenen
Beispieltext. Behoben in **zwei Schichten** (die Trennung rein/Service bleibt gewahrt):

- **Reine Logik** (`wish_nl`): ein allein genannter **Monatsname** (ganzes Token, kein
  Teilstring) setzt `WishIntent.month` (+ `nights` aus der Dauer). Kein Datum, keine
  Verfügbarkeit in der reinen Logik – nur die Absicht.
- **Service** (`services.nl._resolve_month_start`): schlägt daraus das **erste passende
  Datum** im Monat vor – für **Buchungen** das erste **freie + freigeschaltete** Datum der
  genannten (bzw. irgendeiner passenden) Unterkunft, für **Wünsche** das erste Datum im
  Saison-Zeitraum (Freiheit gilt für Wünsche nicht). Findet sich nichts, wird das **ehrlich**
  gemeldet („im <Monat> keine passende freie Zeit gefunden"). Best-effort, nie blockierend.

Tests: `tests/test_wish_nl.py` (Monat/Dauer rein) + `booking/tests_nl.py`
(`NlMonatAufloesungTests`: Wunsch bekommt Datum, Buchung nimmt erstes freies, überspringt
Belegtes, meldet einen komplett belegten Monat ehrlich).

### Nachtrag 2 (2026-07): mehr Vokabular + „Meintest du…?"-Vorschläge

Ziel: **mehr Eingaben erkennen** und **Mehrdeutigkeit** sinnvoll behandeln. Methodik
recherchiert (Slot-Filling/Conversational-Search-Literatur): keine **blockierende**
Rückfrage (bräuchte Dialog-Zustand, widerspricht „nie blockierend"), sondern **rangierter
Bestvorschlag + nicht-blockierende Quick-Reply-Chips** – das empfohlene „geführte Auswahl"-
Fallback, das zur zustandslosen parse-and-confirm-Architektur passt (deterministisch,
auditierbar, CSP-konform).

- **Vokabular (reine Logik):** Jahreszeiten → **geordnete Kandidat-Monate**
  (`_SEASONS`, „Sommer"→[7,8,6]); **`-woche`/`-urlaub`/`-ferien`-Komposita** („Sommerwoche",
  „Juliwoche" → Monat/Saison + ggf. 7 Nächte); **Monatsteil** („Anfang/Mitte/Ende" →
  `day_bias`); **relative Angaben** nur bei **Buchungen** („nächste/übernächste Woche",
  „in N Wochen/Tagen" – „in 2 Wochen" ist Versatz, NICHT Dauer); **Dauer-Synonyme**
  („verlängertes Wochenende"=3, „ein paar Tage"=3). Bewegliche Feste (Ostern/Pfingsten)
  bleiben in den **konfigurierten** `SchoolHoliday`/`SeasonRule` (nichts hartcodiert).
- **`WishIntent`** trägt jetzt **`months: list[int]`** (nach Präferenz geordnet), `day_bias`
  und – vom Service befüllt – **`suggestions`** (bis zu 3 konkrete Vorschläge).
- **Service** (`_resolve_month_start`): erzeugt je Kandidat-Monat das erste passende/freie
  Datum (Monatsteil verschiebt den Suchstart); der beste wird vorbelegt, die weiteren sind
  die **Alternativen**. **Effizient:** Verfügbarkeit wird **einmal** über die ganze Spanne
  vorab geladen (ADR 0111), max. 3 Kandidaten – konstante Abfragezahl statt je Tag.
- **UI:** die Vorschau zeigt unter „✓ Verstanden" eine Zeile **„Meintest du eher: …"** mit
  1-Klick-Chips (vorbefüllte GET-Links ohne `nlq`, `data-ajax`, CSP-treu); ein Klick
  übernimmt den Alternativ-Zeitraum, ohne neu zu parsen.

**Security:** unverändert gehärtet – nur gebundene Regex (kein ReDoS), Längenlimit, kein
eval/SSTI; Ausgabe nur strukturierte Daten (Datum/Label), das Template escapt; kein
Dialog-/Sitzungszustand. Tests: `tests/test_wish_nl.py` (Jahreszeiten/Komposita/Monatsteil/
relativ/Synonyme) + `booking/tests_nl.py` (mehrere Vorschläge, belegten Monat überspringen,
relativ ohne Alternativen, „Meintest du…?"-Chips in der View).

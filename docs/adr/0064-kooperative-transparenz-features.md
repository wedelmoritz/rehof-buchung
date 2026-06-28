# 0064 – Kooperative & transparente Zusatzfeatures (P2)

## Status

Accepted (2026-06-28)

> Klammer-ADR für die kooperativen/gemeinschaftsfördernden P2-Features. Baut auf
> ADR 0062 (verifizierbare Auslosung) und 0063 (Gemeinschafts-Spiegel) auf. Leitlinie:
> Transparenz/Gemeinschaft, schlank, sicher, wenige DB-Abfragen, keine Überfrachtung.

## Kontext

Nach der Verifizierbarkeit (0062) und der aggregierten Transparenz (0063) ergänzen
diese Features die **direkte Kooperation** zwischen Mitgliedern und die
**Nachvollziehbarkeit des Einzel-Ergebnisses** – durchweg additiv, ohne den Kern
(Strategiesicherheit der Losung) zu berühren.

## Entscheidungen

### P2.6 – Losergebnis-Erklärung (warum bekommen / nicht bekommen)

`services._build_lottery_notices` erklärt jeden Wunsch nachvollziehbar (die Texte
landen in der In-App-Benachrichtigung **und** der Ergebnis-Mail – eine Quelle):
- **Gewinn:** bei Ausweichquartier der Grund („dein Wunsch X war belegt"), bei
  Konkurrenz der Hinweis, dass das Los entschieden hat.
- **Verlust:** „im gewünschten Zeitraum war die ganze gleichwertige Quartiersgruppe
  belegt".
- **Übersprungen (kein Verlust):** Sammelhinweis mit Grund (Wunsch-Tagebudget erreicht /
  Saison-Regel) – zählt nicht als Verlust, bringt also kein Karma.

Quelle ist das ohnehin vorhandene Ziehungsprotokoll (`result.log`/`allocations`/
`losses`) – **keine** zusätzlichen Felder/Queries. Wirkt automatisch in
`period_result` (eigene Notiz) und der Mail.

### P2.4 – Wunsch-Koordination (unverbindliche Ausweich-Hinweise)

Auf der Wunschliste zeigt `services.wish_deconfliction` zu einem gewählten Zeitraum
pro umkämpftem Quartier die **nahe Verschiebung** (gleiche Länge, ±2 Tage) mit der
**geringsten Konkurrenz** – als anklickbaren Tipp („💡 Weniger Andrang mit …"), der den
Kalender auf die entspanntere Zeit umstellt. **Rein freiwillig**, kein Schreibpfad ins
Losverfahren (Strategiesicherheit unberührt). **Eine** zusätzliche DB-Abfrage (alle
eingereichten Wünsche im Fenster), Rest in Python; Vorschläge werden auf die
Quartier-Saison gefiltert (`_in_season_range`). Bewusst gewählt (statt verbindlichem
Tausch) für Schlankheit und Strategiesicherheit.

### P2.5 – Solidaritäts-/Schenkungs-Pool für Tage (gedeckelt)

Ein gemeinsamer Topf, in den Mitglieder **ungenutzte Tage spenden** und aus dem
Mitglieder **bei Bedarf, gedeckelt** entnehmen können (Modell `DayPoolEntry`,
Migration 0041; Service `booking/services/pool.py`). Topf-Stand eines Jahres =
Σ Spenden − Σ Entnahmen.

- **Integration ins Budget:** Spenden/Entnahmen fließen in `Member.
  effective_annual_budget` (neue Helfer `pool_donated_in_year`/`pool_received_in_year`)
  – damit respektiert die **gesamte** Buchungs-/Verfügbarkeitsprüfung den Pool
  automatisch (ein Integrationspunkt, kein verstreuter Sonderfall).
- **Fairness-Regeln (bewusst einfach, im Code dokumentiert/änderbar):**
  - **Spenden:** nur, was man noch hat (`nights ≤ nights_remaining_in_year`).
  - **Entnahme nur bei Bedarf:** das eigene Jahresbudget muss fast aufgebraucht sein
    (`remaining ≤ POOL_ELIGIBLE_REMAINING`, Default 5) – schützt das Jahres-Prinzip;
    wer aufgestockt hat, ist nicht mehr berechtigt.
  - **Gedeckelt:** höchstens `POOL_WITHDRAW_CAP_PER_YEAR` (Default 10) Tage je
    Mitglied und Jahr, und nie mehr als im Topf ist.
- **Transparenz/Privatsphäre:** der Topf-Stand ist sichtbar; das Mitglied sieht seine
  **eigenen** Spenden/Entnahmen. Fremde Entnahmen werden NICHT namentlich gezeigt
  (eine Entnahme verriete finanzielle/zeitliche Knappheit – Datensparsamkeit). Die
  Verwaltung sieht alle Einträge im Backend (`DayPoolEntryAdmin`).
- **UI:** Karte „Solidaritäts-Pool" auf `/tage-uebertragen/` (Spenden mit Rückfrage;
  Entnehmen nur wenn berechtigt, sonst erklärender Hinweis).

### P2.7 – Leichte Wertschätzung („Danke")

Die empfangende Person kann sich für eine Tage-Übertragung **einmalig** bedanken
(`services.thank_for_transfer`): erzeugt eine private In-App-Benachrichtigung (+ Mail
je Opt-in) an die schenkende Person und setzt `NightTransfer.thanked_at` (idempotent,
Migration 0040). Knopf „Danke sagen" je erhaltener Übertragung auf `/tage-uebertragen/`
(danach „bedankt ✓"). **Bewusst KEINE** Punkte/Badges/Rangliste – reine, nicht
kompetitive Anerkennung (Reziprozität ohne Bloßstellung).

## Konsequenzen

**Positiv** – das Einzel-Ergebnis ist selbsterklärend (P2.6); soziale Anerkennung
stärkt Reziprozität (P2.7). Minimaler Schema-/Query-Aufwand.

**Negativ / Grenzen** – die Los-Erklärung sieht nur die laufeigene Sicht (nicht,
*wer* den Slot bekam – bewusst, Datenschutz). „Danke" ist auf Tage-Übertragungen
begrenzt (Swaps könnten später analog ergänzt werden).

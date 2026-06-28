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

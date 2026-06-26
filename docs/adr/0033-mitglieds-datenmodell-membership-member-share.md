# 0033 – Mitglieds-Datenmodell: Membership / Member / Share

## Status

Accepted (2026-06-26)

## Kontext

Ein eG-Anteil (Vielleben-eG-Nummer) kann von **mehreren** Personen gehalten werden
(Teil-/Tandem-Mitgliedschaft), und eine Person kann mehreren Anteilen angehören.
Das Tage-Budget hängt am Anteil, das Buchen aber an der einzelnen Person mit ihrem
Login. Ein einzelnes „Mitglied = Login = Budget“-Modell bildet das nicht ab.

## Entscheidung

Drei Modelle mit klaren Rollen (`booking/models.py`):

- **`Membership`** (`models.py:130`) = ein eG-Anteil: Vielleben-eG-Nummer, `kind`
  (Voll/Teil), Gesamt-Tagebudget.
- **`Member`** (`models.py:180`) = das Buchungs-Subjekt je Nutzer (1:1 zum Login).
  Hier hängen Buchungen, Wünsche, Karma.
- **`Share`** (`models.py:262`) = Through-Modell Nutzer↔Anteil mit festem
  `night_budget`/`wish_night_budget`.
- **Budgets summieren sich:** `Member.annual_night_budget`/`wish_night_budget` sind
  die **Summe** der `Share`-Anteile des Nutzers (`models.py:212-219`); ein Nutzer in
  mehreren Anteilen addiert seine Tage (ganze Tage). `effective_annual_budget`
  rechnet erhaltene/abgegebene Tage ein (kein Übertrag, ADR 0009/0010).

## Betrachtete Alternativen

- **Ein Modell „Mitglied = Login = Budget“:** kann geteilte Anteile und
  Mehrfach-Mitgliedschaften nicht abbilden.
- **Budget direkt am Login/User:** vermengt Auth mit Fachdaten; geteilte Anteile
  bleiben unmöglich.
- **Many-to-many ohne Through-Modell:** kein Platz für den **festen Tage-Anteil** je
  Zuordnung.

## Konsequenzen

**Positiv**
- Geteilte Anteile, Tandem-Mitgliedschaften und Mehrfachzugehörigkeit sauber
  abbildbar.
- Budget ist nachvollziehbar herleitbar (Summe der Anteile + Transfers).

**Negativ**
- Drei Modelle statt einem – mehr konzeptionelle Last; im Admin durch Inlines
  vereinfacht (ADR 0019).
- Budget-Berechnung summiert über `Share`s (N+1 beachten; Aggregation/Prefetch).

# 0099 – Solidaritäts-Pool: Anreiz-Analyse + konfigurierbare Parameter + Zeit-Riegel

## Status

Accepted (2026-07-05) · erweitert ADR 0064 (Pool)

## Kontext

Der Solidaritäts-Pool (ADR 0064) erlaubt eine Entnahme nur, wenn das eigene
Jahresbudget **fast aufgebraucht** ist (Rest ≤ 5 Tage) und gedeckelt (10/Jahr). Frage
aus der Praxis: Verleitet die „Rest ≤ 5"-Regel dazu, das **eigene Budget schnell zu
verbrauchen**, um dann aus dem Pool **nachzuladen** (Moral Hazard)? Ist die feste
5-Tage-Grenze sinnvoll?

## Analyse (mit Perspektiven aus vergleichbaren Systemen)

- **Moral Hazard / Free-Riding (Commons, Ostrom; Mutual-Credit-Forschung).** Ein
  Bedarfs-Signal, das sich allein aus **Erschöpfung** ergibt, ist manipulierbar –
  „nearly out" erreicht man durch bloßes Ausgeben. Mutual-Credit-/Time-Bank-Systeme
  begegnen dem mit **Limits, Umlauf-Anreizen und Monitoring**, nicht mit reiner
  Bedarfsprüfung.
- **Leave-Donation-/Shared-Leave-Programme** (der nächste reale Verwandte) koppeln die
  Entnahme an einen **qualifizierenden, externen Bedarf** (Notfall) **plus**
  Erschöpfung – nicht an Erschöpfung allein; Missbrauch (Nutzung zu anderem Zweck) ist
  ausdrücklich sanktioniert.
- **Entschärfender Faktor hier:** „Verbrauchen" heißt echte Nächte **buchen** (reale
  Quartiere, Regeln, Mindestnächte) – es ist nicht kostenlos. Wer 45 Nächte bucht, ist
  meist ein echter Vielnutzer, kein Trickser. Der Deckel (10) begrenzt den Vorteil, und
  der Topf ist ohnehin durch die Spenden begrenzt.
- **Fairness der festen Grenze:** „5" ist **absolut** und trifft Teil-Anteile (25 Tage)
  härter als Voll-Anteile (50). Eine relative/konfigurierbare Grenze ist gerechter.

## Entscheidung

Kein Umbau der Grundlogik, aber **drei Stellschrauben** ins Backend (`BookingPolicy`),
Defaults = bisheriges Verhalten:

1. **`pool_eligible_remaining`** (Default 5) – Entnahme-Schwelle jetzt konfigurierbar
   (Antwort auf „ist 5 sinnvoll?" → die Delegation entscheidet, ohne Code).
2. **`pool_withdraw_cap`** (Default 10) – Jahres-Deckel konfigurierbar.
3. **`pool_withdraw_from_month`** (Default **0 = aus**) – optionaler **Zeit-Riegel**:
   Entnahmen erst ab einem Monat (z. B. 9 = ab September). Das ist der gezielte
   Anreiz-Fix gegen „früh verbrauchen, dann nachladen": wer früh alles ausgibt, kann
   **nicht sofort** nachladen; bis zum Stichtag zeigt sich, wer bis dahin wirklich zu
   wenig hat. Als **Opt-in** ausgelegt, damit die Genossenschaft es beschließt.

Werte kommen über `services.pool._pool_policy()` aus `BookingPolicy.get_solo()`;
`pool_status`/`pool_withdraw` erzwingen Schwelle, Deckel **und** Zeit-Riegel; die
UI erklärt den jeweils greifenden Grund.

## Konsequenzen

**Positiv** – die Genossenschaft kann die Fairness-Parameter selbst tunen; der
Zeit-Riegel adressiert den Moral-Hazard gezielt, ohne den Pool zu verkomplizieren.

**Grenzen / offen (für die Delegation).** Eine **echte** Bedarfsprüfung (Entnahme
gebunden an eine konkrete, sonst nicht deckbare Buchung, wie beim Leave-Bank-„qualifying
need") wäre der stärkste Missbrauchs-Schutz, aber deutlich aufwändiger und mit mehr
Reibung – bewusst NICHT umgesetzt, sondern als Option dokumentiert. Ebenso denkbar:
relative Schwelle (Anteil des Jahresbudgets) statt absoluter Tage.

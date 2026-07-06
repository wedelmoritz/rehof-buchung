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
3. **`pool_withdraw_from_month`** (Default **9 = September**) – **Zeit-Riegel**:
   Entnahmen erst ab diesem Monat. Der gezielte Anreiz-Fix gegen „früh verbrauchen,
   dann nachladen": wer früh alles ausgibt, kann **nicht sofort** nachladen; bis
   September zeigt sich, wer wirklich zu wenig hat. `0` = ganzjährig (Riegel aus).

**Passive Mitglieder dürfen SPENDEN, aber nicht ENTNEHMEN.** Ihre Tage verfallen
sonst ungenutzt – Spenden (und Übertragen an aktive Mitglieder) ist erwünscht;
Entnehmen ist an die aktive Mitgliedschaft gebunden (`Member.can_book`, in
`pool_withdraw`/`pool_status` erzwungen). Die Transfer-Seite ist für passive
Mitglieder daher zugänglich (nur „Geben", nicht „Nehmen").

Werte kommen über `services.pool._pool_policy()` aus `BookingPolicy.get_solo()`;
`pool_status`/`pool_withdraw` erzwingen Schwelle, Deckel, Zeit-Riegel **und** den
Aktiv-Status; die UI erklärt den jeweils greifenden Grund. Die **Hilfe-Seite**
(`help_content/tage.md`) nennt die **konfigurierten** Werte (über den helptexts-
Kontext, nicht die Code-Defaults).

## Konsequenzen

**Positiv** – die Genossenschaft kann die Fairness-Parameter selbst tunen; der
Zeit-Riegel adressiert den Moral-Hazard gezielt, ohne den Pool zu verkomplizieren.

**Bewusst NICHT umgesetzt.** Eine **relative Schwelle** (Anteil des Jahresbudgets statt
absoluter Tage) wurde erwogen, aber verworfen – die absolute, konfigurierbare Grenze
bleibt. Eine **echte** Bedarfsprüfung (Entnahme gebunden an eine konkrete, sonst nicht
deckbare Buchung, wie beim Leave-Bank-„qualifying need") wäre der stärkste Missbrauchs-
Schutz, aber deutlich aufwändiger/reibungsreicher – als spätere Option dokumentiert.

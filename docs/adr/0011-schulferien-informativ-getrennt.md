# 0011 – Schulferien als rein informatives, vom Regelwerk getrenntes Modell

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 4 – Saison- & Buchungsregeln](../FACHKONZEPT.md#4-saison--buchungsregeln)
> (Schulferien). Diese ADR hält die *technische* Entscheidung und ihre Abwägungen
> fest; die Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Schulferien sind für die Planung relevant (sie werden im Kalender angezeigt) und
können – müssen aber nicht – mit Buchungsregeln verknüpft sein. Würde man Anzeige
und Regelwirkung fest koppeln, ließe sich „nur anzeigen, aber nicht regulieren“
nicht abbilden, und jede Anzeige-Änderung träfe sofort die Buchungslogik.

## Entscheidung

Schulferien sind ein **eigenes Modell**, getrennt von den Saison-Regeln:
`booking/models.py:SchoolHoliday` (jährlich wiederkehrend, Monat/Tag).

- **Standardfall: rein informativ** – nur Anzeige im Kalender.
- **Optional regelwirksam:** Sind die Regelfelder gesetzt UND der Eintrag aktiv,
  setzt er im betroffenen Zeitraum dieselben Regeln durch wie eine `SeasonRule`
  (Regelwerte/Semantik: Fachkonzept § 4).

So bleiben Darstellung und Buchungslogik unabhängig voneinander anpassbar.

## Betrachtete Alternativen

- **Schulferien als Spezialfall von `SeasonRule`:** „nur anzeigen ohne Regel“ wäre
  nicht sauber darstellbar; Anzeige und Regel wären verkoppelt.
- **Schulferien nur als Anzeige ohne Regel-Option:** Ferien-spezifische Limits (wenn
  gewünscht) müssten parallel als Saison-Regel doppelt gepflegt werden.

## Konsequenzen

**Positiv**
- Ferien können angezeigt werden, ohne automatisch zu regulieren.
- Bei Bedarf trotzdem regelwirksam – ohne Doppelpflege.

**Negativ**
- Zwei Modelle (`SchoolHoliday`, `SeasonRule`) mit überlappender Regelsemantik, die
  konsistent gehalten werden müssen.

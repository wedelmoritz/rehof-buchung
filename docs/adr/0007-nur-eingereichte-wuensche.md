# 0007 – Nur eingereichte Wünsche nehmen an der Losung teil

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 8 – Wunschliste](../FACHKONZEPT.md#8-wunschliste) (sowie
> [§ 5 – Losverfahren](../FACHKONZEPT.md#5-losverfahren)). Diese ADR hält die
> *technische* Entscheidung und ihre Abwägungen fest; die Regelwerte werden dort
> gepflegt, nicht hier.

## Kontext

Mitglieder sollen ihre Wunschliste in Ruhe zusammenstellen, umsortieren und ändern
können, ohne dass jeder Zwischenstand bereits „zählt“. Gleichzeitig braucht die
Losung einen klar definierten, stabilen Lostopf.

## Entscheidung

Wünsche haben zwei Zustände: **Entwurf** und **eingereicht** (`im Lostopf`). Modell:
`booking/models.py:Wish.submitted` (Default `False`) mit `submitted_at` und Index
`("period", "submitted")`.

- Eingereicht wird bewusst über `booking/services/`:`submit_wishlist`
  (Submodul `wishes`).
- Die Losung berücksichtigt **ausschließlich** eingereichte Wünsche:
  `run_period_lottery` filtert `Wish.objects.filter(period=period, submitted=True)`.
- Bis zur Einreichung bleiben Wünsche privat und frei änderbar; Entwürfe sind in
  der Anzeige als `(Entwurf)` markiert (`Wish.__str__`).

## Betrachtete Alternativen

- **Jeder gespeicherte Wunsch nimmt teil:** kein geschützter Entwurfsraum; jede
  Zwischenspeicherung wäre verbindlich.
- **Separates „Lostopf“-Modell:** doppelte Datenhaltung statt eines einfachen Flags.

## Konsequenzen

**Positiv**
- Klare Trennung Entwurf ↔ Teilnahme; Privatsphäre bis zur Einreichung.
- Stabiler, eindeutig definierter Lostopf zum Ziehungszeitpunkt.

**Negativ**
- Mitglieder müssen den Schritt „Einreichen“ aktiv ausführen – wer das vergisst,
  nimmt nicht teil (durch UI-Hinweise/Hilfe abgefedert).

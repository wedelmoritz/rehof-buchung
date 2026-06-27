# 0006 – Losung bewusst unabhängig von den Buchungszeiträumen

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 3 – Buchungsperiode & Lebenszyklus](../FACHKONZEPT.md#3-buchungsperiode--lebenszyklus)
> (sowie [§ 5 – Losverfahren](../FACHKONZEPT.md#5-losverfahren)). Diese ADR hält die
> *technische* Entscheidung und ihre Abwägungen fest; die Regelwerte werden dort
> gepflegt, nicht hier.

## Kontext

Die Jahres-Losung vergibt die Quartiere für das **Folgejahr** im Voraus – also zu
einem Zeitpunkt, an dem der eigentliche Buchungszeitraum dieses Jahres noch gar
nicht freigeschaltet ist (`BookingPeriod.status` steht noch nicht auf
`free_booking`). Würde die Losung dieselbe Freigabe-Prüfung wie die normale Buchung
anwenden, könnte sie nichts zuteilen.

## Entscheidung

Die Losung ist **nicht** durch den Buchungszeitraum (`[start, end)` der Periode)
begrenzt. `booking/services/`:`run_period_lottery` (Submodul `lottery_ops`) enthält
**kein** Fenster-Gate auf die Periode; es filtert nur auf eingereichte Wünsche
(siehe ADR 0007) und auf die **Quartier-Saison** (`_in_season_range`, damit keine
Buchung außerhalb der ganzjährigen Quartier-Saison entsteht).

Diese Eigenschaft ist auch in der reinen Logik dokumentiert: innerhalb eines
Losdurchlaufs nimmt die Verfügbarkeit monoton ab (`booking/lottery.py:21-26`), ein
externer Zeitraum spielt dort keine Rolle.

> Hinweis (Abweichung zum gegebenen Kontext): Die Losung ist nicht völlig
> bedingungslos – die **Quartier-Saison** (`Quarter.season_*`) wird sehr wohl
> berücksichtigt. Maßgeblich ist also: unabhängig vom **Buchungszeitraum der
> Periode**, aber gebunden an die Quartier-Saison.

## Betrachtete Alternativen

- **Losung an den Buchungszeitraum koppeln:** würde die Vorab-Vergabe des
  Folgejahres unmöglich machen.
- **Gar keine Saison-Prüfung in der Losung:** könnte Buchungen außerhalb der
  Quartier-Saison erzeugen → verworfen.

## Konsequenzen

**Positiv**
- Das Folgejahr kann rechtzeitig im Voraus verlost werden.
- Klare Trennung: Periodensteuerung (`status`/Termine) ≠ Losbarkeit.

**Negativ**
- Die Entkopplung ist nicht offensichtlich; sie ist deshalb durch Tests
  abgesichert (Losung läuft, obwohl die Periode noch nicht `free_booking` ist).

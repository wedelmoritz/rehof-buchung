# 0004 – Karma/Ausgleichsfaktor über die Jahre

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 6 – Karma (Ausgleichsfaktor)](../FACHKONZEPT.md#6-karma-ausgleichsfaktor).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Eine einzelne Losung kann mathematisch nicht zugleich fair und effizient sein: Wer
diesmal Pech hat, könnte ohne Ausgleich auch nächstes Jahr verlieren. Fairness muss
deshalb **über die Zeit** hergestellt werden, ohne das Verfahren angreifbar zu machen.

## Entscheidung

Jede Partei trägt einen **Ausgleichsfaktor** („Karma“), der als Gewicht in die
Reihenfolge-Ziehung einfließt und die Chance auf einen vorderen Platz in der
nächsten Losung erhöht. Umgesetzt in `booking/lottery.py:run_lottery`
(Karma-Aktualisierung Zeilen ~307–317):

- Die Fortschreibung (Start, Schritt pro echtem Verlust, Deckel, Reset bei Gewinn
  eines umkämpften Slots) ist über Parameter steuerbar: `factor_step`, `factor_cap`,
  `reset_on_contested_win` (Regelwerte: Fachkonzept § 6).
- **Budget-bedingtes Aussetzen ist KEIN Verlust** (`budget_skip`, Zeilen ~246–255)
  und verändert das Karma nicht – wer sein Kontingent ausgeschöpft hat, hat seinen
  Anteil bekommen.
- „Echter Verlust“ = gewünschter Zeitraum, in der **ganzen** Äquivalenzklasse
  nichts frei.

Die Faktoren werden im Service persistiert (`Member.factor`); für ein sauberes
Zurückrollen hält der Losdurchlauf einen `karma_snapshot` (siehe ADR 0008).

## Betrachtete Alternativen

- **Kein Ausgleich (jede Losung unabhängig):** wiederholtes Pech möglich, als
  unfair empfunden.
- **Harte Priorisierung von Vorjahres-Verlierern:** vorhersehbar und damit
  manipulierbar; verletzt die Strategiesicherheit.
- **Größere Schritte/kein Deckel:** könnte das Zufallselement übersteuern und neue
  Ungleichgewichte schaffen.

## Konsequenzen

**Positiv**
- Fairness über mehrere Jahre nachweisbar (Monte-Carlo-Nachweis in
  `booking/fairness.py`, Tests in `tests/test_fairness.py`).
- Sanfter Ausgleich, der den Zufall nicht aushebelt (Deckel 1,5).

**Negativ**
- Zusätzlicher Zustand pro Mitglied (`factor`), der korrekt fortgeschrieben und bei
  Rücknahme wiederhergestellt werden muss.
- Parameter (Schritt/Deckel) sind Wertentscheidungen, die begründet bleiben müssen.

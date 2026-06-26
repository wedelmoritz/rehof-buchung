# 0004 – Karma/Ausgleichsfaktor über die Jahre

## Status

Accepted (2026-06-26)

## Kontext

Eine einzelne Losung kann mathematisch nicht zugleich fair und effizient sein: Wer
diesmal Pech hat, könnte ohne Ausgleich auch nächstes Jahr verlieren. Fairness muss
deshalb **über die Zeit** hergestellt werden, ohne das Verfahren angreifbar zu machen.

## Entscheidung

Jede Partei trägt einen **Ausgleichsfaktor** („Karma“, Start 1,0), der die Chance
auf einen vorderen Platz in der nächsten Losung erhöht. Umgesetzt in
`booking/lottery.py:run_lottery` (Karma-Aktualisierung Zeilen ~307–317):

- **+0,1 pro Jahr mit echtem Verlust** (`factor_step`, Default 0.1).
- **Deckel 1,5** (`factor_cap`).
- **Reset auf 1,0** bei Gewinn eines *umkämpften* Slots
  (`reset_on_contested_win`).
- **Budget-bedingtes Aussetzen ist KEIN Verlust** (`budget_skip`, Zeilen ~246–255):
  Wer sein Kontingent ausgeschöpft hat, hat seinen Anteil bekommen.
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

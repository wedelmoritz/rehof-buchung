# 0003 – Losverfahren: gewichtete Zufallsreihenfolge im Runden-Prinzip

## Status

Accepted (2026-06-26)

## Kontext

Die begehrten Quartiere (besonders in Ferienzeiten) sind knapp. Die Vergabe muss
**fair** und **manipulationssicher** sein: Niemand soll durch taktisches Angeben
der Wunschliste bessergestellt werden, und knappe Premium-Slots sollen sich
gleichmäßig verteilen. Das Ergebnis muss nachvollziehbar und auditierbar sein.

## Entscheidung

Wir verwenden eine **gewichtete Zufallsreihenfolge im Runden-Prinzip**
(fachlich „weighted random serial dictatorship“), umgesetzt in
`booking/lottery.py:run_lottery`.

- **Reihenfolge** per gewichteter Ziehung nach Efraimidis-Spirakis
  (`weighted_random_order`, Schlüssel `u ** (1/factor)`), über `seed`
  reproduzierbar.
- **Round-Robin statt Greedy:** pro Runde erhält jede Partei höchstens **eine**
  erfolgreiche Buchung (`run_lottery`, Schleife Zeilen ~235–305, `break` nach
  einer Zuteilung), damit sich knappe Slots gleichmäßig verteilen.
- **Ausweichen** auf gleichwertige Quartiere derselben Äquivalenzklasse, bevor ein
  echter Verlust entsteht (Zeilen ~263–271, siehe ADR 0005).
- **Strategiesicherheit:** Die Wunschliste bestimmt nur *was* man nimmt, nicht
  *wann* man dran ist. Deterministisch geprüft in
  `tests/test_lottery.py::test_strategieproof_ueber_alle_reihenfolgen` – dieser
  Test muss bei Algorithmus-Änderungen grün bleiben.

## Betrachtete Alternativen

- **Windhundverfahren (first come, first served):** belohnt Schnelligkeit/Technik
  statt Fairness; nicht strategiesicher.
- **Reine Zufallslosung ohne Runden (Greedy je Partei):** eine vorne gezogene
  Partei könnte alle Premium-Slots abräumen → ungleiche Verteilung.
- **Reine Präferenz-Optimierung:** anfällig für taktisches Angeben der Wünsche.

## Konsequenzen

**Positiv**
- Fair und strategiesicher; ehrliche Angabe ist nie nachteilig.
- Reproduzierbar über `seed` → auditierbar (`render_log_text`, Protokoll im `log`).
- Gleichmäßigere Verteilung knapper Slots durch das Runden-Prinzip.

**Negativ**
- Komplexer als ein simples FCFS; erfordert sorgfältige Tests.
- Das Ergebnis ist nicht „präferenz-optimal“ im ökonomischen Sinn – bewusst
  zugunsten der Fairness (vgl. ADR 0004).

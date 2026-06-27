# 0005 – Äquivalenzklassen als konfigurierbare Wert-Entscheidung

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 2 – Quartiere & Äquivalenzklassen](../FACHKONZEPT.md#2-quartiere--äquivalenzklassen).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Manche Quartiere sind in der Praxis gleichwertig (vergleichbare Größe/Lage). Wenn
das konkrete Wunschquartier belegt ist, ist ein gleichwertiges meist genauso
willkommen – das vermeidet unnötige „Verluste“ in der Losung. *Welche* Quartiere
gleichwertig sind, ist eine Bewertung der Genossenschaft, kein technischer Fakt.

## Entscheidung

Wir führen **Äquivalenzklassen** ein (`booking/models.py:EquivalenceClass`,
`Quarter.eq_class`). In der Losung wird vor einem echten Verlust auf ein freies,
gleichwertiges Quartier derselben Klasse ausgewichen
(`booking/lottery.py:run_lottery`, Ausweich-Logik Zeilen ~263–271; die Klasse fließt
über `L.Quarter.eq_class` ein).

Die konkrete Einteilung ist **bewusst Daten, nicht Code**: Klassen und Zuordnung
werden gepflegt (Admin `EquivalenceClassAdmin`, Demo-Zuordnung in
`booking/management/commands/seed_demo.py`) und sind ohne Code-Änderung anpassbar.

## Betrachtete Alternativen

- **Keine Klassen (nur exaktes Wunschquartier):** mehr echte Verluste, obwohl ein
  gleichwertiges Quartier frei wäre → Verschwendung.
- **Gleichwertigkeit im Code festverdrahtet:** jede Umbewertung erforderte ein
  Release; die Genossenschaft könnte ihre eigene Einteilung nicht selbst pflegen.

## Konsequenzen

**Positiv**
- Weniger unnötige Verluste; freie gleichwertige Quartiere werden genutzt.
- Die Genossenschaft steuert die Bewertung selbst (Stammdaten im Admin).

**Negativ**
- Eine zu grobe Einteilung könnte Quartiere als „gleichwertig“ behandeln, die es
  für Betroffene nicht sind → erfordert sorgfältige Pflege.

"""Reine Logik-Tests für den anonymen Losergebnis-Rückblick (ADR 0102):
`lottery.summarize_run` aggregiert projizierte Gewinne/Verluste + Karma zu
Quoten, Karma-Bewegung und Verteilungs-Medianen – Django-frei."""
from __future__ import annotations

from booking.lottery import summarize_run


def _won(party, eq="A", band="normal", contested=False):
    return {"party": party, "eq_class": eq, "band": band, "contested": contested}


def _lost(party, eq="A", band="normal"):
    return {"party": party, "eq_class": eq, "band": band}


def test_overall_quote():
    won = [_won("1"), _won("2"), _won("3")]
    lost = [_lost("4")]
    s = summarize_run(won, lost, {}, {})
    assert s["overall"] == {"won": 3, "lost": 1, "total": 4, "pct": 75}


def test_leer_ist_robust():
    s = summarize_run([], [], {}, {})
    assert s["overall"]["pct"] == 0
    assert s["distribution"]["n_parties"] == 0
    assert s["distribution"]["median_wishes"] == 0


def test_by_class_und_band():
    won = [_won("1", eq="Klein", band="holiday"),
           _won("2", eq="Klein", band="normal")]
    lost = [_lost("3", eq="Groß", band="holiday")]
    s = summarize_run(won, lost, {}, {})
    klein = next(c for c in s["by_class"] if c["eq_class"] == "Klein")
    assert klein["won"] == 2 and klein["lost"] == 0 and klein["pct"] == 100
    assert s["by_band"]["holiday"] == {"won": 1, "lost": 1, "total": 2, "pct": 50}
    assert s["by_band"]["normal"]["won"] == 1
    # by_class ist nach Nachfrage (total) sortiert – Klein (2) vor Groß (1).
    assert s["by_class"][0]["eq_class"] == "Klein"


def test_leicht_vs_umkaempft():
    won = [_won("1", contested=True), _won("2"), _won("3", contested=True)]
    s = summarize_run(won, [], {}, {})
    assert s["contested"] == {"contested_wins": 2, "easy_wins": 1}


def test_karma_bewegung():
    before = {"1": 1.0, "2": 1.4, "3": 1.2}
    after = {"1": 1.1, "2": 1.0, "3": 1.2}   # 1 hoch, 2 Reset, 3 gleich
    s = summarize_run([], [], before, after)
    assert s["karma"]["increased"] == 1
    assert s["karma"]["reset"] == 1
    assert s["karma"]["unchanged"] == 1


def test_verteilungs_mediane():
    # Partei 1: 2 Wünsche (1 erfüllt); Partei 2: 1 Wunsch (0 erfüllt);
    # Partei 3: 1 Wunsch (1 erfüllt).
    won = [_won("1"), _won("3")]
    lost = [_lost("1"), _lost("2")]
    s = summarize_run(won, lost, {}, {})
    assert s["distribution"]["n_parties"] == 3
    # Wünsche je Partei: [2,1,1] → Median 1; erfüllt je Partei: [1,0,1] → Median 1.
    assert s["distribution"]["median_wishes"] == 1
    assert s["distribution"]["median_fulfilled"] == 1

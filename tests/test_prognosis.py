"""Reine Logik-Tests für die Wunsch-Prognose (ADR 0101): Monte-Carlo-Trockenlauf
`lottery.simulate_win_probabilities` + qualitative Bänder `lottery.win_band`.
Django-frei, deterministisch über den Simulations-Seed."""
from __future__ import annotations

from datetime import date

from booking.lottery import Party, Quarter, Wish, simulate_win_probabilities, win_band

S, E = date(2027, 5, 24), date(2027, 5, 29)


def test_win_band_grenzen():
    assert win_band(1.0) == "good"
    assert win_band(0.75) == "good"
    assert win_band(0.6) == "open"
    assert win_band(0.4) == "open"
    assert win_band(0.39) == "tight"
    assert win_band(0.0) == "tight"


def test_ohne_konkurrenz_sichere_chance():
    parties = [Party(id="1", name="A")]
    quarters = [Quarter(id="q", name="Q", eq_class="c")]
    wishes = [Wish(party_id="1", priority=1, quarter_id="q", start=S, end=E)]
    probs = simulate_win_probabilities(parties, quarters, wishes, n_runs=50, seed=1)
    assert probs[("1", "q", S, E)] == 1.0


def test_zwei_rivalen_teilen_die_chance():
    # Zwei gleich gestellte Parteien wollen dasselbe Einzelquartier zur selben Zeit.
    parties = [Party(id="1", name="A"), Party(id="2", name="B")]
    quarters = [Quarter(id="q", name="Q", eq_class="c")]
    wishes = [
        Wish(party_id="1", priority=1, quarter_id="q", start=S, end=E),
        Wish(party_id="2", priority=1, quarter_id="q", start=S, end=E),
    ]
    probs = simulate_win_probabilities(parties, quarters, wishes, n_runs=400, seed=7)
    p1 = probs[("1", "q", S, E)]
    p2 = probs[("2", "q", S, E)]
    # Je ~50 %, zusammen genau 100 % (genau eine:r bekommt das Quartier je Lauf).
    assert 0.35 < p1 < 0.65
    assert 0.35 < p2 < 0.65
    assert round(p1 + p2, 6) == 1.0


def test_ausweichquartier_zaehlt_als_gewonnen():
    # Zwei gleichwertige Quartiere (gleiche Klasse): beide Wünsche gehen immer auf
    # (eine:r bekommt das Wunschquartier, die:der andere das gleichwertige Ausweich).
    parties = [Party(id="1", name="A"), Party(id="2", name="B")]
    quarters = [Quarter(id="q1", name="Q1", eq_class="c"),
                Quarter(id="q2", name="Q2", eq_class="c")]
    wishes = [
        Wish(party_id="1", priority=1, quarter_id="q1", start=S, end=E),
        Wish(party_id="2", priority=1, quarter_id="q1", start=S, end=E),
    ]
    probs = simulate_win_probabilities(parties, quarters, wishes, n_runs=100, seed=3)
    assert probs[("1", "q1", S, E)] == 1.0
    assert probs[("2", "q1", S, E)] == 1.0


def test_leere_eingabe_robust():
    assert simulate_win_probabilities([], [], [], n_runs=10, seed=1) == {}
    parties = [Party(id="1", name="A")]
    quarters = [Quarter(id="q", name="Q", eq_class="c")]
    w = [Wish(party_id="1", priority=1, quarter_id="q", start=S, end=E)]
    assert simulate_win_probabilities(parties, quarters, w, n_runs=0, seed=1) == {
        ("1", "q", S, E): 0.0}


def test_deterministisch_bei_festem_seed():
    parties = [Party(id="1", name="A"), Party(id="2", name="B")]
    quarters = [Quarter(id="q", name="Q", eq_class="c")]
    wishes = [Wish(party_id="1", priority=1, quarter_id="q", start=S, end=E),
              Wish(party_id="2", priority=1, quarter_id="q", start=S, end=E)]
    a = simulate_win_probabilities(parties, quarters, wishes, n_runs=100, seed=42)
    b = simulate_win_probabilities(parties, quarters, wishes, n_runs=100, seed=42)
    assert a == b

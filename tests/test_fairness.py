"""Reine Tests für den statistischen Fairness-Nachweis (ohne Django/DB)."""
import math

from booking.fairness import (
    chi2_sf, wilson_interval, simulate_equal_chance, simulate_karma_effect,
)


def test_chi2_sf_grundwerte():
    # P(X² > 0) = 1; große Statistik -> p nahe 0; monoton fallend.
    assert abs(chi2_sf(0.0, 3) - 1.0) < 1e-9
    assert chi2_sf(50.0, 3) < 0.001
    assert chi2_sf(1.0, 3) > chi2_sf(10.0, 3)
    # Bekannter Referenzwert: P(X² > 3.841, df=1) ≈ 0.05
    assert abs(chi2_sf(3.841, 1) - 0.05) < 0.005


def test_wilson_interval_enthaelt_anteil():
    lo, hi = wilson_interval(40, 100)
    assert lo < 0.4 < hi
    assert 0.0 <= lo <= hi <= 1.0


def test_equal_chance_ist_statistisch_fair():
    """Gleich gestellte Parteien (Karma 1,0) -> Gewinnraten gleichverteilt:
    Chi-Quadrat-Test verwirft die Gleichverteilung NICHT (p > 0,05)."""
    res = simulate_equal_chance(n_users=8, n_items=3, n_runs=2000, seed_base=0)
    assert res["uniform_ok"], f"p-Wert zu klein: {res['p_value']}"
    # Jede empirische Rate liegt nahe der erwarteten Rate (3/8 = 0,375).
    for u in res["users"]:
        assert abs(u["rate"] - res["expected_rate"]) < 0.05


def test_karma_erhoeht_gewinnchance():
    """Eine Partei mit höherem Ausgleichsfaktor gewinnt nachweislich häufiger."""
    rows = simulate_karma_effect(n_users=8, n_items=3, n_runs=1500,
                                 factors=[1.0, 1.5], seed_base=0)
    assert rows[-1]["rate"] > rows[0]["rate"]

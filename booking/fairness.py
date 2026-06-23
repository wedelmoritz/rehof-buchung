"""Statistischer Fairness-Nachweis des Losverfahrens (rein, ohne Django).

Das Losverfahren ist im Kern eine *gewichtete Random Serial Dictatorship* (RSD).
Für gleich gestellte Parteien (alle Ausgleichsfaktor 1,0) gilt theoretisch die
Eigenschaft **„equal treatment of equals"**: symmetrische Parteien haben im
Erwartungswert dieselbe Chance. Dieses Modul weist das empirisch über eine
**Monte-Carlo-Simulation** nach (viele Lose-Durchläufe mit unterschiedlichen
Seeds) und prüft die Gleichverteilung mit einem **Chi-Quadrat-Anpassungstest**
samt **Wilson-Konfidenzintervallen**. Zusätzlich wird der **Karma-Effekt**
gezeigt (eine Partei mit höherem Faktor gewinnt nachweislich häufiger).

Quellen (Methodik): Random Serial Dictatorship / „equal treatment of equals";
Pearson-Chi-Quadrat-Goodness-of-Fit; Wilson-Score-Intervall.
"""
from __future__ import annotations

import math
from datetime import date

from .lottery import Party, Quarter, Wish, run_lottery


# --------------------------------------------------------------------------- #
# Statistik-Hilfen (ohne SciPy – bewusst abhängigkeitsfrei)
# --------------------------------------------------------------------------- #

def _gser(a: float, x: float) -> float:
    """Reihenentwicklung der regularisierten unteren Gamma-Funktion P(a, x)."""
    if x <= 0:
        return 0.0
    ap = a
    summ = 1.0 / a
    delv = summ
    for _ in range(1000):
        ap += 1.0
        delv *= x / ap
        summ += delv
        if abs(delv) < abs(summ) * 1e-14:
            break
    return summ * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Kettenbruch der regularisierten oberen Gamma-Funktion Q(a, x)."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        dele = d * c
        h *= dele
        if abs(dele - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(chi2: float, df: int) -> float:
    """Survival-Funktion (p-Wert) der Chi-Quadrat-Verteilung: P(X² > chi2)."""
    if df <= 0 or chi2 < 0:
        return 1.0
    a, x = df / 2.0, chi2 / 2.0
    if x < a + 1.0:
        return 1.0 - _gser(a, x)
    return _gcf(a, x)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson-Score-Konfidenzintervall für eine Anteilsschätzung (Default 95 %)."""
    if n <= 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# --------------------------------------------------------------------------- #
# Szenario: symmetrische, knappe Ressource
# --------------------------------------------------------------------------- #

def _scenario(n_users: int, n_items: int):
    """K symmetrische Parteien konkurrieren um M knappe, gleichwertige-freie
    Quartiere im SELBEN Zeitraum (jedes in eigener Klasse → kein Ausweichen).
    Jede Partei wünscht alle M Quartiere → maximale, symmetrische Konkurrenz.
    Pro Durchlauf gewinnen genau M Parteien je ein Quartier."""
    parties = [Party(id=f"p{i}", name=f"Nutzer {i + 1}") for i in range(n_users)]
    quarters = [Quarter(id=f"q{j}", name=f"Quartier {j + 1}", eq_class=f"c{j}")
                for j in range(n_items)]
    start, end = date(2030, 6, 3), date(2030, 6, 7)
    wishes = [
        Wish(party_id=p.id, priority=prio, quarter_id=q.id, start=start, end=end)
        for p in parties
        for prio, q in enumerate(quarters, start=1)
    ]
    return parties, quarters, wishes


def simulate_equal_chance(n_users: int, n_items: int, n_runs: int,
                          seed_base: int = 0) -> dict:
    """Monte-Carlo: misst, wie oft jede (gleich gestellte) Partei die knappe
    Ressource gewinnt, und prüft Gleichverteilung per Chi-Quadrat-Test."""
    n_users = max(2, int(n_users))
    n_items = max(1, min(int(n_items), n_users - 1))   # echte Knappheit: M < K
    n_runs = max(1, int(n_runs))
    parties, quarters, wishes = _scenario(n_users, n_items)
    idx = {p.id: i for i, p in enumerate(parties)}
    wins = [0] * n_users
    for r in range(n_runs):
        res = run_lottery(parties, quarters, wishes, seed=seed_base + r)
        for a in res.allocations:
            wins[idx[a.party_id]] += 1

    total = sum(wins)
    expected = total / n_users if n_users else 0.0   # = n_runs * n_items / n_users
    chi2 = sum((w - expected) ** 2 / expected for w in wins) if expected > 0 else 0.0
    df = n_users - 1
    p_value = chi2_sf(chi2, df)
    expected_rate = n_items / n_users
    users = []
    for i, w in enumerate(wins):
        lo, hi = wilson_interval(w, n_runs)
        users.append({"index": i + 1, "wins": w, "rate": w / n_runs,
                      "ci_low": lo, "ci_high": hi})
    return {
        "n_users": n_users, "n_items": n_items, "n_runs": n_runs,
        "users": users, "expected_rate": expected_rate,
        "expected_wins": expected, "chi2": chi2, "df": df, "p_value": p_value,
        "uniform_ok": p_value > 0.05,
        "min_rate": min(u["rate"] for u in users),
        "max_rate": max(u["rate"] for u in users),
    }


def simulate_karma_effect(n_users: int, n_items: int, n_runs: int,
                          factors=None, seed_base: int = 0) -> list[dict]:
    """Zeigt den Karma-Effekt: EINE Partei erhält einen erhöhten Ausgleichsfaktor
    (alle anderen 1,0); gemessen wird ihre Gewinnrate über die Faktoren."""
    factors = factors or [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
    n_users = max(2, int(n_users))
    n_items = max(1, min(int(n_items), n_users - 1))
    n_runs = max(1, int(n_runs))
    base_parties, quarters, wishes = _scenario(n_users, n_items)
    rows = []
    for f in factors:
        parties = [Party(id=p.id, name=p.name, factor=(f if i == 0 else 1.0))
                   for i, p in enumerate(base_parties)]
        wins0 = 0
        for r in range(n_runs):
            res = run_lottery(parties, quarters, wishes, seed=seed_base + r)
            if any(a.party_id == parties[0].id for a in res.allocations):
                wins0 += 1
        lo, hi = wilson_interval(wins0, n_runs)
        rows.append({"factor": round(f, 2), "rate": wins0 / n_runs,
                     "ci_low": lo, "ci_high": hi})
    return rows

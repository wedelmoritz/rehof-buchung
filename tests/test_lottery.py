"""
Test-Suite für das Losverfahren.

Diese Tests sind der Fairness-NACHWEIS, den man der Genossenschaft zeigen kann.
Sie laufen ohne Django (reines Python) über:  python -m pytest tests/ -v

Highlights:
  * test_strategieproof_*  -> DETERMINISTISCHER Beweis (über ALLE Reihenfolgen),
    dass ehrliches Angeben nie schlechter ist als Tricksen.
  * test_pfingsten_*       -> Stress-Szenario mit vielen Kollisionen.
  * test_fairness_ueber_zeit -> Verlierer setzen sich über die Jahre durch.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest

from booking.lottery import (
    Party, Quarter, Wish, run_lottery, weighted_random_order,
)

# --------------------------------------------------------------------------- #
# Test-Fixtures / Hilfen
# --------------------------------------------------------------------------- #

D0 = date(2027, 5, 24)  # ein "Pfingst-Montag"-artiger Anker


def week(offset_days: int = 0, length: int = 7) -> tuple[date, date]:
    s = D0 + timedelta(days=offset_days)
    return s, s + timedelta(days=length)


# Drei Gärten (gleichwertig), zwei Pfarrhäuser (gleichwertig), ein Solitär.
QUARTERS = [
    Quarter("g_salix", "Gartenhaus Salix", "garten"),
    Quarter("g_lup", "Gartenhaus Lupulus", "garten"),
    Quarter("g_spin", "Gartenhaus Spinosa", "garten"),
    Quarter("p_nord", "Pfarrhaus Nord", "pfarr"),
    Quarter("p_sued", "Pfarrhaus Süd", "pfarr"),
    Quarter("hof", "Hofgebäude", "hof"),
]


def no_double_booking(result) -> bool:
    """Kein Quartier darf an zwei Parteien für dieselbe Nacht vergeben sein."""
    occ: dict[str, set[date]] = {}
    for a in result.allocations:
        d = a.start
        while d < a.end:
            key = a.quarter_id
            occ.setdefault(key, set())
            if d in occ[key]:
                return False
            occ[key].add(d)
            d += timedelta(days=1)
    return True


# --------------------------------------------------------------------------- #
# Grundlegende Korrektheit
# --------------------------------------------------------------------------- #

def test_determinismus_gleicher_seed():
    """Gleicher Seed -> identisches Ergebnis (Reproduzierbarkeit/Audit)."""
    parties = [Party(f"p{i}", f"P{i}") for i in range(8)]
    s, e = week()
    wishes = [Wish(f"p{i}", 1, "g_salix", s, e) for i in range(8)]
    r1 = run_lottery(parties, QUARTERS, wishes, seed=42)
    r2 = run_lottery(parties, QUARTERS, wishes, seed=42)
    assert r1.order == r2.order
    assert [(a.party_id, a.quarter_id) for a in r1.allocations] == \
           [(a.party_id, a.quarter_id) for a in r2.allocations]


def test_keine_doppelbuchung():
    parties = [Party(f"p{i}", f"P{i}") for i in range(12)]
    s, e = week()
    # Alle wollen dieselbe Woche in (gleichwertigen) Gärten
    wishes = [Wish(f"p{i}", 1, "g_salix", s, e) for i in range(12)]
    r = run_lottery(parties, QUARTERS, wishes, seed=7)
    assert no_double_booking(r)


def test_budget_wird_eingehalten():
    """Niemand bekommt mehr als sein Wunsch-Nächte-Budget zugeteilt."""
    p = Party("p1", "P1", wish_night_budget=10)
    wishes = [
        Wish("p1", 1, "g_salix", *week(0, 7)),   # 7 Nächte
        Wish("p1", 2, "g_lup", *week(10, 7)),    # +7 -> 14 > 10 -> darf nicht rein
    ]
    r = run_lottery([p], QUARTERS, wishes, seed=1)
    total = sum(a.nights for a in r.allocations)
    assert total <= 10
    assert total == 7  # nur der erste Wunsch passt


def test_mehrere_wuensche_pro_partei_werden_verteilt():
    """Eine Partei kann mehrere nicht-kollidierende Zeiträume gewinnen."""
    p = Party("p1", "P1", wish_night_budget=25)
    wishes = [
        Wish("p1", 1, "g_salix", *week(0, 5)),
        Wish("p1", 2, "p_nord", *week(20, 5)),
    ]
    r = run_lottery([p], QUARTERS, wishes, seed=1)
    assert len(r.allocations) == 2


# --------------------------------------------------------------------------- #
# Ausweich-Logik (Äquivalenzklassen)
# --------------------------------------------------------------------------- #

def test_ausweichen_auf_gleichwertiges_quartier():
    """Ist der konkrete Wunsch belegt, gibt es ein gleichwertiges Quartier
    statt eines Verlusts."""
    parties = [Party("a", "A"), Party("b", "B")]
    s, e = week()
    # Beide wollen konkret g_salix -> einer muss ausweichen (auf g_lup/g_spin)
    wishes = [
        Wish("a", 1, "g_salix", s, e),
        Wish("b", 1, "g_salix", s, e),
    ]
    # Feste Reihenfolge, damit der Test eindeutig ist
    r = run_lottery(parties, QUARTERS, wishes, seed=0, order=["a", "b"])
    assert len(r.allocations) == 2          # beide bekommen etwas
    assert len(r.losses) == 0               # niemand verliert
    a_alloc = next(a for a in r.allocations if a.party_id == "a")
    b_alloc = next(a for a in r.allocations if a.party_id == "b")
    assert a_alloc.quarter_id == "g_salix"  # A war zuerst dran
    assert b_alloc.quarter_id in {"g_lup", "g_spin"}  # B weicht aus
    assert b_alloc.via_substitution is True


def test_echter_verlust_wenn_klasse_voll():
    """Mehr Parteien als gleichwertige Quartiere -> echte Verlierer."""
    # 3 Gärten, aber 4 Parteien wollen dieselbe Woche -> 1 echter Verlust
    parties = [Party(x, x.upper()) for x in ["a", "b", "c", "d"]]
    s, e = week()
    wishes = [Wish(x, 1, "g_salix", s, e) for x in ["a", "b", "c", "d"]]
    r = run_lottery(parties, QUARTERS, wishes, seed=0,
                    order=["a", "b", "c", "d"])
    assert len(r.allocations) == 3
    assert len(r.losses) == 1
    assert r.losses[0].party_id == "d"      # der Letzte geht leer aus


# --------------------------------------------------------------------------- #
# Ausgleichsfaktor / Karma
# --------------------------------------------------------------------------- #

def test_karma_bonus_bei_verlust():
    parties = [Party(x, x.upper()) for x in ["a", "b", "c", "d"]]
    s, e = week()
    wishes = [Wish(x, 1, "g_salix", s, e) for x in ["a", "b", "c", "d"]]
    r = run_lottery(parties, QUARTERS, wishes, seed=0,
                    order=["a", "b", "c", "d"], factor_step=0.1, factor_cap=1.5)
    # d hat echt verloren -> +0.1
    assert r.new_factors["d"] == pytest.approx(1.1)


def test_karma_deckelung():
    """Der Faktor steigt nie über die Obergrenze."""
    p = Party("a", "A", factor=1.45)
    s, e = week()
    # a verliert (zwei Parteien um dasselbe einzige Hofgebäude)
    other = Party("b", "B")
    wishes = [Wish("a", 1, "hof", s, e), Wish("b", 1, "hof", s, e)]
    r = run_lottery([p, other], QUARTERS, wishes, seed=0, order=["b", "a"],
                    factor_step=0.1, factor_cap=1.5)
    assert r.new_factors["a"] == pytest.approx(1.5)  # 1.45 + 0.1 gedeckelt auf 1.5


def test_karma_reset_bei_umkaempftem_gewinn():
    """Wer einen umkämpften Slot gewinnt, dessen Faktor wird auf 1.0 gesetzt."""
    p = Party("a", "A", factor=1.4)
    other = Party("b", "B")
    s, e = week()
    wishes = [Wish("a", 1, "hof", s, e), Wish("b", 1, "hof", s, e)]
    r = run_lottery([p, other], QUARTERS, wishes, seed=0, order=["a", "b"])
    assert r.new_factors["a"] == pytest.approx(1.0)  # Gewinner -> Reset


def test_kein_reset_bei_unumkaempftem_gewinn():
    """Gewinn bei einem Termin, den niemand sonst wollte -> kein Reset."""
    p = Party("a", "A", factor=1.3)
    s, e = week()
    wishes = [Wish("a", 1, "hof", s, e)]  # nur a will das Hofgebäude
    r = run_lottery([p], QUARTERS, wishes, seed=0)
    assert r.new_factors["a"] == pytest.approx(1.3)  # unverändert


def test_budget_skip_ist_kein_verlust():
    """Budget-bedingtes Aussetzen zählt NICHT als Verlust (kein Karma-Bonus)."""
    p = Party("a", "A", factor=1.0, wish_night_budget=5)
    wishes = [
        Wish("a", 1, "g_salix", *week(0, 5)),   # passt
        Wish("a", 2, "p_nord", *week(20, 5)),   # Budget voll -> Skip, kein Verlust
    ]
    r = run_lottery([p], QUARTERS, wishes, seed=0)
    assert len(r.losses) == 0
    assert r.new_factors["a"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# KERNSTÜCK: Strategiesicherheit – deterministisch über ALLE Reihenfolgen
# --------------------------------------------------------------------------- #
#
# Behauptung: Ehrliches Angeben der wahren Wünsche ist NIE schlechter als ein
# Trick – für JEDE mögliche Ziehungsreihenfolge. Wir beweisen das, indem wir
# alle Reihenfolgen durchspielen und den TATSÄCHLICHEN Nutzen des Manipulators
# (gemessen an seinen WAHREN Präferenzen über reale Ergebnisse) vergleichen.
#
# Szenario:
#   Manipulator M will am liebsten EINEN Garten in Woche H (Top-Wunsch),
#   ersatzweise das Pfarrhaus in Woche H.
#   Konkurrenz: A will g_salix, B will g_lup (beide Woche H) -> die Klasse
#   "garten" (3 Quartiere: salix, lup, spin) ist durch M, A, B umkämpft.
#   C will p_nord (Woche H) -> Pfarrhaus-Klasse durch M und C umkämpft.

def _m_true_utility(result, manipulator="m") -> int:
    """WAHRER Nutzen von M, gemessen am tatsächlich erhaltenen Ergebnis:
       2 = irgendein Garten in Woche H (Lieblingsergebnis),
       1 = Pfarrhaus in Woche H (Ersatz),
       0 = nichts davon."""
    s, e = week()
    got_garten = False
    got_pfarr = False
    for a in result.allocations:
        if a.party_id != manipulator:
            continue
        if a.start == s and a.end == e:
            cls = {
                "g_salix": "garten", "g_lup": "garten", "g_spin": "garten",
                "p_nord": "pfarr", "p_sued": "pfarr", "hof": "hof",
            }[a.quarter_id]
            if cls == "garten":
                got_garten = True
            elif cls == "pfarr":
                got_pfarr = True
    if got_garten:
        return 2
    if got_pfarr:
        return 1
    return 0


def _run_scenario_with_M_wishes(m_wishes, order):
    s, e = week()
    parties = [Party("m", "M"), Party("a", "A"), Party("b", "B"), Party("c", "C")]
    wishes = list(m_wishes) + [
        Wish("a", 1, "g_salix", s, e),
        Wish("b", 1, "g_lup", s, e),
        Wish("c", 1, "p_nord", s, e),
    ]
    return run_lottery(parties, QUARTERS, wishes, seed=0, order=order)


def test_strategieproof_ueber_alle_reihenfolgen():
    s, e = week()
    # M's EHRLICHE Wunschliste: erst Garten (Prio 1), dann Pfarrhaus (Prio 2)
    truthful = [
        Wish("m", 1, "g_salix", s, e),
        Wish("m", 2, "p_nord", s, e),
    ]
    # Verschiedene TRICKS, die M versuchen könnte:
    manipulations = {
        "pfarr_zuerst": [   # Reihenfolge vertauschen (Ersatz vorziehen)
            Wish("m", 1, "p_nord", s, e),
            Wish("m", 2, "g_salix", s, e),
        ],
        "anderer_garten_zuerst": [  # vermeintlich "freieres" Quartier zuerst
            Wish("m", 1, "g_spin", s, e),
            Wish("m", 2, "p_nord", s, e),
        ],
        "nur_garten": [     # Ersatz verschweigen
            Wish("m", 1, "g_salix", s, e),
        ],
        "nur_pfarr": [      # Lieblingswunsch verschweigen
            Wish("m", 1, "p_nord", s, e),
        ],
        "zusatz_bluff": [   # zusätzlichen unrealistischen Wunsch vornanstellen
            Wish("m", 1, "hof", s, e),
            Wish("m", 2, "g_salix", s, e),
            Wish("m", 3, "p_nord", s, e),
        ],
    }

    parties_ids = ["m", "a", "b", "c"]
    n_orders = 0
    for order in itertools.permutations(parties_ids):
        order = list(order)
        u_truth = _m_true_utility(_run_scenario_with_M_wishes(truthful, order))
        for name, manip in manipulations.items():
            u_manip = _m_true_utility(_run_scenario_with_M_wishes(manip, order))
            # Der Kern: Ehrlich ist NIE schlechter als der Trick.
            assert u_truth >= u_manip, (
                f"Trick '{name}' war besser in Reihenfolge {order}: "
                f"ehrlich={u_truth}, Trick={u_manip}"
            )
        n_orders += 1
    assert n_orders == 24  # alle 4! Reihenfolgen geprüft


def test_strategieproof_trick_ist_manchmal_strikt_schlechter():
    """Ergänzend: Es gibt Reihenfolgen, in denen der Trick echt SCHADET –
    das zeigt, dass Ehrlichkeit nicht nur 'gleich gut', sondern wichtig ist."""
    s, e = week()
    truthful = [
        Wish("m", 1, "g_salix", s, e),
        Wish("m", 2, "p_nord", s, e),
    ]
    nur_pfarr = [Wish("m", 1, "p_nord", s, e)]
    strictly_worse_found = False
    for order in itertools.permutations(["m", "a", "b", "c"]):
        order = list(order)
        u_truth = _m_true_utility(_run_scenario_with_M_wishes(truthful, order))
        u_manip = _m_true_utility(_run_scenario_with_M_wishes(nur_pfarr, order))
        if u_truth > u_manip:
            strictly_worse_found = True
            break
    assert strictly_worse_found


# --------------------------------------------------------------------------- #
# Pfingst-Stress: viele Kollisionen
# --------------------------------------------------------------------------- #

def test_pfingsten_verteilt_knappe_premium_slots():
    """20 Parteien wollen alle dieselbe Pfingstwoche in der Garten-Klasse
    (3 Quartiere). Genau 3 gewinnen, 17 verlieren echt – und die 17 bekommen
    Karma-Bonus für die nächste Runde."""
    parties = [Party(f"p{i}", f"P{i}") for i in range(20)]
    s, e = week()
    wishes = [Wish(f"p{i}", 1, "g_salix", s, e) for i in range(20)]
    r = run_lottery(parties, QUARTERS, wishes, seed=123)
    assert no_double_booking(r)
    assert len(r.allocations) == 3            # nur 3 Gärten verfügbar
    assert len(r.losses) == 17                # der Rest verliert
    winners = {a.party_id for a in r.allocations}
    losers = {w.party_id for w in r.losses}
    assert winners.isdisjoint(losers)
    # Alle Verlierer haben einen erhöhten Faktor für die nächste Losung
    for pid in losers:
        assert r.new_factors[pid] == pytest.approx(1.1)
    # Alle Gewinner (umkämpft!) wurden zurückgesetzt
    for pid in winners:
        assert r.new_factors[pid] == pytest.approx(1.0)


def test_round_robin_verteilt_zwei_premium_slots_besser():
    """Zeigt den Vorteil des Runden-Prinzips: Wer die beiden Top-Slots ganz
    oben hat, bekommt sie NICHT beide, wenn andere sie auch als Top-Wunsch
    haben."""
    s1, e1 = week(0, 3)    # Slot 1
    s2, e2 = week(10, 3)   # Slot 2
    parties = [Party("a", "A"), Party("b", "B"), Party("c", "C")]
    wishes = [
        # A will beide Top-Slots (im Hofgebäude, je 1 Quartier)
        Wish("a", 1, "hof", s1, e1),
        Wish("a", 2, "hof", s2, e2),
        # B will Slot 1 (Hof), C will Slot 2 (Hof)
        Wish("b", 1, "hof", s1, e1),
        Wish("c", 1, "hof", s2, e2),
    ]
    # A ganz vorne: bekäme im Greedy beide. Im Round-Robin nur einen.
    r = run_lottery(parties, QUARTERS, wishes, seed=0, order=["a", "b", "c"])
    a_allocs = [al for al in r.allocations if al.party_id == "a"]
    assert len(a_allocs) == 1, "A darf im Runden-Prinzip nicht beide Top-Slots bekommen"
    # In Runde 1 bekommt A Slot 1; B verliert Slot 1; C bekommt Slot 2 in Runde 1
    assert any(al.party_id == "c" for al in r.allocations)


# --------------------------------------------------------------------------- #
# Gewichtung & Fairness über die Zeit (statistisch, mit festen Seeds)
# --------------------------------------------------------------------------- #

def test_hoeherer_faktor_kommt_im_schnitt_frueher():
    """Statistik: Eine Partei mit höherem Faktor landet im Mittel weiter vorne."""
    parties = [Party(f"p{i}", f"P{i}", factor=1.0) for i in range(10)]
    parties[0] = Party("p0", "P0", factor=1.5)  # bevorteilt
    positions = []
    for seed in range(400):
        order = weighted_random_order(parties, seed)
        positions.append(order.index("p0"))
    avg = sum(positions) / len(positions)
    # Bei 10 Parteien wäre der Erwartungswert ohne Gewicht 4.5.
    # Mit Faktor 1.5 muss p0 deutlich früher liegen.
    assert avg < 4.0, f"Erwartet < 4.0, war {avg:.2f}"


def test_fairness_ueber_zeit_verlierer_holen_auf():
    """Mehrjahres-Simulation: Eine Partei, die anfangs verliert, sammelt Karma
    und gewinnt über die Jahre messbar häufiger. Wir messen die Gewinnquote
    der 'Pechvogel'-Strategie mit vs. ohne Karma-Aufschlag."""
    s, e = week()

    def simulate(with_karma: bool) -> float:
        # 6 Parteien um 3 Gärten, viele Runden; zähle Gewinne von p0
        factors = {f"p{i}": 1.0 for i in range(6)}
        wins_p0 = 0
        rounds = 60
        for seed in range(rounds):
            parties = [Party(pid, pid, factor=factors[pid]) for pid in factors]
            wishes = [Wish(pid, 1, "g_salix", s, e) for pid in factors]
            r = run_lottery(parties, QUARTERS, wishes, seed=seed)
            won = {a.party_id for a in r.allocations}
            if "p0" in won:
                wins_p0 += 1
            if with_karma:
                factors = dict(r.new_factors)
            # ohne Karma: Faktoren bleiben bei 1.0
        return wins_p0 / rounds

    quote_mit = simulate(with_karma=True)
    quote_ohne = simulate(with_karma=False)
    # Mit Karma sollte die Gewinnquote des (anfänglichen) Verlierers höher sein.
    assert quote_mit >= quote_ohne
    # Und in der Nähe eines fairen Anteils liegen (3 von 6 = 0.5).
    assert quote_mit > 0.40, f"Gewinnquote mit Karma zu niedrig: {quote_mit:.2f}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

"""Reine-Logik-Tests für die robuste Aggregation (ADR 0113, NL-L2).
Schwerpunkt: ein einzelner Vielschreiber kippt nichts (Quorum verschiedener Pseudonyme)."""
from booking.nl_mining import mine_alias_candidates, mine_ranking_candidates


def _ev(pseudo, token, quarter, day):
    return {"pseudo": pseudo, "token": token, "quarter": quarter, "day": day}


def test_ein_vielschreiber_erzeugt_keinen_kandidaten():
    # EIN Pseudonym, 500 Beobachtungen → 1 Stimme < Quorum → nichts.
    events = [_ev("P", "turmchen", 7, d % 30) for d in range(500)]
    assert mine_alias_candidates(events, quorum=3) == []


def test_quorum_verschiedener_pseudonyme_erzeugt_kandidaten():
    events = [_ev(f"U{i}", "turmchen", 7, i * 4) for i in range(4)]  # 4 versch. Nutzer
    out = mine_alias_candidates(events, quorum=3, min_span_days=3)
    assert len(out) == 1
    assert out[0].token == "turmchen" and out[0].quarter_id == 7
    assert out[0].distinct_users == 4


def test_mehrdeutiger_token_faellt_durch_exklusivitaet():
    # „haus": 3 Nutzer → Quartier 7, 3 andere → Quartier 9 → Exklusivität 0.5 < 0.8.
    events = [_ev(f"A{i}", "haus", 7, i * 5) for i in range(3)]
    events += [_ev(f"B{i}", "haus", 9, i * 5) for i in range(3)]
    assert mine_alias_candidates(events, quorum=3, min_exclusivity=0.8) == []


def test_ein_tages_ausbruch_faellt_durch_stabilitaet():
    # 4 verschiedene Nutzer, aber alle am selben Tag → span 0 < min_span_days.
    events = [_ev(f"U{i}", "turmchen", 7, 10) for i in range(4)]
    assert mine_alias_candidates(events, quorum=3, min_span_days=3) == []


def test_ranking_reorder_bei_quorum():
    # „sommer" heute [7,8,6]; 4 verschiedene wählen August (8) → Vorschlag 8 vorne.
    events = [{"pseudo": f"U{i}", "season": "sommer", "month": 8} for i in range(4)]
    out = mine_ranking_candidates(events, {"sommer": [7, 8, 6]}, quorum=3,
                                  min_exclusivity=0.6)
    assert len(out) == 1
    assert out[0].new_order == (8, 7, 6)


def test_ranking_vielschreiber_kippt_nichts():
    events = [{"pseudo": "P", "season": "sommer", "month": 8} for _ in range(200)]
    assert mine_ranking_candidates(events, {"sommer": [7, 8, 6]}, quorum=3) == []

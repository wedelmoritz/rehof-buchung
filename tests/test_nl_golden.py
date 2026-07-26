"""NL-L4: der Golden-Set ist der Drift-Wächter – kanonische Eingaben müssen stabil
bleiben (ADR 0113). Reine Logik, ohne DB."""
from __future__ import annotations

from booking import nl_golden


def test_golden_set_ist_gruen():
    assert nl_golden.run_golden() == []


def test_gelernte_reihung_kann_golden_verschieben():
    """Eine vorgeschlagene Reihung, die „Sommer" auf August vorzieht, verändert die
    kanonische „sommerwoche"→Juli-Erwartung – genau dieses Signal nutzt die
    Shadow-Auswertung fürs Review."""
    learned = {"aliases": {}, "rankings": {"sommer": [8, 7, 6]}}
    diffs = nl_golden.run_golden(learned)
    assert any("sommerwoche" in d for d in diffs)


def test_neuer_alias_bricht_golden_nicht():
    """Ein Alias auf ein neues Wort lässt alle kanonischen Fälle unberührt."""
    learned = {"aliases": {"tuermchen": 1}, "rankings": {}}
    assert nl_golden.run_golden(learned) == []

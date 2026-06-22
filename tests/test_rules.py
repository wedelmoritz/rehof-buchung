"""
Tests für die Buchungsregeln (reines Python, ohne Django).

Lauf:  PYTHONPATH=. python -m pytest tests/test_rules.py -v
"""
from __future__ import annotations

from datetime import date, timedelta

from booking.rules import Season, Stay, validate_booking


def day(m, d):
    return date(2026, m, d)


def rng(m, d, nights):
    s = day(m, d)
    return s, s + timedelta(days=nights)


# --------------------------------------------------------------------------- #
# Mindestnächte
# --------------------------------------------------------------------------- #

def test_standard_mindestnaechte_3():
    s, e = rng(6, 1, 2)  # nur 2 Nächte
    err = validate_booking([], 3, s, e, [])
    assert err is not None and "Mindestbuchung" in err


def test_standard_3_ok():
    s, e = rng(6, 1, 3)
    assert validate_booking([], 3, s, e, []) is None


def test_juli_august_braucht_7_naechte():
    hoch = Season("Hochsaison Juli/Aug", day(7, 1), day(9, 1), min_nights=7)
    s, e = rng(7, 10, 5)  # 5 Nächte im Juli -> zu kurz
    err = validate_booking([hoch], 3, s, e, [])
    assert err is not None and "7 Nächte" in err
    # 7 Nächte ok
    s7, e7 = rng(7, 10, 7)
    assert validate_booking([hoch], 3, s7, e7, []) is None


# --------------------------------------------------------------------------- #
# Max. parallele Wohneinheiten in Sonderzeiträumen
# --------------------------------------------------------------------------- #

def test_max_2_parallele_einheiten_in_ferien():
    ferien = Season("Pfingsten", day(5, 22), day(5, 27), max_parallel_units=2)
    # Mitglied hat schon zwei sich überschneidende Buchungen in der Pfingstzeit
    existing = [Stay(day(5, 23), day(5, 26)), Stay(day(5, 23), day(5, 26))]
    # dritte parallele Einheit -> abgelehnt
    s, e = day(5, 23), day(5, 26)
    err = validate_booking([ferien], 3, s, e, existing)
    assert err is not None and "gleichzeitig" in err


def test_zwei_parallele_einheiten_erlaubt():
    ferien = Season("Pfingsten", day(5, 22), day(5, 27), max_parallel_units=2)
    existing = [Stay(day(5, 23), day(5, 26))]  # eine bestehende
    s, e = day(5, 23), day(5, 26)  # die zweite parallel -> ok
    assert validate_booking([ferien], 3, s, e, existing) is None


def test_ausserhalb_sonderzeitraum_unbegrenzt_parallel():
    ferien = Season("Pfingsten", day(5, 22), day(5, 27), max_parallel_units=2)
    # Buchung im Juni (außerhalb), schon zwei parallele bestehen -> trotzdem ok
    existing = [Stay(day(6, 10), day(6, 14)), Stay(day(6, 10), day(6, 14))]
    s, e = day(6, 10), day(6, 14)
    assert validate_booking([ferien], 3, s, e, existing) is None


# --------------------------------------------------------------------------- #
# Aufenthaltsdeckel Sommerferien (14 Einheiten-Nächte)
# --------------------------------------------------------------------------- #

SOMMER = Season(
    "Sommerferien BB", day(7, 9), day(8, 23),
    max_parallel_units=2, max_stay_nights=14,
)


def test_zwei_wochen_eine_einheit_ok():
    s, e = rng(7, 10, 14)  # 14 Nächte am Stück
    assert validate_booking([SOMMER], 3, s, e, []) is None


def test_dritte_woche_ueber_deckel_abgelehnt():
    # schon 14 Nächte gebucht, eine weitere Nacht im Sommer -> abgelehnt
    existing = [Stay(day(7, 10), day(7, 24))]  # 14 Nächte
    s, e = rng(8, 1, 3)
    err = validate_booking([SOMMER], 3, s, e, existing)
    assert err is not None and "je Partei" in err


def test_eine_woche_zwei_einheiten_ok():
    # 1 Woche in Einheit A bereits gebucht; 1 Woche in Einheit B parallel
    existing = [Stay(day(7, 10), day(7, 17))]  # 7 Nächte
    s, e = rng(7, 10, 7)  # weitere 7 Nächte, parallel -> 14 gesamt, ok
    assert validate_booking([SOMMER], 3, s, e, existing) is None


def test_zwei_wochen_zwei_einheiten_abgelehnt():
    # 2 Wochen in Einheit A + 1 Woche in Einheit B -> 21 > 14 -> abgelehnt
    existing = [Stay(day(7, 10), day(7, 24))]  # 14 Nächte
    s, e = rng(7, 10, 7)  # +7 parallel -> 21
    err = validate_booking([SOMMER], 3, s, e, existing)
    assert err is not None and "je Partei" in err


def test_kombiniert_min_und_parallel_und_deckel():
    """Sommerferien: Mindestnächte (über Hochsaison-Regel) + Parallel + Deckel
    greifen gemeinsam."""
    hoch = Season("Hochsaison", day(7, 1), day(9, 1), min_nights=7)
    seasons = [hoch, SOMMER]
    # 3 Nächte im Sommer -> verstößt gegen Mindestnächte (7)
    s, e = rng(7, 12, 3)
    err = validate_booking(seasons, 3, s, e, [])
    assert err is not None and "Mindestbuchung" in err

"""
Tests für die Buchungszeitraum- und Tage-Logik (reines Python, ohne Django).

Lauf:  PYTHONPATH=. python -m pytest tests/test_availability.py -v
"""
from __future__ import annotations

from datetime import date

from booking.availability import (
    Window, is_released, range_released, released_gaps, remaining_nights,
    weekend_keys,
)


def d(m, day):
    return date(2026, m, day)


# --------------------------------------------------------------------------- #
# Globale Freischaltung
# --------------------------------------------------------------------------- #

def test_ohne_fenster_nichts_buchbar():
    assert is_released([], "q1", d(6, 1)) is False


def test_globales_fenster_gibt_alle_quartiere_frei():
    w = Window(start=d(1, 1), end=d(12, 31), applies_to_all=True)
    assert is_released([w], "q1", d(6, 1)) is True
    assert is_released([w], "q2", d(6, 1)) is True


def test_ausserhalb_des_globalen_fensters_gesperrt():
    w = Window(start=d(6, 1), end=d(9, 1), applies_to_all=True)
    assert is_released([w], "q1", d(5, 31)) is False
    assert is_released([w], "q1", d(9, 1)) is False   # end ist exklusiv
    assert is_released([w], "q1", d(8, 31)) is True


def test_gesperrtes_fenster_zaehlt_nicht():
    w = Window(start=d(1, 1), end=d(12, 31), applies_to_all=True, active=False)
    assert is_released([w], "q1", d(6, 1)) is False


# --------------------------------------------------------------------------- #
# Einschränkung für eine Teilmenge (Schnittmengen-Semantik)
# --------------------------------------------------------------------------- #

def test_spezifisches_fenster_schraenkt_weiter_ein():
    """Global Jan–Dez, aber Pfarrhaus nur Mai–Sept -> Pfarrhaus außerhalb
    Mai–Sept gesperrt, andere Quartiere weiter frei."""
    g = Window(start=d(1, 1), end=d(12, 31), applies_to_all=True)
    p = Window(start=d(5, 1), end=d(10, 1), applies_to_all=False,
               quarter_ids=frozenset({"pfarr"}))
    windows = [g, p]
    # Pfarrhaus im Sommer frei, im Winter gesperrt
    assert is_released(windows, "pfarr", d(6, 1)) is True
    assert is_released(windows, "pfarr", d(3, 1)) is False
    # Ein anderes Quartier ohne Einschränkung bleibt ganzjährig frei
    assert is_released(windows, "andere", d(3, 1)) is True


def test_spezifisch_kann_nicht_ueber_global_hinaus_erweitern():
    """Spezifisches Fenster ist weiter als global -> trotzdem nur global zählt
    (Einschränkung, keine Erweiterung)."""
    g = Window(start=d(6, 1), end=d(9, 1), applies_to_all=True)
    p = Window(start=d(1, 1), end=d(12, 31), applies_to_all=False,
               quarter_ids=frozenset({"q1"}))
    windows = [g, p]
    assert is_released(windows, "q1", d(3, 1)) is False  # global deckt nicht ab
    assert is_released(windows, "q1", d(7, 1)) is True    # Schnittmenge


def test_inaktives_spezifisches_fenster_wird_ignoriert():
    g = Window(start=d(1, 1), end=d(12, 31), applies_to_all=True)
    p = Window(start=d(5, 1), end=d(10, 1), applies_to_all=False,
               quarter_ids=frozenset({"pfarr"}), active=False)
    # spezifisches Fenster inaktiv -> nur global zählt -> ganzjährig frei
    assert is_released([g, p], "pfarr", d(3, 1)) is True


# --------------------------------------------------------------------------- #
# Zeitraum-Prüfung und buchbare Lücken
# --------------------------------------------------------------------------- #

def test_range_released_prueft_jeden_tag():
    w = Window(start=d(6, 1), end=d(6, 10), applies_to_all=True)
    assert range_released([w], "q1", d(6, 1), d(6, 5)) is True
    assert range_released([w], "q1", d(6, 8), d(6, 12)) is False  # ragt heraus
    assert range_released([w], "q1", d(6, 5), d(6, 5)) is False   # leer


def test_released_gaps_kombiniert_frei_und_freigeschaltet():
    # Global Juni; ein belegter Block 10.–15. Juni -> zwei Lücken
    w = Window(start=d(6, 1), end=d(7, 1), applies_to_all=True)
    occupied = set()
    cur = d(6, 10)
    while cur < d(6, 15):
        occupied.add(cur)
        from datetime import timedelta
        cur += timedelta(days=1)
    gaps = released_gaps([w], "q1", occupied, d(6, 1), d(6, 30))
    assert (d(6, 1), d(6, 10)) in gaps
    assert (d(6, 15), d(6, 30)) in gaps


def test_released_gaps_nur_im_freigeschalteten_bereich():
    # Global nur 5.–20. Juni; nichts belegt -> nur dieser Bereich ist buchbar
    w = Window(start=d(6, 5), end=d(6, 20), applies_to_all=True)
    gaps = released_gaps([w], "q1", set(), d(6, 1), d(6, 30))
    assert gaps == [(d(6, 5), d(6, 20))]


# --------------------------------------------------------------------------- #
# Verfügbare Tage – Übertragung an Mitglieder, kein Jahresübertrag
# --------------------------------------------------------------------------- #

def test_remaining_basis():
    assert remaining_nights(annual_budget=50, used=10) == 40


def test_remaining_mit_uebertragung():
    # 50 Kontingent, 5 erhalten, 8 abgegeben, 10 verbraucht -> 37
    assert remaining_nights(50, used=10, received=5, given=8) == 37


def test_abgegebene_tage_reduzieren_verfuegbarkeit():
    geber = remaining_nights(50, used=0, given=20)
    nehmer = remaining_nights(50, used=0, received=20)
    assert geber == 30
    assert nehmer == 70


# --------------------------------------------------------------------------- #
# Wochenend-Zählung (Fr-/Sa-Nächte, je Wochenende einmal)
# --------------------------------------------------------------------------- #

def test_weekend_keys_zaehlt_freitag_samstag():
    # 2026-07-03 ist ein Freitag. Fr+Sa-Nacht = 1 Wochenende.
    assert len(weekend_keys(date(2026, 7, 3), date(2026, 7, 5))) == 1


def test_weekend_keys_wochentags_keine():
    # Mo–Do (kein Fr/Sa) → 0 Wochenenden.
    assert weekend_keys(date(2026, 7, 6), date(2026, 7, 9)) == set()


def test_weekend_keys_distinkt_je_woche():
    # Zwei Aufenthalte in verschiedenen Wochen → 2 distinkte Wochenenden.
    keys = weekend_keys(date(2026, 7, 3), date(2026, 7, 4))      # WE 1
    keys |= weekend_keys(date(2026, 7, 10), date(2026, 7, 11))   # WE 2
    assert len(keys) == 2

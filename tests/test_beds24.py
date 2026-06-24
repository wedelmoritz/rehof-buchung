"""Reine Tests für den Beds24-Import (Parsing + unscharfer Namensabgleich)."""
from datetime import date

from booking.beds24 import (
    Beds24Row, Candidate, name_score, parse_csv, rank_candidates,
)


def test_name_score_reihenfolge_und_tippfehler():
    assert name_score("Anna Schmidt", "Anna Schmidt") == 1.0
    # "Nachname, Vorname" trifft trotzdem hoch
    assert name_score("Schmidt, Anna", "Anna Schmidt") > 0.9
    # Tippfehler/Teilname noch ähnlich, aber < exakt
    assert 0.4 < name_score("Anna Schmid", "Anna Schmidt") < 1.0
    # Völlig anders → niedrig
    assert name_score("Anna Schmidt", "Tom Müller") < 0.34


def test_rank_candidates_sortiert_und_filtert():
    cands = [
        Candidate(key=1, names=["Anna Schmidt", "anna0"]),
        Candidate(key=2, names=["Tom Müller"]),
        Candidate(key=3, names=["Anna Schmitt"]),
    ]
    ranked = rank_candidates("Anna Schmidt", cands)
    assert ranked[0][0] == 1                       # exakter Treffer zuerst
    assert all(score >= 0.34 for _, score in ranked)
    assert 2 not in [k for k, _ in ranked]         # Müller fällt raus


def test_parse_csv_semikolon_und_spaltenerkennung():
    data = (
        "Guest Name;Arrival;Departure;Unit;Adults;Status\n"
        "Anna Schmidt;2026-06-01;2026-06-05;Gartenhaus Salix;2;confirmed\n"
        "Müller, Tom;01.07.2026;04.07.2026;Pfarrhaus Nord;3;confirmed\n"
    )
    rows = parse_csv(data)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0.guest_name == "Anna Schmidt"
    assert r0.arrival == date(2026, 6, 1) and r0.departure == date(2026, 6, 5)
    assert r0.unit == "Gartenhaus Salix" and r0.persons == 2
    assert r0.nights == 4 and r0.valid
    # zweite Zeile: deutsches Datumsformat
    assert rows[1].arrival == date(2026, 7, 1)


def test_parse_csv_getrennte_vor_nachname_spalten():
    data = ("firstName,lastName,checkin,checkout,room\n"
            "Anna,Schmidt,2026-06-01,2026-06-05,Hofgebäude\n")
    rows = parse_csv(data)
    assert rows[0].guest_name == "Anna Schmidt"
    assert rows[0].unit == "Hofgebäude"


def test_ungueltige_zeile_erkannt():
    r = Beds24Row(guest_name="X", arrival=None, departure=None)
    assert not r.valid

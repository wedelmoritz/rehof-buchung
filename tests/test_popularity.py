"""Reine-Logik-Tests für die kapazitätsrelative Beliebtheit (ADR 0103, P0)."""
from booking.popularity import (
    band_rank, popularity_band, suitability_score, worse_band,
)


def test_frei_ohne_nachfrage():
    assert popularity_band(0, 5)["key"] == "free"
    assert popularity_band(0, 0)["key"] == "free"


def test_baender_relativ_zur_kapazitaet():
    # capacity 3: <3 etwas gefragt, 3..4.5 beliebt, >4.5 sehr beliebt
    assert popularity_band(2, 3)["key"] == "some"
    assert popularity_band(3, 3)["key"] == "popular"
    assert popularity_band(4, 3)["key"] == "popular"      # 4/3 = 1.33 ≤ 1.5
    assert popularity_band(5, 3)["key"] == "very"         # 5/3 = 1.67 > 1.5


def test_einzelquartier_klasse():
    # capacity 1: 1 Wunsch = beliebt, 2 = sehr beliebt
    assert popularity_band(1, 1)["key"] == "popular"
    assert popularity_band(2, 1)["key"] == "very"


def test_nachfrage_ohne_kapazitaet_ist_maximal():
    assert popularity_band(1, 0)["key"] == "very"


def test_labels_positiv():
    # Wortwahl ADR 0072 – niemals „Konflikt/umkämpft".
    labels = {popularity_band(o, 2)["label"] for o in (0, 1, 2, 9)}
    assert labels == {"frei", "etwas gefragt", "beliebt", "sehr beliebt"}
    for lbl in labels:
        assert "konflikt" not in lbl.lower() and "umkämpft" not in lbl.lower()


def test_tone_bleibt_ampel_kompatibel():
    assert {popularity_band(o, 2)["tone"] for o in (0, 1, 2, 9)} == {
        "free", "many", "few", "full"}


def test_rang_und_schlimmeres_band():
    assert band_rank(popularity_band(0, 3)) == 0
    assert band_rank(popularity_band(9, 1)) == 3
    a, b = popularity_band(1, 3), popularity_band(9, 1)   # some vs very
    assert worse_band(a, b)["key"] == "very"
    assert worse_band(b, a)["key"] == "very"


def test_empfehlungs_sortierung():
    frei = popularity_band(0, 3)
    beliebt = popularity_band(3, 3)
    # Passend + frei schlägt passend + beliebt; unpassend ganz hinten.
    assert suitability_score(True, frei) < suitability_score(True, beliebt)
    assert suitability_score(True, beliebt) < suitability_score(False, frei)
    # Eigener bereits gewünschter Kandidat rutscht hinter fremde gleicher Eignung.
    assert suitability_score(True, frei) < suitability_score(True, frei, own_wish=True)

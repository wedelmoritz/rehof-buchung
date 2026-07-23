"""Reine-Logik-Tests für den regelbasierten NL-Parser (ADR 0103, P2 „Weg A").

Deckt Möglichkeiten (Zeitraum benannt/konkret, Quartier/Klasse, Personen,
barrierefrei, Besonderheiten) UND Grenzen/Security (Längenlimit, keine Ausführung,
best-effort/nie blockierend) ab. Stammdaten werden – wie in echt – injiziert."""
from datetime import date

from booking.wish_nl import MAX_LEN, parse_booking_text, parse_wish_text

YEAR = 2027
QUARTERS = [(1, "Turmzimmer"), (2, "Pfarrhaus"), (3, "Salix")]
CLASSES = [(10, "Stallwohnung"), (11, "Einzelzimmer")]
HOLIDAYS = [("Herbstferien", date(YEAR, 10, 20), date(YEAR, 11, 1))]
SEASONS = [("Hochsaison", date(YEAR, 6, 1), date(YEAR, 8, 31))]


def _wish(text):
    return parse_wish_text(text, quarters=QUARTERS, eq_classes=CLASSES,
                           seasons=SEASONS, holidays=HOLIDAYS, year=YEAR)


# --------------------------------------------------------------------------- #
# Zeitraum
# --------------------------------------------------------------------------- #
def test_konkreter_zeitraum_mit_monatsname():
    i = _wish("gern 12.-19. Juli")
    assert i.start == date(YEAR, 7, 12)
    assert i.end == date(YEAR, 7, 19)


def test_konkreter_zeitraum_numerisch():
    i = _wish("vom 3.10. bis 10.10.")
    assert i.start == date(YEAR, 10, 3)
    assert i.end == date(YEAR, 10, 10)


def test_zeitraum_mit_jahr():
    i = _wish("12.7.2027 bis 19.7.2027")
    assert i.start == date(2027, 7, 12) and i.end == date(2027, 7, 19)


def test_startdatum_plus_dauer():
    i = _wish("ab 3.10. für eine Woche")
    assert i.start == date(YEAR, 10, 3)
    assert i.end == date(YEAR, 10, 10)


def test_benannter_konfigurierter_feiertag():
    i = _wish("am liebsten in den Herbstferien")
    assert i.start == date(YEAR, 10, 20)
    assert i.end == date(YEAR, 11, 1)


def test_benannte_konfigurierte_saison():
    i = _wish("irgendwas in der Hochsaison")
    assert i.start == date(YEAR, 6, 1)


def test_einzeldatum_ohne_dauer_meldet_offenes_ende():
    i = _wish("ab dem 5.8.")
    assert i.start == date(YEAR, 8, 5)
    assert i.end is None
    assert any("Enddatum" in u for u in i.unresolved)


# --------------------------------------------------------------------------- #
# Quartier / Klasse (unscharf gegen KONFIGURIERTE Namen)
# --------------------------------------------------------------------------- #
def test_quartier_unscharf():
    assert _wish("würde gern ins Turmzimmer").quarter_key == 1
    assert _wish("lieber das Pfarrhaus").quarter_key == 2


def test_quartier_gross_klein_und_zeichen():
    # Groß-/Kleinschreibung + angrenzende Satzzeichen stören den Treffer nicht.
    assert _wish("bitte TURMZIMMER!").quarter_key == 1


def test_starker_tippfehler_ist_dokumentierte_grenze():
    # ADR-Grenze: deutliche Tippfehler werden NICHT geraten (lieber kein Treffer als
    # ein falscher) – best-effort, kein Crash. Fällt sauber auf die Formularauswahl.
    assert _wish("ins Turmzmr").quarter_key is None


def test_aequivalenzklasse_wenn_kein_quartier():
    i = _wish("eine Stallwohnung wäre schön")
    assert i.quarter_key is None
    assert i.eq_class_key == 10


def test_kein_falscher_quartier_treffer():
    # nichts Quartier-Ähnliches → kein Treffer (lieber keiner als ein falscher)
    assert _wish("einfach nur mal weg").quarter_key is None


# --------------------------------------------------------------------------- #
# Personen / barrierefrei / flexibel
# --------------------------------------------------------------------------- #
def test_personen():
    assert _wish("für 4 Personen").persons == 4
    assert _wish("wir sind 3").persons == 3


def test_barrierefrei():
    assert _wish("bitte barrierefrei").accessible is True
    assert _wish("etwas mit Rollstuhl").accessible is True


def test_flexibel():
    assert _wish("zeitlich flexibel, egal wann").flexible is True


# --------------------------------------------------------------------------- #
# Besonderheiten (Buchung): Hund / Beistellbett / Endreinigung
# --------------------------------------------------------------------------- #
def _book(text):
    return parse_booking_text(text, quarters=QUARTERS, eq_classes=CLASSES,
                              seasons=SEASONS, holidays=HOLIDAYS, year=YEAR)


def test_hund_und_beistellbett():
    i = _book("12.-19. Juli mit Hund und Beistellbett")
    assert "hund" in i.special
    assert "beistellbett" in i.special


def test_mit_und_ohne_endreinigung():
    assert _book("mit Endreinigung").cleaning is True
    assert _book("ohne Endreinigung bitte").cleaning is False


def test_negation_kein_hund():
    assert "hund" not in _book("kein Hund dabei").special


def test_kind():
    assert "kinder" in _book("wir kommen mit Kindern").special


def test_booking_kind_marker():
    assert _book("egal").kind == "booking"
    assert _wish("egal").kind == "wish"


# --------------------------------------------------------------------------- #
# Grenzen / Security / Robustheit
# --------------------------------------------------------------------------- #
def test_leere_eingabe_ist_leer():
    assert _wish("").is_empty
    assert _wish("   ").is_empty


def test_nicht_modelliertes_landet_nicht_falsch():
    # „ruhig"/„mit Sauna" sind keine Felder → dürfen nichts Falsches setzen.
    i = _wish("ganz ruhig mit Sauna")
    assert i.quarter_key is None and i.accessible is None and i.start is None


def test_laenge_hart_begrenzt_kein_hang():
    # Sehr lange, potenziell missbräuchliche Eingabe: kein Hang, sauber begrenzt.
    huge = "12.7. " + ("a" * 5000) + " 19.7."
    i = _wish(huge)
    # Nur die ersten MAX_LEN Zeichen zählen (das zweite Datum liegt dahinter).
    assert i.start == date(YEAR, 7, 12)
    assert len(huge) > MAX_LEN


def test_html_und_script_werden_nur_als_daten_behandelt():
    # Kein Rendering/keine Ausführung – Eingabe ist reiner Text, Ausgabe strukturiert.
    i = _wish("<script>alert(1)</script> ins Turmzimmer")
    assert i.quarter_key == 1
    # Es gibt keinerlei HTML in den strukturierten Feldern.
    assert all("<" not in m for m in i.matched)


def test_best_effort_nie_exception():
    # Wilde Zeichen dürfen nie eine Exception werfen.
    for junk in ("...", "31.2. bis 40.13.", "€%&/()=", "\x00\x07 kaputt", "42."):
        parse_wish_text(junk, quarters=QUARTERS, eq_classes=CLASSES,
                        seasons=SEASONS, holidays=HOLIDAYS, year=YEAR)


def test_ungueltiges_datum_wird_ignoriert():
    # 31.2. existiert nicht → kein Startdatum, aber auch kein Crash.
    i = _wish("am 31.2.")
    assert i.start is None


def test_bloßer_monat_setzt_month_kein_start():
    # „eine Woche im Juli": die reine Logik erkennt Monat + Dauer, aber (bewusst) KEIN
    # konkretes Startdatum – das erste freie Datum bestimmt der Service-Layer (Verfügbarkeit).
    i = _wish("eine Woche im Juli")
    assert i.start is None
    assert i.month == 7
    assert i.nights == 7
    assert any("Juli" in m for m in i.matched)


def test_monat_kuerzel_und_ohne_dauer():
    i = _wish("im august, barrierefrei")
    assert i.month == 8 and i.start is None and i.accessible is True


def test_konkretes_datum_setzt_keinen_monat():
    # Mit Tag+Monat entsteht ein echtes Datum – kein grober Monatswunsch nötig.
    i = _wish("ab 12. Juli für eine Woche")
    assert i.start == date(YEAR, 7, 12)
    assert i.month is None

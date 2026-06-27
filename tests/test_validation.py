"""Tests der Plausibilitäts-Prüfungen (reines Python, ohne Django)."""
from __future__ import annotations

from booking.validation import (
    city_error, email_error, iban_error, name_error,
    normalize_iban, plz_error, street_error, strip_controls,
)


# --- Name -------------------------------------------------------------------
def test_name_akzeptiert_echte_namen():
    for ok in ["Anna", "Anne-Marie", "O'Brien", "José", "Müller", "Dr. Schmidt",
               "Élodie Dupont", "von der Heide"]:
        assert name_error(ok) is None, ok


def test_name_lehnt_ziffern_markup_und_steuerzeichen_ab():
    assert name_error("Anna3") is not None
    assert name_error("<script>") is not None
    assert name_error("a\tb") is not None
    assert name_error("=cmd") is not None        # Ziffer-/Markup-frei? nein: '=' unzulässig
    assert name_error("") is not None            # leer
    assert name_error("-") is not None           # kein Buchstabe
    assert name_error("A") is not None           # zu kurz


# --- PLZ --------------------------------------------------------------------
def test_plz_genau_fuenf_ziffern():
    assert plz_error("10115") is None
    assert plz_error("1011") is not None
    assert plz_error("101156") is not None
    assert plz_error("1011a") is not None
    assert plz_error("", required=False) is None
    assert plz_error("", required=True) is not None


# --- Ort --------------------------------------------------------------------
def test_city_erlaubt_klammern_und_bindestrich():
    for ok in ["Berlin", "Frankfurt (Oder)", "Halle (Saale)", "Bergisch Gladbach",
               "Sankt Augustin", "Weil am Rhein"]:
        assert city_error(ok) is None, ok


def test_city_lehnt_ziffern_und_markup_ab():
    assert city_error("Berlin1") is not None
    assert city_error("<b>") is not None
    assert city_error("", required=False) is None


# --- Straße -----------------------------------------------------------------
def test_street_erlaubt_hausnummer():
    assert street_error("Hauptstraße 12") is None
    assert street_error("Am Hof 3a") is None
    assert street_error("<x>") is not None
    assert street_error("12345") is not None     # nur Ziffern, kein Name


# --- E-Mail -----------------------------------------------------------------
def test_email_plausibilitaet():
    assert email_error("a@b.de") is None
    assert email_error("max.muster@example.org") is None
    assert email_error("keinatzeichen") is not None
    assert email_error("a@b") is not None
    assert email_error("a b@c.de") is not None
    assert email_error("", required=False) is None


# --- IBAN (Format + Länge + Mod-97) -----------------------------------------
def test_iban_gueltig():
    # Bekannte gültige Test-IBANs (Prüfsumme korrekt).
    assert iban_error("DE89 3704 0044 0532 0130 00") is None
    assert iban_error("GB82 WEST 1234 5698 7654 32") is None


def test_iban_pruefsumme_und_laenge():
    assert iban_error("DE89 3704 0044 0532 0130 01") is not None   # Prüfsumme falsch
    assert iban_error("DE89 3704 0044 0532 0130") is not None      # zu kurz für DE
    assert iban_error("XX00") is not None                          # Format/zu kurz
    assert iban_error("", required=False) is None
    assert iban_error("", required=True) is not None


def test_normalize_iban():
    assert normalize_iban(" de89 3704 ") == "DE893704"


# --- Freitext ---------------------------------------------------------------
def test_strip_controls_behaelt_zeilenumbruch():
    assert strip_controls("a\x00\x07b\tc\nd") == "ab\tc\nd"
    assert strip_controls("x" * 10, max_len=3) == "xxx"

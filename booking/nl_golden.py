"""Golden-Set für den NL-Parser (ADR 0113, Batch NL-L4): eine kleine, kuratierte
Menge kanonischer Eingaben mit **erwartetem** Parse-Ergebnis. Django-frei, damit sie
in der reinen Suite (`tests/`) als **Drift-Wächter** läuft: ändert eine Anpassung am
Parser das kanonische Verhalten, schlägt der Golden-Test an.

Der Golden-Set dient zusätzlich als Sicherung bei der **Shadow-Auswertung** eines
Lern-Vorschlags (Service `nl_shadow_eval`): wirkt eine vorgeschlagene **Reihung** auf
eine kanonische Jahreszeit-Eingabe, wird das als Regression sichtbar – der Mensch
entscheidet dann bewusst.

Nur reine `(key, name)`-Stammdaten + Text; kein Django/keine DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import wish_nl

# Fixe Stammdaten (unabhängig von der DB) – stabile IDs/Namen für die Erwartungen.
YEAR = 2027
QUARTERS = [(1, "Turmzimmer"), (2, "Seeblick"), (3, "Stallhaus")]
EQ_CLASSES = [(10, "Klein"), (11, "Groß")]
SEASONS = [("Sommerferien", date(YEAR, 7, 1), date(YEAR, 8, 31))]
HOLIDAYS: list = []
TODAY = date(YEAR, 1, 15)


@dataclass
class GoldenCase:
    text: str
    kind: str = "wish"                       # "wish" | "booking"
    expect: dict = field(default_factory=dict)  # Teil-Erwartung an WishIntent


# Kanonische, klar korrekte Eingaben. Nur stabile Felder werden geprüft.
GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase("turmzimmer eine woche",
               expect={"quarter_key": 1, "nights": 7}),
    GoldenCase("seeblick 12.7. bis 19.7.",
               expect={"quarter_key": 2,
                       "start": date(YEAR, 7, 12), "end": date(YEAR, 7, 19)}),
    GoldenCase("sommerwoche",
               expect={"month": 7, "nights": 7}),
    GoldenCase("im august 3 nächte",
               expect={"months": [8], "nights": 3}),
    GoldenCase("winter 5 tage",
               expect={"month": 1, "nights": 5}),
    GoldenCase("stallhaus 4 personen barrierefrei", kind="booking",
               expect={"quarter_key": 3, "persons": 4, "accessible": True}),
    GoldenCase("2 wochen ab 3.8.", kind="booking",
               expect={"start": date(YEAR, 8, 3), "nights": 14}),
]


def _parse(case: GoldenCase, learned=None) -> wish_nl.WishIntent:
    fn = (wish_nl.parse_booking_text if case.kind == "booking"
          else wish_nl.parse_wish_text)
    return fn(case.text, quarters=QUARTERS, eq_classes=EQ_CLASSES,
              seasons=SEASONS, holidays=HOLIDAYS, year=YEAR, today=TODAY,
              learned=learned)


def check_case(case: GoldenCase, learned=None) -> list[str]:
    """Prüft eine Fall-Erwartung; gibt eine Liste von Abweichungen (leer = ok)."""
    intent = _parse(case, learned)
    diffs: list[str] = []
    for key, want in case.expect.items():
        got = getattr(intent, key)
        if got != want:
            diffs.append(f"{case.text!r}: {key}={got!r} (erwartet {want!r})")
    return diffs


def run_golden(learned=None) -> list[str]:
    """Alle Golden-Fälle prüfen; gibt die gesammelten Abweichungen (leer = alles ok)."""
    out: list[str] = []
    for case in GOLDEN_CASES:
        out.extend(check_case(case, learned))
    return out

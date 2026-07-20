"""Service-Naht für den regelbasierten NL-Parser (ADR 0103/0108): baut die
**injizierten Stammdaten** aus der DB (aktive Quartiere/Klassen + materialisierte,
konfigurierte Ferien/Saison des Zieljahrs) und ruft die reine Logik `booking.wish_nl`.

Die Parse-Logik selbst bleibt Django-frei/isoliert testbar; hier nur die Brücke.
Teil des `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from datetime import date

from .. import wish_nl
from ..availability import recurring_range
from ..models import EquivalenceClass, Quarter, SchoolHoliday, SeasonRule

__all__ = ["nl_stammdaten", "nl_parse_wish", "nl_parse_booking"]


def nl_stammdaten(year: int) -> dict:
    """Konfigurierte Stammdaten fürs `year` als reine `(key, name)`/`(name, start,
    end)`-Tupel – **keine** hartcodierten Werte. Benannte Zeiträume werden aus den
    aktiven `SchoolHoliday`/`SeasonRule` ins Zieljahr materialisiert."""
    quarters = list(Quarter.objects.filter(active=True)
                    .values_list("id", "name"))
    eq_classes = list(EquivalenceClass.objects.values_list("id", "name"))
    holidays = [
        (h.name, *recurring_range(h.start_month, h.start_day,
                                  h.end_month, h.end_day, year))
        for h in SchoolHoliday.objects.filter(active=True)]
    seasons = [
        (s.name, *recurring_range(s.start_month, s.start_day,
                                  s.end_month, s.end_day, year))
        for s in SeasonRule.objects.filter(active=True)]
    return {"quarters": quarters, "eq_classes": eq_classes,
            "seasons": seasons, "holidays": holidays}


def nl_parse_wish(text: str, period) -> "wish_nl.WishIntent":
    """Parst eine Wunsch-Kurz-Eingabe gegen die konfigurierten Stammdaten der Periode
    (Zieljahr). Best-effort, nie blockierend (die reine Logik ist gehärtet)."""
    year = period.target_year if period else date.today().year + 1
    return wish_nl.parse_wish_text(text, year=year, today=date.today(),
                                   **nl_stammdaten(year))


def nl_parse_booking(text: str, year: int | None = None) -> "wish_nl.WishIntent":
    """Parst eine Buchungs-Kurz-Eingabe (zusätzlich Personen/Endreinigung/
    Besonderheiten) gegen die konfigurierten Stammdaten des `year`."""
    year = year or date.today().year
    return wish_nl.parse_booking_text(text, year=year, today=date.today(),
                                      **nl_stammdaten(year))

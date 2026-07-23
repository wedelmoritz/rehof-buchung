"""Service-Naht für den regelbasierten NL-Parser (ADR 0103/0108): baut die
**injizierten Stammdaten** aus der DB (aktive Quartiere/Klassen + materialisierte,
konfigurierte Ferien/Saison des Zieljahrs) und ruft die reine Logik `booking.wish_nl`.

Die Parse-Logik selbst bleibt Django-frei/isoliert testbar; hier nur die Brücke.
Teil des `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import wish_nl
from ..availability import recurring_range
from ..models import EquivalenceClass, Quarter, SchoolHoliday, SeasonRule

__all__ = ["nl_stammdaten", "nl_parse_wish", "nl_parse_booking"]


def _resolve_month_start(intent, *, year: int, today: date) -> None:
    """Grober Zeitwunsch ohne konkretes Startdatum (nur Monat „im Juli", evtl. Dauer
    „eine Woche") → **erstes passendes Datum** im Monat vorschlagen, statt „kein
    Startdatum" zu melden (ADR 0108-Nachtrag). Für **Buchungen** wird die
    Verfügbarkeit geprüft (erstes **freies** Datum der genannten bzw. irgendeiner
    passenden Unterkunft); für **Wünsche** genügt der Saison-Zeitraum (Freiheit gilt
    dort nicht). Best-effort, nie blockierend – bei einem Fehler bleibt das Formular
    unverändert."""
    if intent.start is not None or intent.month is None:
        return
    try:
        m = intent.month
        fom = date(year, m, 1)
        # Liegt der Monat schon ganz in der Vergangenheit (Buchung im laufenden Jahr),
        # ist das nächste Vorkommen im Folgejahr gemeint.
        if fom < date(today.year, today.month, 1):
            fom = date(year + 1, m, 1)
        month_end = date(fom.year + 1, 1, 1) if m == 12 else date(fom.year, m + 1, 1)
        scan_from = max(fom, today + timedelta(days=1))
        if scan_from >= month_end:
            return
        nights = intent.nights or 0
        span = nights or 1                      # Prüf-Fenster (min. 1 Nacht)

        quarter = None
        if intent.quarter_key is not None:
            quarter = Quarter.objects.filter(
                id=intent.quarter_key, active=True).first()

        from .slots import quarter_is_free, range_is_released, _in_season_range

        def _ok(d: date) -> bool:
            end = d + timedelta(days=span)
            if intent.kind == "wish":
                # Wünsche: keine Freiheits-Prüfung, nur Saison des (evtl.) Quartiers.
                return quarter is None or _in_season_range(quarter, d, end)
            if quarter is not None:
                return (range_is_released(quarter, d, end)
                        and quarter_is_free(quarter, d, end))
            from .booking_ops import free_quarters_for
            return bool(free_quarters_for(d, end, intent.persons or 1))

        d, found = scan_from, None
        while d < month_end:
            if _ok(d):
                found = d
                break
            d += timedelta(days=1)
        if found is None:
            intent.unresolved.append(
                f"im {wish_nl._MONTH_NAMES[m]} keine passende freie Zeit gefunden – "
                f"bitte im Kalender wählen")
            return
        intent.start = found
        if nights:
            intent.end = found + timedelta(days=nights)
        intent.matched.append(
            f"ab {found:%d.%m.} vorgeschlagen"
            + (" (erstes freies Datum)" if intent.kind == "booking" else ""))
    except Exception:  # noqa: BLE001 – nie blockierend; Formular bleibt unverändert
        return


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
    today = date.today()
    intent = wish_nl.parse_wish_text(text, year=year, today=today,
                                     **nl_stammdaten(year))
    _resolve_month_start(intent, year=year, today=today)
    return intent


def nl_parse_booking(text: str, year: int | None = None) -> "wish_nl.WishIntent":
    """Parst eine Buchungs-Kurz-Eingabe (zusätzlich Personen/Endreinigung/
    Besonderheiten) gegen die konfigurierten Stammdaten des `year`."""
    year = year or date.today().year
    today = date.today()
    intent = wish_nl.parse_booking_text(text, year=year, today=today,
                                        **nl_stammdaten(year))
    _resolve_month_start(intent, year=year, today=today)
    return intent

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

_MAX_SUGGESTIONS = 3


def _learned() -> dict:
    """Das aktive, von der Verwaltung bestätigte NL-Lexikon (ADR 0113) als
    injizierbares Dict für den Parser – best-effort, nie blockierend: schlägt der
    Zugriff fehl oder ist nichts aktiv/kein Opt-in, parst der Parser unverändert
    weiter (leeres Dict). Das Lexikon ist reine **Vergleichsdaten** (kein Code),
    daher bleibt die reine Logik deterministisch/testbar."""
    try:
        from .nl_lexicon import nl_active_lexicon
        return nl_active_lexicon()
    except Exception:  # noqa: BLE001 – Lexikon ist optional; Parser läuft ohne weiter
        return {}


def _resolve_month_start(intent, *, year: int, today: date) -> None:
    """Grober Zeitwunsch ohne konkretes Startdatum (Kandidat-Monate „im Juli"/
    „Sommerwoche", evtl. Dauer/Monatsteil) → bis zu drei konkrete Vorschläge: je
    Kandidat-Monat das **erste passende/freie Datum**. Der beste wird als Start/Ende
    übernommen (Vorbelegung), die weiteren landen als „Meintest du…?"-Alternativen in
    `intent.suggestions` (ADR 0108-Nachtrag). **Buchungen** prüfen die Verfügbarkeit
    (erstes **freies** Datum der genannten bzw. irgendeiner passenden Unterkunft),
    **Wünsche** nur die Saison. Effizient: Verfügbarkeit wird EINMAL vorab geladen
    (ADR 0111). Best-effort, nie blockierend – bei einem Fehler bleibt das Formular
    unverändert."""
    if intent.start is not None or not intent.months:
        return
    try:
        from .slots import (quarter_is_free, range_is_released, _in_season_range,
                             _active_windows, _occupied_days_by_quarter)
        nights = intent.nights or 0
        span = nights or 1                      # Prüf-Fenster (min. 1 Nacht)

        # Kandidat-Monate → (Monat, Suchstart, Monatsende); Vergangenes ins Folgejahr.
        # Der Monatsteil (Anfang/Mitte/Ende) verschiebt nur den Suchstart.
        cur_first = date(today.year, today.month, 1)
        ranges: list[tuple[int, date, date]] = []
        for m in intent.months[:_MAX_SUGGESTIONS]:
            fom = date(year, m, 1)
            if fom < cur_first:
                fom = date(year + 1, m, 1)
            month_end = date(fom.year + 1, 1, 1) if m == 12 else date(fom.year, m + 1, 1)
            biased = fom
            if intent.day_bias == "mid":
                biased = fom + timedelta(days=12)
            elif intent.day_bias == "end":
                biased = fom + timedelta(days=21)
            scan_from = max(biased, today + timedelta(days=1))
            if scan_from < month_end:
                ranges.append((m, scan_from, month_end))
        if not ranges:
            return

        quarter = None
        if intent.quarter_key is not None:
            quarter = Quarter.objects.filter(
                id=intent.quarter_key, active=True).first()

        # Verfügbarkeit für Buchungen EINMAL über die ganze Spanne vorab laden.
        windows = occ = cand_quarters = None
        if intent.kind == "booking":
            span_first = min(r[1] for r in ranges)
            span_last = max(r[2] for r in ranges) + timedelta(days=span)
            windows = _active_windows()
            occ = _occupied_days_by_quarter(span_first, span_last)
            if quarter is None:
                qs = Quarter.objects.filter(active=True)
                if intent.accessible:
                    qs = qs.filter(accessible=True)
                if intent.persons:
                    qs = qs.filter(min_occupancy__lte=intent.persons,
                                   max_occupancy__gte=intent.persons)
                cand_quarters = list(qs)

        def _free_on(d: date) -> bool:
            end = d + timedelta(days=span)
            if intent.kind == "wish":
                return quarter is None or _in_season_range(quarter, d, end)
            if quarter is not None:
                return (range_is_released(quarter, d, end, windows=windows)
                        and quarter_is_free(
                            quarter, d, end,
                            occupied_days=occ.get(str(quarter.id), set())))
            for q in cand_quarters:
                if (range_is_released(q, d, end, windows=windows)
                        and quarter_is_free(
                            q, d, end, occupied_days=occ.get(str(q.id), set()))):
                    return True
            return False

        suggestions: list[dict] = []
        for _m, scan_from, month_end in ranges:
            d = scan_from
            while d < month_end:
                if _free_on(d):
                    end = d + timedelta(days=nights) if nights else None
                    label = f"{d:%d.%m.}" + (f"–{end:%d.%m.}" if end else "")
                    suggestions.append({"start": d, "end": end, "label": label})
                    break
                d += timedelta(days=1)

        if not suggestions:
            names = " / ".join(wish_nl._MONTH_NAMES[m] for m, _, _ in ranges)
            intent.unresolved.append(
                f"in {names} keine passende freie Zeit gefunden – "
                f"bitte im Kalender wählen")
            return
        intent.start = suggestions[0]["start"]
        intent.end = suggestions[0]["end"]
        intent.suggestions = suggestions
        intent.matched.append(
            f"ab {intent.start:%d.%m.} vorgeschlagen"
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
                                     learned=_learned(), **nl_stammdaten(year))
    _resolve_month_start(intent, year=year, today=today)
    return intent


def nl_parse_booking(text: str, year: int | None = None) -> "wish_nl.WishIntent":
    """Parst eine Buchungs-Kurz-Eingabe (zusätzlich Personen/Endreinigung/
    Besonderheiten) gegen die konfigurierten Stammdaten des `year`."""
    year = year or date.today().year
    today = date.today()
    intent = wish_nl.parse_booking_text(text, year=year, today=today,
                                        learned=_learned(), **nl_stammdaten(year))
    _resolve_month_start(intent, year=year, today=today)
    return intent

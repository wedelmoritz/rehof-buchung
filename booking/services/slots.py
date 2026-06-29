"""Service-Layer (slots): Verfügbarkeit & Buchungsregeln: Freiheit der Quartiere, Saison-Regeln, Mindestnächte, Freischaltung, Lücken/Splitting.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from .. import availability as A
from .. import lottery as L
from .. import rules as R
from ..models import (
    Allocation, BookingPeriod, BookingPolicy, ExternalBooking,
    ExternalConfig, Member, Quarter, SchoolHoliday, SeasonRule,
)

__all__ = [
    '_quarters_payload', '_external_blocking_qs', 'quarter_is_free',
    'find_gaps', '_materialized_seasons', 'check_booking_rules',
    'schedule_blocker', 'season_min_nights', 'min_nights_for_range',
    'external_min_nights', 'wish_rule_error', '_active_windows',
    '_in_season_range', 'range_is_released', 'find_bookable_gaps',
    'split_quarters_for_range', '_occupied_days_by_quarter',
    'is_gap_fill', 'gap_fill_allowed', 'is_group_booking', 'lead_time_blocker',
    'high_demand_periods', 'winter_usage',
]

def _quarters_payload() -> list[L.Quarter]:
    return [
        L.Quarter(id=str(q.id), name=q.name, eq_class=str(q.eq_class_id))
        for q in Quarter.objects.filter(active=True).select_related("eq_class")
    ]


def _external_blocking_qs(quarter: Quarter, start: date, end: date):
    """Externe Buchungen, die [start, end) für `quarter` blockieren."""
    return ExternalBooking.objects.filter(
        quarter=quarter, status=ExternalBooking.CONFIRMED,
        start__lt=end, end__gt=start)


def quarter_is_free(quarter: Quarter, start: date, end: date) -> bool:
    """Prüft, ob ein Quartier im Zeitraum [start, end) komplett frei ist –
    berücksichtigt Mitglieder-Zuteilungen UND bestätigte externe Buchungen."""
    if Allocation.objects.filter(
            quarter=quarter, start__lt=end, end__gt=start).exists():
        return False
    return not _external_blocking_qs(quarter, start, end).exists()


def find_gaps(
    quarter: Quarter, window_start: date, window_end: date,
    min_nights: int = 1,
) -> list[tuple[date, date]]:
    """Findet freie Lücken eines Quartiers im Fenster [window_start, window_end)."""
    intervals = [
        (a.start, a.end) for a in Allocation.objects.filter(
            quarter=quarter, start__lt=window_end, end__gt=window_start)]
    intervals += [(b.start, b.end)
                  for b in _external_blocking_qs(quarter, window_start, window_end)]
    intervals.sort()
    gaps: list[tuple[date, date]] = []
    cursor = window_start
    for a_start0, a_end0 in intervals:
        a_start = max(a_start0, window_start)
        if a_start > cursor:
            if (a_start - cursor).days >= min_nights:
                gaps.append((cursor, a_start))
        cursor = max(cursor, min(a_end0, window_end))
    if cursor < window_end and (window_end - cursor).days >= min_nights:
        gaps.append((cursor, window_end))
    return gaps


def _materialized_seasons(span_start: date, span_end: date) -> list[R.Season]:
    """Materialisiert die jährlich wiederkehrenden Regeln (Saison-Regeln und
    aktive Schulferien mit Regelfeldern) zu konkreten Zeiträumen, die [span_start,
    span_end) berühren. So bleibt die reine Logik in rules.py datumsbasiert."""
    out: list[R.Season] = []
    years = range(span_start.year - 1, span_end.year + 1)

    def add(name, sm, sd, em, ed, mn, mp, ms):
        for y in years:
            s, e = A.recurring_range(sm, sd, em, ed, y)
            if s < span_end and e > span_start:
                out.append(R.Season(
                    name=name, start=s, end=e, min_nights=mn,
                    max_parallel_units=mp, max_stay_nights=ms, active=True,
                ))

    for r in SeasonRule.objects.filter(active=True):
        add(r.name, r.start_month, r.start_day, r.end_month, r.end_day,
            r.min_nights, r.max_parallel_units, r.max_stay_nights)
    for h in SchoolHoliday.objects.filter(active=True):
        # Nur Schulferien mit mindestens einer gesetzten Regel wirken sich aus.
        if h.min_nights is None and h.max_parallel_units is None \
                and h.max_stay_nights is None:
            continue
        add(h.name, h.start_month, h.start_day, h.end_month, h.end_day,
            h.min_nights, h.max_parallel_units, h.max_stay_nights)
    return out


def check_booking_rules(
    member: Member, start: date, end: date, membership=None,
    skip_min_nights: bool = False,
) -> str | None:
    """Prüft eine geplante Buchung gegen die globalen + saisonalen Regeln
    (inkl. regelsetzender Schulferien). Gibt einen Fehlertext zurück oder None.

    Parallel-Limit/Aufenthaltsdeckel gelten auf den VOLLEN Mitglieds-Anteil
    (ADR 0066): die schon vorhandenen Belegungen werden über alle Tandem-Partner
    DIESES Anteils gezählt, nicht nur die des einzelnen Nutzers. `membership` ist
    der Ziel-Anteil (Default: der eindeutige bzw. größte Anteil des Nutzers);
    ohne Anteil (externer Gast) fällt die Prüfung auf die eigenen Buchungen
    zurück. `skip_min_nights` hebt nur die Mindestnächte-Prüfung auf (Lücken-
    füllung, ADR 0075)."""
    from ..models import Allocation
    policy = BookingPolicy.get_solo()
    ms = membership if membership is not None else member.membership_for()
    if ms is not None:
        existing = [
            R.Stay(start=s, end=e)
            for (s, e) in Allocation.objects.filter(membership=ms)
            .values_list("start", "end")
        ]
    else:
        existing = [
            R.Stay(start=a.start, end=a.end) for a in member.allocations.all()
        ]
    return R.validate_booking(
        _materialized_seasons(start, end), policy.default_min_nights,
        start, end, existing, skip_min_nights=skip_min_nights,
    )


def is_gap_fill(quarter: Quarter, start: date, end: date) -> bool:
    """Füllt die Buchung [start, end) eine freie Lücke des Quartiers EXAKT aus?

    Wahr, wenn der Zeitraum beidseitig „geschlossen" ist – die Nacht direkt davor
    (start-1→start) und direkt danach (end→end+1) ist NICHT frei buchbar (belegt
    oder außerhalb des freigeschalteten/saisonalen Zeitraums). Dann lässt sich der
    Zeitraum nicht verlängern, er füllt die Lücke also in ihrer ganzen Länge
    (ADR 0075). Bewusst nur wenige, gezielte DB-Abfragen (je Randnacht eine
    Frei-/Freigabe-Prüfung); der Innenraum gilt als frei (wird vor dem Buchen
    ohnehin separat geprüft)."""
    day = timedelta(days=1)
    left_closed = (not range_is_released(quarter, start - day, start)
                   or not quarter_is_free(quarter, start - day, start))
    right_closed = (not range_is_released(quarter, end, end + day)
                    or not quarter_is_free(quarter, end, end + day))
    return left_closed and right_closed


def is_group_booking(persons: int) -> bool:
    """Gilt eine Buchung mit `persons` Personen als „Gruppe" (ab
    `BookingPolicy.group_min_persons`)? Dann werden Gruppen-Wohneinheiten (z. B.
    Stallgebäude) zuerst angeboten (ADR 0075)."""
    return int(persons or 0) >= (BookingPolicy.get_solo().group_min_persons or 0)


def gap_fill_allowed(quarter: Quarter, start: date, end: date) -> bool:
    """Ist [start, end) eine erlaubte Lückenfüllung? (Schalter `allow_gap_fill`
    aktiv UND der Zeitraum füllt eine Lücke exakt aus.) Bündelt Policy + Geometrie
    für Views, ohne dass diese das Policy-Modell kennen müssen (ADR 0075)."""
    return bool(BookingPolicy.get_solo().allow_gap_fill) and is_gap_fill(
        quarter, start, end)


def lead_time_blocker(start: date, today: date | None = None) -> str | None:
    """Verstößt der Anreisetag gegen die Spontan-Vorausfrist (`BookingPolicy.
    min_lead_days`)? Gibt einen Fehlertext zurück oder None. Lückenfüllende
    Buchungen prüft der Aufrufer separat und übergeht diese Prüfung (ADR 0075)."""
    lead = BookingPolicy.get_solo().min_lead_days or 0
    if lead <= 0:
        return None
    today = today or date.today()
    earliest = today + timedelta(days=lead)
    if start < earliest:
        return (f"Spontanbuchungen brauchen mindestens {lead} Tage Vorlauf "
                f"(frühester Anreisetag: {earliest:%d.%m.%Y}). Eine bestehende "
                f"Lücke darfst du auch kurzfristig füllen.")
    return None


def schedule_blocker(
    member: Member, start: date, end: date,
    skip_min_nights: bool = False, skip_lead: bool = False,
) -> str | None:
    """Grund, warum der Zeitraum (Termin/Regeln/Budget) NICHT buchbar ist –
    ohne Personenzahl- und Belegungsprüfung. Quartiers-unabhängig, daher pro
    Auswahl nur EINMAL berechnen (nicht je Kandidat). Für die Vorab-Anzeige.

    `skip_min_nights`/`skip_lead` heben Mindestnächte bzw. Spontan-Vorausfrist auf
    – für lückenfüllende Buchungen, die ja beides ausnehmen (ADR 0075)."""
    nights = (end - start).days
    if nights <= 0:
        return "Ungültiger Zeitraum."
    remaining = member.nights_remaining_in_year(start.year)
    if remaining < nights:
        return f"Nicht genügend Tage ({remaining} übrig, {nights} benötigt)."
    if not skip_lead:
        lead = lead_time_blocker(start)
        if lead:
            return lead
    return check_booking_rules(member, start, end, skip_min_nights=skip_min_nights)


def season_min_nights(start: date, end: date) -> int:
    """Strengste Saison-Mindestnächte (SeasonRule/Schulferien) für [start, end) –
    OHNE den globalen Standard. 0, wenn keine Saison-Regel greift. Wird für externe
    Gäste genutzt: deren eigener Mindestaufenthalt steht separat in der
    ExternalConfig, die Saison-Mindestnächte gelten zusätzlich (das strengere zählt)."""
    required = 0
    for s in _materialized_seasons(start, end):
        if s.min_nights and s.start < end and s.end > start:
            required = max(required, s.min_nights)
    return required


def min_nights_for_range(start: date, end: date) -> int:
    """Effektiver Mindestaufenthalt für [start, end): Standard-Mindestnächte,
    verschärft durch überlappende Saison-/Schulferien-Regeln."""
    return max(BookingPolicy.get_solo().default_min_nights or 0,
               season_min_nights(start, end))


def external_min_nights(start: date, end: date, cfg=None) -> int:
    """Mindestaufenthalt für externe Buchungen in [start, end).

    Standard (`ExternalConfig.min_nights_follow_internal=True`): identisch zu den
    internen Mindestnächten (`min_nights_for_range` = Standard-Mindestnächte +
    Saison-Mindestnächte) – Externe und Mitglieder sind dann gleichgestellt. Ist
    der Schalter im Backend AUS, gilt der eigene feste Wert
    (`ExternalConfig.min_nights`), der bewusst von den internen Vorgaben abweichen
    darf (höher ODER niedriger, ohne Saison-Verschärfung)."""
    cfg = cfg or ExternalConfig.get_solo()
    if cfg.min_nights_follow_internal:
        return min_nights_for_range(start, end)
    return cfg.min_nights or 0


def wish_rule_error(start: date, end: date) -> str | None:
    """Saison-Regeln für einen EINZELNEN Wunsch: Mindestnächte (Standard + Saison)
    und der Aufenthaltsdeckel als Obergrenze einer einzelnen Buchung. Das
    **Parallel-Limit** betrifft mehrere gleichzeitige Buchungen und ist je Einzel-
    wunsch nicht prüfbar; es wird in der Losung bewusst nicht erzwungen (Beschluss:
    Saison-Regeln nur beim Eintragen/Einreichen der Wunschliste prüfen, der Los-
    Algorithmus bleibt unverändert). Gibt einen Fehlertext zurück oder None."""
    policy = BookingPolicy.get_solo()
    # Leere „existing"-Liste: prüft Mindestnächte + Einzel-Deckel, nicht das
    # (cross-buchungs-)Parallel-Limit.
    return R.validate_booking(
        _materialized_seasons(start, end), policy.default_min_nights,
        start, end, [],
    )


def high_demand_periods(start: date, end: date) -> list[str]:
    """Namen der „begehrten Zeiten", die [start, end) berühren – für den sanften
    Rücksichts-Hinweis (ADR 0075): alle aktiven Schulferien sowie Saison-Regeln
    mit Parallel-Limit (= Feiertage/Brückentage wie Pfingsten, Weihnachten …).
    Reine Anzeige, blockiert nichts. Wenige Abfragen (zwei Tabellen, jährlich
    materialisiert)."""
    if end <= start:
        return []
    years = range(start.year - 1, end.year + 1)
    names: list[str] = []
    seen: set[str] = set()

    def add(name, sm, sd, em, ed):
        for y in years:
            s, e = A.recurring_range(sm, sd, em, ed, y)
            if s < end and e > start and name not in seen:
                seen.add(name)
                names.append(name)
                return

    for h in SchoolHoliday.objects.filter(active=True):
        add(h.name, h.start_month, h.start_day, h.end_month, h.end_day)
    for r in SeasonRule.objects.filter(active=True,
                                       max_parallel_units__isnull=False):
        add(r.name, r.start_month, r.start_day, r.end_month, r.end_day)
    return names


def winter_usage(member: Member, ref_date: date | None = None) -> dict:
    """Richtwert-Orientierung (kein Limit, ADR 0075): wie viele Tage hat das
    Mitglied im aktuellen/kommenden Winterhalbjahr (1.10.–31.3.) gebucht, gemessen
    am Richtwert `BookingPolicy.winter_guideline_nights`. Eine Abfrage über die
    überlappenden Buchungen."""
    today = ref_date or date.today()
    # Das relevante Winterhalbjahr: beginnt am 1.10. des Jahres, dessen Winter
    # heute läuft oder als nächstes ansteht. Jan–Sep → Winter ab Okt des Vorjahres
    # (Jan–Mär: laufend) bzw. des laufenden Jahres (Apr–Sep: kommend).
    if today.month <= 3:
        win_start = date(today.year - 1, 10, 1)
    else:
        win_start = date(today.year, 10, 1)
    win_end = date(win_start.year + 1, 4, 1)        # exklusiv (bis 31.3.)
    booked = 0
    for s, e in (Allocation.objects.filter(
            member=member, provisional=False,
            start__lt=win_end, end__gt=win_start)
            .values_list("start", "end")):
        booked += (min(e, win_end) - max(s, win_start)).days
    target = BookingPolicy.get_solo().winter_guideline_nights or 0
    return {
        "booked": booked, "target": target,
        "win_start": win_start, "win_end": win_end - timedelta(days=1),
        "label": f"Okt {win_start.year} – Mär {win_end.year}",
    }


def _active_windows() -> list[A.Window]:
    """Lädt die zur freien Buchung freigegebenen Perioden als reine Window-
    Objekte. Buchbar ist ein Tag nur innerhalb einer Periode im Status
    „Freie Bebuchbarkeit innerhalb Zeitraum“."""
    out: list[A.Window] = []
    for p in BookingPeriod.objects.filter(status=BookingPeriod.FREE_BOOKING):
        # Genau eine Periode pro Jahr, immer global. Quartiersspezifische
        # Grenzen kommen aus der Quartier-Saison (siehe range_is_released).
        out.append(A.Window(
            start=p.start, end=p.end, applies_to_all=True, active=True,
        ))
    return out


def _in_season_range(quarter: Quarter, start: date, end: date) -> bool:
    """Ist das Quartier über den ganzen Zeitraum saisonal buchbar?"""
    d = start
    while d < end:
        if not quarter.bookable_on(d):
            return False
        d += timedelta(days=1)
    return True


def range_is_released(quarter: Quarter, start: date, end: date) -> bool:
    """Ist der Zeitraum [start, end) für das Quartier freigeschaltet UND liegt er
    im (jährlichen) Buchbarkeitszeitraum des Quartiers?"""
    return (
        A.range_released(_active_windows(), str(quarter.id), start, end)
        and _in_season_range(quarter, start, end)
    )


def find_bookable_gaps(
    quarter: Quarter, window_start: date, window_end: date,
) -> list[tuple[date, date]]:
    """Buchbare Lücken eines Quartiers: frei UND freigeschaltet."""
    occupied: set[date] = set()
    intervals = [
        (a.start, a.end) for a in Allocation.objects.filter(
            quarter=quarter, start__lt=window_end, end__gt=window_start)]
    intervals += [(b.start, b.end)
                  for b in _external_blocking_qs(quarter, window_start, window_end)]
    for i_start, i_end in intervals:
        d = max(i_start, window_start)
        upper = min(i_end, window_end)
        while d < upper:
            occupied.add(d)
            d += timedelta(days=1)
    return A.released_gaps(
        _active_windows(), str(quarter.id), occupied, window_start, window_end,
    )


def split_quarters_for_range(
    start: date, end: date,
) -> tuple[list[Quarter], list[Quarter]]:
    """Für den Zeitraum [start, end): teilt die freigeschalteten Quartiere in
    (frei buchbar, belegt). Quartiere, die im Zeitraum gar nicht freigeschaltet
    sind, tauchen in keiner der beiden Listen auf."""
    windows = _active_windows()
    free: list[Quarter] = []
    occupied: list[Quarter] = []
    if end <= start:
        return free, occupied
    for q in Quarter.objects.filter(active=True).order_by("name"):
        if not A.range_released(windows, str(q.id), start, end):
            continue
        if not _in_season_range(q, start, end):
            continue
        (free if quarter_is_free(q, start, end) else occupied).append(q)
    return free, occupied


_OCC_VER_KEY = "rehof:occ:ver"


def _occ_cache_on() -> bool:
    """Belegungs-Cache nur mit GETEILTEM Cache (Redis) – LocMemCache ist pro
    Prozess/Worker, eine Invalidierung erreichte andere Worker nicht (stale).
    Ohne Redis (Dev/Tests) wird direkt aus der DB gerechnet (kein Verhalten ändert
    sich)."""
    from django.conf import settings
    try:
        return "redis" in settings.CACHES["default"]["BACKEND"].lower()
    except Exception:
        return False


def bump_occupancy_version() -> None:
    """Invalidiert den geteilten Belegungs-Cache (alle Monate auf einmal). Wird per
    Signal nach jeder Buchungsänderung aufgerufen (Allocation/ExternalBooking)."""
    if not _occ_cache_on():
        return
    from django.core.cache import cache
    try:
        cache.incr(_OCC_VER_KEY)
    except ValueError:
        cache.set(_OCC_VER_KEY, 1, None)


def _compute_occupied(first: date, last: date) -> dict[str, set[date]]:
    occupied: dict[str, set[date]] = defaultdict(set)
    rows = [(a.quarter_id, a.start, a.end)
            for a in Allocation.objects.filter(start__lte=last, end__gt=first)]
    rows += [(b.quarter_id, b.start, b.end) for b in ExternalBooking.objects.filter(
        status=ExternalBooking.CONFIRMED, start__lte=last, end__gt=first)]
    for qid, s, e in rows:
        d = max(s, first)
        upper = min(e, last + timedelta(days=1))
        while d < upper:
            occupied[str(qid)].add(d)
            d += timedelta(days=1)
    return occupied


def _occupied_days_by_quarter(first: date, last: date) -> dict[str, set[date]]:
    """Belegte Tage je Quartier-ID im Bereich [first, last]. GETEILTE, nicht
    personenbezogene Daten (wer wo belegt ist sehen ohnehin alle Mitglieder) →
    bei aktivem Redis kurz gecacht und per Signal invalidiert (sonst direkt aus
    der DB). Die eigentliche Buchung prüft IMMER frisch unter Sperre – der Cache
    ist reine Anzeige-Beschleunigung."""
    if not _occ_cache_on():
        return _compute_occupied(first, last)
    from django.core.cache import cache
    ver = cache.get(_OCC_VER_KEY)
    if ver is None:
        cache.set(_OCC_VER_KEY, 1, None)
        ver = 1
    key = f"rehof:occ:{ver}:{first.isoformat()}:{last.isoformat()}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    val = _compute_occupied(first, last)
    cache.set(key, val, 120)
    return val

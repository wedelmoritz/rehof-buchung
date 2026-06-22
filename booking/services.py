"""Service-Layer: Brücke zwischen Django-Modellen und dem reinen Losmodul.

Hier liegt bewusst die gesamte Geschäftslogik, die DB und Algorithmus
verbindet – die Views bleiben dünn, das Losmodul bleibt rein.
"""
from __future__ import annotations

import calendar as _calendar
from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import availability as A
from . import lottery as L
from . import rules as R
from .models import (
    Allocation, BookingPeriod, BookingPolicy, LotteryRun, Member, NightTransfer,
    Notification, Quarter, SchoolHoliday, SeasonRule, SwapRequest, WaitlistEntry,
    Wish,
)


def _quarters_payload() -> list[L.Quarter]:
    return [
        L.Quarter(id=str(q.id), name=q.name, eq_class=str(q.eq_class_id))
        for q in Quarter.objects.filter(active=True).select_related("eq_class")
    ]


@transaction.atomic
def run_period_lottery(
    period: BookingPeriod,
    *,
    seed: int,
    factor_step: float = 0.1,
    factor_cap: float = 1.5,
    reset_on_contested_win: bool = True,
) -> LotteryRun:
    """Führt die Losung für eine Periode aus, schreibt Zuteilungen, aktualisiert
    die Ausgleichsfaktoren und legt ein Audit-Protokoll an."""
    members = list(Member.objects.filter(is_external=False))
    quarters = list(Quarter.objects.filter(active=True))
    # Nur eingereichte Wünsche ("im Lostopf") nehmen an der Losung teil.
    wishes_qs = list(
        Wish.objects.filter(period=period, submitted=True)
        .select_related("member", "quarter")
    )

    parties = [
        L.Party(
            id=str(m.id), name=m.display_name,
            factor=m.factor, wish_night_budget=m.wish_night_budget,
        )
        for m in members
    ]
    q_payload = [
        L.Quarter(id=str(q.id), name=q.name, eq_class=str(q.eq_class_id))
        for q in quarters
    ]
    w_payload = [
        L.Wish(
            party_id=str(w.member_id), priority=w.priority,
            quarter_id=str(w.quarter_id), start=w.start, end=w.end,
        )
        for w in wishes_qs
    ]

    result = L.run_lottery(
        parties, q_payload, w_payload,
        seed=seed, factor_step=factor_step, factor_cap=factor_cap,
        reset_on_contested_win=reset_on_contested_win,
    )

    # Alte Los-Zuteilungen dieser Periode entfernen (Idempotenz bei Re-Run)
    Allocation.objects.filter(period=period, source="lottery").delete()

    for a in result.allocations:
        Allocation.objects.create(
            member_id=int(a.party_id),
            quarter_id=int(a.quarter_id),
            start=a.start, end=a.end,
            source="lottery", period=period,
            via_substitution=a.via_substitution, contested=a.contested,
        )

    # Faktoren aktualisieren (alte Werte für die Transparenz-Meldung merken)
    old_factors = {str(m.id): m.factor for m in members}
    for m in members:
        new_f = result.new_factors.get(str(m.id))
        if new_f is not None and new_f != m.factor:
            m.factor = new_f
            m.save(update_fields=["factor"])

    period.status = BookingPeriod.LOTTERY_DONE
    period.seed = seed
    period.save(update_fields=["status", "seed"])

    party_names = {str(m.id): m.display_name for m in members}
    quarter_names = {str(q.id): q.name for q in quarters}

    # Transparenz: jedem Teilnehmer (mit eingereichten Wünschen) eine
    # Benachrichtigung mit Gewinnen, Verlusten und Karma-Änderung schicken.
    _notify_lottery_results(
        period, members, result, old_factors, quarter_names)

    log_text = L.render_log_text(result, party_names, quarter_names)
    summary = (
        f"{len(result.allocations)} Zuteilungen, "
        f"{len(result.losses)} Verluste, Seed {seed}"
    )
    return LotteryRun.objects.create(
        period=period, seed=seed, log_text=log_text, summary=summary,
    )


def _notify_lottery_results(period, members, result, old_factors, quarter_names):
    """Schreibt jedem Teilnehmer (eingereichte Wünsche) eine Benachrichtigung mit
    seinen Gewinnen, Verlusten und der Karma-Änderung – für Nachvollziehbarkeit."""
    wins_by: dict[str, list] = defaultdict(list)
    losses_by: dict[str, list] = defaultdict(list)
    for a in result.allocations:
        wins_by[a.party_id].append(a)
    for w in result.losses:
        losses_by[w.party_id].append(w)

    participant_ids = {
        str(mid) for mid in Wish.objects.filter(period=period, submitted=True)
        .values_list("member_id", flat=True).distinct()
    }
    url = reverse("period_result", args=[period.id])
    year = period.target_year
    # Idempotenz: bei einem Re-Run alte Losungs-Benachrichtigungen ersetzen.
    Notification.objects.filter(url=url).delete()

    for m in members:
        pid = str(m.id)
        if pid not in participant_ids:
            continue
        wins = wins_by.get(pid, [])
        losses = losses_by.get(pid, [])
        old_f = old_factors.get(pid, m.factor)
        new_f = result.new_factors.get(pid, old_f)

        msg = (f"Auslosung {year}: {len(wins)} Wunsch/Wünsche bekommen, "
               f"{len(losses)} leider nicht.")
        lines: list[str] = []
        if wins:
            lines.append("Du hast bekommen:")
            for a in wins:
                qn = quarter_names.get(a.quarter_id, a.quarter_id)
                sub = " (gleichwertiges Ausweichquartier)" if a.via_substitution else ""
                lines.append(f"  ✓ {qn} {a.start:%d.%m.%Y}–{a.end:%d.%m.%Y}{sub}")
        if losses:
            lines.append("Es tut uns leid – diese Wünsche waren nicht erfüllbar:")
            for w in losses:
                qn = quarter_names.get(w.quarter_id, w.quarter_id)
                lines.append(f"  ✗ {qn} {w.start:%d.%m.%Y}–{w.end:%d.%m.%Y}")
        if new_f > old_f:
            lines.append(
                f"Als Ausgleich steigt dein Ausgleichsfaktor um "
                f"+{round(new_f - old_f, 1)} auf {round(new_f, 1)} – damit hast du "
                f"bei der nächsten Auslosung bessere Chancen auf einen vorderen Platz.")
        elif new_f < old_f:
            lines.append(
                f"Dein Ausgleichsfaktor wurde nach dem Gewinn eines umkämpften "
                f"Wunsches auf {round(new_f, 1)} zurückgesetzt.")
        Notification.objects.create(
            member=m, message=msg, detail="\n".join(lines), url=url)


def quarter_is_free(quarter: Quarter, start: date, end: date) -> bool:
    """Prüft, ob ein Quartier im Zeitraum [start, end) komplett frei ist."""
    overlapping = Allocation.objects.filter(
        quarter=quarter, start__lt=end, end__gt=start,
    ).exists()
    return not overlapping


def find_gaps(
    quarter: Quarter, window_start: date, window_end: date,
    min_nights: int = 1,
) -> list[tuple[date, date]]:
    """Findet freie Lücken eines Quartiers im Fenster [window_start, window_end)."""
    allocs = list(
        Allocation.objects.filter(
            quarter=quarter, start__lt=window_end, end__gt=window_start,
        ).order_by("start")
    )
    gaps: list[tuple[date, date]] = []
    cursor = window_start
    for a in allocs:
        a_start = max(a.start, window_start)
        if a_start > cursor:
            if (a_start - cursor).days >= min_nights:
                gaps.append((cursor, a_start))
        cursor = max(cursor, min(a.end, window_end))
    if cursor < window_end and (window_end - cursor).days >= min_nights:
        gaps.append((cursor, window_end))
    return gaps


@transaction.atomic
def book_spontaneous(
    member: Member, quarter: Quarter, start: date, end: date,
    persons: int = 1, source: str = "spontaneous",
) -> tuple[Allocation | None, str | None]:
    """Bucht eine freie Lücke mit den verfügbaren Tagen. Gibt
    (Allocation, None) bei Erfolg zurück bzw. (None, Fehlermeldung) sonst.

    Geprüft wird in dieser Reihenfolge:
      1. gültiger Zeitraum,
      2. Personenzahl passt zur Belegung des Quartiers,
      3. liegt vollständig in einem freigeschalteten Buchungszeitraum,
      4. Quartier ist frei,
      5. genügend verfügbare Tage (inkl. erhaltener/abgegebener) im Jahr.
    """
    nights = (end - start).days
    if nights <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    persons = int(persons or 0)
    if persons < quarter.min_occupancy or persons > quarter.max_occupancy:
        return None, (f"{quarter.name} ist für {quarter.min_occupancy}–"
                      f"{quarter.max_occupancy} Personen ausgelegt "
                      f"(angegeben: {persons}).")
    if not range_is_released(quarter, start, end):
        return None, ("Dieser Zeitraum ist (noch) nicht zur Buchung "
                      "freigeschaltet.")
    if not quarter_is_free(quarter, start, end):
        return None, "Das Quartier ist in diesem Zeitraum bereits belegt."
    if member.nights_remaining_in_year(start.year) < nights:
        return None, ("Nicht genügend verfügbare Tage für diesen Zeitraum "
                      f"({member.nights_remaining_in_year(start.year)} übrig, "
                      f"{nights} benötigt).")
    # Saison-Regeln: Mindestnächte, Parallel-Limit, Aufenthaltsdeckel
    rule_error = check_booking_rules(member, start, end)
    if rule_error:
        return None, rule_error
    alloc = Allocation.objects.create(
        member=member, quarter=quarter, start=start, end=end,
        persons=persons, source=source,
    )
    return alloc, None


# --------------------------------------------------------------------------- #
# Saison-/Sonderregeln (Mindestnächte, Parallel-Limit, Aufenthaltsdeckel)
# --------------------------------------------------------------------------- #

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
    member: Member, start: date, end: date,
) -> str | None:
    """Prüft eine geplante Buchung gegen die globalen + saisonalen Regeln
    (inkl. regelsetzender Schulferien). Gibt einen Fehlertext zurück oder None."""
    policy = BookingPolicy.get_solo()
    existing = [
        R.Stay(start=a.start, end=a.end) for a in member.allocations.all()
    ]
    return R.validate_booking(
        _materialized_seasons(start, end), policy.default_min_nights,
        start, end, existing,
    )


def schedule_blocker(
    member: Member, quarter: Quarter, start: date, end: date,
) -> str | None:
    """Grund, warum der Zeitraum (Termin/Regeln/Budget) NICHT buchbar ist –
    ohne Personenzahl- und Belegungsprüfung. Für die Vorab-Anzeige im Kalender."""
    nights = (end - start).days
    if nights <= 0:
        return "Ungültiger Zeitraum."
    remaining = member.nights_remaining_in_year(start.year)
    if remaining < nights:
        return f"Nicht genügend Tage ({remaining} übrig, {nights} benötigt)."
    return check_booking_rules(member, start, end)


def min_nights_for_range(start: date, end: date) -> int:
    """Effektiver Mindestaufenthalt für [start, end): Standard-Mindestnächte,
    verschärft durch überlappende Saison-/Schulferien-Regeln."""
    required = BookingPolicy.get_solo().default_min_nights or 0
    for s in _materialized_seasons(start, end):
        if s.min_nights and s.start < end and s.end > start:
            required = max(required, s.min_nights)
    return required


# --------------------------------------------------------------------------- #
# Freigeschaltete Buchungszeiträume (Perioden im Status "Freie Bebuchbarkeit")
# --------------------------------------------------------------------------- #

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
    for a in Allocation.objects.filter(
        quarter=quarter, start__lt=window_end, end__gt=window_start,
    ):
        d = max(a.start, window_start)
        upper = min(a.end, window_end)
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


def _occupied_days_by_quarter(first: date, last: date) -> dict[str, set[date]]:
    """Belegte Tage je Quartier-ID im Bereich [first, last]."""
    occupied: dict[str, set[date]] = defaultdict(set)
    for a in Allocation.objects.filter(start__lte=last, end__gt=first):
        d = max(a.start, first)
        upper = min(a.end, last + timedelta(days=1))
        while d < upper:
            occupied[str(a.quarter_id)].add(d)
            d += timedelta(days=1)
    return occupied


def build_booking_calendar(
    member, year: int, month: int,
    sel_start: date | None = None, sel_end: date | None = None,
) -> dict:
    """Monatsmatrix für die Buchung mit Ampel-Färbung je Tag:

      free  (grün)      – noch gar nichts belegt
      many  (hellgrün)  – noch viele Quartiere frei (> 50 %)
      few   (gelb)      – nur noch wenige frei
      full  (rot)       – nichts mehr frei
      none  (neutral)   – an diesem Tag ist nichts freigeschaltet

    `sel_start`/`sel_end` markieren die aktuelle Auswahl im Kalender.
    """
    cal = _calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    windows = _active_windows()
    quarters = list(Quarter.objects.filter(active=True))
    qmap = {str(q.id): q for q in quarters}
    qids = list(qmap)
    occupied = _occupied_days_by_quarter(first, last)
    hols = school_holidays_in_range(first, last + timedelta(days=1))
    own_days: set[date] = set()
    if member:
        for a in member.allocations.filter(start__lte=last, end__gt=first):
            d = max(a.start, first)
            upper = min(a.end, last + timedelta(days=1))
            while d < upper:
                own_days.add(d)
                d += timedelta(days=1)
    today = date.today()

    grid = []
    for week in weeks:
        row = []
        for d in week:
            released = [
                qid for qid in qids
                if A.is_released(windows, qid, d) and qmap[qid].bookable_on(d)
            ]
            total = len(released)
            free = sum(1 for qid in released if d not in occupied[qid])
            if total == 0:
                level = "none"
            elif free == total:
                level = "free"
            elif free == 0:
                level = "full"
            elif free * 2 > total:
                level = "many"
            else:
                level = "few"
            in_range = bool(
                sel_start and (
                    (sel_end and sel_start <= d < sel_end)
                    or (not sel_end and d == sel_start)
                )
            )
            row.append({
                "date": d,
                "iso": d.isoformat(),
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
                "is_past": d < today,
                "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
                "level": level,
                "free": free,
                "total": total,
                "mine": d in own_days,
                "in_range": in_range,
                "is_start": sel_start == d,
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "weeks": grid,
        "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year, "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
    }


def build_wish_calendar(
    member, period, year: int, month: int,
    sel_start: date | None = None, sel_end: date | None = None,
) -> dict:
    """Monatsmatrix für die Wunschliste mit Ampel nach Wunsch-Nachfrage:

      free  (grün)     – noch keine eingereichten Wünsche
      many  (hellgrün) – wenig Nachfrage
      few   (gelb)     – mittlere Nachfrage
      full  (rot)      – mehr Wünsche als Quartiere → hart umkämpft

    Eigene Wünsche werden markiert (eingereicht vs. Entwurf).
    """
    cal = _calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    n_quarters = max(1, Quarter.objects.filter(active=True).count())
    submitted, own = [], []
    if period:
        submitted = list(Wish.objects.filter(
            period=period, submitted=True, start__lte=last, end__gt=first))
        if member:
            own = list(Wish.objects.filter(
                period=period, member=member, start__lte=last, end__gt=first))
    hols = school_holidays_in_range(first, last + timedelta(days=1))
    today = date.today()

    grid = []
    for week in weeks:
        row = []
        for d in week:
            demand = sum(1 for w in submitted if w.start <= d < w.end)
            if demand == 0:
                level = "free"
            elif demand <= n_quarters // 2 or demand == 1:
                level = "many"
            elif demand <= n_quarters:
                level = "few"
            else:
                level = "full"
            own_sub = any(w.start <= d < w.end for w in own if w.submitted)
            own_draft = any(w.start <= d < w.end for w in own if not w.submitted)
            in_range = bool(
                sel_start and ((sel_end and sel_start <= d < sel_end)
                               or (not sel_end and d == sel_start)))
            row.append({
                "date": d, "iso": d.isoformat(), "day": d.day,
                "in_month": d.month == month, "is_today": d == today,
                "is_weekend": d.weekday() >= 5, "is_past": d < today,
                "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
                "level": level, "demand": demand,
                "own_sub": own_sub, "own_draft": own_draft,
                "in_range": in_range, "is_start": sel_start == d,
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "weeks": grid, "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year, "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
    }


def quarter_wish_counts(period, start: date, end: date) -> dict[str, int]:
    """Anzahl eingereichter Wünsche je Quartier, die [start, end) überlappen –
    zeigt, welche Quartiere im Wunschzeitraum besonders umkämpft sind."""
    counts: dict[str, int] = defaultdict(int)
    if not period or end <= start:
        return counts
    for w in Wish.objects.filter(
        period=period, submitted=True, start__lt=end, end__gt=start,
    ):
        counts[str(w.quarter_id)] += 1
    return counts


# --------------------------------------------------------------------------- #
# Warteliste (Spontanbuchung) & In-App-Benachrichtigungen
# --------------------------------------------------------------------------- #

@transaction.atomic
def add_waitlist_entry(
    member: Member, quarter: Quarter, start: date, end: date, persons: int = 1,
) -> tuple[WaitlistEntry | None, str | None]:
    """Trägt einen Wunschzeitraum für ein belegtes Quartier in die Warteliste ein."""
    if (end - start).days <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    if not A.range_released(_active_windows(), str(quarter.id), start, end):
        return None, "Dieser Zeitraum ist nicht zur Buchung freigeschaltet."
    if quarter_is_free(quarter, start, end):
        return None, "Dieses Quartier ist in dem Zeitraum bereits frei – du kannst direkt buchen."
    existing = WaitlistEntry.objects.filter(
        member=member, quarter=quarter, start=start, end=end, fulfilled=False,
    ).exists()
    if existing:
        return None, "Du stehst für diesen Zeitraum bereits auf der Warteliste."
    entry = WaitlistEntry.objects.create(
        member=member, quarter=quarter, start=start, end=end,
        persons=int(persons or 1),
    )
    return entry, None


def waiters_for_allocation(allocation: Allocation):
    """Aktive Wartelisten-Einträge, die diese Buchung betreffen (gleiches
    Quartier, überlappender Zeitraum) – damit die Buchenden sehen, dass jemand
    wartet."""
    return list(
        WaitlistEntry.objects.filter(
            quarter=allocation.quarter, fulfilled=False,
            start__lt=allocation.end, end__gt=allocation.start,
        ).select_related("member").exclude(member=allocation.member)
    )


def notify_waitlist_if_free(quarter: Quarter, start: date, end: date) -> int:
    """Prüft offene Wartelisten-Einträge für `quarter`, die den freigewordenen
    Zeitraum [start, end) berühren: Ist ihr Wunschzeitraum jetzt komplett frei
    (und freigeschaltet), wird das Mitglied benachrichtigt. Gibt die Anzahl der
    Benachrichtigungen zurück."""
    count = 0
    candidates = WaitlistEntry.objects.filter(
        quarter=quarter, fulfilled=False, start__lt=end, end__gt=start,
    ).select_related("member", "quarter")
    for entry in candidates:
        if not quarter_is_free(quarter, entry.start, entry.end):
            continue
        if not A.range_released(_active_windows(), str(quarter.id),
                                entry.start, entry.end):
            continue
        entry.fulfilled = True
        entry.notified_at = timezone.now()
        entry.save(update_fields=["fulfilled", "notified_at"])
        Notification.objects.create(
            member=entry.member,
            message=(f"{quarter.name} ist von {entry.start} bis {entry.end} "
                     f"frei geworden – jetzt buchen."),
            url=f"/buchen/?start={entry.start}&end={entry.end}",
        )
        count += 1
    return count


def unread_notifications(member):
    return list(member.notifications.filter(read=False)) if member else []


def mark_notifications_read(member) -> int:
    if not member:
        return 0
    return member.notifications.filter(read=False).update(read=True)


# --------------------------------------------------------------------------- #
# Tages-Detail (Übersicht) & Wechselwünsche
# --------------------------------------------------------------------------- #

def day_detail(member, day: date) -> dict:
    """Wer ist an `day` in welchem Quartier (mit Personenzahl) – und welche
    Quartiere sind an dem Tag noch frei?"""
    nxt = day + timedelta(days=1)
    occupied = [
        {
            "quarter": a.quarter.name,
            "who": a.member.display_name,
            "persons": a.persons,
            "mine": bool(member) and a.member_id == member.id,
        }
        for a in Allocation.objects.select_related("quarter", "member")
        .filter(start__lte=day, end__gt=day).order_by("quarter__name")
    ]
    free, _occ = split_quarters_for_range(day, nxt)
    return {"day": day, "occupied": occupied, "free": [q.name for q in free]}


def concurrent_allocations(allocation: Allocation):
    """Andere Buchungen (anderer Mitglieder), die zeitlich mit `allocation`
    überlappen – „wer ist zur gleichen Zeit da“."""
    return list(
        Allocation.objects.select_related("quarter", "member").filter(
            start__lt=allocation.end, end__gt=allocation.start,
        ).exclude(member_id=allocation.member_id).order_by("start", "quarter__name")
    )


@transaction.atomic
def create_swap_request(from_member, from_allocation, to_allocation, message=""):
    """Legt einen Wechselwunsch an und benachrichtigt das Gegenüber."""
    if to_allocation.member_id == from_member.id:
        return None, "Das ist deine eigene Buchung."
    sr = SwapRequest.objects.create(
        from_member=from_member, to_member=to_allocation.member,
        from_allocation=from_allocation, to_allocation=to_allocation,
        message=message,
    )
    Notification.objects.create(
        member=to_allocation.member,
        message=(f"{from_member.display_name} fragt nach einem Quartier-Tausch "
                 f"({from_allocation.quarter.name} ↔ {to_allocation.quarter.name})."),
        url="/meine-buchungen/",
    )
    return sr, None


@transaction.atomic
def respond_swap_request(member, swap_id, accept: bool) -> tuple[bool, str | None]:
    """Nimmt einen eingegangenen Wechselwunsch an oder lehnt ihn ab und
    benachrichtigt die anfragende Person."""
    try:
        sr = SwapRequest.objects.select_related("from_allocation", "to_allocation") \
            .get(id=swap_id, to_member=member, status=SwapRequest.PENDING)
    except SwapRequest.DoesNotExist:
        return False, "Wechselwunsch nicht gefunden."
    sr.status = SwapRequest.ACCEPTED if accept else SwapRequest.DECLINED
    sr.responded_at = timezone.now()
    sr.save(update_fields=["status", "responded_at"])
    verb = "angenommen" if accept else "abgelehnt"
    Notification.objects.create(
        member=sr.from_member,
        message=(f"{member.display_name} hat deinen Wechselwunsch {verb} "
                 f"({sr.from_allocation.quarter.name} ↔ {sr.to_allocation.quarter.name})."),
        url="/meine-buchungen/",
    )
    return True, None


def pending_swaps_for(member):
    """Offene, an `member` gerichtete Wechselwünsche."""
    return list(
        SwapRequest.objects.filter(to_member=member, status=SwapRequest.PENDING)
        .select_related("from_member", "from_allocation__quarter",
                        "to_allocation__quarter")
    )


# --------------------------------------------------------------------------- #
# Tage an andere Mitglieder übertragen
# --------------------------------------------------------------------------- #

@transaction.atomic
def transfer_nights(
    from_member: Member, to_member: Member, nights: int, year: int,
    note: str = "",
) -> tuple[NightTransfer | None, str | None]:
    """Überträgt `nights` Tage von einem Mitglied auf ein anderes (für `year`).
    Gibt (NightTransfer, None) oder (None, Fehlermeldung) zurück."""
    if from_member.id == to_member.id:
        return None, "Empfänger muss ein anderes Mitglied sein."
    if nights <= 0:
        return None, "Die Anzahl der Tage muss positiv sein."
    remaining = from_member.nights_remaining_in_year(year)
    if remaining < nights:
        return None, (f"Nicht genügend verfügbare Tage zum Übertragen "
                      f"({remaining} übrig, {nights} angefragt).")
    t = NightTransfer.objects.create(
        from_member=from_member, to_member=to_member, nights=nights,
        year=year, note=note,
    )
    return t, None


# --------------------------------------------------------------------------- #
# Schulferien (Anzeige) & Mitglieder-Kalender
# --------------------------------------------------------------------------- #

class _Holiday:
    """Materialisierte (konkrete) Schulferien-Instanz für die Kalender-Anzeige."""
    __slots__ = ("name", "start", "end", "region")

    def __init__(self, name, start, end, region):
        self.name, self.start, self.end, self.region = name, start, end, region


def school_holidays_in_range(start: date, end: date) -> list:
    """Materialisiert die jährlich wiederkehrenden Schulferien zu konkreten
    Zeiträumen, die [start, end) berühren (für die Kalender-Anzeige)."""
    out: list[_Holiday] = []
    years = range(start.year - 1, end.year + 1)
    for h in SchoolHoliday.objects.filter(active=True):
        for y in years:
            s, e = A.recurring_range(h.start_month, h.start_day,
                                     h.end_month, h.end_day, y)
            if s < end and e > start:
                out.append(_Holiday(h.name, s, e, h.region))
    out.sort(key=lambda x: x.start)
    return out


GERMAN_MONTHS = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
    "August", "September", "Oktober", "November", "Dezember",
]


def build_member_calendar(member: Member, year: int, month: int) -> dict:
    """Baut die Monatsmatrix (Wochen × 7 Tage) mit Ferien- und Buchungs-Infos.

    Rückgabe enthält die Wochen, die Monatsbezeichnung und die Navigations-
    Ziele (Vor-/Folgemonat)."""
    cal = _calendar.Calendar(firstweekday=0)  # Montag zuerst
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    hols = school_holidays_in_range(first, last + timedelta(days=1))
    allocs = []
    if member:
        allocs = list(
            member.allocations.select_related("quarter").filter(
                start__lte=last, end__gt=first,
            )
        )
    today = date.today()

    grid = []
    for week in weeks:
        row = []
        for d in week:
            holiday = next((h.name for h in hols if h.start <= d < h.end), None)
            day_allocs = [a for a in allocs if a.start <= d < a.end]
            row.append({
                "date": d,
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
                "holiday": holiday,
                "allocations": day_allocs,
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "weeks": grid,
        "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year,
        "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
    }


def build_community_calendar(member, year, month) -> dict:
    """Monatsmatrix mit ALLEN Buchungen der Gemeinschaft (wer ist wann wo).
    Die eigenen Buchungen des angemeldeten Mitglieds werden markiert."""
    cal = _calendar.Calendar(firstweekday=0)  # Montag zuerst
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    allocs = list(
        Allocation.objects.select_related("quarter", "member").filter(
            start__lte=last, end__gt=first,
        ).order_by("quarter__name")
    )
    hols = school_holidays_in_range(first, last + timedelta(days=1))
    own_id = member.id if member else None
    today = date.today()

    grid = []
    for week in weeks:
        row = []
        for d in week:
            holiday = next((h.name for h in hols if h.start <= d < h.end), None)
            bookings = [
                {
                    "quarter": a.quarter.name,
                    "who": a.member.display_name,
                    "persons": a.persons,
                    "member_id": a.member_id,
                    "mine": a.member_id == own_id,
                }
                for a in allocs if a.start <= d < a.end
            ]
            row.append({
                "date": d,
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
                "holiday": holiday,
                "bookings": bookings,
                "has_mine": any(b["mine"] for b in bookings),
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "weeks": grid,
        "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year,
        "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
    }


# --------------------------------------------------------------------------- #
# Stornierung
# --------------------------------------------------------------------------- #

@transaction.atomic
def cancel_allocation(member: Member, allocation_id) -> tuple[bool, str | None]:
    """Storniert eine Buchung des Mitglieds. Vergangene Buchungen bleiben.
    Wird dadurch ein Wartelisten-Zeitraum frei, werden die Wartenden
    benachrichtigt."""
    try:
        a = member.allocations.get(id=allocation_id)
    except Allocation.DoesNotExist:
        return False, "Buchung nicht gefunden."
    if a.end <= date.today():
        return False, "Vergangene Buchungen können nicht storniert werden."
    quarter, start, end = a.quarter, a.start, a.end
    a.delete()
    notify_waitlist_if_free(quarter, start, end)
    return True, None


# --------------------------------------------------------------------------- #
# Wunschliste: Reihenfolge, Einreichen, Zurückziehen
# --------------------------------------------------------------------------- #

def _renumber_wishes(member: Member, period: BookingPeriod) -> None:
    """Setzt die Prioritäten lückenlos auf 1..N gemäß aktueller Reihenfolge."""
    wishes = list(
        Wish.objects.filter(member=member, period=period).order_by("priority", "id")
    )
    for i, w in enumerate(wishes, start=1):
        if w.priority != i:
            w.priority = i
            w.save(update_fields=["priority"])


def add_wish(member, period, quarter, start, end) -> Wish:
    """Fügt einen Wunsch als Entwurf ans Ende der Liste an."""
    last = (
        Wish.objects.filter(member=member, period=period)
        .order_by("-priority").first()
    )
    next_prio = (last.priority + 1) if last else 1
    return Wish.objects.create(
        member=member, period=period, quarter=quarter, start=start, end=end,
        priority=next_prio, submitted=False,
    )


@transaction.atomic
def move_wish(member, period, wish_id, direction: str) -> None:
    wishes = list(
        Wish.objects.filter(member=member, period=period).order_by("priority", "id")
    )
    idx = next((i for i, w in enumerate(wishes) if str(w.id) == str(wish_id)), None)
    if idx is None:
        return
    swap = idx - 1 if direction == "up" else idx + 1
    if swap < 0 or swap >= len(wishes):
        return
    a, b = wishes[idx], wishes[swap]
    a.priority, b.priority = b.priority, a.priority
    a.save(update_fields=["priority"])
    b.save(update_fields=["priority"])


@transaction.atomic
def reorder_wishes(member, period, ordered_ids: list[str]) -> None:
    by_id = {
        str(w.id): w
        for w in Wish.objects.filter(member=member, period=period)
    }
    prio = 1
    for wid in ordered_ids:
        w = by_id.get(str(wid))
        if w is None:
            continue
        if w.priority != prio:
            w.priority = prio
            w.save(update_fields=["priority"])
        prio += 1


@transaction.atomic
def delete_wish(member, period, wish_id) -> None:
    Wish.objects.filter(id=wish_id, member=member, period=period).delete()
    _renumber_wishes(member, period)


@transaction.atomic
def submit_wishlist(member, period) -> int:
    """Reicht alle Entwurfs-Wünsche des Mitglieds in den Lostopf ein."""
    _renumber_wishes(member, period)
    return Wish.objects.filter(
        member=member, period=period, submitted=False,
    ).update(submitted=True, submitted_at=timezone.now())


@transaction.atomic
def withdraw_wishlist(member, period) -> int:
    """Zieht die Wünsche aus dem Lostopf zurück (wieder Entwurf)."""
    return Wish.objects.filter(
        member=member, period=period, submitted=True,
    ).update(submitted=False, submitted_at=None)

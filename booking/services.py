"""Service-Layer: Brücke zwischen Django-Modellen und dem reinen Losmodul.

Hier liegt bewusst die gesamte Geschäftslogik, die DB und Algorithmus
verbindet – die Views bleiben dünn, das Losmodul bleibt rein.
"""
from __future__ import annotations

import calendar as _calendar
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from . import availability as A
from . import lottery as L
from . import rules as R
from .models import (
    Allocation, BookingPeriod, BookingPolicy, LotteryRun,
    Member, NightTransfer, Quarter, SchoolHoliday, SeasonRule, Wish,
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

    # Faktoren aktualisieren
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
    log_text = L.render_log_text(result, party_names, quarter_names)
    summary = (
        f"{len(result.allocations)} Zuteilungen, "
        f"{len(result.losses)} Verluste, Seed {seed}"
    )
    return LotteryRun.objects.create(
        period=period, seed=seed, log_text=log_text, summary=summary,
    )


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
    source: str = "spontaneous",
) -> tuple[Allocation | None, str | None]:
    """Bucht eine freie Lücke mit den verfügbaren Tagen. Gibt
    (Allocation, None) bei Erfolg zurück bzw. (None, Fehlermeldung) sonst.

    Geprüft wird in dieser Reihenfolge:
      1. gültiger Zeitraum,
      2. liegt vollständig in einem freigeschalteten Buchungszeitraum,
      3. Quartier ist frei,
      4. genügend verfügbare Tage (inkl. erhaltener/abgegebener) im Jahr.
    """
    nights = (end - start).days
    if nights <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
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
        member=member, quarter=quarter, start=start, end=end, source=source,
    )
    return alloc, None


# --------------------------------------------------------------------------- #
# Saison-/Sonderregeln (Mindestnächte, Parallel-Limit, Aufenthaltsdeckel)
# --------------------------------------------------------------------------- #

def _seasons() -> list[R.Season]:
    out: list[R.Season] = []
    for s in SeasonRule.objects.filter(active=True):
        out.append(R.Season(
            name=s.name, start=s.start, end=s.end,
            min_nights=s.min_nights,
            max_parallel_units=s.max_parallel_units,
            max_stay_nights=s.max_stay_nights,
            active=True,
        ))
    return out


def check_booking_rules(
    member: Member, start: date, end: date,
) -> str | None:
    """Prüft eine geplante Buchung gegen die globalen + saisonalen Regeln.
    Gibt einen Fehlertext zurück oder None, wenn alles passt."""
    policy = BookingPolicy.get_solo()
    # Alle bestehenden Buchungen des Mitglieds (Jahresgrenzen-sicher: die reine
    # Prüflogik zählt ohnehin nur die Überlappungen mit den jeweiligen Saisons).
    existing = [
        R.Stay(start=a.start, end=a.end) for a in member.allocations.all()
    ]
    return R.validate_booking(
        _seasons(), policy.default_min_nights, start, end, existing,
    )


# --------------------------------------------------------------------------- #
# Freigeschaltete Buchungszeiträume (Perioden im Status "Freie Bebuchbarkeit")
# --------------------------------------------------------------------------- #

def _active_windows() -> list[A.Window]:
    """Lädt die zur freien Buchung freigegebenen Perioden als reine Window-
    Objekte. Buchbar ist ein Tag nur innerhalb einer Periode im Status
    „Freie Bebuchbarkeit innerhalb Zeitraum“."""
    out: list[A.Window] = []
    periods = BookingPeriod.objects.filter(
        status=BookingPeriod.FREE_BOOKING
    ).prefetch_related("quarters")
    for p in periods:
        qids = frozenset(str(q.id) for q in p.quarters.all())
        out.append(A.Window(
            start=p.start, end=p.end, applies_to_all=p.applies_to_all,
            quarter_ids=qids, active=True,
        ))
    return out


def range_is_released(quarter: Quarter, start: date, end: date) -> bool:
    """Ist der Zeitraum [start, end) für das Quartier freigeschaltet?"""
    return A.range_released(_active_windows(), str(quarter.id), start, end)


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

def school_holidays_in_range(start: date, end: date) -> list[SchoolHoliday]:
    return list(
        SchoolHoliday.objects.filter(active=True, start__lt=end, end__gt=start)
        .order_by("start")
    )


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
    """Storniert eine Buchung des Mitglieds. Vergangene Buchungen bleiben."""
    try:
        a = member.allocations.get(id=allocation_id)
    except Allocation.DoesNotExist:
        return False, "Buchung nicht gefunden."
    if a.end <= date.today():
        return False, "Vergangene Buchungen können nicht storniert werden."
    a.delete()
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

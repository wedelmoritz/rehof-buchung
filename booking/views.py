"""Views der Buchungs-App. Bewusst dünn – Logik liegt im Service-Layer.

Seitenstruktur:
  * overview  – Community-Übersicht (wer ist wann da), eigene hervorgehoben.
  * book      – „Buchen“: eigener Kalender + Spontanbuchung + eigene Buchungen.
  * wishlist  – „Wunschliste fürs nächste Jahr“: Wünsche fürs Losverfahren.
  * transfer  – Tage an ein anderes Mitglied übertragen.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import TransferForm, WishForm
from .models import Allocation, BookingPeriod, Member, Quarter, Wish
from . import services as svc


# Pastell-Palette zur Unterscheidung der Mitglieder in der Übersicht.
MEMBER_COLORS = [
    "#cfe6c7", "#f6dcc0", "#d9e3f3", "#f3d9e2", "#e7dcf0", "#cfe7e6",
    "#f7eccc", "#e0e8c8", "#f1d7d0", "#d6e6da", "#ecd9c4", "#dde0ee",
]


def _current_member(request) -> Member | None:
    return getattr(request.user, "member", None)


def _parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def _parse_booking_post(request):
    """Liest quarter/start/end/persons aus einem Buchungs- oder Warteformular."""
    try:
        quarter = Quarter.objects.get(id=request.POST.get("quarter"), active=True)
    except (Quarter.DoesNotExist, ValueError, TypeError):
        return None, None, None, None, "Quartier nicht gefunden."
    start = _parse_date(request.POST.get("start"))
    end = _parse_date(request.POST.get("end"))
    if not start or not end:
        return None, None, None, None, "Ungültiger Zeitraum."
    try:
        persons = int(request.POST.get("persons", "1"))
    except (TypeError, ValueError):
        persons = 0
    return quarter, start, end, persons, None


def _month_from_request(request, today) -> tuple[int, int]:
    """Liest year/month aus GET (oder POST) und fällt auf den aktuellen Monat zurück."""
    src = request.POST if request.method == "POST" else request.GET
    try:
        year = int(src.get("year", today.year))
        month = int(src.get("month", today.month))
        if not (1 <= month <= 12):
            year, month = today.year, today.month
    except (TypeError, ValueError):
        year, month = today.year, today.month
    return year, month


def _redirect_month(name: str, year, month):
    return redirect(f"{reverse(name)}?year={year}&month={month}")


# --------------------------------------------------------------------------- #
# Übersicht (Community)
# --------------------------------------------------------------------------- #

@login_required
def overview(request):
    """Wer hat im Monat was gebucht? Eigene Buchungen sind hervorgehoben;
    über die Navigation lassen sich auch die kommenden Monate ansehen."""
    member = _current_member(request)
    today = date.today()
    if request.method == "POST" and member and \
            request.POST.get("action") == "read_notifications":
        svc.mark_notifications_read(member)
        return redirect("overview")
    year, month = _month_from_request(request, today)
    cal = svc.build_community_calendar(member, year, month)
    # Jedem im Monat vorkommenden Mitglied eine feste Pastellfarbe geben, damit
    # auf einen Blick sichtbar ist, wer wann da ist (Gemeinschaftsaspekt).
    color_map: dict[int, str] = {}
    legend: list[dict] = []
    for week in cal["weeks"]:
        for d in week:
            for b in d["bookings"]:
                mid = b["member_id"]
                if mid not in color_map:
                    color_map[mid] = MEMBER_COLORS[len(color_map) % len(MEMBER_COLORS)]
                    legend.append({"name": b["who"], "color": color_map[mid],
                                   "mine": b["mine"]})
                b["color"] = color_map[mid]
    sel_day = _parse_date(request.GET.get("day"))
    detail = svc.day_detail(member, sel_day) if sel_day else None
    return render(request, "booking/overview.html", {
        "member": member,
        "cal": cal,
        "today": today,
        "year": today.year,
        "legend": legend,
        "sel_day": sel_day,
        "detail": detail,
        "nights_remaining": (
            member.nights_remaining_in_year(today.year) if member else 0
        ),
        "notifications": svc.unread_notifications(member),
        "open_period": BookingPeriod.objects.filter(
            status=BookingPeriod.WISHES_OPEN).first(),
        "released_windows": BookingPeriod.objects.filter(
            status=BookingPeriod.FREE_BOOKING, end__gte=today).order_by("start"),
    })


# --------------------------------------------------------------------------- #
# Buchen
# --------------------------------------------------------------------------- #

def _book_redirect(year, month, persons, accessible):
    url = f"{reverse('book')}?year={year}&month={month}&persons={persons}"
    if accessible:
        url += "&accessible=1"
    return redirect(url)


@login_required
def book(request):
    """Klick-Buchung: Personen + Barrierefrei oben einstellen, im Ampel-Kalender
    Anreise/Abreise wählen, dann passendes Quartier buchen (oder Warteliste)."""
    member = _current_member(request)
    today = date.today()
    year, month = _month_from_request(request, today)

    try:
        persons = max(1, int(request.GET.get("persons") or request.POST.get("persons") or 2))
    except (TypeError, ValueError):
        persons = 2
    need_accessible = (request.GET.get("accessible") == "1") or \
        (request.POST.get("accessible") == "1")

    if request.method == "POST" and member:
        action = request.POST.get("action", "")
        p_year = request.POST.get("year", year)
        p_month = request.POST.get("month", month)

        if action == "book":
            quarter, start, end, persons_in, err0 = _parse_booking_post(request)
            if err0:
                messages.error(request, err0)
            else:
                alloc, err = svc.book_spontaneous(member, quarter, start, end, persons_in)
                messages.success(
                    request,
                    f"Gebucht: {quarter.name}, {start} – {end} ({persons_in} Pers.).") \
                    if alloc else messages.error(request, err or "Buchung nicht möglich.")
            return _book_redirect(p_year, p_month, persons, need_accessible)

        if action == "waitlist":
            quarter, start, end, persons_in, err0 = _parse_booking_post(request)
            if err0:
                messages.error(request, err0)
            else:
                entry, err = svc.add_waitlist_entry(member, quarter, start, end, persons_in)
                messages.success(
                    request,
                    f"Auf die Warteliste gesetzt: {quarter.name}, {start} – {end}. "
                    f"Du wirst benachrichtigt, sobald der Zeitraum frei wird.") \
                    if entry else messages.error(request, err or "Warteliste nicht möglich.")
            return _book_redirect(p_year, p_month, persons, need_accessible)

        if action == "read_notifications":
            svc.mark_notifications_read(member)
            return _book_redirect(p_year, p_month, persons, need_accessible)

        return _book_redirect(p_year, p_month, persons, need_accessible)

    # --- GET: Kalender + Auswahl ---
    sel_start = _parse_date(request.GET.get("start"))
    sel_end = _parse_date(request.GET.get("end"))
    if sel_start and sel_end and sel_end <= sel_start:
        sel_end = None
    cal = svc.build_booking_calendar(member, year, month, sel_start, sel_end) \
        if member else None

    # Query-Suffix, der Personenzahl/Filter UND Auswahl über die Monats-
    # Navigation hinweg erhält (damit auch Buchungen über Monatsgrenzen gehen).
    sel_qs = f"&persons={persons}"
    if need_accessible:
        sel_qs += "&accessible=1"
    if sel_start:
        sel_qs += f"&start={sel_start.isoformat()}"
    if sel_end:
        sel_qs += f"&end={sel_end.isoformat()}"

    eff_start = eff_end = None
    suitable, maybe_unsuitable, occ_quarters = [], [], []
    range_min_nights = 0
    too_short = False
    not_enough_days = False
    days_remaining_year = 0
    if member and sel_start:
        eff_start = sel_start
        eff_end = sel_end if sel_end else sel_start + timedelta(days=1)
        nights = (eff_end - eff_start).days
        range_min_nights = svc.min_nights_for_range(eff_start, eff_end)
        too_short = nights < range_min_nights
        days_remaining_year = member.nights_remaining_in_year(eff_start.year)
        not_enough_days = nights > days_remaining_year
        free_quarters, occ_quarters = svc.split_quarters_for_range(eff_start, eff_end)
        for q in free_quarters:
            reason = svc.schedule_blocker(member, q, eff_start, eff_end)
            fits_persons = q.min_occupancy <= persons <= q.max_occupancy
            fits_access = (not need_accessible) or q.accessible
            info = {
                "q": q, "reason": reason,
                "fits_persons": fits_persons, "fits_access": fits_access,
                "bookable": reason is None and fits_persons,
            }
            if fits_persons and fits_access and reason is None:
                suitable.append(info)
            else:
                maybe_unsuitable.append(info)

    return render(request, "booking/book.html", {
        "member": member,
        "cal": cal,
        "today": today,
        "persons": persons,
        "need_accessible": need_accessible,
        "sel_qs": sel_qs,
        "sel_start": sel_start,
        "sel_end": sel_end,
        "eff_start": eff_start,
        "eff_end": eff_end,
        "nights_selected": (eff_end - eff_start).days if eff_start and eff_end else 0,
        "range_min_nights": range_min_nights,
        "too_short": too_short,
        "not_enough_days": not_enough_days,
        "days_remaining_year": days_remaining_year,
        "suitable": suitable,
        "maybe_unsuitable": maybe_unsuitable,
        "occ_quarters": occ_quarters,
        "nights_remaining": member.nights_remaining_in_year(today.year) if member else 0,
        "notifications": svc.unread_notifications(member),
        "released_windows": BookingPeriod.objects.filter(
            status=BookingPeriod.FREE_BOOKING, end__gte=today).order_by("start"),
    })


@login_required
def my_bookings(request):
    """Eigene Buchungen: bevorstehende (mit Storno) und vergangene."""
    member = _current_member(request)
    today = date.today()

    if request.method == "POST" and member:
        action = request.POST.get("action", "")
        if action == "cancel":
            ok, err = svc.cancel_allocation(member, request.POST.get("allocation_id"))
            messages.success(request, "Buchung storniert.") if ok \
                else messages.error(request, err or "Stornierung nicht möglich.")
        elif action == "read_notifications":
            svc.mark_notifications_read(member)
        elif action == "swap_request":
            try:
                mine = member.allocations.get(id=request.POST.get("from_allocation"))
                other = Allocation.objects.select_related("quarter", "member").get(
                    id=request.POST.get("to_allocation"))
            except Allocation.DoesNotExist:
                messages.error(request, "Buchung nicht gefunden.")
            else:
                sr, err = svc.create_swap_request(
                    member, mine, other, request.POST.get("message", "").strip())
                messages.success(request, f"Wechselwunsch an {other.member.display_name} gesendet.") \
                    if sr else messages.error(request, err or "Nicht möglich.")
        elif action == "swap_respond":
            ok, err = svc.respond_swap_request(
                member, request.POST.get("swap_id"),
                request.POST.get("decision") == "accept")
            messages.success(request, "Antwort gesendet.") if ok \
                else messages.error(request, err or "Nicht möglich.")
        return redirect("my_bookings")

    upcoming, past = [], []
    incoming_swaps = []
    if member:
        for a in member.allocations.select_related("quarter").order_by("start"):
            (upcoming if a.end > today else past).append(a)
        for a in upcoming:
            a.waiters = svc.waiters_for_allocation(a)
            a.concurrent = svc.concurrent_allocations(a)
        incoming_swaps = svc.pending_swaps_for(member)

    return render(request, "booking/my_bookings.html", {
        "member": member,
        "today": today,
        "booking_year": today.year,
        "nights_remaining": member.nights_remaining_in_year(today.year) if member else 0,
        "nights_used": member.nights_used_in_year(today.year) if member else 0,
        "annual_budget": member.annual_night_budget if member else 0,
        "upcoming": upcoming,
        "past": past,
        "incoming_swaps": incoming_swaps,
        "notifications": svc.unread_notifications(member),
    })


# --------------------------------------------------------------------------- #
# Wunschliste fürs nächste Jahr
# --------------------------------------------------------------------------- #

@login_required
def wishlist(request):
    """Wunschliste fürs Losverfahren der nächsten Periode. Anders als beim
    Buchen dürfen Wünsche bewusst miteinander kollidieren."""
    member = _current_member(request)
    today = date.today()
    year, month = _month_from_request(request, today)
    period = BookingPeriod.objects.filter(status=BookingPeriod.WISHES_OPEN).first()

    if request.method == "POST" and member and period:
        action = request.POST.get("action", "")
        p_year = request.POST.get("year", year)
        p_month = request.POST.get("month", month)
        is_submitted = Wish.objects.filter(
            member=member, period=period, submitted=True).exists()

        if action == "add_wish" and not is_submitted:
            form = WishForm(request.POST)
            if form.is_valid():
                svc.add_wish(
                    member, period, form.cleaned_data["quarter"],
                    form.cleaned_data["start"], form.cleaned_data["end"])
            else:
                messages.error(request, "Bitte einen gültigen Wunsch eingeben.")
            # Auswahl im Kalender erhalten, damit man weitere Wünsche eintragen kann
            url = f"{reverse('wishlist')}?year={p_year}&month={p_month}"
            if request.POST.get("start"):
                url += f"&start={request.POST['start']}"
            if request.POST.get("end"):
                url += f"&end={request.POST['end']}"
            return redirect(url)

        if action == "delete_wish" and not is_submitted:
            svc.delete_wish(member, period, request.POST.get("wish_id"))
            return _redirect_month("wishlist", p_year, p_month)

        if action == "move_wish" and not is_submitted:
            svc.move_wish(member, period, request.POST.get("wish_id"),
                          request.POST.get("direction", "up"))
            return _redirect_month("wishlist", p_year, p_month)

        if action == "reorder" and not is_submitted:
            ids = [x for x in request.POST.get("order", "").split(",") if x]
            svc.reorder_wishes(member, period, ids)
            return _redirect_month("wishlist", p_year, p_month)

        if action == "submit_wishlist" and not is_submitted:
            n = svc.submit_wishlist(member, period)
            messages.success(
                request, f"{n} Wunsch/Wünsche in den Lostopf eingereicht.")
            return _redirect_month("wishlist", p_year, p_month)

        if action == "withdraw_wishlist":
            svc.withdraw_wishlist(member, period)
            messages.info(request, "Wünsche zurückgezogen – wieder bearbeitbar.")
            return _redirect_month("wishlist", p_year, p_month)

        return _redirect_month("wishlist", p_year, p_month)

    wishes = []
    wishlist_submitted = False
    wish_nights = 0
    if member and period:
        wishes = list(
            Wish.objects.filter(member=member, period=period)
            .select_related("quarter").order_by("priority", "id")
        )
        wishlist_submitted = any(w.submitted for w in wishes) and len(wishes) > 0
        wish_nights = sum(w.nights for w in wishes)

    # Kalender + Auswahl (analog zum Buchen, aber Wünsche dürfen kollidieren)
    sel_start = _parse_date(request.GET.get("start"))
    sel_end = _parse_date(request.GET.get("end"))
    if sel_start and sel_end and sel_end <= sel_start:
        sel_end = None
    cal = svc.build_wish_calendar(member, period, year, month, sel_start, sel_end) \
        if (member and period) else None
    sel_qs = ""
    if sel_start:
        sel_qs += f"&start={sel_start.isoformat()}"
    if sel_end:
        sel_qs += f"&end={sel_end.isoformat()}"

    eff_start = eff_end = None
    candidates = []
    if member and period and sel_start:
        eff_start = sel_start
        eff_end = sel_end if sel_end else sel_start + timedelta(days=1)
        counts = svc.quarter_wish_counts(period, eff_start, eff_end)
        for q in Quarter.objects.filter(active=True).order_by("name"):
            candidates.append({"q": q, "count": counts.get(str(q.id), 0)})

    return render(request, "booking/wishlist.html", {
        "member": member,
        "today": today,
        "period": period,
        "cal": cal,
        "sel_qs": sel_qs,
        "sel_start": sel_start,
        "sel_end": sel_end,
        "eff_start": eff_start,
        "eff_end": eff_end,
        "nights_selected": (eff_end - eff_start).days if eff_start and eff_end else 0,
        "candidates": candidates,
        "wish_form": WishForm(),
        "wishes": wishes,
        "wishlist_submitted": wishlist_submitted,
        "wish_nights": wish_nights,
        "wish_budget": member.wish_night_budget if member else 0,
    })


# --------------------------------------------------------------------------- #
# Tage übertragen
# --------------------------------------------------------------------------- #

@login_required
def transfer(request):
    """Tage an ein anderes Mitglied übertragen (innerhalb des Jahres)."""
    member = _current_member(request)
    year = date.today().year
    if not member:
        return redirect("overview")

    if request.method == "POST":
        form = TransferForm(request.POST, exclude_member=member)
        if form.is_valid():
            t, err = svc.transfer_nights(
                member, form.cleaned_data["to_member"],
                form.cleaned_data["nights"], year,
                note=form.cleaned_data.get("note", ""),
            )
            messages.success(request, f"{t.nights} Tage an {t.to_member} übertragen.") \
                if t else messages.error(request, err or "Übertragung nicht möglich.")
            return redirect("transfer")
    else:
        form = TransferForm(exclude_member=member)

    outgoing = member.transfers_out.filter(year=year).select_related("to_member")
    incoming = member.transfers_in.filter(year=year).select_related("from_member")
    return render(request, "booking/transfer.html", {
        "form": form, "member": member, "year": year,
        "remaining": member.nights_remaining_in_year(year),
        "outgoing": outgoing, "incoming": incoming,
    })


@login_required
def period_result(request, period_id: int):
    period = get_object_or_404(BookingPeriod, id=period_id)
    run = period.runs.first()
    allocations = (
        Allocation.objects.filter(period=period, source="lottery")
        .select_related("member", "quarter").order_by("start", "quarter__name")
    )
    return render(request, "booking/result.html", {
        "period": period, "run": run, "allocations": allocations,
    })

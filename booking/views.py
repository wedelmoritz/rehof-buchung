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
    return render(request, "booking/overview.html", {
        "member": member,
        "cal": cal,
        "today": today,
        "year": today.year,
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

@login_required
def book(request):
    """Klick-Buchung: Ampel-Kalender → Tag wählen → Quartier + Personen buchen
    (oder bei Belegung auf die Warteliste). Plus eigene Buchungen."""
    member = _current_member(request)
    today = date.today()
    year, month = _month_from_request(request, today)

    if request.method == "POST" and member:
        action = request.POST.get("action", "")
        p_year = request.POST.get("year", year)
        p_month = request.POST.get("month", month)

        if action == "book":
            quarter, start, end, persons, err0 = _parse_booking_post(request)
            if err0:
                messages.error(request, err0)
            else:
                alloc, err = svc.book_spontaneous(member, quarter, start, end, persons)
                messages.success(
                    request,
                    f"Gebucht: {quarter.name}, {start} – {end} ({persons} Pers.).") \
                    if alloc else messages.error(request, err or "Buchung nicht möglich.")
            return _redirect_month("book", p_year, p_month)

        if action == "waitlist":
            quarter, start, end, persons, err0 = _parse_booking_post(request)
            if err0:
                messages.error(request, err0)
            else:
                entry, err = svc.add_waitlist_entry(member, quarter, start, end, persons)
                messages.success(
                    request,
                    f"Auf die Warteliste gesetzt: {quarter.name}, {start} – {end}. "
                    f"Du wirst benachrichtigt, sobald der Zeitraum frei wird.") \
                    if entry else messages.error(request, err or "Warteliste nicht möglich.")
            return _redirect_month("book", p_year, p_month)

        if action == "cancel":
            ok, err = svc.cancel_allocation(member, request.POST.get("allocation_id"))
            messages.success(request, "Buchung storniert.") if ok \
                else messages.error(request, err or "Stornierung nicht möglich.")
            return _redirect_month("book", p_year, p_month)

        if action == "read_notifications":
            svc.mark_notifications_read(member)
            return _redirect_month("book", p_year, p_month)

        return _redirect_month("book", p_year, p_month)

    # --- GET: Kalender + Auswahl ---
    sel_start = _parse_date(request.GET.get("start"))
    sel_end = _parse_date(request.GET.get("end"))
    if sel_start and sel_end and sel_end <= sel_start:
        sel_end = None
    cal = svc.build_booking_calendar(member, year, month, sel_start, sel_end) \
        if member else None

    eff_start = eff_end = None
    free_quarters = occ_quarters = []
    if member and sel_start:
        eff_start = sel_start
        eff_end = sel_end if sel_end else sel_start + timedelta(days=1)
        free_quarters, occ_quarters = svc.split_quarters_for_range(eff_start, eff_end)

    upcoming, past = [], []
    if member:
        for a in member.allocations.select_related("quarter").order_by("start"):
            (upcoming if a.end > today else past).append(a)
        for a in upcoming:
            a.waiters = svc.waiters_for_allocation(a)

    return render(request, "booking/book.html", {
        "member": member,
        "cal": cal,
        "today": today,
        "booking_year": today.year,
        "nights_remaining": member.nights_remaining_in_year(today.year) if member else 0,
        "nights_used": member.nights_used_in_year(today.year) if member else 0,
        "annual_budget": member.annual_night_budget if member else 0,
        "sel_start": sel_start,
        "sel_end": sel_end,
        "eff_start": eff_start,
        "eff_end": eff_end,
        "nights_selected": (eff_end - eff_start).days if eff_start and eff_end else 0,
        "free_quarters": free_quarters,
        "occ_quarters": occ_quarters,
        "upcoming": upcoming,
        "past": past,
        "notifications": svc.unread_notifications(member),
        "released_windows": BookingPeriod.objects.filter(
            status=BookingPeriod.FREE_BOOKING, end__gte=today).order_by("start"),
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
            return _redirect_month("wishlist", p_year, p_month)

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

    return render(request, "booking/wishlist.html", {
        "member": member,
        "today": today,
        "period": period,
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

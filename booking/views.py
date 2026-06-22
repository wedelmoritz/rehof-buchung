"""Views der Buchungs-App. Bewusst dünn – Logik liegt im Service-Layer."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import SpontaneousBookingForm, TransferForm, WishForm
from .models import (
    Allocation, BookingPeriod, BookingWindow, Member, NightTransfer, Quarter,
    Wish,
)
from . import services as svc


def _current_member(request) -> Member | None:
    return getattr(request.user, "member", None)


@login_required
def dashboard(request):
    member = _current_member(request)
    year = date.today().year
    context = {
        "member": member,
        "year": year,
        "nights_used": member.nights_used_in_year(year) if member else 0,
        "nights_remaining": member.nights_remaining_in_year(year) if member else 0,
        "nights_received": member.nights_received_in_year(year) if member else 0,
        "nights_given": member.nights_given_in_year(year) if member else 0,
        "allocations": (
            member.allocations.select_related("quarter").order_by("start")
            if member else []
        ),
        "open_period": BookingPeriod.objects.filter(status="open").first(),
        "released_windows": BookingWindow.objects.filter(
            active=True, end__gte=date.today(),
        ).order_by("start")[:5],
    }
    return render(request, "booking/dashboard.html", context)


@login_required
def wishlist(request):
    # Die Wunschliste ist in die Kalenderseite integriert.
    return redirect("calendar")


def _redirect_to_month(year, month):
    return redirect(f"/kalender/?year={year}&month={month}")


@login_required
def calendar(request):
    """Zentrale Mitglieder-Seite: Monatskalender mit Buchungen und Berliner
    Ferien, Stornieren, Buchen, verfügbare Tage und Wunschlisten-Editor."""
    member = _current_member(request)
    today = date.today()

    # Angezeigter Monat
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        if not (1 <= month <= 12):
            year, month = today.year, today.month
    except (TypeError, ValueError):
        year, month = today.year, today.month

    period = BookingPeriod.objects.filter(status="open").first()

    if request.method == "POST" and member:
        action = request.POST.get("action", "")
        p_year = request.POST.get("year", year)
        p_month = request.POST.get("month", month)

        if action == "book":
            form = SpontaneousBookingForm(request.POST)
            if form.is_valid():
                alloc, err = svc.book_spontaneous(
                    member, form.cleaned_data["quarter"],
                    form.cleaned_data["start"], form.cleaned_data["end"],
                )
                messages.success(request, f"Gebucht: {alloc}") if alloc \
                    else messages.error(request, err or "Buchung nicht möglich.")
            else:
                messages.error(request, "Bitte eine gültige Buchung eingeben.")
            return _redirect_to_month(p_year, p_month)

        if action == "cancel":
            ok, err = svc.cancel_allocation(member, request.POST.get("allocation_id"))
            messages.success(request, "Buchung storniert.") if ok \
                else messages.error(request, err or "Stornierung nicht möglich.")
            return _redirect_to_month(p_year, p_month)

        # --- Wunschlisten-Aktionen (nur solange Entwurf) ---
        if period:
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
                return _redirect_to_month(p_year, p_month)

            if action == "delete_wish" and not is_submitted:
                svc.delete_wish(member, period, request.POST.get("wish_id"))
                return _redirect_to_month(p_year, p_month)

            if action == "move_wish" and not is_submitted:
                svc.move_wish(member, period, request.POST.get("wish_id"),
                              request.POST.get("direction", "up"))
                return _redirect_to_month(p_year, p_month)

            if action == "reorder" and not is_submitted:
                ids = [x for x in request.POST.get("order", "").split(",") if x]
                svc.reorder_wishes(member, period, ids)
                return _redirect_to_month(p_year, p_month)

            if action == "submit_wishlist" and not is_submitted:
                n = svc.submit_wishlist(member, period)
                messages.success(
                    request, f"{n} Wunsch/Wünsche in den Lostopf eingereicht.")
                return _redirect_to_month(p_year, p_month)

            if action == "withdraw_wishlist":
                svc.withdraw_wishlist(member, period)
                messages.info(request, "Wünsche zurückgezogen – wieder bearbeitbar.")
                return _redirect_to_month(p_year, p_month)

        return _redirect_to_month(p_year, p_month)

    # --- GET: Kontext aufbauen ---
    cal = svc.build_member_calendar(member, year, month) if member else None

    booking_year = today.year
    upcoming = []
    past = []
    if member:
        for a in member.allocations.select_related("quarter").order_by("start"):
            (upcoming if a.end > today else past).append(a)

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

    return render(request, "booking/calendar.html", {
        "member": member,
        "cal": cal,
        "today": today,
        "booking_year": booking_year,
        "nights_remaining": member.nights_remaining_in_year(booking_year) if member else 0,
        "nights_used": member.nights_used_in_year(booking_year) if member else 0,
        "annual_budget": member.annual_night_budget if member else 0,
        "upcoming": upcoming,
        "past": past,
        "booking_form": SpontaneousBookingForm(),
        "wish_form": WishForm(),
        "wishes": wishes,
        "wishlist_submitted": wishlist_submitted,
        "wish_nights": wish_nights,
        "wish_budget": member.wish_night_budget if member else 0,
        "period": period,
        "released_windows": BookingWindow.objects.filter(
            active=True, end__gte=today).order_by("start"),
    })


@login_required
def transfer(request):
    """Tage an ein anderes Mitglied übertragen (innerhalb des Jahres)."""
    member = _current_member(request)
    year = date.today().year
    if not member:
        return redirect("dashboard")

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

"""Service-Layer (dashboard): Verwaltungs-Dashboard: Statistik, Reinigungs-/Buchungslisten, Exporte/Texte, Monats-Mail.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

import calendar as _calendar
from datetime import date, timedelta
from ..models import (
    Allocation, ExternalBooking, LotteryRun, Member, Quarter,
)
from .dates import WEEKDAYS_DE, month_bounds, month_label, next_month
from .notify import absolute_url, queue_email_many

__all__ = [
    '_annotate_cleaning', '_ExtRow', '_external_confirmed',
    '_month_occupancy', 'dashboard_stats', 'arrivals_in_range',
    'departures_in_range', 'BOOKING_COLUMNS', 'booking_rows',
    'CLEANING_COLUMNS', 'cleaning_rows', 'bookings_text', 'cleaning_text',
    'notify_admins_upcoming', 'users_without_membership',
    'onboard_as_member', 'onboard_as_terminal', 'deactivate_account',
]


def onboard_as_member(user, *, display_name, night_budget, wish_night_budget,
                      membership_id=None, new_label=""):
    """Geführte Zuordnung „als Mitglied": stellt das Mitglieds-Profil sicher und
    legt einen Tage-Anteil (`Share`) an einem bestehenden ODER neuen Mitglieds-
    Anteil an. Danach kann die Person buchen (taucht nicht mehr unter „Neue
    Benutzer" auf). Idempotent: ein vorhandener Share wird aktualisiert."""
    from django.db import transaction
    from ..models import Member, Membership, Share
    name = (display_name or user.get_username()).strip()
    nb, wb = int(night_budget), int(wish_night_budget)
    if nb < 0 or wb < 0:
        raise ValueError("Tage-Anteil darf nicht negativ sein.")
    with transaction.atomic():
        member, _ = Member.objects.get_or_create(
            user=user, defaults={"display_name": name})
        changed = []
        if not member.display_name:
            member.display_name = name; changed.append("display_name")
        if member.is_external:                       # vom Hofladen-Gast zum Mitglied
            member.is_external = False; changed.append("is_external")
        if changed:
            member.save(update_fields=changed)
        if membership_id:
            ms = Membership.objects.get(pk=membership_id)
        else:
            ms = Membership.objects.create(
                label=(new_label or name), annual_night_budget=50, wish_night_budget=25)
        share, created = Share.objects.get_or_create(
            membership=ms, member=member,
            defaults={"night_budget": nb, "wish_night_budget": wb})
        if not created and (share.night_budget != nb or share.wish_night_budget != wb):
            share.night_budget, share.wish_night_budget = nb, wb
            share.save(update_fields=["night_budget", "wish_night_budget"])
        return share


def onboard_as_terminal(user, *, display_name):
    """Geführte Zuordnung „nur Hofladen/Terminal": stellt ein Mitglieds-Profil als
    **Hofladen-Gast** (`is_external=True`, kein Buchungs-Mitglied) mit aktivem
    Terminal sicher. Die Person kann am Vor-Ort-Terminal auf die Monatsrechnung
    einkaufen (PIN setzt sie selbst) und taucht nicht in Losung/Mitgliedersuche/
    „Neue Benutzer" auf."""
    from ..models import Member
    name = (display_name or user.get_username()).strip()
    member, _ = Member.objects.get_or_create(
        user=user, defaults={"display_name": name})
    if not member.display_name:
        member.display_name = name
    member.is_external = True
    member.terminal_enabled = True
    member.save()
    return member


def deactivate_account(user):
    """Konto deaktivieren (Login gesperrt) – z.B. wenn die registrierte Person
    unbekannt ist. Reversibel über das Benutzer-Formular (Haken „Aktiv")."""
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


def users_without_membership():
    """Aktive Login-Konten, die **noch keinem Mitglieds-Anteil** (`Share`) zugeordnet
    sind – also die frisch registrierten Benutzer, die die Verwaltung im Backend noch
    freischalten muss (Mitglieds-Profil + Tage-Anteil). Schließt Admin-/Staff- und
    Verwaltungs-Konten (brauchen kein Profil) sowie externe Gäste aus. Erfasst sowohl
    Konten ohne Mitglieds-Profil als auch solche mit Profil, aber ohne Anteil.
    Neueste zuerst."""
    from django.contrib.auth.models import User
    from django.db.models import Count
    from ..permissions import VERWALTUNG_GROUP
    return (
        User.objects.filter(is_active=True, is_superuser=False, is_staff=False)
        .exclude(groups__name=VERWALTUNG_GROUP)
        .exclude(member__is_external=True)
        .annotate(_n_shares=Count("member__shares"))
        .filter(_n_shares=0)
        .order_by("-date_joined")
    )


def _annotate_cleaning(qs):
    """Markiert je Buchung, ob eine Endreinigung mitgebucht wurde."""
    from django.db.models import Exists, OuterRef
    from shop.models import LineItem
    sq = LineItem.objects.filter(
        allocation=OuterRef("pk"), product__counts_as_cleaning=True)
    return qs.annotate(has_cleaning=Exists(sq))


class _ExtRow:
    """Adapter, damit externe Buchungen in denselben Listen/Exports/Mails wie
    Mitglieder-Zuteilungen auftauchen (Reinigung, anstehende Buchungen)."""
    def __init__(self, b: ExternalBooking):
        from types import SimpleNamespace
        self.start, self.end, self.persons = b.start, b.end, b.persons
        self.companions = ""
        self.has_cleaning = True          # externe Buchung enthält Endreinigung
        self.quarter = b.quarter
        self.member = SimpleNamespace(display_name=f"{b.guest.name} (extern)")

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def get_source_display(self) -> str:
        return "Externer Gast"


def _external_confirmed(**flt):
    return (ExternalBooking.objects
            .filter(status=ExternalBooking.CONFIRMED, **flt)
            .select_related("quarter", "guest"))


def _month_occupancy(year: int, month: int) -> dict:
    """Auslastung eines Monats: gebuchte Unterkunfts-Nächte (Mitglieder + bestätigte
    externe Gäste) gegen die maximal möglichen (Quartiere × Tage)."""
    days = _calendar.monthrange(year, month)[1]
    m_first = date(year, month, 1)
    m_end = m_first + timedelta(days=days)
    n_quarters = Quarter.objects.count()
    possible = n_quarters * days
    booked = 0
    for a in Allocation.objects.filter(start__lt=m_end, end__gt=m_first,
                                       provisional=False):
        booked += (min(a.end, m_end) - max(a.start, m_first)).days
    for b in ExternalBooking.objects.filter(
            status=ExternalBooking.CONFIRMED, start__lt=m_end, end__gt=m_first):
        booked += (min(b.end, m_end) - max(b.start, m_first)).days
    pct = round(100 * booked / possible) if possible else 0
    return {"year": year, "month": month, "label": month_label(year, month),
            "booked": booked, "possible": possible, "pct": pct}


def dashboard_stats() -> dict:
    """Kennzahlen für die Verwaltung: Nutzer/Mitglieder, Auslastung (aktueller +
    kommender Monat) und das Ergebnis der letzten (bestätigten) Verlosung."""
    from django.contrib.auth.models import User
    today = date.today()
    ny, nm = next_month(today)
    run = (LotteryRun.objects.filter(confirmed=True).select_related("period")
           .order_by("-confirmed_at").first())
    last_lottery = None
    if run:
        last_lottery = {
            "period": run.period, "fulfilled": run.n_allocations,
            "unfulfilled": run.n_losses, "when": run.confirmed_at,
            "total": run.n_allocations + run.n_losses,
        }
    return {
        "n_users": User.objects.count(),
        "n_members": Member.objects.count(),
        "occ_current": _month_occupancy(today.year, today.month),
        "occ_next": _month_occupancy(ny, nm),
        "last_lottery": last_lottery,
    }


def arrivals_in_range(d_from: date, d_to: date):
    """Anreisen in [d_from, d_to) – Mitglieder UND externe Gäste."""
    qs = _annotate_cleaning(Allocation.objects.filter(
        start__gte=d_from, start__lt=d_to)).select_related("quarter", "member")
    rows = list(qs) + [_ExtRow(b) for b in _external_confirmed(
        start__gte=d_from, start__lt=d_to)]
    rows.sort(key=lambda a: (a.start, a.quarter.name))
    return rows


def departures_in_range(d_from: date, d_to: date):
    """Abreisen in [d_from, d_to) – Reinigungstage; Mitglieder UND externe Gäste."""
    qs = _annotate_cleaning(Allocation.objects.filter(
        end__gte=d_from, end__lt=d_to)).select_related("quarter", "member")
    rows = list(qs) + [_ExtRow(b) for b in _external_confirmed(
        end__gte=d_from, end__lt=d_to)]
    rows.sort(key=lambda a: (a.end, a.quarter.name))
    return rows


BOOKING_COLUMNS = ["Anreise", "Abreise", "Nächte", "Quartier", "Mitglied",
                   "Personen", "Begleitung", "Endreinigung", "Quelle"]


def booking_rows(allocs):
    for a in allocs:
        yield [a.start.isoformat(), a.end.isoformat(), a.nights, a.quarter.name,
               a.member.display_name, a.persons, a.companions,
               "ja" if getattr(a, "has_cleaning", False) else "nein",
               a.get_source_display()]


CLEANING_COLUMNS = ["Reinigung am", "Wochentag", "Quartier", "Mitglied",
                    "Personen", "Endreinigung gebucht"]


def cleaning_rows(deps, only_cleaning: bool = False):
    for a in deps:
        has = getattr(a, "has_cleaning", False)
        if only_cleaning and not has:
            continue
        yield [a.end.isoformat(), WEEKDAYS_DE[a.end.weekday()], a.quarter.name,
               a.member.display_name, a.persons, "ja" if has else "nein"]


def bookings_text(allocs) -> str:
    lines = []
    for a in allocs:
        clean = " · inkl. Endreinigung" if getattr(a, "has_cleaning", False) else ""
        lines.append(f"{a.start:%d.%m.}–{a.end:%d.%m.%Y}  {a.quarter.name}  "
                     f"{a.member.display_name} ({a.persons} Pers.){clean}")
    return "\n".join(lines) if lines else "— keine —"


def cleaning_text(deps, only_cleaning: bool = False) -> str:
    lines = []
    for a in deps:
        has = getattr(a, "has_cleaning", False)
        if only_cleaning and not has:
            continue
        mark = "ENDREINIGUNG" if has else "(keine Endreinigung gebucht)"
        lines.append(f"{WEEKDAYS_DE[a.end.weekday()]} {a.end:%d.%m.%Y}  "
                     f"{a.quarter.name}  – {mark}  "
                     f"({a.member.display_name}, {a.persons} Pers.)")
    return "\n".join(lines) if lines else "— keine Abreisen —"


def notify_admins_upcoming(force: bool = False) -> int:
    """Schickt der Verwaltung die Buchungen des Folgemonats. Vom Scheduler täglich
    aufgerufen; sendet idempotent nur am eingestellten Tag, einmal pro Monat.
    Gibt die Zahl der Empfänger zurück (0 = nichts gesendet)."""
    from ..models import OpsConfig
    cfg = OpsConfig.get_solo()
    today = date.today()
    if not force:
        if today.day != cfg.notify_day:
            return 0
        if (cfg.last_admin_notice and cfg.last_admin_notice.year == today.year
                and cfg.last_admin_notice.month == today.month):
            return 0
    recipients = cfg.admin_list()
    if not recipients:
        return 0
    y, m = next_month(today)
    d_from, d_to = month_bounds(y, m)
    arrivals = list(arrivals_in_range(d_from, d_to))
    deps = list(departures_in_range(d_from, d_to))
    body = (f"Anstehende Buchungen – {month_label(y, m)}\n\n"
            f"ANREISEN / AUFENTHALTE ({len(arrivals)}):\n{bookings_text(arrivals)}\n\n"
            f"REINIGUNG / ABREISEN ({len(deps)}):\n{cleaning_text(deps)}\n\n"
            f"Details im Verwaltungs-Dashboard: {absolute_url('/verwaltung/')}\n")
    queue_email_many(recipients, f"Re:Hof – Buchungen {m:02d}/{y}", body)
    cfg.last_admin_notice = today
    cfg.save(update_fields=["last_admin_notice"])
    return len(recipients)

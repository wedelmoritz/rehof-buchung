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
    '_month_occupancy', 'year_occupancy_curve',
    'dashboard_stats', 'quarter_occupancy_ampel', 'recent_booking_activity', 'karma_distribution', 'community_stats', 'arrivals_in_range',
    'departures_in_range', 'BOOKING_COLUMNS', 'booking_rows',
    'CLEANING_COLUMNS', 'cleaning_rows', 'bookings_text', 'cleaning_text',
    'notify_admins_upcoming', 'users_without_membership',
    'onboard_as_member', 'onboard_as_terminal', 'deactivate_account',
    'ensure_personal_membership', 'run_scheduled_notifications',
    'send_status_warnings', 'send_bookings_overview', 'send_occupancy_overview',
    'send_overdue_overview', 'send_lottery_reminder', 'notify_booking_activity',
    'BROADCAST_AUDIENCES', 'broadcast_message', 'role_recipients',
]

# Zielgruppen für Rundnachrichten/Export (ADR 0090). „members"-Gruppen bekommen
# In-App + Mail (Opt-in) + Push; „bl"/„admins" bekommen Mail (+ In-App, falls sie
# ein Mitglieds-Profil haben).
BROADCAST_AUDIENCES = [
    ("active_members", "Alle aktiven Mitglieder"),
    ("all_members", "Alle Mitglieder (inkl. passive)"),
    ("bl", "Alle in der Rolle Verwaltung"),
    ("admins", "Alle Admins"),
]


def _audience_members(audience):
    from ..models import Member
    qs = Member.objects.filter(is_external=False).select_related("user")
    if audience == "all_members":
        return list(qs)
    if audience == "active_members":
        return [m for m in qs if m.can_book]
    return []


def _audience_users(audience):
    from django.contrib.auth.models import User
    from django.db.models import Q
    from ..permissions import VERWALTUNG_GROUP
    if audience == "bl":
        return list(User.objects.filter(is_active=True).filter(
            Q(groups__name=VERWALTUNG_GROUP) | Q(is_superuser=True)).distinct())
    if audience == "admins":
        return list(User.objects.filter(is_active=True, is_superuser=True))
    return []


def broadcast_message(audience: str, subject: str, body: str) -> dict:
    """Rundnachricht an eine **Rolle** (ADR 0090): Mitglieder-Zielgruppen bekommen
    In-App-Benachrichtigung + E-Mail (Opt-in) + Push; „bl"/„admins" E-Mail (+ In-App,
    falls Mitglieds-Profil). Nur von Admin/Verwaltung aufzurufen (View prüft das)."""
    from ..models import Notification
    from ..validation import strip_controls
    from .notify import email_member, queue_email
    subject = strip_controls(subject, max_len=160)
    body = strip_controls(body, max_len=4000)
    n_inapp = n_mail = 0
    full_subject = f"Re:Hof: {subject}"
    if audience in ("active_members", "all_members"):
        for m in _audience_members(audience):
            # Push kommt automatisch über das Notification-post_save-Signal
            # (Betreff als Titel, Text als Inhalt) – NICHT zusätzlich hier senden,
            # sonst gäbe es zwei Push-Nachrichten je Empfänger.
            Notification.objects.create(member=m, message=subject[:255], detail=body)
            n_inapp += 1
            if email_member(m, full_subject, body):
                n_mail += 1
    else:
        for u in _audience_users(audience):
            m = getattr(u, "member", None)
            if m is not None:
                Notification.objects.create(member=m, message=subject[:255], detail=body)
                n_inapp += 1
            if (getattr(u, "email", "") or "").strip():
                queue_email(u.email, full_subject, body)
                n_mail += 1
    return {"inapp": n_inapp, "mail": n_mail}


def role_recipients(audience: str) -> list[tuple[str, str]]:
    """(Name, E-Mail) je Rolle – für den Export in externe Verteilerlisten (ADR 0090,
    Punkt 5b): die App führt die Mitgliedschaft, die Liste lebt beim Mailprovider."""
    rows: list[tuple[str, str]] = []
    if audience in ("active_members", "all_members"):
        for m in _audience_members(audience):
            email = (getattr(m.user, "email", "") or "").strip()
            if email:
                rows.append((m.display_name, email))
    else:
        for u in _audience_users(audience):
            email = (getattr(u, "email", "") or "").strip()
            if email:
                rows.append((u.get_full_name() or u.username, email))
    return rows


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


def ensure_personal_membership(member, *, night_budget=None, wish_night_budget=None):
    """Stellt sicher, dass ein **buchendes** Mitglied immer EINEN Mitglieds-Anteil
    hat. Hat ein (nicht-externes) Mitglied noch keinen Tage-Anteil (`Share`), wird
    automatisch ein **eigener Voll-Anteil** angelegt (eG-Nummer später nachtragbar,
    Standard-Budget) und der Person voll zugeordnet – so sind „Mitglied" und
    „Mitglieds-Anteil" nach dem Anlegen IMMER verknüpft, ohne Extra-Schritt.

    Ein **Tandem** (mehrere Nutzer teilen einen Anteil) entsteht bewusst dadurch,
    dass am Anteil weitere Nutzer mit ihrem Tage-Anteil ergänzt werden – nicht hier.
    **Idempotent:** hat die Person schon irgendeinen Anteil (auch als Tandem-
    Partner) oder ist sie ein Hofladen-Gast (`is_external`), passiert nichts."""
    from ..models import Membership, Share
    if member is None or member.is_external or member.shares.exists():
        return None
    # Voller Anteil = das nominale Jahresbudget (50/25). Bewusst NICHT anteilig fürs
    # Anlagejahr (anders als die editierbare Vorgabe im geführten Onboarding) – „voller
    # Anteil = 50 Tage" ist als automatische Vorgabe am verständlichsten; bei
    # unterjährigem Eintritt kann die Verwaltung den Tage-Anteil am Anteil anpassen.
    ms = Membership.objects.create(
        label=(member.display_name or member.user.get_username()),
        kind=Membership.VOLL, annual_night_budget=50, wish_night_budget=25)
    nb = ms.annual_night_budget if night_budget is None else int(night_budget)
    wb = ms.wish_night_budget if wish_night_budget is None else int(wish_night_budget)
    return Share.objects.create(
        membership=ms, member=member, night_budget=nb, wish_night_budget=wb)


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
    # Camping-/Gemeinschaftsflächen zählen nicht in die Quote (count_in_occupancy=False,
    # ADR 0096) – weder in der Kapazität noch in den gebuchten Nächten.
    n_quarters = Quarter.objects.filter(count_in_occupancy=True).count()
    possible = n_quarters * days
    booked = 0
    for a in Allocation.objects.filter(start__lt=m_end, end__gt=m_first,
                                       provisional=False,
                                       quarter__count_in_occupancy=True):
        booked += (min(a.end, m_end) - max(a.start, m_first)).days
    for b in ExternalBooking.objects.filter(
            status=ExternalBooking.CONFIRMED, start__lt=m_end, end__gt=m_first,
            quarter__count_in_occupancy=True):
        booked += (min(b.end, m_end) - max(b.start, m_first)).days
    pct = round(100 * booked / possible) if possible else 0
    return {"year": year, "month": month, "label": month_label(year, month),
            "booked": booked, "possible": possible, "pct": pct}


def recent_booking_activity(days: int = 7) -> dict:
    """„Was ist reingekommen / hat sich geändert" fürs Handlungsbedarf-Dashboard:
    zuletzt angelegte Buchungen (`Allocation.created_at`) + zuletzt stornierte
    (`CancellationLog`) der letzten `days` Tage. Wenige, mit select_related."""
    from django.utils import timezone
    from ..models import CancellationLog
    since = timezone.now() - timedelta(days=days)
    new = list(Allocation.objects.filter(created_at__gte=since, provisional=False)
               .select_related("quarter", "member").order_by("-created_at")[:12])
    cancelled = list(CancellationLog.objects.select_related("member")
                     .filter(cancelled_at__gte=since).order_by("-cancelled_at")[:12])
    return {"new": new, "cancelled": cancelled, "days": days,
            "count": len(new) + len(cancelled)}


def quarter_occupancy_ampel(year: int, month: int) -> list[dict]:
    """Auslastung **je Unterkunft** im Monat (gebuchte Nächte / Tage) + statische
    **Ampel** gegen die optionale Ziel-Auslastung `Quarter.target_occupancy`
    (#63/#64): 🟢 ab Ziel, 🟡 bis 20 Prozentpunkte darunter, 🔴 darunter; ohne Ziel
    keine Ampel. Eine Query je Quelle über den Monat, dann in Python je Quartier
    gruppiert (kein N+1)."""
    days = _calendar.monthrange(year, month)[1]
    m_first = date(year, month, 1)
    m_end = m_first + timedelta(days=days)
    # Nur Einheiten, die in die Quote zählen (Camping/Gemeinschaft ausgenommen,
    # ADR 0096) – sie haben keine sinnvolle Ziel-Ampel.
    quarters = list(Quarter.objects.filter(active=True, count_in_occupancy=True)
                    .order_by("sort_order", "name"))
    booked = {q.id: 0 for q in quarters}
    for a in Allocation.objects.filter(start__lt=m_end, end__gt=m_first,
                                       provisional=False):
        if a.quarter_id in booked:
            booked[a.quarter_id] += (min(a.end, m_end) - max(a.start, m_first)).days
    for b in ExternalBooking.objects.filter(
            status=ExternalBooking.CONFIRMED, start__lt=m_end, end__gt=m_first):
        if b.quarter_id in booked:
            booked[b.quarter_id] += (min(b.end, m_end) - max(b.start, m_first)).days
    rows = []
    for q in quarters:
        bn = booked[q.id]
        pct = round(100 * bn / days) if days else 0
        target = q.target_occupancy
        level = None
        if target:
            level = "good" if pct >= target else (
                "warn" if pct >= target - 20 else "bad")
        rows.append({"quarter": q, "booked": bn, "days": days, "pct": pct,
                     "target": target, "level": level})
    return rows


_MONTHS_DE_ABBR = ["", "Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug",
                   "Sep", "Okt", "Nov", "Dez"]


def year_occupancy_curve(year: int) -> dict:
    """Auslastung **je Monat** des Kalenderjahres `year` (Gemeinschafts-Spiegel,
    ADR 0079/0095). Liefert 12 Monatswerte für ein **reines HTML/CSS-Balkendiagramm**
    (kein SVG) – das rendert auf ALLEN Engines identisch und lesbar (Safari-Historie
    mit SVG-`<text>`: ADR 0095).

    Effizient: lädt die Belegungen des Jahres EINMAL (Mitglieder + bestätigte externe
    Gäste) und verteilt die Nächte in Python auf die Monate – **zwei** Abfragen (plus
    Quarter-Count) statt 24 Einzel-Monatsabfragen. Je Monat: `pct` (gebuchte/mögliche
    Unterkunfts-Nächte), `booked`, `possible`, `label`."""
    # Camping-/Gemeinschaftsflächen (count_in_occupancy=False, ADR 0096) zählen weder
    # in die Kapazität noch in die gebuchten Nächte.
    n_quarters = Quarter.objects.filter(count_in_occupancy=True).count()
    y_first, y_end = date(year, 1, 1), date(year + 1, 1, 1)
    days_in = [_calendar.monthrange(year, m)[1] for m in range(1, 13)]
    m_starts = [date(year, m, 1) for m in range(1, 13)]
    m_ends = [m_starts[i] + timedelta(days=days_in[i]) for i in range(12)]
    booked = [0] * 12

    def _spread(s: date, e: date) -> None:
        """Verteilt die Nächte einer Belegung [s, e) auf die berührten Monate."""
        for i in range(12):
            lo, hi = max(s, m_starts[i]), min(e, m_ends[i])
            if hi > lo:
                booked[i] += (hi - lo).days

    for s, e in Allocation.objects.filter(
            start__lt=y_end, end__gt=y_first, provisional=False,
            quarter__count_in_occupancy=True
    ).values_list("start", "end"):
        _spread(s, e)
    for s, e in ExternalBooking.objects.filter(
            status=ExternalBooking.CONFIRMED, start__lt=y_end, end__gt=y_first,
            quarter__count_in_occupancy=True
    ).values_list("start", "end"):
        _spread(s, e)

    points = []
    for i in range(12):
        possible = n_quarters * days_in[i]
        pct = round(100 * booked[i] / possible) if possible else 0
        points.append({"label": _MONTHS_DE_ABBR[i + 1], "pct": pct,
                       "booked": booked[i], "possible": possible})
    peak = max((p["pct"] for p in points), default=0)
    avg = round(sum(p["pct"] for p in points) / 12) if points else 0
    return {"year": year, "points": points, "peak": peak, "avg": avg}


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


def karma_distribution() -> dict:
    """Anonyme Verteilung der Ausgleichsfaktoren (Karma) über alle Mitglieder.

    Reine Aggregat-Ansicht (k-anonym, keine Namen) für den Gemeinschafts-Spiegel.
    Eine einzige DB-Abfrage; Buckets in 0,1-Schritten von 1,0 bis 1,5."""
    factors = list(Member.objects.filter(is_external=False)
                   .values_list("factor", flat=True))
    buckets = {round(1.0 + i * 0.1, 1): 0 for i in range(6)}   # 1.0 … 1.5
    for f in factors:
        key = round(round((min(max(f, 1.0), 1.5) - 1.0) / 0.1) * 0.1 + 1.0, 1)
        buckets[key] = buckets.get(key, 0) + 1
    total = len(factors)
    max_count = max(buckets.values()) if buckets else 0
    rows = [{"factor": k, "count": v,
             "pct": round(100 * v / total) if total else 0,
             "bar": round(100 * v / max_count) if max_count else 0}
            for k, v in sorted(buckets.items())]
    return {"rows": rows, "total": total}


def community_stats() -> dict:
    """Aggregierte, mitglieder-sichtbare Transparenz-Kennzahlen (Gemeinschafts-
    Spiegel, ADR 0063): Auslastung (aktueller + kommender Monat), Ergebnis-Historie
    der letzten Verlosungen und die anonyme Karma-Verteilung. Bewusst nur Aggregate
    (Datensparsamkeit), wenige Abfragen.

    Kurz gecacht (10 Min): die Zahlen ändern sich langsam, der Spiegel kann aber von
    vielen gleichzeitig abgerufen werden – so entlastet der Cache die DB (greift mit
    Redis workerübergreifend, mit LocMem je Worker; beides unkritisch, da nur
    ohnehin allgemein sichtbare Aggregate, ADR 0064/E2)."""
    from django.core.cache import cache
    cached = cache.get("community_stats")
    if cached is not None:
        return cached
    today = date.today()
    ny, nm = next_month(today)
    runs = list(LotteryRun.objects.filter(confirmed=True).select_related("period")
                .order_by("-confirmed_at")[:6])
    history = []
    for r in runs:
        total = r.n_allocations + r.n_losses
        history.append({
            "year": r.period.target_year,
            "fulfilled": r.n_allocations, "unfulfilled": r.n_losses,
            "total": total,
            "pct": round(100 * r.n_allocations / total) if total else 0,
        })
    stats = {
        "occ_current": _month_occupancy(today.year, today.month),
        "occ_next": _month_occupancy(ny, nm),
        "occ_curve": year_occupancy_curve(today.year),
        "lottery_history": history,
        "karma": karma_distribution(),
        "n_members": Member.objects.filter(is_external=False).count(),
    }
    cache.set("community_stats", stats, 600)   # 10 Minuten
    return stats


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


# --------------------------------------------------------------------------- #
# Benachrichtigungs-Framework: geplante (regelmäßige) Verwaltungs-Meldungen
# (ADR 0089). Ein Einstiegspunkt für den Scheduler; jede Meldung prüft ihre
# eigene Frequenz/Idempotenz über die NotificationSetting.
# --------------------------------------------------------------------------- #

def send_status_warnings(today=None) -> int:
    """Vorwarnung an die Verwaltung: Konten, bei denen in den nächsten
    `lead_days` ein Statuswechsel (passiv/ausgeschieden) greift (ADR 0087/0089).
    Läuft nur, wenn die NotificationSetting es heute vorsieht (Frequenz/Idempotenz)."""
    from django.db.models import Q
    from ..models import NotificationSetting
    from .notify import dispatch_event
    today = today or date.today()
    setting = NotificationSetting.for_event("member_status_upcoming")
    if not setting.due_today(today):
        return 0
    horizon = today + timedelta(days=setting.lead_days)
    rows: list[str] = []
    for m in (Member.objects.select_related("user").filter(
            Q(passive_from__gte=today, passive_from__lte=horizon)
            | Q(excluded_from__gte=today, excluded_from__lte=horizon))
            .order_by("display_name")):
        if m.passive_from and today <= m.passive_from <= horizon:
            rows.append(f"- {m.display_name}: passiv ab {m.passive_from:%d.%m.%Y}")
        if m.excluded_from and today <= m.excluded_from <= horizon:
            rows.append(f"- {m.display_name}: ausgeschieden ab {m.excluded_from:%d.%m.%Y}")
    if rows:
        dispatch_event("member_status_upcoming",
                       {"lead_days": setting.lead_days, "list": "\n".join(rows)})
    setting.last_run_on = today
    setting.save(update_fields=["last_run_on"])
    return len(rows)


def send_bookings_overview(today=None) -> int:
    """Regelmäßige Buchungsübersicht (An-/Abreisen inkl. Endreinigungen) an die
    Verwaltung – mit **Plan-PDF** als Anhang, sofern WeasyPrint verfügbar (ADR 0089/
    B3). Fasst den aktuellen + kommenden Monat zusammen."""
    from ..models import NotificationSetting
    from .notify import dispatch_event
    today = today or date.today()
    setting = NotificationSetting.for_event("bookings_overview")
    if not setting.due_today(today):
        return 0
    m_from, _ = month_bounds(today.year, today.month)
    ny, nm = next_month(today)
    _, m_to = month_bounds(ny, nm)
    allocs = list(arrivals_in_range(m_from, m_to))
    body = bookings_text(allocs)
    pdf, name = None, ""
    if setting.attach_pdf:
        try:
            from .. import plan_pdf as pp
            if pp.weasyprint_available():
                pdf = pp.plan_pdf_bytes(today, 28, management=True)
                name = f"belegungsplan-{today:%Y-%m-%d}.pdf"
        except Exception:      # PDF ist Kür – Mail geht auch ohne
            pdf, name = None, ""
    dispatch_event("bookings_overview",
                   {"month": f"{today.month:02d}–{nm:02d}/{today.year}", "body": body},
                   attachment=pdf, attachment_name=name)
    setting.last_run_on = today
    setting.save(update_fields=["last_run_on"])
    return len(allocs)


def send_occupancy_overview(today=None) -> int:
    """Regelmäßige Auslastungs-Übersicht je Unterkunft (mit Ziel-Ampel) an die
    Verwaltung (ADR 0089/B3)."""
    from ..models import NotificationSetting
    from .notify import dispatch_event
    today = today or date.today()
    setting = NotificationSetting.for_event("occupancy_overview")
    if not setting.due_today(today):
        return 0
    rows = quarter_occupancy_ampel(today.year, today.month)
    amp = {"good": "🟢", "warn": "🟡", "bad": "🔴"}
    lines = [f"- {r['quarter'].name}: {r['booked']}/{r['days']} Nächte "
             f"({r['pct']} %) {amp.get(r['level'], '')}"
             + (f" · Ziel {r['target']} %" if r.get("target") else "")
             for r in rows]
    dispatch_event("occupancy_overview",
                   {"month": month_label(today.year, today.month),
                    "body": "\n".join(lines) or "—"})
    setting.last_run_on = today
    setting.save(update_fields=["last_run_on"])
    return len(rows)


def send_overdue_overview(today=None) -> int:
    """Regelmäßige Übersicht überfälliger Rechnungen an die Verwaltung (ADR 0089/B3)."""
    from ..models import NotificationSetting
    from .notify import dispatch_event
    from shop import services as shop_svc
    today = today or date.today()
    setting = NotificationSetting.for_event("overdue_overview")
    if not setting.due_today(today):
        return 0
    overdue = list(shop_svc.overdue_invoices().order_by("due_date", "number"))
    lines = [f"- {i.number}: {i.recipient_label} · {i.total_gross} € · fällig "
             f"{i.due_date:%d.%m.%Y}" for i in overdue]
    dispatch_event("overdue_overview", {"body": "\n".join(lines) or "keine 🎉"})
    setting.last_run_on = today
    setting.save(update_fields=["last_run_on"])
    return len(overdue)


def send_lottery_reminder(today=None) -> int:
    """Erinnert die Verwaltung, wenn eine Losung in ≤ `lead_days` ansteht – einmal je
    Periode (ADR 0089/B3)."""
    from ..models import BookingPeriod, NotificationSetting
    from .notify import dispatch_event
    today = today or date.today()
    setting = NotificationSetting.for_event("lottery_reminder")
    if not setting.enabled:
        return 0
    horizon = today + timedelta(days=setting.lead_days)
    n = 0
    for p in BookingPeriod.objects.filter(
            draw_at__isnull=False, draw_at__date__gte=today,
            draw_at__date__lte=horizon, bl_reminder_at__isnull=True):
        draw_d = p.draw_at.date()
        dispatch_event("lottery_reminder", {
            "period": str(p), "lead_days": (draw_d - today).days,
            "draw": f"{draw_d:%d.%m.%Y}"})
        p.bl_reminder_at = today
        p.save(update_fields=["bl_reminder_at"])
        n += 1
    return n


def notify_booking_activity(alloc, *, action: str) -> None:
    """Sofort-Meldung mit Dringlichkeit an die Verwaltung bei **kurzfristigen**
    Buchungen/Stornos (Anreise ≤ short_notice_days, ADR 0089/B3). Länger entfernte
    Vorgänge landen im wöchentlichen Digest (send_bookings_overview)."""
    from .booking_ops import is_short_notice
    from .notify import dispatch_event
    if not is_short_notice(alloc.start):
        return
    verb = {"new": "Neue Buchung", "cancel": "Stornierung"}.get(action, action)
    what = (f"{verb}: {alloc.quarter.name if alloc.quarter_id else '—'} "
            f"{alloc.start:%d.%m.}–{alloc.end:%d.%m.} · {alloc.member.display_name}")
    detail = (f"{alloc.persons} Pers. · Quelle {alloc.get_source_display()}"
              if action == "new" else "Zeitraum wird wieder frei.")
    dispatch_event("booking_activity_urgent", {"what": what, "detail": detail})


def run_scheduled_notifications(today=None) -> dict:
    """Zentraler Scheduler-Einstiegspunkt für die geplanten Benachrichtigungen
    (ADR 0089). Erweiterbar: neue geplante Meldung = neue Zeile hier. Gibt je
    Meldung die Anzahl der betroffenen Einträge zurück."""
    today = today or date.today()
    return {
        "status_warnings": send_status_warnings(today),
        "bookings_overview": send_bookings_overview(today),
        "occupancy_overview": send_occupancy_overview(today),
        "overdue_overview": send_overdue_overview(today),
        "lottery_reminder": send_lottery_reminder(today),
    }

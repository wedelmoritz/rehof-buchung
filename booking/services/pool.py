"""Service-Layer (pool): Solidaritäts-/Schenkungs-Pool für Tage (P2.5, ADR 0064).

Mitglieder spenden ungenutzte Tage in einen gemeinsamen Topf; wer (fast) kein
Budget mehr hat, kann daraus **gedeckelt** und **bei Bedarf** entnehmen. Spenden/
Entnahmen wirken über `Member.effective_annual_budget`; ein Eintrag je Vorgang
(transparentes Protokoll).

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from ..models import DayPoolEntry, Member

__all__ = [
    'POOL_ELIGIBLE_REMAINING', 'POOL_WITHDRAW_CAP_PER_YEAR',
    'pool_balance', 'pool_status', 'pool_donate', 'pool_withdraw',
]

# Fairness-Parameter – **Defaults**; die tatsächlichen Werte kommen aus dem Backend
# (`BookingPolicy`, ADR 0099), damit die Genossenschaft sie ohne Code-Änderung tunen
# kann. Entnahme nur, wenn das eigene Jahresbudget (fast) aufgebraucht ist …
POOL_ELIGIBLE_REMAINING = 5
# … und gedeckelt auf so viele Tage je Mitglied und Jahr.
POOL_WITHDRAW_CAP_PER_YEAR = 10

_MONTHS_DE = ("", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
              "August", "September", "Oktober", "November", "Dezember")


def _pool_policy():
    """Die (backend-konfigurierbaren) Pool-Parameter (ADR 0099): (Entnahme-Schwelle,
    Jahres-Deckel, Entnahme-ab-Monat)."""
    from ..models import BookingPolicy
    p = BookingPolicy.get_solo()
    return (p.pool_eligible_remaining, p.pool_withdraw_cap,
            p.pool_withdraw_from_month)


def pool_balance(year: int) -> int:
    """Aktueller Topf-Stand eines Jahres = Σ Spenden − Σ Entnahmen."""
    agg = DayPoolEntry.objects.filter(year=year).values("kind").annotate(s=Sum("nights"))
    by = {row["kind"]: row["s"] or 0 for row in agg}
    return by.get(DayPoolEntry.DONATE, 0) - by.get(DayPoolEntry.WITHDRAW, 0)


def _lock_pool_year(year: int) -> None:
    """Serialisiert gleichzeitige Pool-Vorgänge eines Jahres (Nebenläufigkeit,
    S1/ADR 0064): sperrt die vorhandenen Jahres-Zeilen mit SELECT … FOR UPDATE.
    Muss INNERHALB einer Transaktion laufen. Auf Postgres greift die Sperre; auf
    SQLite (Tests/Dev) ist sie ein No-Op – dort gibt es ohnehin keine echte
    Parallelität. Eine Entnahme setzt einen positiven Stand (also vorhandene
    Spenden-Zeilen) voraus, daher werden konkurrierende Entnahmen zuverlässig
    serialisiert."""
    list(DayPoolEntry.objects.select_for_update().filter(year=year))


def pool_status(member: Member, year: int) -> dict:
    """Topf-Stand + was DIESES Mitglied tun darf (für die UI; rein lesend)."""
    from datetime import date
    threshold, cap, from_month = _pool_policy()
    remaining = member.nights_remaining_in_year(year)
    withdrawn = member.pool_received_in_year(year)
    cap_left = max(0, cap - withdrawn)
    balance = pool_balance(year)
    time_ok = (from_month == 0) or (date.today().month >= from_month)
    # Passive/ausgeschiedene Mitglieder dürfen SPENDEN, aber nicht ENTNEHMEN (ADR 0099).
    active = member.can_book
    eligible = active and remaining <= threshold and time_ok
    return {
        "balance": balance,
        "remaining": remaining,
        "member_active": active,
        "can_donate": remaining > 0,
        "max_donate": max(0, remaining),
        "eligible_to_withdraw": eligible,
        "need_ok": remaining <= threshold,
        "time_ok": time_ok,
        "withdraw_from_month": from_month,
        "withdraw_from_month_name": _MONTHS_DE[from_month] if from_month else "",
        "cap_left": cap_left,
        "max_withdraw": min(balance, cap_left) if eligible else 0,
        "donated": member.pool_donated_in_year(year),
        "withdrawn": withdrawn,
        "eligible_remaining_threshold": threshold,
        "cap": cap,
    }


@transaction.atomic
def pool_donate(member: Member, nights: int, year: int, note: str = "") -> tuple[DayPoolEntry | None, str | None]:
    """Spendet `nights` Tage in den Pool. Man kann nur spenden, was man noch hat."""
    try:
        nights = int(nights)
    except (TypeError, ValueError):
        return None, "Bitte eine gültige Tagezahl angeben."
    if nights <= 0:
        return None, "Die Anzahl der Tage muss positiv sein."
    _lock_pool_year(year)   # gegen gleichzeitige Pool-Vorgänge serialisieren
    remaining = member.nights_remaining_in_year(year)
    if nights > remaining:
        return None, f"Du hast nur noch {remaining} Tage – so viele kannst du nicht spenden."
    entry = DayPoolEntry.objects.create(
        year=year, member=member, kind=DayPoolEntry.DONATE, nights=nights,
        note=(note or "")[:200])
    return entry, None


@transaction.atomic
def pool_withdraw(member: Member, nights: int, year: int, note: str = "") -> tuple[DayPoolEntry | None, str | None]:
    """Entnimmt `nights` Tage aus dem Pool – nur bei Bedarf und gedeckelt."""
    try:
        nights = int(nights)
    except (TypeError, ValueError):
        return None, "Bitte eine gültige Tagezahl angeben."
    if nights <= 0:
        return None, "Die Anzahl der Tage muss positiv sein."
    from datetime import date
    threshold, cap, from_month = _pool_policy()
    # Passive/ausgeschiedene Mitglieder dürfen spenden, aber NICHT entnehmen (ADR 0099).
    if not member.can_book:
        return None, ("Als passives Mitglied kannst du in den Pool spenden, aber nicht "
                      "daraus entnehmen.")
    _lock_pool_year(year)   # gegen gleichzeitige Entnahmen serialisieren (S1)
    # Zeit-Riegel (ADR 0099): erst ab konfiguriertem Monat entnehmbar – entschärft
    # „Budget früh verbrauchen, dann nachladen".
    if from_month and date.today().month < from_month:
        return None, (f"Entnahmen aus dem Pool sind erst ab {_MONTHS_DE[from_month]} "
                      f"möglich (damit zuerst klar ist, wer bis dahin wirklich zu "
                      f"wenig hat).")
    remaining = member.nights_remaining_in_year(year)
    if remaining > threshold:
        return None, (f"Eine Entnahme ist nur möglich, wenn dein Jahresbudget fast "
                      f"aufgebraucht ist (höchstens {threshold} Tage übrig).")
    cap_left = cap - member.pool_received_in_year(year)
    if nights > cap_left:
        return None, (f"Pro Jahr sind höchstens {cap} Tage aus dem Pool möglich – "
                      f"du kannst noch {max(0, cap_left)} entnehmen.")
    balance = pool_balance(year)
    if nights > balance:
        return None, f"Im Pool sind nur {balance} Tage – so viele gibt es gerade nicht."
    entry = DayPoolEntry.objects.create(
        year=year, member=member, kind=DayPoolEntry.WITHDRAW, nights=nights,
        note=(note or "")[:200])
    return entry, None

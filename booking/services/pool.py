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

# Fairness-Parameter (bewusst einfach gehalten, im Code dokumentiert/änderbar):
# Entnahme nur, wenn das eigene Jahresbudget (fast) aufgebraucht ist …
POOL_ELIGIBLE_REMAINING = 5
# … und gedeckelt auf so viele Tage je Mitglied und Jahr.
POOL_WITHDRAW_CAP_PER_YEAR = 10


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
    remaining = member.nights_remaining_in_year(year)
    withdrawn = member.pool_received_in_year(year)
    cap_left = max(0, POOL_WITHDRAW_CAP_PER_YEAR - withdrawn)
    balance = pool_balance(year)
    eligible = remaining <= POOL_ELIGIBLE_REMAINING
    return {
        "balance": balance,
        "remaining": remaining,
        "can_donate": remaining > 0,
        "max_donate": max(0, remaining),
        "eligible_to_withdraw": eligible,
        "cap_left": cap_left,
        "max_withdraw": min(balance, cap_left),
        "donated": member.pool_donated_in_year(year),
        "withdrawn": withdrawn,
        "eligible_remaining_threshold": POOL_ELIGIBLE_REMAINING,
        "cap": POOL_WITHDRAW_CAP_PER_YEAR,
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
    _lock_pool_year(year)   # gegen gleichzeitige Entnahmen serialisieren (S1)
    remaining = member.nights_remaining_in_year(year)
    if remaining > POOL_ELIGIBLE_REMAINING:
        return None, (f"Eine Entnahme ist nur möglich, wenn dein Jahresbudget fast "
                      f"aufgebraucht ist (höchstens {POOL_ELIGIBLE_REMAINING} Tage übrig).")
    cap_left = POOL_WITHDRAW_CAP_PER_YEAR - member.pool_received_in_year(year)
    if nights > cap_left:
        return None, (f"Pro Jahr sind höchstens {POOL_WITHDRAW_CAP_PER_YEAR} Tage aus dem "
                      f"Pool möglich – du kannst noch {max(0, cap_left)} entnehmen.")
    balance = pool_balance(year)
    if nights > balance:
        return None, f"Im Pool sind nur {balance} Tage – so viele gibt es gerade nicht."
    entry = DayPoolEntry.objects.create(
        year=year, member=member, kind=DayPoolEntry.WITHDRAW, nights=nights,
        note=(note or "")[:200])
    return entry, None

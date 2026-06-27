"""Service-Layer (terminal_ops): Hofladen-Terminal vor Ort (ADR 0053).

Das Terminal authentifiziert sich gegenüber dem Server NUR mit dem Geräte-**Token**
(kein Mitglieder-Login, keine Django-Sitzung). Es darf ausschließlich:
  * die Roster (freigeschaltete Mitglieder + PIN-Hash) und den Katalog laden,
  * offline erfasste Einkäufe auf die jeweilige **Monatsrechnung** nachreichen.
Mehr ist über die Token-Endpunkte nicht erreichbar – keine Profil-/Rechnungs-/
Zahlungs-/Backend-Daten. Die PIN-Prüfung passiert offline im Gerät gegen den
mitgelieferten Django-PBKDF2-Hash (Web Crypto). Siehe ADR 0053 für das Bedrohungs-
modell.
"""
from __future__ import annotations

import hmac

from ..models import Member, TerminalConfig

__all__ = [
    "terminal_token_ok", "terminal_payload", "terminal_record",
]


def terminal_token_ok(token: str) -> bool:
    """Konstantzeit-Vergleich gegen das konfigurierte Token; nur wenn aktiv."""
    cfg = TerminalConfig.get_solo()
    if not cfg.enabled or not cfg.token:
        return False
    return hmac.compare_digest(str(token or ""), cfg.token)


def _roster() -> list[dict]:
    """Minimaldaten der terminalfähigen Konten: Benutzername, Anzeigename, PIN-Hash.
    BEWUSST KEINE PII (Adresse/IBAN/Rechnungen) – das Gerät ist geteilt/offline."""
    out = []
    qs = (Member.objects.filter(terminal_enabled=True)
          .exclude(terminal_pin="").select_related("user")
          .order_by("display_name"))
    for m in qs:
        if not m.user_id:
            continue
        out.append({"u": m.user.username, "n": m.display_name, "p": m.terminal_pin})
    return out


def _catalog() -> list[dict]:
    from shop.models import Product
    out = []
    for p in (Product.objects.filter(active=True)
              .select_related("group").order_by("group__sort_order", "name")):
        out.append({
            "id": p.id, "name": p.name, "unit": p.unit or "",
            "price": str(p.price),
            "group": p.group.name if p.group_id else "",
            "emoji": (p.group.emoji if p.group_id else "") or "",
        })
    return out


def terminal_payload() -> dict:
    """Alles, was das Gerät zum Offline-Betrieb braucht (Token bereits geprüft)."""
    cfg = TerminalConfig.get_solo()
    return {
        "ok": True,
        "config": {"idle": cfg.idle_timeout_seconds,
                   "max_attempts": cfg.max_pin_attempts},
        "roster": _roster(),
        "products": _catalog(),
    }


def terminal_record(username: str, item_pairs: list[tuple[int, int]], ref: str
                    ) -> tuple[bool, str | None]:
    """Bucht einen am Terminal erfassten Einkauf idempotent auf die Monatsrechnung
    des Mitglieds. `item_pairs` = [(product_id, quantity), …]. `ref` ist die client-
    seitig erzeugte ID (verhindert Doppelbuchung beim Nachsyncen)."""
    from decimal import Decimal
    from django.db import transaction
    from shop.models import LineItem, Product, Purchase

    ref = (ref or "").strip()[:64]
    if not ref:
        return False, "ref fehlt"
    member = (Member.objects.filter(user__username=username, terminal_enabled=True)
              .exclude(terminal_pin="").select_related("user").first())
    if not member:
        return False, "Mitglied nicht (mehr) terminalfähig"
    with transaction.atomic():
        # Idempotenz: gibt es den Einkauf schon, nichts tun (erfolgreich).
        if Purchase.objects.filter(terminal_ref=ref).exists():
            return True, None
        clean = []
        for pid, qty in item_pairs:
            try:
                q = int(qty)
            except (TypeError, ValueError):
                continue
            if q <= 0:
                continue
            p = Product.objects.filter(id=pid, active=True).first()
            if p:
                clean.append((p, q))
        if not clean:
            return False, "keine gültigen Positionen"
        purchase = Purchase.objects.create(member=member, terminal_ref=ref)
        for p, q in clean:
            LineItem.objects.create(
                member=member, product=p, name=p.name, unit=p.unit,
                unit_price=p.price, vat_rate=p.vat_rate, quantity=Decimal(q),
                purchase=purchase)
    return True, None

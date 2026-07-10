"""Stellt die Rollen-Flags `is_admin`/`is_verwaltung` und die freigeschalteten
Verwaltungs-Capabilities (`verw_caps`) allen Templates bereit – für die
**rollengefilterte** Navigation und bedingte Anzeige (ADR 0100)."""
from . import authz
from .permissions import is_admin, is_verwaltung


def roles(request):
    user = getattr(request, "user", None)
    member = getattr(user, "member", None) if user is not None else None
    # Mitgliedsstatus für die rollen-reine Navigation (ADR 0087): passive Mitglieder
    # sehen keine Buchungs-Punkte; „Meine Buchungen"/„Übersicht" nur mit Buchungen.
    can_book = bool(member and member.can_book)
    is_passive = bool(member and member.is_passive)
    member_has_bookings = bool(member and (can_book or member.has_bookings))
    return {
        "is_admin": is_admin(user), "is_verwaltung": is_verwaltung(user),
        # Datengetriebene, rollengefilterte Verwaltungs-Nav: nur erlaubte Seiten.
        "verw_caps": authz.allowed_capabilities(user) if user is not None else [],
        "can_book": can_book, "is_passive": is_passive,
        "member_has_bookings": member_has_bookings,
    }


def legal(request):
    """Fußzeilen-Daten (Impressum/Datenschutz/AGB/Kontakt) für alle Seiten. Das
    Impressum ist Pflicht und immer verlinkt; Datenschutz/AGB nur, wenn gepflegt."""
    try:
        from shop.models import ShopConfig
        cfg = ShopConfig.get_solo()
        return {"footer": {
            "coop_name": cfg.coop_name,
            "contact_email": cfg.contact_email,
            "has_privacy": bool((cfg.privacy_policy or "").strip()),
            "has_terms": bool((cfg.terms_agb or "").strip()),
        }}
    except Exception:  # noqa: BLE001 – Fußzeile darf das Rendern nie kippen
        return {"footer": {}}


def push(request):
    """Web-Push-Status für alle Templates: der öffentliche VAPID-Schlüssel (für
    `pushManager.subscribe`) und ob Push überhaupt konfiguriert ist."""
    from django.conf import settings
    return {
        "push_enabled": settings.PUSH_ENABLED,
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
    }

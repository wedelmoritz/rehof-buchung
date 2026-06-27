"""Stellt die Rollen-Flags `is_admin`/`is_verwaltung` allen Templates bereit
(für Navigation und bedingte Anzeige)."""
from .permissions import is_admin, is_verwaltung


def roles(request):
    user = getattr(request, "user", None)
    return {"is_admin": is_admin(user), "is_verwaltung": is_verwaltung(user)}


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

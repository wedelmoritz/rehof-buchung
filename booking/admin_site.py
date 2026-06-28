"""Fachliche Gliederung des Backends (Django-Admin) in Sektionen.

Statt der technischen App-Gruppierung (booking / shop / auth / axes) zeigt das
Backend fünf fachliche Sektionen – auf der Startseite UND in der Seitenleiste.
Die Modelle bleiben dort registriert, wo sie sind; nur ihre *Darstellung* wird
über `get_app_list` umsortiert (Modell-Listen/Formulare laufen unverändert über
ihre echten URLs). Siehe ADR 0049.
"""
from __future__ import annotations

from django.contrib import admin

# Reihenfolge der Sektionen + der Modelle darin (Schlüssel: "app_label.ModelName").
# Nicht eingeplante Modelle landen als Sicherheitsnetz unter „Weitere".
SECTIONS: list[tuple[str, list[str]]] = [
    ("Benutzer & Mitglieder", [
        "booking.PendingUser",                       # Onboarding-Seite zuerst (ADR 0056)
        "auth.User", "auth.Group",
        "booking.Membership", "booking.NightTransfer",
    ]),
    ("Quartiere & Buchungssystem", [
        "booking.Quarter", "booking.EquivalenceClass", "booking.BookingPolicy",
        "booking.Allocation", "booking.UpcomingAllocation",
        "booking.WaitlistEntry", "booking.SwapRequest",
        # Externe Gäste buchen ebenfalls Quartiere (inkl. ihrer Rechnungen):
        "booking.Guest", "booking.ExternalBooking", "shop.ExternalInvoice",
        "booking.ExternalConfig",
    ]),
    ("Losverfahren", [
        "booking.BookingPeriod", "booking.Wish", "booking.LotteryRun",
        "booking.FairnessSimConfig",
    ]),
    ("Hofladen", [
        "shop.ProductGroup", "shop.Product", "shop.Purchase", "shop.LineItem",
        "shop.Invoice", "shop.Payment",
        "shop.BankImport", "shop.BankTransaction",
    ]),
    ("Administratives & Logs", [
        # Übergreifende Einstellungen (gelten für Hofladen UND externe Gäste):
        "shop.ShopConfig", "booking.OpsConfig", "booking.TerminalConfig",
        "booking.Notification", "booking.OutboxEmail", "booking.Beds24Import",
        "axes.AccessAttempt", "axes.AccessLog", "axes.AccessFailureLog",
    ]),
]


class RehofAdminSite(admin.AdminSite):
    """Admin-Site mit fachlicher Sektions-Gliederung (site_header/index_template
    werden weiterhin in booking/admin.py gesetzt)."""

    # Statt der eingebauten linken Seitenleiste rendern wir EINEN persistenten
    # Navigator (Suche + Bereiche) oben auf jeder Seite (templates/admin/
    # _rehof_navigator.html via base_site.html). Die eingebaute Leiste würde nur
    # doppeln, daher aus (ADR 0055).
    enable_nav_sidebar = False

    def each_context(self, request):
        """Zähler offener „Neue Benutzer" für das Badge am Navigator-Eintrag (auf
        jeder Seite). Günstige COUNT-Abfrage; nur für eingeloggte Staff-Sicht."""
        ctx = super().each_context(request)
        try:
            from . import services as svc
            ctx["pending_user_count"] = svc.users_without_membership().count()
        except Exception:
            ctx["pending_user_count"] = 0
        return ctx

    def index(self, request, extra_context=None):
        """Backend-Startseite um den Abschnitt „Neue Benutzer“ ergänzen: Konten, die
        noch keinem Mitglieds-Anteil zugeordnet sind und freigeschaltet werden
        müssen (so sieht die Verwaltung sie sofort und kann sie schnell zuordnen)."""
        extra_context = extra_context or {}
        from . import services as svc
        pending = list(svc.users_without_membership()[:50])
        extra_context["new_users"] = pending
        extra_context["new_users_count"] = len(pending)
        return super().index(request, extra_context)

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        # Bei App-spezifischer Ansicht (/admin/<app>/) das Standardverhalten lassen.
        if app_label is not None:
            return app_list

        # Alle (berechtigten) Modelle nach "app_label.ModelName" indexieren.
        by_key: dict[str, dict] = {}
        for app in app_list:
            for m in app["models"]:
                model = m.get("model")
                if model is not None:
                    by_key[f"{model._meta.app_label}.{model.__name__}"] = m

        sections, used = [], set()
        for title, keys in SECTIONS:
            models = [by_key[k] for k in keys if k in by_key]
            if not models:
                continue
            used.update(keys)
            sections.append({
                "name": title,
                "app_label": "sec_" + title.split()[0].lower(),
                "app_url": "",
                "has_module_perms": True,
                "models": models,
            })
        # Sicherheitsnetz: nie etwas „verschwinden" lassen (z.B. neu registriert).
        rest = [m for k, m in by_key.items() if k not in used]
        if rest:
            sections.append({
                "name": "Weitere", "app_label": "sec_weitere", "app_url": "",
                "has_module_perms": True, "models": rest,
            })
        return sections

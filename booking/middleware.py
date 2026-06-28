"""Freischaltungs-Sperre.

Selbst registrierte Nutzer können sich anmelden, sehen aber NICHTS, bis die
Verwaltung sie einem Mitglied zugeordnet hat (= ein `Member`-Profil existiert).
Bis dahin werden sie auf die Warte-Seite umgeleitet. Verwaltungs-/Superuser sind
ausgenommen (sie verwalten, brauchen kein Buchungs-Profil).
"""
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse


# Sparsame, restriktive Permissions-Policy: mächtige Browser-Funktionen aus, die
# die App nicht nutzt (Kamera/Mikro/Geolocation/USB/Bezahl-API; FLoC abwählen).
_PERMISSIONS_POLICY = (
    "geolocation=(), camera=(), microphone=(), usb=(), magnetometer=(), "
    "gyroscope=(), accelerometer=(), payment=(), interest-cohort=()"
)


class SecurityHeadersMiddleware:
    """Ergänzt Sicherheits-Header, die Django nicht von Haus aus setzt
    (ADR 0061, P3.11): Permissions-Policy global; Cross-Origin-Resource-Policy
    `same-origin`, AUSSER für das bewusst fremd-einbettbare Externen-Widget –
    dort setzt die View den Wert selbst auf `cross-origin`. (Cross-Origin-Opener-
    Policy setzt Djangos SecurityMiddleware bereits auf `same-origin`.)"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", _PERMISSIONS_POLICY)
        if "Cross-Origin-Resource-Policy" not in response:
            response["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


class ActivationGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .permissions import is_verwaltung
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated
                and not is_verwaltung(user)
                and not hasattr(user, "member")):
            allowed = {reverse("pending"), reverse("logout"),
                       reverse("offline"), reverse("sw"), reverse("healthz"),
                       reverse("imprint"), reverse("privacy"), reverse("terms")}
            path = request.path
            if path not in allowed and not path.startswith("/static/"):
                return redirect("pending")
        return self.get_response(request)

"""Freischaltungs-Sperre.

Selbst registrierte Nutzer können sich anmelden, sehen aber NICHTS, bis die
Verwaltung sie einem Mitglied zugeordnet hat (= ein `Member`-Profil existiert).
Bis dahin werden sie auf die Warte-Seite umgeleitet. Verwaltungs-/Superuser sind
ausgenommen (sie verwalten, brauchen kein Buchungs-Profil).
"""
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse


class ActivationGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated
                and not user.is_staff and not user.is_superuser
                and not hasattr(user, "member")):
            allowed = {reverse("pending"), reverse("logout"),
                       reverse("offline"), reverse("sw")}
            path = request.path
            if path not in allowed and not path.startswith("/static/"):
                return redirect("pending")
        return self.get_response(request)

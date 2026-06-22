"""Authentifizierungs-Backend: Login per E-Mail ODER Benutzername.

Bewusst klein gehalten – baut auf Djangos ModelBackend auf (sauberes Hashing,
`user_can_authenticate`-Prüfung). Der Brute-Force-Schutz kommt von django-axes
(separates Backend, siehe settings.AUTHENTICATION_BACKENDS).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """Erlaubt die Anmeldung mit Benutzername oder E-Mail (case-insensitive)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = User.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username))
        except User.DoesNotExist:
            # Gleicher Rechenaufwand wie bei existierendem Nutzer (gegen Timing).
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # Mehrdeutig (z.B. E-Mail = fremder Benutzername) → nicht anmelden.
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

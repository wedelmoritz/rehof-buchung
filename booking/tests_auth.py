"""Tests rund um Authentifizierung, Selbstregistrierung und Freischaltung."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking.models import Member

PW = "Korbflechter7x"


class RegistrierungUndFreischaltungTests(TestCase):
    def test_registrierung_legt_konto_ohne_profil_an(self):
        resp = self.client.post(reverse("register"), {
            "email": "neu@example.org", "name": "Neu Mitglied",
            "password1": PW, "password2": PW,
        })
        self.assertRedirects(resp, reverse("pending"))
        user = User.objects.get(email="neu@example.org")
        self.assertEqual(user.username, "neu@example.org")  # E-Mail = Benutzername
        self.assertFalse(user.is_staff)
        self.assertFalse(hasattr(user, "member"))  # noch kein Buchungs-Profil

    def test_konto_ohne_profil_sieht_nichts(self):
        user = User.objects.create_user("warte", "warte@example.org", PW)
        self.client.force_login(user)
        # Übersicht ist gesperrt → Umleitung auf die Warte-Seite
        self.assertRedirects(self.client.get(reverse("overview")), reverse("pending"))
        self.assertRedirects(self.client.get(reverse("wishlist")), reverse("pending"))
        # Nach Zuordnung eines Mitglieds-Profils ist alles erreichbar
        Member.objects.create(user=user, display_name="Warte")
        self.assertEqual(self.client.get(reverse("overview")).status_code, 200)

    def test_doppelte_email_wird_abgelehnt(self):
        User.objects.create_user("a@example.org", "a@example.org", PW)
        resp = self.client.post(reverse("register"), {
            "email": "a@example.org", "name": "Zwei",
            "password1": PW, "password2": PW,
        })
        self.assertEqual(resp.status_code, 200)  # Formular mit Fehler
        self.assertEqual(User.objects.filter(email="a@example.org").count(), 1)


class LoginTests(TestCase):
    def test_login_per_email_und_benutzername(self):
        user = User.objects.create_user("hans", "hans@example.org", PW)
        Member.objects.create(user=user, display_name="Hans")
        # per E-Mail
        ok = self.client.post(reverse("login"),
                              {"username": "hans@example.org", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        # per Benutzername
        self.client.post(reverse("login"), {"username": "hans", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)

    def test_losdurchlauf_kann_nicht_manuell_angelegt_werden(self):
        """Regression: das manuelle Anlegen schlug mit 500 fehl (Pflicht-Seed
        nicht setzbar). Die Add-Ansicht ist jetzt gesperrt."""
        su = User.objects.create_superuser("root", "root@example.org", PW)
        self.client.force_login(su)
        resp = self.client.get("/admin/booking/lotteryrun/add/")
        self.assertEqual(resp.status_code, 403)

    def test_brute_force_sperrt_auch_korrektes_passwort(self):
        user = User.objects.create_user("opfer", "opfer@example.org", PW)
        Member.objects.create(user=user, display_name="Opfer")
        for _ in range(5):
            self.client.post(reverse("login"),
                             {"username": "opfer", "password": "falsch-falsch"})
        # Auch mit korrektem Passwort jetzt gesperrt (django-axes)
        self.client.post(reverse("login"), {"username": "opfer", "password": PW})
        self.assertNotIn("_auth_user_id", self.client.session)

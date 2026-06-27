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

    def test_unplausibler_name_wird_abgelehnt(self):
        # Name mit Ziffern/Markup -> Formularfehler, kein Konto.
        resp = self.client.post(reverse("register"), {
            "email": "neu2@example.org", "name": "<b>Hack3r",
            "password1": PW, "password2": PW,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="neu2@example.org").exists())


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


class ProfilAnmeldedatenTests(TestCase):
    """Mitglied ändert E-Mail (= Login) und Passwort selbst im Profil."""

    def setUp(self):
        self.user = User.objects.create_user("max", "max@example.org", PW)
        Member.objects.create(user=self.user, display_name="Max")
        self.client.force_login(self.user)

    def test_email_aendern_setzt_login_und_ist_eindeutig(self):
        # Bestätigung mit dem aktuellen Passwort, KEIN neues Passwort nötig.
        resp = self.client.post(reverse("profile"), {
            "action": "change_email", "email": "neu@example.org",
            "password": PW})
        self.assertRedirects(resp, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "neu@example.org")
        # Login folgt der E-Mail: Benutzername = neue E-Mail
        self.assertEqual(self.user.username, "neu@example.org")
        # Passwort unverändert
        self.assertTrue(self.user.check_password(PW))
        # Anmeldung mit der neuen E-Mail klappt, mit der alten nicht mehr
        self.client.logout()
        self.client.post(reverse("login"),
                         {"username": "neu@example.org", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.client.post(reverse("login"),
                         {"username": "max@example.org", "password": PW})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_aendern_braucht_korrektes_passwort(self):
        resp = self.client.post(reverse("profile"), {
            "action": "change_email", "email": "neu@example.org",
            "password": "falsch-falsch"})
        self.assertEqual(resp.status_code, 200)   # Formular mit Fehler
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "max@example.org")  # unverändert

    def test_email_aendern_lehnt_fremde_email_ab(self):
        User.objects.create_user("other", "other@example.org", PW)
        resp = self.client.post(reverse("profile"), {
            "action": "change_email", "email": "other@example.org",
            "password": PW})
        self.assertEqual(resp.status_code, 200)   # Formular mit Fehler
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "max@example.org")  # unverändert

    def test_passwort_aendern_bleibt_eingeloggt(self):
        new_pw = "Drachenflieger9z"
        resp = self.client.post(reverse("profile"), {
            "action": "change_password",
            "old_password": PW,
            "new_password1": new_pw, "new_password2": new_pw})
        self.assertRedirects(resp, reverse("profile"))
        # Session bleibt gültig (update_session_auth_hash)
        self.assertIn("_auth_user_id", self.client.session)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_pw))


class RechtstexteTests(TestCase):
    """Impressum (Pflicht), Datenschutz & AGB – öffentlich erreichbar, im Fuß verlinkt."""

    def test_impressum_oeffentlich(self):
        from shop.models import ShopConfig
        ShopConfig.objects.create(
            coop_name="Re:Hof eG", coop_address="Hofweg 1\n12345 Dorf",
            board="Vorstand X", contact_email="info@example.org")
        r = self.client.get(reverse("imprint"))      # anonym
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Re:Hof eG")
        self.assertContains(r, "§ 5 DDG")
        self.assertContains(r, reverse("imprint"))   # Fuß verlinkt Impressum

    def test_datenschutz_und_agb(self):
        from shop.models import ShopConfig
        ShopConfig.objects.create(
            privacy_policy="Wir schützen deine Daten.", terms_agb="Es gelten AGB.")
        self.assertContains(self.client.get(reverse("privacy")), "schützen")
        self.assertContains(self.client.get(reverse("terms")), "AGB")
        # Im Fuß verlinkt, weil gepflegt
        self.assertContains(self.client.get(reverse("imprint")), reverse("privacy"))

    def test_nicht_freigeschalteter_nutzer_erreicht_impressum(self):
        from shop.models import ShopConfig
        ShopConfig.objects.create(coop_name="Re:Hof eG")
        u = User.objects.create_user("warte9", "warte9@example.org", PW)
        self.client.force_login(u)   # eingeloggt, aber kein Mitglied
        self.assertEqual(self.client.get(reverse("imprint")).status_code, 200)

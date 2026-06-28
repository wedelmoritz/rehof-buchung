"""Tests für die Backend-Zwei-Faktor-Pflicht (TOTP, ADR 0061).

Kernidee: Die Erzwingung hängt an ADMIN_OTP_REQUIRED. Default in Tests (DEBUG=1)
ist sie AUS – darum laufen alle übrigen force_login-Backend-Tests unverändert.
Ist sie AN, braucht ein Backend-Konto zusätzlich eine bestätigte TOTP-Bestätigung.
"""
from django.contrib.admin import site as default_site
from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase, override_settings

from booking.admin_site import RehofAdminSite


class _FakeUser:
    """Minimaler Nutzer-Stub für has_permission (umgeht Middleware/Session)."""
    is_active = True
    is_staff = True
    is_superuser = True

    def __init__(self, verified):
        self._verified = verified

    def is_verified(self):
        return self._verified


class AdminOtpPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        # Die echte App-Site (RehofAdminConfig.default_site) ist eine RehofAdminSite.
        self.site = default_site if isinstance(default_site, RehofAdminSite) \
            else RehofAdminSite()

    def _req(self, user):
        r = self.factory.get("/admin/")
        r.user = user
        return r

    @override_settings(ADMIN_OTP_REQUIRED=False)
    def test_ohne_pflicht_reicht_staff(self):
        # 2FA aus: normaler Staff-/Superuser-Zugang wie bisher (Tests bleiben grün).
        self.assertTrue(self.site.has_permission(self._req(_FakeUser(verified=False))))

    @override_settings(ADMIN_OTP_REQUIRED=True)
    def test_mit_pflicht_unverifiziert_gesperrt(self):
        # 2FA an, aber Konto nicht per TOTP bestätigt → kein Backend-Zugang.
        self.assertFalse(self.site.has_permission(self._req(_FakeUser(verified=False))))

    @override_settings(ADMIN_OTP_REQUIRED=True)
    def test_mit_pflicht_verifiziert_erlaubt(self):
        # 2FA an und Konto verifiziert → Zugang.
        self.assertTrue(self.site.has_permission(self._req(_FakeUser(verified=True))))

    @override_settings(ADMIN_OTP_REQUIRED=True)
    def test_anonym_bleibt_gesperrt(self):
        self.assertFalse(self.site.has_permission(self._req(AnonymousUser())))


@override_settings(ADMIN_OTP_REQUIRED=True)
class AdminOtpLiveGateTests(TestCase):
    """End-to-End über den Test-Client: ein eingeloggter, aber un-verifizierter
    Superuser wird trotz force_login vom Backend abgewiesen (Redirect auf Login)."""

    def test_superuser_ohne_2fa_wird_abgewiesen(self):
        adm = User.objects.create_superuser("adm", "a@example.org", "pw12345")
        self.client.force_login(adm)
        r = self.client.get("/admin/", follow=False)
        # has_permission False → Admin leitet auf die Login-Seite um.
        self.assertEqual(r.status_code, 302)


class AdminOtpSetupCommandTests(TestCase):
    def test_command_legt_bestaetigtes_geraet_an(self):
        from io import StringIO
        from django.core.management import call_command
        from django_otp.plugins.otp_totp.models import TOTPDevice

        User.objects.create_superuser("adm", "a@example.org", "pw12345")
        out = StringIO()
        call_command("admin_otp_setup", "--user", "adm", stdout=out)
        dev = TOTPDevice.objects.get(user__username="adm")
        self.assertTrue(dev.confirmed)
        self.assertIn("otpauth://", out.getvalue())

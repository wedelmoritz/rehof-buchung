"""Tests für das RBAC-Fundament (ADR 0100): Rollen-Seeding, Capability-Prüfung,
additive Supersets, Legacy-Mapping ohne Rechte-Eskalation, `requires`-Decorator."""
from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from booking import authz


class SyncRolesTests(TestCase):
    def setUp(self):
        call_command("sync_roles", verbosity=0)
        self.rf = RequestFactory()

    def _user(self, *roles) -> User:
        u = User.objects.create_user(
            username=f"u{User.objects.count()}", password="x" * 12)
        for r in roles:
            u.groups.add(Group.objects.get(name=r))
        return User.objects.get(pk=u.pk)          # frischer Permission-Cache

    def test_alle_rollen_angelegt(self):
        for role in authz.ROLES:
            self.assertTrue(Group.objects.filter(name=role).exists(), role)

    def test_additiver_superset(self):
        codes = set(Group.objects.get(name="Buchungs-Verwaltung-Erweitert")
                    .permissions.values_list("codename", flat=True))
        self.assertSetEqual(codes, {
            authz.P_BOOK_FOR_MEMBER, authz.P_ADD_WISH_FOR_MEMBER,   # eigene
            authz.P_BUCHUNGEN, authz.P_EXPORT_WISHES, authz.P_BROADCAST,  # geerbt
        })

    def test_idempotent(self):
        call_command("sync_roles", verbosity=0)   # zweiter Lauf
        self.assertEqual(Group.objects.filter(name__in=authz.ROLES).count(), 6)

    def test_capability_gating(self):
        u = self._user("Rechnungs-Verwaltung")
        self.assertTrue(authz.user_can(u, authz.P_RECHNUNGEN))
        self.assertFalse(authz.user_can(u, authz.P_BUCHUNGEN))
        keys = {c.key for c in authz.allowed_capabilities(u)}
        self.assertLessEqual({"rechnungen", "konto", "dashboard", "auslastung"}, keys)
        self.assertNotIn("mitglieder", keys)
        self.assertTrue(authz.is_any_verwaltung(u))

    def test_sperrzeiten_any_of(self):
        perm = authz.CAPABILITY_BY_KEY["sperrzeiten"].perm
        self.assertTrue(authz.user_can(self._user("Quartiers-Verwaltung"), perm))
        self.assertTrue(authz.user_can(self._user("Buchungs-Verwaltung"), perm))

    def test_mehrere_rollen_vereinigen(self):
        u = self._user("Rechnungs-Verwaltung", "Mitglieder-Verwaltung")
        self.assertTrue(authz.user_can(u, authz.P_RECHNUNGEN))
        self.assertTrue(authz.user_can(u, authz.P_MITGLIEDER))

    def test_requires_decorator(self):
        @authz.requires_capability("rechnungen")
        def view(request):
            return HttpResponse("ok")
        req = self.rf.get("/x"); req.user = self._user("Buchungs-Verwaltung")
        with self.assertRaises(PermissionDenied):
            view(req)
        ok = self.rf.get("/x"); ok.user = self._user("Rechnungs-Verwaltung")
        self.assertEqual(view(ok).status_code, 200)

    def test_superuser_darf_alles(self):
        su = User.objects.create_superuser("boss", "b@x.de", "x" * 12)
        self.assertTrue(authz.user_can(su, authz.P_BOOK_FOR_MEMBER))
        self.assertEqual(len(authz.allowed_capabilities(su)), len(authz.CAPABILITIES))

    def test_nicht_angemeldet_gesperrt(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(authz.is_any_verwaltung(AnonymousUser()))
        self.assertFalse(authz.user_can(AnonymousUser(), None))

    def test_legacy_mapping_ohne_eskalation(self):
        u = User.objects.create_user("legacy", password="x" * 12)
        u.groups.add(Group.objects.get_or_create(name=authz.LEGACY_ROLE)[0])
        call_command("sync_roles", verbosity=0)
        u = User.objects.get(pk=u.pk)
        # Erhält die bisherigen Basis-Zugriffe …
        for p in (authz.P_RECHNUNGEN, authz.P_BUCHUNGEN, authz.P_MITGLIEDER,
                  authz.P_HOFLADEN, authz.P_BROADCAST):
            self.assertTrue(authz.user_can(u, p), p)
        # … aber KEINE neuen Schreib-/Quartier-Rechte (Least Privilege).
        self.assertFalse(authz.user_can(u, authz.P_BOOK_FOR_MEMBER))
        self.assertFalse(authz.user_can(u, authz.P_ADD_WISH_FOR_MEMBER))
        self.assertFalse(authz.user_can(u, authz.P_QUARTIERE))


class ViewAccessTests(TestCase):
    """End-to-End: rollen-gegatete Verwaltungs-Seiten (403 fail-closed) und die
    rollengefilterte Navigation (ADR 0100)."""

    def setUp(self):
        call_command("sync_roles", verbosity=0)

    def _login(self, *roles):
        u = User.objects.create_user(f"v{User.objects.count()}", password="x" * 12)
        for r in roles:
            u.groups.add(Group.objects.get(name=r))
        self.client.force_login(u)
        return u

    def test_rechnungs_rolle_sieht_nur_finanzen(self):
        self._login("Rechnungs-Verwaltung")
        self.assertEqual(self.client.get(reverse("verw_rechnungen")).status_code, 200)
        self.assertEqual(self.client.get(reverse("verw_konto")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)   # None
        self.assertEqual(self.client.get(reverse("verw_mitglieder")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard_products")).status_code, 403)

    def test_mitglieder_rolle_getrennt(self):
        self._login("Mitglieder-Verwaltung")
        self.assertEqual(self.client.get(reverse("verw_mitglieder")).status_code, 200)
        self.assertEqual(self.client.get(reverse("verw_rechnungen")).status_code, 403)

    def test_sperrzeiten_beide_rollen(self):
        self._login("Quartiers-Verwaltung")
        self.assertEqual(self.client.get(reverse("verw_sperrzeiten")).status_code, 200)
        self.client.logout()
        self._login("Buchungs-Verwaltung")
        self.assertEqual(self.client.get(reverse("verw_sperrzeiten")).status_code, 200)

    def test_nav_ist_rollengefiltert(self):
        self._login("Rechnungs-Verwaltung")
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn(reverse("verw_rechnungen"), html)        # erlaubt → in der Nav
        self.assertNotIn(reverse("verw_mitglieder"), html)     # verboten → nicht in der Nav

    def test_export_je_kind_gegated(self):
        self._login("Rechnungs-Verwaltung")
        self.assertEqual(self.client.get("/verwaltung/export/rechnungen.csv").status_code, 200)
        self.assertEqual(self.client.get("/verwaltung/export/buchungen.csv").status_code, 403)

    def test_ohne_rolle_403(self):
        # Mitglied (passiert das Aktivierungs-Gate) OHNE Verwaltungsrolle → 403.
        from booking.models import Member
        u = User.objects.create_user("plain", password="x" * 12)
        Member.objects.create(user=u, display_name="Plain")
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("verw_rechnungen")).status_code, 403)

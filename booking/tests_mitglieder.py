"""Tests für die native Mitglieder-Verwaltung (ADR 0100, Phase 2):
Onboarding-Warteschlange, Status-Aktion passiv/aktiv und die flachen Grenzen
(kein Löschen nativ, nur Konten ohne Anteil, Rollen-Gating)."""
from __future__ import annotations

from datetime import date

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import Member, Membership, Share


def _pending_user(username="neu", email="neu@example.org"):
    """Frisch registriertes Konto ohne Mitglieds-Anteil (Onboarding-Kandidat)."""
    return User.objects.create_user(username=username, password="x" * 12, email=email)


def _member(username="mit", email="mit@example.org"):
    u = User.objects.create_user(username=username, password="x" * 12, email=email)
    m = Member.objects.create(user=u, display_name=username)
    ms = Membership.objects.create(label=username, annual_night_budget=50,
                                   wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


class MitgliederVerwaltungTests(TestCase):
    def setUp(self):
        call_command("sync_roles", verbosity=0)
        self.bl = User.objects.create_user("bl", password="x" * 12)
        self.bl.groups.add(Group.objects.get(name="Mitglieder-Verwaltung"))
        self.client.force_login(self.bl)

    # --- Onboarding-Warteschlange ---------------------------------------- #
    def test_queue_zeigt_nur_konten_ohne_anteil(self):
        pend = _pending_user()
        _member("hatanteil")
        html = self.client.get(reverse("verw_mitglieder")).content.decode()
        self.assertIn(pend.username, html)          # in der Warteschlange
        self.assertIn("hatanteil", html)            # nur in der Mitgliederliste
        # Genau ein offenes Konto in der Queue.
        self.assertEqual(svc.users_without_membership().count(), 1)

    def test_onboard_als_mitglied(self):
        pend = _pending_user()
        r = self.client.post(reverse("verw_mitglieder"), {
            "action": "member", "user_id": pend.pk, "display_name": "Neu Mitglied",
            "membership": "new", "night_budget": "50"})
        self.assertEqual(r.status_code, 302)
        m = Member.objects.get(user=pend)
        self.assertFalse(m.is_external)
        self.assertTrue(m.shares.exists())
        self.assertTrue(m.can_book)
        self.assertEqual(svc.users_without_membership().count(), 0)

    def test_onboard_terminal(self):
        pend = _pending_user()
        self.client.post(reverse("verw_mitglieder"), {
            "action": "terminal", "user_id": pend.pk, "display_name": "Laden"})
        m = Member.objects.get(user=pend)
        self.assertTrue(m.is_external)
        self.assertTrue(m.terminal_enabled)

    def test_onboard_deactivate(self):
        pend = _pending_user()
        self.client.post(reverse("verw_mitglieder"), {
            "action": "deactivate", "user_id": pend.pk})
        pend.refresh_from_db()
        self.assertFalse(pend.is_active)

    def test_kein_natives_loeschen(self):
        """Löschen bleibt dem Backend vorbehalten – die Aktion existiert nativ nicht."""
        pend = _pending_user()
        self.client.post(reverse("verw_mitglieder"), {
            "action": "delete", "user_id": pend.pk})
        self.assertTrue(User.objects.filter(pk=pend.pk).exists())

    def test_onboard_nur_fuer_konten_ohne_anteil(self):
        """Defense in depth: ein bereits zugeordnetes Konto lässt sich nicht
        über die Onboarding-Aktion umbiegen."""
        m = _member()
        before = m.shares.count()
        self.client.post(reverse("verw_mitglieder"), {
            "action": "member", "user_id": m.user_id, "display_name": "X",
            "membership": "new", "night_budget": "10"})
        self.assertEqual(m.shares.count(), before)   # unverändert

    # --- Status passiv/aktiv --------------------------------------------- #
    def test_passiv_und_aktiv_toggle(self):
        m = _member()
        self.client.post(reverse("verw_mitglieder"), {
            "action": "passive", "member_id": m.id})
        m.refresh_from_db()
        self.assertEqual(m.status, "passive")
        self.assertFalse(m.can_book)
        self.client.post(reverse("verw_mitglieder"), {
            "action": "active", "member_id": m.id})
        m.refresh_from_db()
        self.assertEqual(m.status, "active")
        self.assertTrue(m.can_book)

    def test_ausgeschieden_kein_toggle(self):
        m = _member()
        m.excluded_from = date.today()
        m.save(update_fields=["excluded_from"])
        self.assertFalse(svc.set_member_passive(m, passive=True))
        m.refresh_from_db()
        self.assertIsNone(m.passive_from)

    def test_status_chip_in_liste(self):
        _member("aktiv_m")
        pm = _member("passiv_m", email="p@example.org")
        pm.passive_from = date.today()
        pm.save(update_fields=["passive_from"])
        html = self.client.get(reverse("verw_mitglieder")).content.decode()
        self.assertIn("aktiv", html)
        self.assertIn("passiv", html)


class MitgliederVerwaltungGatingTests(TestCase):
    """Rollen-Gating: nur die Mitglieder-Verwaltung darf – fail-closed 403."""

    def setUp(self):
        call_command("sync_roles", verbosity=0)

    def test_andere_rolle_kein_zugriff(self):
        u = User.objects.create_user("fin", password="x" * 12)
        u.groups.add(Group.objects.get(name="Rechnungs-Verwaltung"))
        self.client.force_login(u)
        m = _member()
        # GET 403 …
        self.assertEqual(self.client.get(reverse("verw_mitglieder")).status_code, 403)
        # … und POST ebenso (keine Status-Änderung durch fremde Rolle).
        self.assertEqual(self.client.post(reverse("verw_mitglieder"), {
            "action": "passive", "member_id": m.id}).status_code, 403)
        m.refresh_from_db()
        self.assertEqual(m.status, "active")

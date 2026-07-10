"""Tests für BL-Buchungen im Namen von Mitgliedern (ADR 0100, Phase 3):
`book_for_member` (strikt + auditierter Override), Defense in depth, Audit
(created_by) + Benachrichtigung, Rollen-Gating der View."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import (
    Allocation, BookingPeriod, BookingPolicy, EquivalenceClass, Member,
    Membership, Notification, Quarter, Share,
)

NEXT = date.today().year + 1


def _member(name, nights=50):
    u = User.objects.create_user(username=name, password="x" * 12,
                                 email=f"{name}@example.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=nights, wish_night_budget=nights // 2)
    Share.objects.create(membership=ms, member=m, night_budget=nights,
                         wish_night_budget=nights // 2)
    return m


class BookForMemberServiceTests(TestCase):
    def setUp(self):
        call_command("sync_roles", verbosity=0)
        self.actor = User.objects.create_user("bl", password="x" * 12)
        self.actor.groups.add(Group.objects.get(name="Buchungs-Verwaltung-Erweitert"))
        self.actor = User.objects.get(pk=self.actor.pk)   # frischer Perm-Cache
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="K1", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="K2", eq_class=cls,
                                         min_occupancy=1, max_occupancy=4)
        BookingPeriod.objects.create(name="g", target_year=NEXT,
                                     start=date(NEXT, 1, 1), end=date(NEXT + 1, 1, 1),
                                     status=BookingPeriod.FREE_BOOKING)
        p = BookingPolicy.get_solo()
        p.min_lead_days = 0
        p.save(update_fields=["min_lead_days"])
        self.m = _member("anna")
        self.start = date(NEXT, 5, 1)
        self.end = self.start + timedelta(days=4)

    # --- strikter Standard-Pfad ------------------------------------------ #
    def test_strict_erfolg_audit_und_notify(self):
        a, err = svc.book_for_member(self.actor, self.m, self.q, self.start, self.end, 2)
        self.assertIsNotNone(a, err)
        self.assertEqual(a.created_by_id, self.actor.id)
        self.assertTrue(a.by_management)
        self.assertEqual(a.source, "spontaneous")
        # Mitglied wurde benachrichtigt.
        self.assertTrue(Notification.objects.filter(member=self.m).exists())

    def test_strict_blockt_passiv(self):
        self.m.passive_from = date.today()
        self.m.save(update_fields=["passive_from"])
        a, err = svc.book_for_member(self.actor, self.m, self.q, self.start, self.end, 2)
        self.assertIsNone(a)
        self.assertIn("nicht buchungsberechtigt", err)

    def test_strict_blockt_ueber_budget(self):
        small = _member("timo", nights=2)
        a, err = svc.book_for_member(self.actor, small, self.q, self.start, self.end, 2)
        self.assertIsNone(a)
        self.assertIn("Tage", err)

    # --- auditierter Override -------------------------------------------- #
    def test_override_erlaubt_passiv_und_ueberbudget(self):
        small = _member("nina", nights=2)
        small.passive_from = date.today()
        small.save(update_fields=["passive_from"])
        a, err = svc.book_for_member(self.actor, small, self.q, self.start, self.end, 2,
                                     override=True, reason="Sonderfall Telefon")
        self.assertIsNotNone(a, err)
        self.assertIn("BL-Ausnahme", a.internal_note)
        self.assertIn("Sonderfall Telefon", a.internal_note)
        self.assertEqual(a.created_by_id, self.actor.id)

    def test_override_blockt_trotzdem_doppelbuchung(self):
        # Erste Buchung belegt K1.
        svc.book_for_member(self.actor, self.m, self.q, self.start, self.end, 2)
        other = _member("olaf")
        a, err = svc.book_for_member(self.actor, other, self.q, self.start, self.end, 2,
                                     override=True, reason="egal")
        self.assertIsNone(a)
        self.assertIn("berschneidung", err)   # „Überschneidung …"

    # --- Defense in depth ------------------------------------------------ #
    def test_service_prueft_capability(self):
        nobody = User.objects.create_user("x", password="x" * 12)
        with self.assertRaises(PermissionDenied):
            svc.book_for_member(nobody, self.m, self.q, self.start, self.end, 2)


class BookForMemberViewTests(TestCase):
    def setUp(self):
        call_command("sync_roles", verbosity=0)
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="K1", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        BookingPeriod.objects.create(name="g", target_year=NEXT,
                                     start=date(NEXT, 1, 1), end=date(NEXT + 1, 1, 1),
                                     status=BookingPeriod.FREE_BOOKING)
        p = BookingPolicy.get_solo()
        p.min_lead_days = 0
        p.save(update_fields=["min_lead_days"])
        self.m = _member("anna")
        self.start = date(NEXT, 6, 1)
        self.end = self.start + timedelta(days=3)

    def _login(self, role):
        u = User.objects.create_user(f"u_{role}", password="x" * 12)
        u.groups.add(Group.objects.get(name=role))
        self.client.force_login(u)
        return u

    def test_erweitert_sieht_formular_und_bucht(self):
        self._login("Buchungs-Verwaltung-Erweitert")
        html = self.client.get(reverse("verw_buchungen")).content.decode()
        self.assertIn("Buchung für ein Mitglied anlegen", html)
        r = self.client.post(reverse("verw_book_for_member"), {
            "member_id": self.m.id, "quarter_id": self.q.id,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "persons": "2"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Allocation.objects.filter(member=self.m).exists())

    def test_basis_rolle_kein_formular_und_403(self):
        self._login("Buchungs-Verwaltung")
        html = self.client.get(reverse("verw_buchungen")).content.decode()
        self.assertNotIn("Buchung für ein Mitglied anlegen", html)
        # POST auf die Aktion ist fail-closed 403 (kein book_for_member-Recht).
        r = self.client.post(reverse("verw_book_for_member"), {
            "member_id": self.m.id, "quarter_id": self.q.id,
            "start": self.start.isoformat(), "end": self.end.isoformat()})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Allocation.objects.filter(member=self.m).exists())

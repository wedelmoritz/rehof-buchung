"""Integrationstest: Buchungen nach der Losung vervollständigen + 4-Wochen-
Erinnerung (ADR 0104).

* Los-Zuteilungen tragen `details_pending=True` (bleibt nach der Bestätigung).
* `complete_lottery_details` trägt Personen/Begleitung/Besonderheiten nach und
  räumt das Flag ab (Personen-Rahmen wird geprüft).
* `send_booking_details_reminders` erinnert genau einmal, sobald die Anreise
  ≤ 28 Tage entfernt ist – In-App + Mail; nur bestätigte, offene Los-Buchungen.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import (
    Allocation, BookingPeriod, EquivalenceClass, Member, Membership,
    Notification, OutboxEmail, Quarter, Share,
)

NEXT = date.today().year + 1


def _member(name):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50,
                         wish_night_budget=25)
    return m


class LotteryAllocationDetailsTests(TestCase):
    def setUp(self):
        cache.clear()
        cls = EquivalenceClass.objects.create(name="Solo")
        self.q = Quarter.objects.create(name="Turm", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.alice = _member("alice")
        self.bob = _member("bob")
        self.period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
            wishlist_close=date.today(), status=BookingPeriod.WISHES_OPEN)
        self.s = date(NEXT, 5, 24)
        self.e = self.s + timedelta(days=5)
        svc.add_wish(self.alice, self.period, self.q, self.s, self.e)
        svc.add_wish(self.bob, self.period, self.q, self.s, self.e)

    def test_los_buchung_ist_details_pending(self):
        run = svc.run_period_lottery(self.period, seed=1)
        svc.confirm_lottery(run)
        allocs = list(Allocation.objects.filter(source="lottery",
                                                provisional=False))
        # Ausweich-Logik gibt beide Parteien eine Zuteilung (gleiche Klasse) –
        # mindestens eine existiert; alle tragen das Nachtrage-Flag.
        self.assertTrue(allocs)
        self.assertTrue(all(a.details_pending for a in allocs))

    def test_complete_traegt_nach_und_raeumt_flag_ab(self):
        a = Allocation.objects.create(
            member=self.alice, quarter=self.q, start=self.s, end=self.e,
            source="lottery", period=self.period, details_pending=True)
        alloc, err = svc.complete_lottery_details(
            self.alice, a.id, persons=3, companions="Familie",
            special_requests="Hund")
        self.assertIsNone(err)
        a.refresh_from_db()
        self.assertFalse(a.details_pending)
        self.assertEqual(a.persons, 3)
        self.assertEqual(a.companions, "Familie")
        self.assertEqual(a.special_requests, "Hund")

    def test_complete_lehnt_zu_viele_personen_ab(self):
        a = Allocation.objects.create(
            member=self.alice, quarter=self.q, start=self.s, end=self.e,
            source="lottery", period=self.period, details_pending=True)
        alloc, err = svc.complete_lottery_details(self.alice, a.id, persons=9)
        self.assertIsNone(alloc)
        self.assertIn("höchstens", err)
        a.refresh_from_db()
        self.assertTrue(a.details_pending)   # unverändert

    def test_complete_nur_eigene_und_nur_offene(self):
        a = Allocation.objects.create(
            member=self.alice, quarter=self.q, start=self.s, end=self.e,
            source="lottery", period=self.period, details_pending=True)
        # Fremdes Mitglied darf nicht.
        _, err = svc.complete_lottery_details(self.bob, a.id, persons=2)
        self.assertIsNotNone(err)
        # Bereits vervollständigt → nicht erneut.
        svc.complete_lottery_details(self.alice, a.id, persons=2)
        _, err2 = svc.complete_lottery_details(self.alice, a.id, persons=2)
        self.assertIsNotNone(err2)


class BookingDetailsReminderTests(TestCase):
    def setUp(self):
        cache.clear()
        cls = EquivalenceClass.objects.create(name="Solo")
        self.q = Quarter.objects.create(name="Turm", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.alice = _member("alice")
        self.today = date.today()

    def _alloc(self, start, **kw):
        opts = dict(member=self.alice, quarter=self.q, start=start,
                    end=start + timedelta(days=4), source="lottery",
                    details_pending=True, provisional=False)
        opts.update(kw)
        return Allocation.objects.create(**opts)

    def test_erinnerung_innerhalb_4_wochen_einmalig(self):
        a = self._alloc(self.today + timedelta(days=20))
        n = svc.send_booking_details_reminders(self.today)
        self.assertEqual(n, 1)
        a.refresh_from_db()
        self.assertEqual(a.details_reminded_on, self.today)
        self.assertTrue(Notification.objects.filter(member=self.alice).exists())
        self.assertTrue(OutboxEmail.objects.filter(
            to_email="alice@e.org").exists())
        # Idempotent: ein zweiter Lauf erinnert nicht erneut.
        self.assertEqual(svc.send_booking_details_reminders(self.today), 0)

    def test_ausserhalb_horizont_keine_erinnerung(self):
        self._alloc(self.today + timedelta(days=60))
        self.assertEqual(svc.send_booking_details_reminders(self.today), 0)

    def test_vorlaeufige_und_vervollstaendigte_ausgenommen(self):
        self._alloc(self.today + timedelta(days=10), provisional=True)
        self._alloc(self.today + timedelta(days=10), details_pending=False)
        self.assertEqual(svc.send_booking_details_reminders(self.today), 0)


class MyBookingsCompletionViewTests(TestCase):
    def setUp(self):
        cache.clear()
        cls = EquivalenceClass.objects.create(name="Solo")
        self.q = Quarter.objects.create(name="Turm", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.alice = _member("alice")
        self.client.force_login(self.alice.user)

    def test_karte_sichtbar_und_absenden(self):
        a = Allocation.objects.create(
            member=self.alice, quarter=self.q,
            start=date.today() + timedelta(days=40),
            end=date.today() + timedelta(days=44),
            source="lottery", details_pending=True, provisional=False)
        html = self.client.get(reverse("my_bookings")).content.decode()
        self.assertIn("Bitte diese Buchung vervollständigen", html)
        self.client.post(reverse("my_bookings"), {
            "action": "complete_details", "allocation_id": a.id,
            "persons": 2, "companions": "Anna", "special_requests": "Beistellbett"})
        a.refresh_from_db()
        self.assertFalse(a.details_pending)
        self.assertEqual(a.persons, 2)
        self.assertEqual(a.special_requests, "Beistellbett")

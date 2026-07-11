"""Integrationstest der Wunsch-Prognose (ADR 0101): `services.wish_prognosis`
über eingereichte Wünsche und die Anzeige auf der Wunschliste."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from booking import services as svc
from booking.models import (
    BookingPeriod, EquivalenceClass, Member, Membership, Quarter, Share,
)

NEXT = date.today().year + 1


def _member(name):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


class WishPrognosisTests(TestCase):
    def setUp(self):
        cache.clear()
        self.cls = EquivalenceClass.objects.create(name="Solo")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.alice = _member("alice")
        self.bob = _member("bob")
        self.period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
            draw_at=timezone.now() + timedelta(days=3),
            status=BookingPeriod.WISHES_REVIEW)
        self.s = date(NEXT, 5, 24)
        self.e = self.s + timedelta(days=5)

    def test_ohne_konkurrenz_gute_chance(self):
        w, _ = svc.add_wish(self.alice, self.period, self.q, self.s, self.e)
        prog = svc.wish_prognosis(self.period)
        self.assertIn(w.id, prog)
        self.assertEqual(prog[w.id]["prob"], 100)
        self.assertEqual(prog[w.id]["band"], "good")

    def test_zwei_rivalen_geteilte_chance(self):
        wa, _ = svc.add_wish(self.alice, self.period, self.q, self.s, self.e)
        wb, _ = svc.add_wish(self.bob, self.period, self.q, self.s, self.e)
        prog = svc.wish_prognosis(self.period)
        self.assertTrue(30 <= prog[wa.id]["prob"] <= 70)
        self.assertTrue(30 <= prog[wb.id]["prob"] <= 70)
        # ein Einzelquartier, zwei Rivalen → „offen“ (kein sicheres Ergebnis).
        self.assertEqual(prog[wa.id]["band"], "open")

    def test_eingetragener_wunsch_erscheint_in_prognose(self):
        # Seit ADR 0101 nimmt jeder eingetragene Wunsch teil (kein Einreichen mehr) –
        # er erscheint daher direkt in der Prognose.
        w, _ = svc.add_wish(self.alice, self.period, self.q, self.s, self.e)
        self.assertIn(w.id, svc.wish_prognosis(self.period))

    def test_wishlist_seite_zeigt_prognose(self):
        svc.add_wish(self.alice, self.period, self.q, self.s, self.e)
        self.client.force_login(self.alice.user)
        html = self.client.get(reverse("wishlist")).content.decode()
        self.assertIn("Gute Chance", html)

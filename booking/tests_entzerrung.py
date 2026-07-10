"""Integrationstests für die weiteren Entzerrungs-Funktionen (ADR 0101):
Nachfrage-Heatmap (C), Absprachen + Opt-out (D), Wunsch-Export + Admin-Nachtrag (E).
Wächst mit den einzelnen Batches."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
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


def _period(status=BookingPeriod.WISHES_REVIEW):
    return BookingPeriod.objects.create(
        name="Losung", target_year=NEXT, start=date(NEXT, 1, 1),
        end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
        draw_at=timezone.now() + timedelta(days=3), status=status)


class DemandGridTests(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Hütte", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.period = _period()

    def test_grid_zaehlt_eingereichte_wuensche_je_monat(self):
        a = _member("a")
        b = _member("b")
        # Zwei eingereichte Wünsche im Mai für „Turm“, einer im Juli für „Hütte“.
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.add_wish(b, self.period, self.q, date(NEXT, 5, 20), date(NEXT, 5, 24))
        svc.add_wish(a, self.period, self.q2, date(NEXT, 7, 1), date(NEXT, 7, 5))
        svc.submit_wishlist(a, self.period)
        svc.submit_wishlist(b, self.period)
        grid = svc.wish_demand_grid(self.period)
        self.assertEqual(len(grid["months"]), 12)
        turm = next(r for r in grid["rows"] if r["quarter"] == "Turm")
        huette = next(r for r in grid["rows"] if r["quarter"] == "Hütte")
        self.assertEqual(turm["cells"][4]["count"], 2)   # Mai (Index 4)
        self.assertEqual(huette["cells"][6]["count"], 1)  # Juli (Index 6)
        self.assertEqual(grid["max"], 2)

    def test_nur_eingereichte_zaehlen(self):
        a = _member("a")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        # nicht eingereicht → max 0 → keine Heatmap
        grid = svc.wish_demand_grid(self.period)
        self.assertEqual(grid["max"], 0)

    def test_wishlist_zeigt_heatmap(self):
        a = _member("a")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.submit_wishlist(a, self.period)
        self.client.force_login(a.user)
        html = self.client.get(reverse("wishlist")).content.decode()
        self.assertIn("Nachfrage-Übersicht", html)

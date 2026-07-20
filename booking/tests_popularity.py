"""Integrationstest: kapazitätsrelative Beliebtheit im Wunsch-Kalender + proaktive
Vorschläge beim Eintragen (ADR 0103, P0)."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

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
    Share.objects.create(membership=ms, member=m, night_budget=50,
                         wish_night_budget=25)
    return m


class PopularityTests(TestCase):
    def setUp(self):
        cache.clear()
        # Klasse mit ZWEI gleichwertigen Quartieren → Kapazität 2.
        self.cls = EquivalenceClass.objects.create(name="Klein")
        self.q1 = Quarter.objects.create(name="Haus A", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Haus B", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        # Freie Klasse mit einem Quartier ohne Nachfrage (für „Empfohlen").
        self.cls2 = EquivalenceClass.objects.create(name="Solo")
        self.q3 = Quarter.objects.create(name="Turm", eq_class=self.cls2,
                                         min_occupancy=1, max_occupancy=4)
        self.period = BookingPeriod.objects.create(
            name="P", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
            wishlist_close=date.today(), status=BookingPeriod.WISHES_OPEN)
        self.s = date(NEXT, 5, 11)
        self.e = self.s + timedelta(days=5)

    def _wish(self, member, q):
        svc.add_wish(member, self.period, q, self.s, self.e)

    def test_band_relativ_zur_kapazitaet(self):
        # 3 Wünsche in der Klasse (Kapazität 2) → ratio 1.5 → „beliebt".
        for i, q in enumerate((self.q1, self.q2, self.q1)):
            self._wish(_member(f"m{i}"), q)
        bands = svc.class_popularity_for_range(self.period, self.s, self.e)
        self.assertEqual(bands[str(self.q1.id)]["key"], "popular")
        self.assertEqual(bands[str(self.q1.id)]["label"], "beliebt")
        # Das nachfragefreie Solo-Quartier bleibt „frei".
        self.assertEqual(bands[str(self.q3.id)]["key"], "free")

    def test_sehr_beliebt_ab_ueberzeichnung(self):
        for i, q in enumerate((self.q1, self.q2, self.q1, self.q2)):
            self._wish(_member(f"n{i}"), q)   # 4 Wünsche / Kapazität 2 = 2.0
        bands = svc.class_popularity_for_range(self.period, self.s, self.e)
        self.assertEqual(bands[str(self.q1.id)]["key"], "very")

    def test_kalender_faerbt_kapazitaetsrelativ(self):
        for i, q in enumerate((self.q1, self.q2, self.q1, self.q2)):
            self._wish(_member(f"k{i}"), q)
        cal = svc.build_wish_calendar(None, self.period, NEXT, 5)
        # Ein Tag im Wunschzeitraum trägt das „sehr beliebt"-Level (tone „full").
        levels = {d["level"] for wk in cal["weeks"] for d in wk
                  if self.s <= d["date"] < self.e}
        self.assertIn("full", levels)
        # Ein Tag klar außerhalb ist „frei".
        outside = {d["level"] for wk in cal["weeks"] for d in wk
                   if d["date"] == self.s - timedelta(days=1)}
        self.assertEqual(outside, {"free"})

    def test_wishlist_zeigt_empfehlung_und_baender(self):
        # Nachfrage nur in der „Klein"-Klasse; das Solo-Quartier ist frei → Empfehlung.
        for i, q in enumerate((self.q1, self.q2, self.q1, self.q2)):
            self._wish(_member(f"w{i}"), q)
        viewer = _member("viewer")
        self.client.force_login(viewer.user)
        url = reverse("wishlist") + (
            f"?view=neu&year={NEXT}&month=5"
            f"&start={self.s:%Y-%m-%d}&end={self.e:%Y-%m-%d}")
        html = self.client.get(url).content.decode()
        self.assertIn("Empfohlen: hier hast du die besten Chancen", html)
        self.assertIn("sehr beliebt", html)   # die überzeichnete Klasse
        self.assertIn("Turm", html)            # das freie Solo-Quartier

"""Integrationstest für den Losergebnis-Rückblick (ADR 0102): der Rückblick wird
bei der Ziehung vorberechnet und erst NACH der Bestätigung im Gemeinschaftsspiegel
gezeigt (anonym, `confirmed`)."""
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
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


class RetrospectiveTests(TestCase):
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
        s = date(NEXT, 5, 24)
        e = s + timedelta(days=5)
        # Beide wollen dasselbe Einzelquartier → 1 gewinnt, 1 verliert.
        svc.add_wish(self.alice, self.period, self.q, s, e)
        svc.add_wish(self.bob, self.period, self.q, s, e)
        svc.submit_wishlist(self.alice, self.period)
        svc.submit_wishlist(self.bob, self.period)

    def test_rueckblick_vorberechnet_und_erst_nach_bestaetigung_sichtbar(self):
        run = svc.run_period_lottery(self.period, seed=1)
        # Am Lauf vorberechnet (auch vor Bestätigung).
        retro = run.retrospective
        self.assertTrue(retro)
        self.assertEqual(retro["year"], NEXT)
        self.assertEqual(retro["total_wishes"], 2)
        self.assertEqual(retro["overall"]["won"], 1)
        self.assertEqual(retro["overall"]["lost"], 1)
        self.assertEqual(retro["overall"]["pct"], 50)
        # „Turm" ist das begehrteste Quartier (2 Wünsche, 1 erfüllt).
        self.assertEqual(retro["popular"][0]["quarter"], "Turm")
        self.assertEqual(retro["popular"][0]["demand"], 2)

        # Vor Bestätigung: der Gemeinschaftsspiegel zeigt KEINEN Rückblick.
        cache.clear()
        self.assertIsNone(svc.community_stats()["lottery_retro"])

        # Nach Bestätigung: sichtbar.
        svc.confirm_lottery(run)
        cache.clear()
        stats = svc.community_stats()
        self.assertIsNotNone(stats["lottery_retro"])
        self.assertEqual(stats["lottery_retro"]["year"], NEXT)

    def test_community_seite_rendert_rueckblick(self):
        run = svc.run_period_lottery(self.period, seed=1)
        svc.confirm_lottery(run)
        cache.clear()
        u = User.objects.create_user("viewer", password="x" * 12)
        Member.objects.create(user=u, display_name="Viewer")
        self.client.force_login(u)
        html = self.client.get(reverse("community")).content.decode()
        self.assertIn(f"Rückblick Losung {NEXT}", html)
        self.assertIn("Am meisten gewünscht", html)

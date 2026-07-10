"""Tests für die Entzerrungs-/Review-Phase vor der Losung (ADR 0101, Batch A):
Lebenszyklus (WISHES_REVIEW), abgeleitete Fristen (review_open/freeze_start),
Freeze-Flag und der Bearbeitbarkeits-Guard der Wunsch-Services."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from booking import services as svc
from booking.models import (
    BookingPeriod, BookingPolicy, EquivalenceClass, Member, Membership,
    Quarter, Share, Wish,
)

NEXT = date.today().year + 1


def _member(name="anna"):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


class LifecycleTests(TestCase):
    def _period(self, **kw):
        defaults = dict(name="P", target_year=NEXT, start=date(NEXT, 1, 1),
                        end=date(NEXT + 1, 1, 1))
        defaults.update(kw)
        return BookingPeriod(**defaults)

    def test_review_open_aus_review_days(self):
        draw = timezone.now() + timedelta(days=10)
        p = self._period(wishlist_open=date.today() - timedelta(days=20), draw_at=draw)
        # Kein wishlist_close → review_open = draw − review_days (Default 7).
        self.assertEqual(p.review_open, (draw - timedelta(days=7)).date())
        self.assertEqual(p.submission_deadline, p.review_open)

    def test_review_open_bevorzugt_wishlist_close(self):
        draw = timezone.now() + timedelta(days=10)
        wc = date.today() + timedelta(days=2)
        p = self._period(wishlist_close=wc, draw_at=draw)
        self.assertEqual(p.review_open, wc)

    def test_effective_review_days_override(self):
        BookingPolicy.get_solo()   # Default 7
        p = self._period(draw_at=timezone.now() + timedelta(days=5))
        self.assertEqual(p.effective_review_days, 7)
        p.review_days = 3
        self.assertEqual(p.effective_review_days, 3)
        self.assertEqual(p.review_open, (p.draw_at - timedelta(days=3)).date())

    def test_compute_status_durchlaeuft_review(self):
        now = timezone.now()
        draw = now + timedelta(days=3)          # Losung in 3 Tagen
        p = self._period(wishlist_open=date.today() - timedelta(days=20),
                         draw_at=draw, review_days=7)
        # review_open = draw − 7 = vor 4 Tagen → heute in der Entzerrungsphase.
        self.assertEqual(p.compute_status(now), BookingPeriod.WISHES_REVIEW)
        # Vor review_open: Wunsch-Fenster.
        early = now - timedelta(days=10)
        self.assertEqual(p.compute_status(early), BookingPeriod.WISHES_OPEN)
        # Nach der Ziehung: zur Prüfung.
        after = draw + timedelta(hours=1)
        self.assertEqual(p.compute_status(after), BookingPeriod.LOTTERY_REVIEW)

    def test_freeze_start_und_display_frozen(self):
        now = timezone.now()
        draw = now + timedelta(hours=10)         # < 24 h → eingefroren
        p = self._period(draw_at=draw)
        self.assertEqual(p.freeze_start, draw - timedelta(hours=24))
        self.assertTrue(p.display_frozen(now))
        # 30 h vor der Losung: noch nicht eingefroren.
        self.assertFalse(p.display_frozen(draw - timedelta(hours=30)))
        # nach der Losung: nicht mehr „frozen“ (Anzeige-Fenster vorbei).
        self.assertFalse(p.display_frozen(draw + timedelta(hours=1)))

    def test_wishes_review_im_lifecycle_zwischen_open_und_ready(self):
        lc = BookingPeriod.LIFECYCLE
        self.assertLess(lc.index(BookingPeriod.WISHES_OPEN),
                        lc.index(BookingPeriod.WISHES_REVIEW))
        self.assertLess(lc.index(BookingPeriod.WISHES_REVIEW),
                        lc.index(BookingPeriod.LOTTERY_READY))


class WishGuardTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="K1", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.m = _member()
        self.s = date(NEXT, 6, 1)
        self.e = self.s + timedelta(days=4)

    def _period(self, status):
        return BookingPeriod.objects.create(
            name="P", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), status=status,
            draw_at=timezone.now() + timedelta(days=3))

    def test_add_wish_erlaubt_in_review(self):
        p = self._period(BookingPeriod.WISHES_REVIEW)
        w, err = svc.add_wish(self.m, p, self.q, self.s, self.e)
        self.assertIsNotNone(w, err)

    def test_add_wish_gesperrt_ausserhalb_der_phasen(self):
        p = self._period(BookingPeriod.LOTTERY_REVIEW)
        w, err = svc.add_wish(self.m, p, self.q, self.s, self.e)
        self.assertIsNone(w)
        self.assertIn("keine Wünsche", err)

    def test_wishlist_seite_bedient_review_phase(self):
        p = self._period(BookingPeriod.WISHES_REVIEW)
        self.client.force_login(self.m.user)
        html = self.client.get(reverse("wishlist")).content.decode()
        self.assertIn("Entzerrungsphase", html)

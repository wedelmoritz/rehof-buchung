"""Integrationstest: NL-Parser-Naht (Service baut Stammdaten aus der DB) + Einbindung
in Wunsch- und Buchungs-Flow (ADR 0103/0108). Zwei getrennte Felder, Vorbelegung."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import (
    BookingPeriod, EquivalenceClass, Member, Membership, Quarter, SchoolHoliday,
    Share,
)

NEXT = date.today().year + 1


def _member(name):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


class NlServiceTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        # KONFIGURIERTE, benannte Ferien (materialisiert ins Zieljahr).
        SchoolHoliday.objects.create(name="Herbstferien", start_month=10,
                                     start_day=20, end_month=11, end_day=1)
        self.period = BookingPeriod.objects.create(
            name="P", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
            wishlist_close=date.today(), status=BookingPeriod.WISHES_OPEN)

    def test_nl_parse_wish_nutzt_konfigurierte_stammdaten(self):
        intent = svc.nl_parse_wish("in den Herbstferien ins Turmzimmer", self.period)
        self.assertEqual(intent.start, date(NEXT, 10, 20))
        self.assertEqual(intent.end, date(NEXT, 11, 1))
        self.assertEqual(intent.quarter_key, self.q.id)

    def test_nl_parse_booking_personen_und_barrierefrei(self):
        intent = svc.nl_parse_booking(
            "ab 12.7. für eine Woche, 4 Personen, barrierefrei", NEXT)
        self.assertEqual(intent.start, date(NEXT, 7, 12))
        self.assertEqual(intent.end, date(NEXT, 7, 19))
        self.assertEqual(intent.persons, 4)
        self.assertIs(intent.accessible, True)


class NlWishlistViewTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.period = BookingPeriod.objects.create(
            name="P", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
            wishlist_close=date.today(), status=BookingPeriod.WISHES_OPEN)
        self.m = _member("anna")
        self.client.force_login(self.m.user)

    def test_freitext_fuellt_vor_und_zeigt_vorschau(self):
        url = reverse("wishlist") + "?view=neu&nlq=" + \
            "12.7. bis 19.7. ins Turmzimmer".replace(" ", "+")
        html = self.client.get(url).content.decode()
        self.assertIn("Verstanden", html)          # Vorschau-Banner
        self.assertIn("vorgeschlagen", html)        # Kandidat markiert
        # Der geparste Zeitraum ist als Auswahl übernommen (Kandidaten-Formular).
        self.assertIn(f'value="{NEXT}-07-12"', html)


class NlBookViewTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=6)
        self.m = _member("bob")
        self.client.force_login(self.m.user)

    def test_freitext_fuellt_personen_und_barrierefrei_vor(self):
        url = reverse("book") + "?nlq=" + \
            "4 Personen barrierefrei".replace(" ", "+")
        html = self.client.get(url).content.decode()
        self.assertIn("Verstanden", html)
        # Personenzahl vorbelegt + Barrierefrei-Haken gesetzt.
        self.assertIn('name="persons" value="4"', html)
        self.assertIn('name="accessible" value="1" checked', html)

"""Integrationstest: NL-Parser-Naht (Service baut Stammdaten aus der DB) + Einbindung
in Wunsch- und Buchungs-Flow (ADR 0103/0108). Zwei getrennte Felder, Vorbelegung."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import (
    Allocation, BookingPeriod, EquivalenceClass, Member, Membership, Quarter,
    SchoolHoliday, Share,
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

    def test_sommerwoche_zeigt_meintest_du_chips(self):
        # „Sommerwoche" ist mehrdeutig (Juli/August/Juni) → bester Vorschlag vorbelegt,
        # Alternativen als „Meintest du…?"-Chips (1-Klick-Links).
        html = self.client.get(
            reverse("wishlist") + "?view=neu&nlq=Sommerwoche").content.decode()
        self.assertIn("Meintest du eher", html)
        # Chips verweisen auf konkrete Alternativ-Zeiträume (August/Juni).
        self.assertIn(f"start={NEXT}-08-01", html)
        self.assertIn(f"start={NEXT}-06-01", html)


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


class NlMonatAufloesungTests(TestCase):
    """Grober Zeitwunsch ohne Startdatum („eine Woche im Juli") → der Service schlägt
    das erste (freie) Datum vor, statt „kein Startdatum" zu melden (ADR 0108-Nachtrag)."""

    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        # Freigabe fürs ganze Zieljahr (für die Buchungs-Freiheitsprüfung).
        self.period = BookingPeriod.objects.create(
            name=f"g{NEXT}", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), status=BookingPeriod.FREE_BOOKING)

    def test_wunsch_grober_monat_bekommt_startdatum(self):
        intent = svc.nl_parse_wish("eine woche im juli", self.period)
        self.assertIsNotNone(intent.start)
        self.assertEqual(intent.start.month, 7)
        self.assertEqual(intent.start.year, NEXT)
        self.assertEqual(intent.end, intent.start + timedelta(days=7))
        self.assertTrue(any("vorgeschlagen" in m for m in intent.matched))
        self.assertFalse(any("kein Startdatum" in u for u in intent.unresolved))

    def test_buchung_grober_monat_erstes_freies_datum(self):
        intent = svc.nl_parse_booking("eine woche im juli ins turm", year=NEXT)
        self.assertEqual(intent.quarter_key, self.q.id)   # Unterkunft erkannt
        self.assertIsNotNone(intent.start)
        self.assertEqual(intent.start.month, 7)
        self.assertEqual(intent.end, intent.start + timedelta(days=7))

    def test_buchung_ueberspringt_belegte_tage(self):
        # Turm im ersten Juli-Drittel belegt → der Vorschlag liegt danach.
        Allocation.objects.create(
            member=_member("occ1"), quarter=self.q,
            start=date(NEXT, 7, 1), end=date(NEXT, 7, 20),
            source="spontaneous", provisional=False)
        intent = svc.nl_parse_booking("eine woche im juli ins turm", year=NEXT)
        self.assertIsNotNone(intent.start)
        self.assertGreaterEqual(intent.start, date(NEXT, 7, 20))

    def test_buchung_monat_komplett_belegt_meldet_ehrlich(self):
        Allocation.objects.create(
            member=_member("occ2"), quarter=self.q,
            start=date(NEXT, 7, 1), end=date(NEXT, 8, 1),
            source="spontaneous", provisional=False)
        intent = svc.nl_parse_booking("eine woche im juli ins turm", year=NEXT)
        self.assertIsNone(intent.start)
        self.assertTrue(any("keine passende freie Zeit" in u
                            for u in intent.unresolved))

    def test_wunsch_jahreszeit_liefert_mehrere_vorschlaege(self):
        # „Sommerwoche" → Kandidaten Juli/August/Juni; bester vorbelegt, Rest als
        # Alternativen in intent.suggestions (für die „Meintest du…?"-Chips).
        intent = svc.nl_parse_wish("Sommerwoche", self.period)
        self.assertEqual(intent.start, date(NEXT, 7, 1))
        self.assertEqual(intent.end, date(NEXT, 7, 8))
        months = [s["start"].month for s in intent.suggestions]
        self.assertEqual(months, [7, 8, 6])

    def test_buchung_jahreszeit_ueberspringt_belegten_monat(self):
        # Ganzer Juli belegt → der beste Vorschlag ist der August (Juli fällt raus).
        Allocation.objects.create(
            member=_member("occ3"), quarter=self.q,
            start=date(NEXT, 7, 1), end=date(NEXT, 8, 1),
            source="spontaneous", provisional=False)
        intent = svc.nl_parse_booking("Sommerwoche ins turm", year=NEXT)
        self.assertIsNotNone(intent.start)
        self.assertEqual(intent.start.month, 8)
        # Kein Vorschlag liegt im (voll belegten) Juli.
        self.assertFalse(any(s["start"].month == 7 for s in intent.suggestions))

    def test_relativ_naechste_woche_ohne_alternativen(self):
        intent = svc.nl_parse_booking("nächste Woche ins turm", year=NEXT)
        self.assertIsNotNone(intent.start)
        self.assertEqual(intent.suggestions, [])   # konkret → keine Chips

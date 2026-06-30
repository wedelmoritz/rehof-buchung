"""Tests für die neuen Buchungsrichtlinien (ADR 0075):

* Spontan-Vorausfrist (`BookingPolicy.min_lead_days`) – konfigurierbar,
* Lückenfüllung (`allow_gap_fill`) hebt Mindestnächte UND Vorausfrist auf,
* „begehrte Zeiten" (`high_demand_periods`) für den Rücksichts-Hinweis,
* Winter-Richtwert (`winter_usage`).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from booking import services as svc
from booking.models import (
    Allocation, BookingPeriod, BookingPolicy, EquivalenceClass, Member,
    Membership, Quarter, SchoolHoliday, SeasonRule, Share,
)

TODAY = date.today()


def mk_member(name, nights=50):
    u = User.objects.create_user(username=name, password="x" * 12)
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(
        eg_number=f"EG-{name}", label=name,
        annual_night_budget=nights, wish_night_budget=nights // 2)
    Share.objects.create(membership=ms, member=m,
                         night_budget=nights, wish_night_budget=nights // 2)
    return m


class PolicyBase(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(
            name="Q", eq_class=self.cls, min_occupancy=1, max_occupancy=4)
        self.alice = mk_member("alice")
        # Ganzjährige Freigabe über zwei Jahre (heute + Zukunft sicher abgedeckt).
        BookingPeriod.objects.create(
            name="global", target_year=TODAY.year,
            start=date(TODAY.year, 1, 1), end=date(TODAY.year + 2, 1, 1),
            status=BookingPeriod.FREE_BOOKING)
        self.policy = BookingPolicy.get_solo()
        self.policy.default_min_nights = 3
        self.policy.min_lead_days = 7
        self.policy.allow_gap_fill = True
        self.policy.save()

    def _alloc(self, start, end):
        """Belegung direkt anlegen (umgeht Service-Regeln, um Nachbarn zu setzen)."""
        return Allocation.objects.create(
            member=self.alice, quarter=self.q, start=start, end=end,
            persons=2, source="spontaneous",
            membership=self.alice.membership_for())


class LeadTimeTests(PolicyBase):
    def test_blockt_kurzfristig(self):
        s = TODAY + timedelta(days=3)
        a, err = svc.book_spontaneous(self.alice, self.q, s, s + timedelta(days=4))
        self.assertIsNone(a)
        self.assertIn("Vorlauf", err)

    def test_erlaubt_mit_genug_vorlauf(self):
        s = TODAY + timedelta(days=10)
        a, err = svc.book_spontaneous(self.alice, self.q, s, s + timedelta(days=4))
        self.assertIsNotNone(a, err)

    def test_konfigurierbar_aus(self):
        self.policy.min_lead_days = 0
        self.policy.save(update_fields=["min_lead_days"])
        s = TODAY + timedelta(days=1)
        a, err = svc.book_spontaneous(self.alice, self.q, s, s + timedelta(days=4))
        self.assertIsNotNone(a, err)


class GapFillTests(PolicyBase):
    def test_fuellt_luecke_unter_mindestnaechten(self):
        # Nachbarn weit genug in der Zukunft (Vorausfrist spielt keine Rolle),
        # lassen eine 2-Nächte-Lücke; die ist < Mindestnächte (3), füllt aber
        # die Lücke exakt → erlaubt.
        a = TODAY + timedelta(days=20)
        self._alloc(a, a + timedelta(days=3))                 # [a, a+3)
        self._alloc(a + timedelta(days=5), a + timedelta(days=8))  # [a+5, a+8)
        gap_start, gap_end = a + timedelta(days=3), a + timedelta(days=5)
        alloc, err = svc.book_spontaneous(self.alice, self.q, gap_start, gap_end)
        self.assertIsNotNone(alloc, err)
        self.assertEqual(alloc.nights, 2)

    def test_abschaltbar(self):
        self.policy.allow_gap_fill = False
        self.policy.save(update_fields=["allow_gap_fill"])
        a = TODAY + timedelta(days=20)
        self._alloc(a, a + timedelta(days=3))
        self._alloc(a + timedelta(days=5), a + timedelta(days=8))
        alloc, err = svc.book_spontaneous(
            self.alice, self.q, a + timedelta(days=3), a + timedelta(days=5))
        self.assertIsNone(alloc)
        self.assertIn("Mindestbuchung", err)

    def test_teilweise_luecke_bleibt_gesperrt(self):
        # Freier Raum, aber nur teilweise belegt → 2 Nächte ohne exakte Füllung.
        a = TODAY + timedelta(days=20)
        self._alloc(a, a + timedelta(days=3))                 # [a, a+3)
        # Lücke ab a+3 ist groß/offen; 2 Nächte mittendrin füllen sie NICHT aus.
        alloc, err = svc.book_spontaneous(
            self.alice, self.q, a + timedelta(days=10), a + timedelta(days=12))
        self.assertIsNone(alloc)
        self.assertIn("Mindestbuchung", err)

    def test_luecke_ist_von_vorausfrist_ausgenommen(self):
        # Nachbarn nah an heute (direkt angelegt), Lücke innerhalb der 7 Tage.
        self._alloc(TODAY + timedelta(days=1), TODAY + timedelta(days=2))
        self._alloc(TODAY + timedelta(days=4), TODAY + timedelta(days=6))
        alloc, err = svc.book_spontaneous(
            self.alice, self.q, TODAY + timedelta(days=2), TODAY + timedelta(days=4))
        self.assertIsNotNone(alloc, err)
        self.assertEqual(alloc.nights, 2)


class HighDemandTests(PolicyBase):
    def test_erkennt_feiertag_und_ferien(self):
        SeasonRule.objects.create(
            name="Pfingsten", start_month=5, start_day=22, end_month=5,
            end_day=27, max_parallel_units=2, active=True)
        SchoolHoliday.objects.create(
            name="Sommerferien", start_month=7, start_day=9, end_month=8,
            end_day=23, region="Berlin", active=True)
        names = svc.high_demand_periods(date(TODAY.year, 5, 23),
                                        date(TODAY.year, 5, 25))
        self.assertIn("Pfingsten", names)
        # Normaler Zeitraum ohne begehrte Zeit:
        self.assertEqual(
            svc.high_demand_periods(date(TODAY.year, 3, 3),
                                    date(TODAY.year, 3, 6)), [])


class PolicyViewRenderTests(PolicyBase):
    """Smoke: die neuen Template-Zweige (Rücksichts-Hinweis, Gruppen-Reihung,
    Winter-Chip, Hilfe-Abschnitt) rendern fehlerfrei."""

    def setUp(self):
        super().setUp()
        self.q.prefer_for_groups = True
        self.q.building = "Stallgebäude"
        self.q.save(update_fields=["prefer_for_groups", "building"])
        SeasonRule.objects.create(
            name="Pfingsten", start_month=5, start_day=22, end_month=5,
            end_day=27, max_parallel_units=2, active=True)
        self.client.force_login(self.alice.user)

    def test_book_zeigt_hinweis_und_gruppen_reihung(self):
        s = date(TODAY.year, 5, 23)
        r = self.client.get(
            f"/buchen/?start={s.isoformat()}&end={(s + timedelta(days=3)).isoformat()}"
            f"&persons=4&year={s.year}&month={s.month}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Begehrte Zeit")
        self.assertContains(r, "Stallgebäude")

    def test_overview_winter_chip(self):
        self.assertContains(self.client.get("/"), "Winter")

    def test_hilfe_regeln_abschnitt(self):
        r = self.client.get("/hilfe/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Buchungsregeln")
        self.assertContains(r, "Lücken füllen")


class WinterUsageTests(PolicyBase):
    def test_zaehlt_oktober_maerz_mindestwert(self):
        # 20 Tage gelten auf den vollen Anteil (50) → Ziel 20.
        win = svc.winter_usage(self.alice, ref_date=date(TODAY.year, 11, 1))
        self.assertEqual(win["booked"], 0)
        self.assertEqual(win["target"], 20)
        self.assertFalse(win["reached"])
        Allocation.objects.create(
            member=self.alice, quarter=self.q,
            start=date(TODAY.year, 11, 10), end=date(TODAY.year, 11, 14),
            persons=2, source="spontaneous", membership=self.alice.membership_for())
        win = svc.winter_usage(self.alice, ref_date=date(TODAY.year, 11, 20))
        self.assertEqual(win["booked"], 4)

    def test_tandem_anteilig(self):
        # Halber Anteil (25 Tage) → Winter-Ziel anteilig 10.
        bob = mk_member("bobtandem", nights=25)
        self.assertEqual(svc.winter_usage(bob)["target"], 10)


class WeekendUsageTests(PolicyBase):
    def _friday(self, month):
        d = date(TODAY.year, month, 1)
        while d.weekday() != 4:                      # nächster Freitag
            d += timedelta(days=1)
        return d

    def test_zaehlt_distinkte_wochenenden(self):
        f1 = self._friday(7)
        self._alloc(f1, f1 + timedelta(days=2))                 # Fr+Sa → 1 WE
        self._alloc(f1 + timedelta(days=14), f1 + timedelta(days=16))  # 2 Wo später
        we = svc.weekend_usage(self.alice, ref_date=date(TODAY.year, 7, 1))
        self.assertEqual(we["booked"], 2)
        self.assertEqual(we["target"], 9)
        self.assertFalse(we["near"])

    def test_near_und_over(self):
        self.policy.max_weekends_per_year = 2
        self.policy.save(update_fields=["max_weekends_per_year"])
        f1 = self._friday(8)
        self._alloc(f1, f1 + timedelta(days=2))
        we = svc.weekend_usage(self.alice, ref_date=date(TODAY.year, 8, 1))
        self.assertTrue(we["near"])     # 1 von 2 → nah dran (>= target-1)
        self.assertFalse(we["over"])


class UndersizedTests(PolicyBase):
    def test_erlaubt_wenn_konfiguriert(self):
        self.policy.allow_undersized_units = True
        self.policy.save(update_fields=["allow_undersized_units"])
        s = TODAY + timedelta(days=10)
        a, err = svc.book_spontaneous(self.alice, self.q, s, s + timedelta(days=4),
                                      persons=6)   # q ist für max 4 ausgelegt
        self.assertIsNotNone(a, err)
        self.assertEqual(a.persons, 6)

    def test_gesperrt_wenn_aus(self):
        self.policy.allow_undersized_units = False
        self.policy.save(update_fields=["allow_undersized_units"])
        s = TODAY + timedelta(days=10)
        a, err = svc.book_spontaneous(self.alice, self.q, s, s + timedelta(days=4),
                                      persons=6)
        self.assertIsNone(a)
        self.assertIn("Personen", err)


class PolicySummaryTests(PolicyBase):
    def test_liest_konfiguration(self):
        SeasonRule.objects.create(
            name="Hochsaison", start_month=7, start_day=1, end_month=9, end_day=1,
            min_nights=7, active=True)
        SeasonRule.objects.create(
            name="Sommerferien", start_month=7, start_day=9, end_month=8, end_day=23,
            max_parallel_units=2, max_stay_nights=14, active=True)
        s = svc.booking_policy_summary()
        self.assertEqual(s["default_min_nights"], 3)
        self.assertEqual(s["min_lead_days"], 7)
        self.assertEqual(s["season_min_nights"], 7)
        self.assertIn("Hochsaison", s["season_min_names"])
        self.assertEqual(s["parallel_limit"], 2)
        self.assertEqual(s["stay_cap_nights"], 14)
        self.assertEqual(s["stay_cap_weeks"], 2)
        self.assertTrue(s["allow_undersized"])

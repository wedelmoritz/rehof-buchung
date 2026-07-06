"""Tests für den Solidaritäts-/Schenkungs-Pool für Tage (P2.5, ADR 0064)."""
from datetime import date

from django.test import TestCase

from booking import services as svc
from booking.tests_usecases import make_member

YEAR = date.today().year


class PoolTests(TestCase):
    def setUp(self):
        self.donor = make_member("donor", nights=50)
        self.needy = make_member("needy", nights=5)   # remaining 5 → „bei Bedarf"

    def test_spende_reduziert_budget_und_fuellt_pool(self):
        e, err = svc.pool_donate(self.donor, 20, YEAR)
        self.assertIsNotNone(e, err)
        self.assertEqual(svc.pool_balance(YEAR), 20)
        self.assertEqual(self.donor.nights_remaining_in_year(YEAR), 30)

    def test_kann_nicht_mehr_spenden_als_vorhanden(self):
        e, err = svc.pool_donate(self.donor, 999, YEAR)
        self.assertIsNone(e)
        self.assertIn("nur noch", err)

    def test_entnahme_nur_bei_bedarf(self):
        svc.pool_donate(self.donor, 20, YEAR)
        # donor hat 30 übrig (> Schwelle 5) → nicht berechtigt.
        e, err = svc.pool_withdraw(self.donor, 3, YEAR)
        self.assertIsNone(e)
        self.assertIn("fast aufgebraucht", err)

    def test_entnahme_gedeckelt_und_erhoeht_budget(self):
        svc.pool_donate(self.donor, 20, YEAR)
        # needy hat 5 übrig (≤ Schwelle) → berechtigt; aber Deckel 10/Jahr.
        e, err = svc.pool_withdraw(self.needy, 11, YEAR)
        self.assertIsNone(e); self.assertIn("höchstens", err)
        e2, err2 = svc.pool_withdraw(self.needy, 4, YEAR)
        self.assertIsNotNone(e2, err2)
        self.assertEqual(self.needy.nights_remaining_in_year(YEAR), 9)
        self.assertEqual(svc.pool_balance(YEAR), 16)

    def test_nach_aufstockung_nicht_mehr_berechtigt(self):
        svc.pool_donate(self.donor, 20, YEAR)
        svc.pool_withdraw(self.needy, 4, YEAR)   # remaining 5 → 9
        e, err = svc.pool_withdraw(self.needy, 1, YEAR)
        self.assertIsNone(e)
        self.assertIn("fast aufgebraucht", err)

    def test_entnahme_nicht_mehr_als_im_pool(self):
        # needy berechtigt (5 übrig), aber Pool leer.
        e, err = svc.pool_withdraw(self.needy, 3, YEAR)
        self.assertIsNone(e)
        self.assertIn("Pool", err)

    def test_status_dict(self):
        svc.pool_donate(self.donor, 8, YEAR)
        st = svc.pool_status(self.needy, YEAR)
        self.assertEqual(st["balance"], 8)
        self.assertTrue(st["eligible_to_withdraw"])
        self.assertEqual(st["max_withdraw"], 8)   # min(balance 8, cap 10)

    def test_zeit_riegel_sperrt_entnahme(self):
        # Optionaler Zeit-Riegel (ADR 0099): Entnahme erst ab einem späteren Monat.
        from booking.models import BookingPolicy
        p = BookingPolicy.get_solo()
        p.pool_withdraw_from_month = 12 if date.today().month < 12 else 1
        # sicher in der Zukunft: nächster Monat (oder Dezember)
        future = date.today().month + 1
        p.pool_withdraw_from_month = future if future <= 12 else 12
        p.save(update_fields=["pool_withdraw_from_month"])
        svc.pool_donate(self.donor, 20, YEAR)
        e, err = svc.pool_withdraw(self.needy, 3, YEAR)
        if date.today().month < p.pool_withdraw_from_month:
            self.assertIsNone(e)
            self.assertIn("erst ab", err)
            self.assertFalse(svc.pool_status(self.needy, YEAR)["time_ok"])

    def test_konfigurierbare_schwelle(self):
        # Schwelle im Backend hochsetzen → auch wer mehr übrig hat, ist berechtigt.
        from booking.models import BookingPolicy
        mid = make_member("mid", nights=20)          # 20 übrig
        svc.pool_donate(self.donor, 10, YEAR)
        # Mit Default-Schwelle 5 ist mid NICHT berechtigt.
        e, err = svc.pool_withdraw(mid, 2, YEAR)
        self.assertIsNone(e)
        # Schwelle auf 25 → mid (20 übrig) ist jetzt berechtigt.
        p = BookingPolicy.get_solo()
        p.pool_eligible_remaining = 25
        p.save(update_fields=["pool_eligible_remaining"])
        e2, err2 = svc.pool_withdraw(mid, 2, YEAR)
        self.assertIsNotNone(e2, err2)
        self.assertEqual(mid.nights_remaining_in_year(YEAR), 22)

    def test_transfer_seite_zeigt_pool_und_spende_per_post(self):
        from django.urls import reverse
        self.client.force_login(self.donor.user)
        r = self.client.get(reverse("transfer"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Solidaritäts-Pool")
        r2 = self.client.post(reverse("transfer"),
                              {"action": "pool_donate", "nights": "6"})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(svc.pool_balance(YEAR), 6)

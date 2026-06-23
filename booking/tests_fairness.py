"""Integrationstests für den Fairness-Nachweis (Seite + Admin-Lauf)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import FairnessSimConfig, Member


class FairnessPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u1", password="pw12345")
        Member.objects.create(user=self.user, display_name="U Eins")

    def test_seite_braucht_login(self):
        r = self.client.get(reverse("lottery_fairness"))
        self.assertEqual(r.status_code, 302)  # redirect auf Login

    def test_seite_zeigt_hinweis_ohne_ergebnis(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("lottery_fairness"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "noch kein Ergebnis")

    def test_seite_zeigt_grafen_nach_lauf(self):
        cfg = FairnessSimConfig.get_solo()
        cfg.n_users, cfg.n_items, cfg.n_runs = 8, 3, 800
        cfg.save()
        svc.run_fairness_simulation(cfg)
        self.client.force_login(self.user)
        r = self.client.get(reverse("lottery_fairness"))
        self.assertContains(r, "Chi-Quadrat")
        self.assertContains(r, "<svg")
        self.assertContains(r, "Karma")


class FairnessAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.org", "pw12345")

    def test_admin_button_startet_simulation(self):
        self.client.force_login(self.admin)
        cfg = FairnessSimConfig.get_solo()
        cfg.n_users, cfg.n_items, cfg.n_runs = 6, 2, 500
        cfg.save()
        url = reverse("admin:booking_fairnesssimconfig_change", args=[cfg.id])
        r = self.client.post(url, {
            "n_users": 6, "n_items": 2, "n_runs": 500, "_run_sim": "1"})
        self.assertEqual(r.status_code, 302)
        cfg.refresh_from_db()
        self.assertIsNotNone(cfg.last_result)
        self.assertIn("equal", cfg.last_result)

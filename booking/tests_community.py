"""Tests für den Gemeinschafts-Spiegel + Karma-Transparenz (ADR 0063)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import Member


class KarmaDistributionTests(TestCase):
    def test_buckets_und_aggregat(self):
        for i, f in enumerate([1.0, 1.0, 1.2, 1.5]):
            u = User.objects.create_user(f"m{i}", password="pw12345")
            Member.objects.create(user=u, display_name=f"M{i}", factor=f)
        dist = svc.karma_distribution()
        self.assertEqual(dist["total"], 4)
        by = {r["factor"]: r["count"] for r in dist["rows"]}
        self.assertEqual(by[1.0], 2)
        self.assertEqual(by[1.2], 1)
        self.assertEqual(by[1.5], 1)
        # Es gibt für jeden 0,1-Schritt 1,0…1,5 eine Zeile (auch leere).
        self.assertEqual(len(dist["rows"]), 6)

    def test_externe_zaehlen_nicht_mit(self):
        u = User.objects.create_user("g", password="pw12345")
        Member.objects.create(user=u, display_name="Gast", factor=1.3,
                              is_external=True)
        self.assertEqual(svc.karma_distribution()["total"], 0)


class CommunityViewTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()   # gecachte community_stats nicht zwischen Tests verschleppen
        self.u = User.objects.create_user("a", password="pw12345")
        self.m = Member.objects.create(user=self.u, display_name="A", factor=1.1)

    def test_seite_erreichbar_und_zeigt_aggregate(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("community"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gemeinschafts-Spiegel")
        self.assertContains(r, "Auslastung")

    def test_login_noetig(self):
        r = self.client.get(reverse("community"))
        self.assertEqual(r.status_code, 302)  # Login-Redirect

    def test_wunschliste_zeigt_eigenen_faktor(self):
        # Der Ausgleichsfaktor steht jetzt auf der Wunschliste (ADR 0073),
        # nicht mehr im Profil/unter Buchungen.
        self.client.force_login(self.u)
        r = self.client.get(reverse("wishlist"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ausgleichsfaktor")
        # nicht mehr im Profil
        self.assertNotContains(self.client.get(reverse("profile")), "Ausgleichsfaktor")

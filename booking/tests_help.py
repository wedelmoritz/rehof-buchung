"""Integration: ausgelagerte Hilfetexte (ADR 0093) werden geladen + sicher gerendert."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking.models import Member
from booking import services as svc


class HelpSectionsTests(TestCase):
    def test_help_sections_geladen_und_verlinkt(self):
        secs = svc.help_sections()
        self.assertIn("warteliste", secs)
        self.assertIn("Warteliste", secs["warteliste"]["title"])
        # Der $url_my_bookings-Platzhalter wurde zu einem echten Pfad aufgelöst.
        self.assertIn(reverse("my_bookings"), secs["warteliste"]["html"])
        self.assertNotIn("$url_my_bookings", secs["warteliste"]["html"])

    def test_help_seite_zeigt_ausgelagerte_abschnitte(self):
        u = User.objects.create_user("hilde", "hilde@example.org", "x" * 12)
        Member.objects.create(user=u, display_name="Hilde")
        self.client.force_login(u)
        r = self.client.get(reverse("help"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        self.assertIn('id="warteliste"', body)
        self.assertIn("Solidaritäts-Pool", body)      # aus gemeinschaft.md
        self.assertIn("Sammelrechnung", body)         # aus hofladen.md

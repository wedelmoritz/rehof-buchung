"""Tests für das Rate-Limiting sensibler Endpunkte (django-ratelimit, ADR 0061).

In Tests ist RATELIMIT_ENABLE standardmäßig aus (damit die übrigen Suiten nicht
an Limits laufen). Hier wird es gezielt scharf geschaltet und der Block geprüft.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings


class RegisterRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()   # Zähler je Test frisch

    @override_settings(RATELIMIT_ENABLE=True)
    def test_registrierung_wird_nach_limit_geblockt(self):
        # Limit: 10 POSTs/Stunde je IP → der 11. muss 403 (Ratelimited) liefern.
        last = None
        for _ in range(11):
            last = self.client.post("/registrieren/", {})
        self.assertEqual(last.status_code, 403)

    @override_settings(RATELIMIT_ENABLE=False)
    def test_ohne_aktivierung_kein_block(self):
        # Default in Tests: aus → viele POSTs bleiben erlaubt (kein 403).
        for _ in range(12):
            r = self.client.post("/registrieren/", {})
            self.assertNotEqual(r.status_code, 403)

"""Tests für Batch-F-Härtung (ADR 0061, P3.9/P3.11).

Sicherheits-Header (Permissions-Policy, Cross-Origin-Resource-Policy + Embed-
Ausnahme), die Member-Scope-Korrektur am Push-Abmelde-Endpunkt und der
WeasyPrint-URL-Fetcher (SSRF-Schutz).
"""
from django.contrib.auth.models import User
from django.test import TestCase

from booking.models import Member, PushSubscription


class SecurityHeaderTests(TestCase):
    def test_permissions_policy_und_corp(self):
        r = self.client.get("/offline/")
        self.assertIn("Permissions-Policy", r)
        self.assertIn("camera=()", r["Permissions-Policy"])
        self.assertEqual(r["Cross-Origin-Resource-Policy"], "same-origin")

    def test_embed_corp_cross_origin(self):
        r = self.client.get("/extern/widget/")
        self.assertEqual(r["Cross-Origin-Resource-Policy"], "cross-origin")


class PushUnsubscribeScopeTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("a", password="pw12345")
        self.ma = Member.objects.create(user=self.a, display_name="A")
        self.b = User.objects.create_user("b", password="pw12345")
        self.mb = Member.objects.create(user=self.b, display_name="B")
        self.sub = PushSubscription.objects.create(
            member=self.ma, endpoint="https://push.example/aaa",
            p256dh="x", auth="y")

    def test_fremder_kann_abo_nicht_loeschen(self):
        # B versucht, das Abo von A über den (bekannten) Endpoint zu entfernen.
        self.client.force_login(self.b)
        r = self.client.post("/push/abmelden/",
                             data='{"endpoint": "https://push.example/aaa"}',
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(PushSubscription.objects.filter(pk=self.sub.pk).exists())

    def test_eigentuemer_kann_abo_loeschen(self):
        self.client.force_login(self.a)
        r = self.client.post("/push/abmelden/",
                             data='{"endpoint": "https://push.example/aaa"}',
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(PushSubscription.objects.filter(pk=self.sub.pk).exists())


class WeasyPrintFetcherTests(TestCase):
    def test_blockt_remote_urls(self):
        # Der sicherheitsrelevante Teil (Block) läuft ohne WeasyPrint – er wirft,
        # bevor der data:-Pfad das Paket importiert.
        from shop.pdf import _no_remote_fetcher
        with self.assertRaises(ValueError):
            _no_remote_fetcher("https://169.254.169.254/latest/meta-data/")
        with self.assertRaises(ValueError):
            _no_remote_fetcher("file:///etc/passwd")

    def test_erlaubt_data_uri(self):
        from shop.pdf import weasyprint_available, _no_remote_fetcher
        if not weasyprint_available():
            self.skipTest("WeasyPrint/native Libs nicht installiert")
        # data:-URIs sind erlaubt (kein Block). Der Rückgabetyp von WeasyPrints
        # default_url_fetcher variiert je Version (dict ODER URLFetcherResponse) –
        # daher nur prüfen, dass ein Ergebnis OHNE Ausnahme zurückkommt.
        got = _no_remote_fetcher("data:text/plain;base64,aGFsbG8=")
        self.assertIsNotNone(got)

"""Tests für die Content-Security-Policy (nonce-basiert, ADR 0061).

Prüft: (1) der CSP-Header wird gesetzt und ist nonce-basiert (kein 'unsafe-inline'
für Skripte), (2) ausgelieferte <script>-Tags tragen den passenden Nonce,
(3) das einbettbare Externen-Widget lockert frame-ancestors, (4) in den
gerenderten Seiten gibt es keine Inline-Event-Handler mehr.
"""
import re

from django.test import TestCase


class CspHeaderTests(TestCase):
    def _csp(self, resp):
        return resp.headers.get("Content-Security-Policy", "")

    def test_header_ist_nonce_basiert(self):
        r = self.client.get("/offline/")
        csp = self._csp(r)
        self.assertIn("script-src", csp)
        self.assertIn("'nonce-", csp)
        # Kein 'unsafe-inline' im script-src (das wäre der ausgehebelte Schutz).
        script_src = [p for p in csp.split(";") if "script-src" in p][0]
        self.assertNotIn("unsafe-inline", script_src)
        # Starke Zusatz-Direktiven.
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri", csp)
        self.assertIn("frame-ancestors", csp)

    def test_script_tag_traegt_passenden_nonce(self):
        r = self.client.get("/offline/")
        m = re.search(r"'nonce-([A-Za-z0-9+/=_-]+)'", self._csp(r))
        self.assertIsNotNone(m)
        nonce = m.group(1)
        body = r.content.decode()
        self.assertIn('nonce="%s"' % nonce, body)

    def test_embed_lockert_frame_ancestors(self):
        # Das öffentliche Widget muss von fremden Seiten einbettbar bleiben.
        r = self.client.get("/extern/widget/")
        csp = self._csp(r)
        self.assertIn("frame-ancestors *", csp)


class NoInlineHandlerTests(TestCase):
    """Stellt sicher, dass kritische Seiten ohne Inline-Event-Handler rendern
    (sonst würde die strikte CSP sie blockieren). Login-freie Seiten genügen,
    um die gemeinsame base.html + Kalender-Includes abzudecken."""

    PATTERN = re.compile(r"\son(click|submit|change|load|focus|error)\s*=", re.I)

    def test_offline_und_login_ohne_inline_handler(self):
        for url in ("/offline/", "/login/", "/extern/", "/extern/widget/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertIsNone(self.PATTERN.search(r.content.decode()),
                              "Inline-Handler in %s" % url)

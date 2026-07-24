"""NL-L5: die Backend-Review-Seite (ADR 0113). RBAC (nur Admin), Opt-in-Gate,
Übernehmen/Ablehnen/Zurückrollen, keine Inline-Handler (CSP)."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking.models import (
    EquivalenceClass, NlLexiconEntry, NlProposal, OpsConfig, Quarter,
)


class ReviewUiTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.admin = User.objects.create_superuser("admin", "a@b.de", "pw")
        self.member_user = User.objects.create_user("m", password="pw")
        cfg = OpsConfig.get_solo()
        cfg.nl_learning_enabled = True
        cfg.save(update_fields=["nl_learning_enabled"])
        self.url = reverse("nl_proposals")

    def _proposal(self):
        return NlProposal.objects.create(
            kind="alias", dedup_key="alias:tuermchen:%d" % self.q.id,
            payload={"token": "tuermchen", "quarter_id": self.q.id},
            evidence={"distinct_users": 4}, status="open")

    def test_nur_admin(self):
        self.client.force_login(self.member_user)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)          # → dashboard

    def test_gate_bei_deaktiviert(self):
        cfg = OpsConfig.get_solo()
        cfg.nl_learning_enabled = False
        cfg.save(update_fields=["nl_learning_enabled"])
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_seite_zeigt_vorschlag_und_ist_csp_sauber(self):
        self._proposal()
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Turmzimmer", html)
        self.assertIn("tuermchen", html)
        # Keine Inline-Event-Handler (CSP, ADR 0061).
        for h in ("onclick=", "onsubmit=", "onchange="):
            self.assertNotIn(h, html)

    def test_uebernehmen_aktiviert_eintrag(self):
        p = self._proposal()
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {"action": "apply", "proposal": p.id})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, "accepted")
        self.assertTrue(NlLexiconEntry.objects.filter(active=True).exists())

    def test_ablehnen_setzt_status(self):
        p = self._proposal()
        self.client.force_login(self.admin)
        self.client.post(self.url, {"action": "reject", "proposal": p.id})
        p.refresh_from_db()
        self.assertEqual(p.status, "rejected")

    def test_zurueckrollen_deaktiviert(self):
        e = NlLexiconEntry.objects.create(
            kind="alias", dedup_key="alias:tuermchen:%d" % self.q.id,
            payload={"token": "tuermchen", "quarter_id": self.q.id}, active=True)
        self.client.force_login(self.admin)
        self.client.post(self.url, {"action": "retire", "entry": e.id})
        e.refresh_from_db()
        self.assertFalse(e.active)

    def test_leerer_zustand(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertContains(r, "Keine offenen Vorschläge")

    def test_monitoring_kennzahlen_sichtbar(self):
        p = self._proposal()
        from booking import services as svc
        svc.reject_proposal(NlProposal.objects.get(id=p.id), self.admin)
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertContains(r, "abgelehnt")
        self.assertContains(r, "aktiv gelernt")


class StatsServiceTests(TestCase):
    def test_stats_zaehlt_korrekt(self):
        from booking import services as svc
        cls = EquivalenceClass.objects.create(name="K")
        q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                   min_occupancy=1, max_occupancy=4)
        NlProposal.objects.create(kind="alias", dedup_key="a:1",
                                  payload={}, evidence={}, status="open")
        NlProposal.objects.create(kind="alias", dedup_key="a:2",
                                  payload={}, evidence={}, status="accepted")
        NlLexiconEntry.objects.create(kind="alias", dedup_key="a:2",
                                      payload={"token": "x", "quarter_id": q.id},
                                      active=True)
        s = svc.nl_learning_stats()
        self.assertEqual(s["open"], 1)
        self.assertEqual(s["accepted"], 1)
        self.assertEqual(s["entries_active"], 1)

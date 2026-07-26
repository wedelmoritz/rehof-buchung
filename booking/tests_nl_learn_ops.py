"""NL-L2: der Lerner erzeugt aus pseudonymen Signalen robuste Vorschläge (ADR 0113).
Schwerpunkt: Quorum verschiedener Pseudonyme (ein Vielschreiber kippt nichts),
Idempotenz, respektiert Entscheidungen.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from booking import services as svc
from booking.models import (
    EquivalenceClass, NlInteraction, NlProposal, OpsConfig, Quarter,
)

SALT = "test-salt"


def _sig(pseudo, token, quarter_id, *, days_ago, month=7):
    row = NlInteraction.objects.create(
        pseudonym=pseudo, kind="booking", unresolved=[token],
        proposed_quarter_id=None, suggestion_shown=False,
        outcome_at=timezone.now(), chosen_quarter_id=quarter_id, chosen_month=month,
        overridden=True)
    NlInteraction.objects.filter(id=row.id).update(
        created_at=timezone.now() - timedelta(days=days_ago))
    return row


@override_settings(NL_LEARN_SALT=SALT)
class LernerTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        cfg = OpsConfig.get_solo()
        cfg.nl_learning_enabled = True
        cfg.save(update_fields=["nl_learning_enabled"])

    def test_vielschreiber_erzeugt_keinen_vorschlag(self):
        for d in range(30):          # EIN Pseudonym, 30 Signale über 30 Tage
            _sig("HEAVY", "tuermchen", self.q.id, days_ago=d)
        out = svc.mine_nl_proposals()
        self.assertEqual(out["alias"], 0)
        self.assertEqual(NlProposal.objects.count(), 0)

    def test_quorum_verschiedener_pseudonyme_erzeugt_vorschlag(self):
        for i in range(4):           # 4 verschiedene Pseudonyme, über Tage verteilt
            _sig(f"U{i}", "tuermchen", self.q.id, days_ago=i * 3)
        out = svc.mine_nl_proposals()
        self.assertEqual(out["alias"], 1)
        p = NlProposal.objects.get()
        self.assertEqual(p.kind, "alias")
        self.assertEqual(p.payload["token"], "tuermchen")
        self.assertEqual(p.payload["quarter_id"], self.q.id)
        self.assertEqual(p.evidence["distinct_users"], 4)
        self.assertEqual(p.status, "open")

    def test_idempotent_und_respektiert_ablehnung(self):
        for i in range(4):
            _sig(f"U{i}", "tuermchen", self.q.id, days_ago=i * 3)
        svc.mine_nl_proposals()
        p = NlProposal.objects.get()
        # Ablehnen → erneuter Lauf legt NICHTS Neues an.
        p.status = "rejected"
        p.save(update_fields=["status"])
        out = svc.mine_nl_proposals()
        self.assertEqual(out["alias"], 0)
        self.assertEqual(NlProposal.objects.count(), 1)
        self.assertEqual(NlProposal.objects.get().status, "rejected")

    def test_bekannter_token_wird_nicht_vorgeschlagen(self):
        # „turmzimmer" ist ein Quartier-Name-Token → kein Alias-Kandidat.
        for i in range(4):
            _sig(f"U{i}", "turmzimmer", self.q.id, days_ago=i * 3)
        out = svc.mine_nl_proposals()
        self.assertEqual(out["alias"], 0)

    def test_ohne_optin_kein_lauf(self):
        cfg = OpsConfig.get_solo()
        cfg.nl_learning_enabled = False
        cfg.save(update_fields=["nl_learning_enabled"])
        for i in range(4):
            _sig(f"U{i}", "tuermchen", self.q.id, days_ago=i * 3)
        self.assertEqual(svc.mine_nl_proposals(), {"alias": 0, "ranking": 0})

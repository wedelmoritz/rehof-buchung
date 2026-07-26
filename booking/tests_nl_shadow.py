"""NL-L4: die Shadow-Auswertung rechnet den Effekt eines Vorschlags kontrafaktisch
vor (ADR 0113) – Beleg fürs Review, ohne den aktiven Parser zu ändern."""
from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from booking import services as svc
from booking.models import (
    EquivalenceClass, NlInteraction, NlLexiconEntry, NlProposal, Quarter,
)


def _proposal(kind, dedup_key, payload):
    return NlProposal.objects.create(
        kind=kind, dedup_key=dedup_key, payload=payload,
        evidence={"distinct_users": 4}, status=NlProposal.OPEN)


class ShadowEvalTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)

    def _record(self, tokens, quarter_id):
        NlInteraction.objects.create(
            pseudonym="P", kind="wish", unresolved=tokens,
            proposed_quarter_id=None, suggestion_shown=False,
            outcome_at=__import__("django.utils.timezone",
                                  fromlist=["now"]).now(),
            chosen_quarter_id=quarter_id, overridden=True)

    def test_alias_vorschlag_zeigt_neu_geloest(self):
        # Zwei aufgezeichnete Signale, in denen „tuermchen" auf das Quartier fiel.
        self._record(["tuermchen"], self.q.id)
        self._record(["tuermchen"], self.q.id)
        p = _proposal("alias", "alias:tuermchen:%d" % self.q.id,
                      {"token": "tuermchen", "quarter_id": self.q.id})
        out = svc.nl_shadow_eval(p)
        self.assertTrue(out["golden_ok"])
        self.assertEqual(out["replay_sample"], 2)
        self.assertEqual(out["newly_resolved"], 2)
        self.assertEqual(out["changed"], 0)

    def test_alias_aendert_bestehende_aufloesung_nicht(self):
        # Eingabe, die schon per Quartier-Name gelöst ist → Alias darf nichts ändern.
        self._record(["turmzimmer"], self.q.id)
        p = _proposal("alias", "alias:tuermchen:%d" % self.q.id,
                      {"token": "tuermchen", "quarter_id": self.q.id})
        out = svc.nl_shadow_eval(p)
        self.assertEqual(out["changed"], 0)
        self.assertEqual(out["newly_resolved"], 0)

    def test_ranking_vorschlag_meldet_golden_regression(self):
        p = _proposal("ranking", "ranking:sommer:8",
                      {"season": "sommer", "month": 8, "new_order": [8, 7, 6]})
        out = svc.nl_shadow_eval(p)
        self.assertFalse(out["golden_ok"])
        self.assertTrue(any("sommerwoche" in d for d in out["golden_regressions"]))

    def test_ohne_signale_leere_aber_ehrliche_struktur(self):
        p = _proposal("alias", "alias:nest:%d" % self.q.id,
                      {"token": "nest", "quarter_id": self.q.id})
        out = svc.nl_shadow_eval(p)
        self.assertEqual(out["replay_sample"], 0)
        self.assertEqual(out["newly_resolved"], 0)
        self.assertTrue(out["golden_ok"])

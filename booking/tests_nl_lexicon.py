"""NL-L3: das aktive, bestätigte Lexikon + Übernehmen/Ablehnen/Rollback (ADR 0113).
Schwerpunkt: gehärtetes Schreiben (Allowlist/Ambiguität/Konflikt), deterministische
Injektion in den Parser (Gelerntes ist Daten, nie Code), Rollback wirkt sofort.
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from booking import services as svc
from booking import wish_nl
from booking.models import (
    BookingPeriod, EquivalenceClass, NlLexiconEntry, NlProposal, Quarter,
)


def _proposal(kind, dedup_key, payload, **kw):
    return NlProposal.objects.create(
        kind=kind, dedup_key=dedup_key, payload=payload,
        evidence=kw.get("evidence", {"distinct_users": 4}),
        status=kw.get("status", NlProposal.OPEN))


class LexikonAufbauTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.admin = User.objects.create_user("admin", is_superuser=True,
                                               is_staff=True)

    def test_active_lexicon_baut_aliase_und_rankings(self):
        NlLexiconEntry.objects.create(
            kind=NlLexiconEntry.ALIAS, dedup_key="alias:tuermchen:%d" % self.q.id,
            payload={"token": "tuermchen", "quarter_id": self.q.id}, active=True)
        NlLexiconEntry.objects.create(
            kind=NlLexiconEntry.RANKING, dedup_key="ranking:sommer:8",
            payload={"season": "sommer", "order": [8, 7, 6]}, active=True)
        # inaktiver Eintrag zählt nicht
        NlLexiconEntry.objects.create(
            kind=NlLexiconEntry.ALIAS, dedup_key="alias:x:%d" % self.q.id,
            payload={"token": "veraltet", "quarter_id": self.q.id}, active=False)
        lex = svc.nl_active_lexicon()
        self.assertEqual(lex["aliases"], {"tuermchen": self.q.id})
        self.assertEqual(lex["rankings"], {"sommer": [8, 7, 6]})
        self.assertNotIn("veraltet", lex["aliases"])

    def test_alias_wirkt_im_echten_parser(self):
        """Ende-zu-Ende über die Service-Naht: ein bestätigter Alias lässt den Parser
        das Quartier erkennen – ohne Code-Änderung, rein über injizierte Daten."""
        NlLexiconEntry.objects.create(
            kind=NlLexiconEntry.ALIAS, dedup_key="alias:tuermchen:%d" % self.q.id,
            payload={"token": "tuermchen", "quarter_id": self.q.id}, active=True)
        y = date.today().year + 1
        period = BookingPeriod.objects.create(
            name=f"P{y}", target_year=y, start=date(y, 1, 1),
            end=date(y + 1, 1, 1), status=BookingPeriod.FREE_BOOKING)
        intent = svc.nl_parse_wish("tuermchen 5 nächte", period)
        self.assertEqual(intent.quarter_key, self.q.id)

    def test_ohne_lexikon_kein_treffer(self):
        y = date.today().year + 1
        period = BookingPeriod.objects.create(
            name=f"P{y}", target_year=y, start=date(y, 1, 1),
            end=date(y + 1, 1, 1), status=BookingPeriod.FREE_BOOKING)
        intent = svc.nl_parse_wish("tuermchen 5 nächte", period)
        self.assertIsNone(intent.quarter_key)


class UebernehmenHaertungTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Seeblick", eq_class=cls,
                                         min_occupancy=1, max_occupancy=4)
        self.admin = User.objects.create_user("admin", is_superuser=True)

    def test_uebernehmen_legt_aktiven_eintrag_an(self):
        p = _proposal("alias", "alias:tuermchen:%d" % self.q.id,
                      {"token": "tuermchen", "quarter_id": self.q.id})
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(err)
        self.assertTrue(entry.active)
        self.assertEqual(entry.approved_by, self.admin)
        p.refresh_from_db()
        self.assertEqual(p.status, NlProposal.ACCEPTED)
        self.assertEqual(svc.nl_active_lexicon()["aliases"],
                         {"tuermchen": self.q.id})

    def test_bekanntes_wort_wird_abgelehnt(self):
        # „turmzimmer" ist ein Quartier-Name-Token → Ambiguitäts-Sperre.
        p = _proposal("alias", "alias:turmzimmer:%d" % self.q.id,
                      {"token": "turmzimmer", "quarter_id": self.q.id})
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(entry)
        self.assertIsNotNone(err)
        self.assertEqual(NlLexiconEntry.objects.count(), 0)

    def test_ungueltiges_token_wird_abgelehnt(self):
        p = _proposal("alias", "alias:bad:%d" % self.q.id,
                      {"token": "hat leer!", "quarter_id": self.q.id})
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(entry)
        self.assertIsNotNone(err)

    def test_konflikt_mit_aktivem_alias_auf_anderes_quartier(self):
        NlLexiconEntry.objects.create(
            kind=NlLexiconEntry.ALIAS, dedup_key="alias:nest:%d" % self.q.id,
            payload={"token": "nest", "quarter_id": self.q.id}, active=True)
        p = _proposal("alias", "alias:nest:%d" % self.q2.id,
                      {"token": "nest", "quarter_id": self.q2.id})
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(entry)
        self.assertIsNotNone(err)

    def test_ranking_muss_permutation_sein(self):
        p = _proposal("ranking", "ranking:sommer:1",
                      {"season": "sommer", "month": 1, "new_order": [1, 2, 3]})
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(entry)
        self.assertIsNotNone(err)

    def test_ranking_permutation_wird_uebernommen(self):
        order = list(reversed(wish_nl._SEASONS["sommer"]))
        p = _proposal("ranking", "ranking:sommer:8",
                      {"season": "sommer", "month": 8, "new_order": order})
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(err)
        self.assertEqual(svc.nl_active_lexicon()["rankings"]["sommer"], order)

    def test_neuer_stand_ersetzt_alten_gleichen_schluessel(self):
        old = NlLexiconEntry.objects.create(
            kind=NlLexiconEntry.RANKING, dedup_key="ranking:sommer:8",
            payload={"season": "sommer", "order": [7, 8, 6]}, active=True)
        neu = list(reversed(wish_nl._SEASONS["sommer"]))
        p = _proposal("ranking", "ranking:sommer:8",
                      {"season": "sommer", "month": 8, "new_order": neu})
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(err)
        old.refresh_from_db()
        self.assertFalse(old.active)
        # nur EIN aktiver Eintrag je Schlüssel
        self.assertEqual(NlLexiconEntry.objects.filter(
            active=True, dedup_key="ranking:sommer:8").count(), 1)

    def test_bereits_entschiedener_vorschlag(self):
        p = _proposal("alias", "alias:tuermchen:%d" % self.q.id,
                      {"token": "tuermchen", "quarter_id": self.q.id},
                      status=NlProposal.ACCEPTED)
        entry, err = svc.apply_proposal(p, self.admin)
        self.assertIsNone(entry)
        self.assertIsNotNone(err)


class RollbackTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turmzimmer", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4)
        self.admin = User.objects.create_user("admin", is_superuser=True)

    def test_retire_entfernt_aus_lexikon(self):
        e = NlLexiconEntry.objects.create(
            kind=NlLexiconEntry.ALIAS, dedup_key="alias:tuermchen:%d" % self.q.id,
            payload={"token": "tuermchen", "quarter_id": self.q.id}, active=True)
        self.assertIn("tuermchen", svc.nl_active_lexicon()["aliases"])
        self.assertTrue(svc.retire_entry(e))
        self.assertNotIn("tuermchen", svc.nl_active_lexicon()["aliases"])
        # idempotent
        self.assertFalse(svc.retire_entry(e))

    def test_ablehnen_setzt_status(self):
        p = _proposal("alias", "alias:tuermchen:%d" % self.q.id,
                      {"token": "tuermchen", "quarter_id": self.q.id})
        self.assertTrue(svc.reject_proposal(p, self.admin))
        p.refresh_from_db()
        self.assertEqual(p.status, NlProposal.REJECTED)
        self.assertEqual(p.decided_by, self.admin)
        # idempotent
        self.assertFalse(svc.reject_proposal(p, self.admin))

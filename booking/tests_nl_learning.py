"""NL-L1: pseudonymisierte Instrumentierung fürs NL-Parser-Lernen (ADR 0113).

Prüft: fail-closed (Opt-in + Salt), Pseudonym (stabil, personen-unterscheidend),
kein Klartext-Satz gespeichert, Korrelation Parse→Ergebnis (Überstimmt-Erkennung),
Retention-Löschung.
"""
from __future__ import annotations

import types
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from booking import services as svc
from booking.models import Member, NlInteraction, OpsConfig

SALT = "test-salt-please-rotate"


def _member(name):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    return Member.objects.create(user=u, display_name=name)


def _req():
    # Minimaler Request-Ersatz mit dict-Session (der Service nutzt nur .session).
    return types.SimpleNamespace(session={})


def _intent(quarter_key=None, start=None, suggestions=None):
    return types.SimpleNamespace(
        quarter_key=quarter_key, start=start,
        suggestions=suggestions or [], unresolved=[], matched=[])


class NlLearnGatingTests(TestCase):
    def setUp(self):
        self.m = _member("anna")

    def test_default_aus_sammelt_nichts(self):
        # Ohne Opt-in (Default) und ohne Salt: nichts wird gespeichert.
        svc.nl_log_interaction(_req(), self.m, "booking",
                               _intent(), raw_text="türmchen im juli")
        self.assertEqual(NlInteraction.objects.count(), 0)

    @override_settings(NL_LEARN_SALT="")
    def test_flag_an_aber_kein_salt_bleibt_aus(self):
        # Fail-closed: Opt-in gesetzt, aber Salt leer → weiterhin nichts.
        cfg = OpsConfig.get_solo()
        cfg.nl_learning_enabled = True
        cfg.save(update_fields=["nl_learning_enabled"])
        self.assertFalse(svc.nl_learning_active())
        svc.nl_log_interaction(_req(), self.m, "booking",
                               _intent(), raw_text="türmchen")
        self.assertEqual(NlInteraction.objects.count(), 0)


@override_settings(NL_LEARN_SALT=SALT)
class NlLearnActiveTests(TestCase):
    def setUp(self):
        self.m = _member("anna")
        cfg = OpsConfig.get_solo()
        cfg.nl_learning_enabled = True
        cfg.save(update_fields=["nl_learning_enabled"])

    def test_pseudonym_stabil_und_personen_unterscheidend(self):
        other = _member("bob")
        p1 = svc.nl_pseudonym(self.m.id)
        self.assertEqual(p1, svc.nl_pseudonym(self.m.id))     # stabil
        self.assertNotEqual(p1, svc.nl_pseudonym(other.id))   # unterscheidet Personen
        self.assertEqual(len(p1), 64)                          # SHA-256 hex (nicht umkehrbar)

    def test_log_speichert_tokens_kein_freitext_und_pseudonym(self):
        svc.nl_log_interaction(_req(), self.m, "booking",
                               _intent(), raw_text="ins Türmchen im Juli, bitte!")
        row = NlInteraction.objects.get()
        self.assertEqual(row.pseudonym, svc.nl_pseudonym(self.m.id))
        # Nur normalisierte Einzel-Tokens, KEIN zusammenhängender Satz.
        self.assertIn("turmchen", row.unresolved)
        self.assertTrue(all(" " not in t for t in row.unresolved))
        self.assertIsNone(row.outcome_at)

    def test_korrelation_haengt_ergebnis_an_und_erkennt_ueberstimmen(self):
        req = _req()
        # Parser schlug Quartier 7 / Juli vor …
        svc.nl_log_interaction(req, self.m, "booking",
                               _intent(quarter_key=7, start=date(2027, 7, 1)),
                               raw_text="turm juli")
        # … die Person wählt aber Quartier 9 / August → überstimmt.
        svc.nl_attach_outcome(req, self.m, "booking",
                              quarter_id=9, start=date(2027, 8, 3))
        row = NlInteraction.objects.get()
        self.assertIsNotNone(row.outcome_at)
        self.assertEqual(row.chosen_quarter_id, 9)
        self.assertEqual(row.chosen_month, 8)
        self.assertTrue(row.overridden)
        # Korrelation ist verbraucht (kein zweites Anhängen).
        self.assertNotIn("nl_pending", req.session)

    def test_ergebnis_ohne_passende_korrelation_ignoriert(self):
        req = _req()
        # Kein vorheriges Log → attach macht nichts.
        svc.nl_attach_outcome(req, self.m, "wish", quarter_id=1, start=date(2027, 5, 1))
        self.assertEqual(NlInteraction.objects.count(), 0)

    def test_retention_loescht_alte_signale(self):
        svc.nl_log_interaction(_req(), self.m, "booking", _intent(), raw_text="turm")
        old = NlInteraction.objects.get()
        NlInteraction.objects.filter(id=old.id).update(
            created_at=timezone.now() - timedelta(days=200))
        out = svc.run_data_retention()
        self.assertEqual(out.get("nl_interactions"), 1)
        self.assertEqual(NlInteraction.objects.count(), 0)

"""Tests: Sperrzeit-Konflikte, dringende Sperrung, Umbuchung, Ausgleich (ADR 0097)."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from booking import services as svc
from booking.models import (
    Allocation, BookingPolicy, CompensationGrant, EquivalenceClass, Member,
    Membership, OpsConfig, Quarter, QuarterBlock, RelocationRequest, Share,
)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BlockConflictTests(TestCase):
    def setUp(self):
        OpsConfig.objects.all().delete()
        OpsConfig.objects.create(admin_emails="office@example.org")
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q1 = Quarter.objects.create(name="Q1", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Q2", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.q_small = Quarter.objects.create(name="Klein", eq_class=self.cls,
                                              min_occupancy=1, max_occupancy=2)
        self.m = self._member("mara")
        # Buchung in Q1 in ~40 Tagen (regulärer Vorlauf).
        self.start = date.today() + timedelta(days=40)
        self.end = self.start + timedelta(days=5)
        self.alloc = Allocation.objects.create(
            member=self.m, quarter=self.q1, start=self.start, end=self.end,
            persons=3, source="spontaneous", membership=self.m.membership_for())

    def _member(self, name):
        u = User.objects.create_user(name, f"{name}@example.org", "x" * 12)
        m = Member.objects.create(user=u, display_name=name)
        ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                       annual_night_budget=50, wish_night_budget=25)
        Share.objects.create(membership=ms, member=m, night_budget=50,
                             wish_night_budget=25)
        return m

    def _release_year(self):
        from booking.models import BookingPeriod
        y = self.start.year
        BookingPeriod.objects.create(name="g", target_year=y, start=date(y, 1, 1),
                                     end=date(y + 1, 1, 1),
                                     status=BookingPeriod.FREE_BOOKING)

    def test_konflikt_blockt_ohne_force(self):
        info = svc.create_quarter_block(self.q1, self.start, self.end, "Reparatur")
        self.assertIsNone(info["block"])                 # NICHT angelegt
        self.assertEqual(len(info["allocs"]), 1)
        self.assertFalse(QuarterBlock.objects.exists())
        self.assertFalse(info["within_notice"])          # 40 Tage → regulär

    def test_suggestion_findet_freies_fenster(self):
        info = svc.create_quarter_block(self.q1, self.start, self.end, "x")
        self.assertIsNotNone(info["suggestion"])
        s, e = info["suggestion"]
        self.assertEqual((e - s).days, 5)
        # Vorgeschlagenes Fenster ist wirklich frei.
        allocs, ext = svc.block_conflicts(self.q1, s, e)
        self.assertEqual(allocs, [])

    def test_kein_konflikt_legt_an(self):
        far = self.end + timedelta(days=10)
        info = svc.create_quarter_block(self.q1, far, far + timedelta(days=2), "x")
        self.assertIsNotNone(info["block"])
        self.assertTrue(QuarterBlock.objects.filter(id=info["block"].id).exists())

    def test_force_legt_trotz_konflikt_an(self):
        info = svc.create_quarter_block(self.q1, self.start, self.end, "Rohrbruch",
                                        force=True)
        self.assertIsNotNone(info["block"])
        self.assertEqual(len(info["allocs"]), 1)

    def test_within_notice_bei_kurzfrist(self):
        soon = date.today() + timedelta(days=3)
        a = Allocation.objects.create(
            member=self.m, quarter=self.q2, start=soon, end=soon + timedelta(days=2),
            persons=2, source="spontaneous", membership=self.m.membership_for())
        info = svc.create_quarter_block(self.q2, a.start, a.end, "x")
        self.assertTrue(info["within_notice"])

    def test_relocation_options_passend_vs_zu_klein(self):
        self._release_year()
        opts = svc.relocation_options(self.alloc)   # 3 Personen
        ids_fit = [q.id for q in opts["fitting"]]
        ids_under = [q.id for q in opts["undersized"]]
        self.assertIn(self.q2.id, ids_fit)          # Q2 passt (1–4)
        self.assertIn(self.q_small.id, ids_under)   # Klein (1–2) zu klein
        self.assertNotIn(self.q1.id, ids_fit + ids_under)  # eigenes nicht

    def test_propose_und_accept_zieht_um(self):
        req = svc.propose_relocation(self.alloc, self.q2, "Rohrbruch")
        self.assertEqual(req.status, RelocationRequest.PROPOSED)
        self.assertFalse(req.undersized)
        ok, err = svc.respond_relocation(self.m, req.id, accept=True)
        self.assertTrue(ok, err)
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.quarter_id, self.q2.id)   # umgezogen

    def test_propose_undersized_markiert(self):
        req = svc.propose_relocation(self.alloc, self.q_small, "Rohrbruch")
        self.assertTrue(req.undersized)             # 3 Pers. in 1–2

    def test_reject_laesst_buchung(self):
        req = svc.propose_relocation(self.alloc, self.q2, "x")
        ok, err = svc.respond_relocation(self.m, req.id, accept=False)
        self.assertTrue(ok, err)
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.quarter_id, self.q1.id)   # bleibt
        req.refresh_from_db()
        self.assertEqual(req.status, RelocationRequest.REJECTED)

    def test_apology_storniert_und_gleicht_aus(self):
        year = self.start.year
        budget_before = self.m.effective_annual_budget(year)
        res = svc.cancel_with_apology(self.alloc, "Wasserrohrbruch",
                                      compensation_days=2)
        self.assertEqual(res["compensation"], 2)
        self.assertFalse(Allocation.objects.filter(id=self.alloc.id).exists())
        # Tage zurück (kein Verfall) + 2 Ausgleich → Budget um 2 höher als vorher.
        self.assertEqual(self.m.effective_annual_budget(year), budget_before + 2)
        self.assertTrue(CompensationGrant.objects.filter(member=self.m, days=2).exists())

    def test_ausgleich_gedeckelt(self):
        p = BookingPolicy.get_solo()
        p.max_compensation_days = 2
        p.save(update_fields=["max_compensation_days"])
        res = svc.cancel_with_apology(self.alloc, "x", compensation_days=99)
        self.assertEqual(res["compensation"], 2)     # gedeckelt


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BlockViewFlowTests(TestCase):
    """End-to-End über die Views: Konflikt-Panel → dringend sperren → Umbuchung
    vorschlagen → Mitglied nimmt an (Buchung zieht um)."""
    def setUp(self):
        from booking.models import BookingPeriod
        from booking.permissions import ensure_verwaltung_group
        OpsConfig.objects.all().delete()
        OpsConfig.objects.create(admin_emails="office@example.org")
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q1 = Quarter.objects.create(name="Q1", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Q2", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        u = User.objects.create_user("mem", "mem@example.org", "x" * 12)
        self.m = Member.objects.create(user=u, display_name="Mem")
        ms = Membership.objects.create(eg_number="EG-m", label="m",
                                       annual_night_budget=50, wish_night_budget=25)
        Share.objects.create(membership=ms, member=self.m, night_budget=50,
                             wish_night_budget=25)
        self.start = date.today() + timedelta(days=5)     # dringend (<14)
        self.end = self.start + timedelta(days=3)
        self.alloc = Allocation.objects.create(
            member=self.m, quarter=self.q1, start=self.start, end=self.end,
            persons=2, source="spontaneous", membership=ms)
        y = self.start.year
        BookingPeriod.objects.create(name="g", target_year=y, start=date(y, 1, 1),
                                     end=date(y + 1, 1, 1),
                                     status=BookingPeriod.FREE_BOOKING)
        self.staff = User.objects.create_user("chef", "chef@example.org", "x" * 12)
        self.staff.groups.add(ensure_verwaltung_group())

    def test_voller_ablauf(self):
        from booking.models import QuarterBlock, RelocationRequest
        c = self.client
        c.force_login(self.staff)
        url = "/verwaltung/sperrzeiten/"
        # 1) Sperrzeit über die Buchung → Konflikt, NICHT angelegt, Panel-Session.
        c.post(url, {"action": "add_block", "quarter": self.q1.id,
                     "start": self.start.isoformat(), "end": self.end.isoformat(),
                     "reason": "Rohrbruch"}, HTTP_HOST="localhost")
        self.assertFalse(QuarterBlock.objects.exists())
        r = c.get(url, HTTP_HOST="localhost")
        self.assertContains(r, "Das geht nicht")
        self.assertContains(r, "unumgänglich")            # <14 Tage → dringend-Frage
        # 2) Dringend trotzdem sperren.
        c.post(url, {"action": "force_block", "quarter": self.q1.id,
                     "start": self.start.isoformat(), "end": self.end.isoformat(),
                     "reason": "Rohrbruch"}, HTTP_HOST="localhost")
        self.assertTrue(QuarterBlock.objects.exists())
        r = c.get(url, HTTP_HOST="localhost")
        self.assertContains(r, "Umbuchung nötig")
        # 3) Umbuchung nach Q2 vorschlagen.
        c.post(url, {"action": "propose_reloc", "allocation_id": self.alloc.id,
                     "to_quarter": self.q2.id, "reason": "Rohrbruch"},
               HTTP_HOST="localhost")
        req = RelocationRequest.objects.get(allocation=self.alloc)
        self.assertEqual(req.status, RelocationRequest.PROPOSED)
        # 4) Mitglied sieht den Vorschlag und nimmt an → Buchung zieht um.
        c.logout(); c.force_login(self.m.user)
        r = c.get("/meine-buchungen/", HTTP_HOST="localhost")
        self.assertContains(r, "Umbuchungs-Vorschlag")
        c.post("/meine-buchungen/", {"action": "reloc_respond",
               "request_id": req.id, "decision": "accept"}, HTTP_HOST="localhost")
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.quarter_id, self.q2.id)

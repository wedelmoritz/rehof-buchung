"""Integrationstests für den Beds24-Migrations-Assistenten (DB-Ebene)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import (
    Allocation, Beds24Import, Beds24ImportRow, EquivalenceClass, Member, Quarter,
)

CSV = (
    "Guest Name;Arrival;Departure;Unit;Adults;Status\n"
    "Anna Schmidt;2026-06-01;2026-06-05;Gartenhaus Salix;2;confirmed\n"
    "Wanderfreund Ohne Konto;2026-07-01;2026-07-04;Hofgebäude;3;confirmed\n"
)


class Beds24StageTests(TestCase):
    def setUp(self):
        eq = EquivalenceClass.objects.create(name="G")
        self.salix = Quarter.objects.create(name="Gartenhaus Salix", eq_class=eq,
                                            min_occupancy=1, max_occupancy=4)
        self.hof = Quarter.objects.create(name="Hofgebäude", eq_class=eq,
                                          min_occupancy=1, max_occupancy=4)
        u = User.objects.create_user("anna0", password="x")
        self.anna = Member.objects.create(user=u, display_name="Anna (anna0)",
                                          legal_name="Anna Schmidt")

    def test_stage_macht_vorschlaege(self):
        batch = svc.beds24_stage(CSV, "beds24.csv")
        self.assertEqual(batch.n_rows, 2)
        r1 = batch.rows.get(guest_name="Anna Schmidt")
        # Name trifft Mitglied sicher, Unit trifft Quartier
        self.assertEqual(r1.suggested_member, self.anna)
        self.assertGreaterEqual(r1.suggested_score, 0.7)
        self.assertEqual(r1.suggested_quarter, self.salix)
        self.assertEqual(r1.chosen_member, self.anna)   # sicher -> vorausgewählt
        r2 = batch.rows.get(guest_name="Wanderfreund Ohne Konto")
        self.assertIsNone(r2.chosen_member)             # kein Treffer

    def test_apply_legt_buchung_an_ohne_rechnung(self):
        batch = svc.beds24_stage(CSV, "x.csv")
        r1 = batch.rows.get(guest_name="Anna Schmidt")
        res = svc.beds24_apply(batch, {r1.id: {"action": "import",
                                               "member": self.anna.id,
                                               "quarter": self.salix.id,
                                               "persons": 2}})
        self.assertEqual(res["imported"], 1)
        alloc = Allocation.objects.get()
        self.assertEqual(alloc.source, "import")
        self.assertEqual(alloc.member, self.anna)
        self.assertFalse(alloc.provisional)
        r1.refresh_from_db()
        self.assertEqual(r1.status, Beds24ImportRow.IMPORTED)

    def test_apply_idempotent(self):
        batch = svc.beds24_stage(CSV, "x.csv")
        r1 = batch.rows.get(guest_name="Anna Schmidt")
        d = {r1.id: {"action": "import", "member": self.anna.id,
                     "quarter": self.salix.id, "persons": 2}}
        svc.beds24_apply(batch, d)
        # erneut anwenden -> keine zweite Buchung
        batch2 = svc.beds24_stage(CSV, "x.csv")
        r = batch2.rows.get(guest_name="Anna Schmidt")
        svc.beds24_apply(batch2, {r.id: {"action": "import", "member": self.anna.id,
                                         "quarter": self.salix.id, "persons": 2}})
        self.assertEqual(Allocation.objects.count(), 1)

    def test_create_member_fuer_unbekannten_gast(self):
        m = svc.beds24_create_member("Wanderfreund Ohne Konto")
        self.assertEqual(m.display_name, "Wanderfreund Ohne Konto")
        self.assertTrue(m.shares.exists())  # bekommt einen Anteil
        self.assertFalse(m.user.has_usable_password())


class Beds24AccessTests(TestCase):
    def test_nur_admin(self):
        from booking.permissions import ensure_verwaltung_group
        verw = User.objects.create_user("verw", password="x")
        verw.groups.add(ensure_verwaltung_group())
        self.client.force_login(verw)
        r = self.client.get(reverse("beds24_import"))
        self.assertRedirects(r, reverse("dashboard"))
        adm = User.objects.create_superuser("adm", "a@e.de", "x")
        self.client.force_login(adm)
        self.assertEqual(self.client.get(reverse("beds24_import")).status_code, 200)

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

    def test_create_member_mit_email_schickt_einladung(self):
        from booking.models import OutboxEmail
        m = svc.beds24_create_member("Neuer Gast", "neu@example.org")
        self.assertEqual(m.user.email, "neu@example.org")
        self.assertEqual(OutboxEmail.objects.filter(
            to_email="neu@example.org").count(), 1)

    def test_email_anker_schlaegt_namen(self):
        # Mitglied mit abweichendem Namen, aber passender E-Mail -> sicherer Treffer.
        u = User.objects.create_user("bob9", email="anchor@example.org",
                                     password="x")
        bob = Member.objects.create(user=u, display_name="Bob (bob9)",
                                    legal_name="Robert Other")
        csv = ("Guest Name;Email;Arrival;Departure;Unit;Adults;Status\n"
               "Voellig Anderer Name;anchor@example.org;2026-06-01;2026-06-05;"
               "Gartenhaus Salix;2;confirmed\n")
        batch = svc.beds24_stage(csv, "x.csv")
        r = batch.rows.get()
        self.assertEqual(r.email, "anchor@example.org")
        self.assertEqual(r.suggested_member, bob)
        self.assertEqual(r.match_kind, Beds24ImportRow.EMAIL)
        self.assertEqual(r.chosen_member, bob)   # sicher -> vorausgewählt

    def test_einzelner_namens_treffer_ist_gelb(self):
        # Genau ein passendes Mitglied, ohne E-Mail -> NAME (gelb), vorgeschlagen.
        batch = svc.beds24_stage(CSV, "x.csv")
        r1 = batch.rows.get(guest_name="Anna Schmidt")
        self.assertEqual(r1.match_kind, Beds24ImportRow.NAME)
        self.assertEqual(r1.chosen_member, self.anna)   # bequem vorgeschlagen

    def test_mehrere_namens_treffer_sind_gelb_ohne_vorauswahl(self):
        # Zwei Mitglieder mit demselben Namen -> MULTI (gelb), KEINE Vorauswahl.
        u2 = User.objects.create_user("anna1", password="x")
        Member.objects.create(user=u2, display_name="Anna (anna1)",
                              legal_name="Anna Schmidt")
        batch = svc.beds24_stage(CSV, "x.csv")
        r1 = batch.rows.get(guest_name="Anna Schmidt")
        self.assertEqual(r1.match_kind, Beds24ImportRow.MULTI)
        self.assertIsNone(r1.chosen_member)    # mehrdeutig -> Admin muss wählen
        self.assertIsNotNone(r1.suggested_member)  # Vorschlag bleibt sichtbar


class Beds24RowCheckTests(TestCase):
    def setUp(self):
        from booking.models import BookingPolicy
        eq = EquivalenceClass.objects.create(name="G")
        self.q = Quarter.objects.create(name="Gartenhaus Salix", eq_class=eq,
                                        min_occupancy=1, max_occupancy=4)
        u = User.objects.create_user("anna0", password="x")
        self.anna = Member.objects.create(user=u, display_name="Anna",
                                          legal_name="Anna Schmidt")
        pol = BookingPolicy.get_solo()
        pol.default_min_nights = 5
        pol.save()

    def _stage_one(self, arrival, departure):
        csv = ("Guest Name;Arrival;Departure;Unit;Adults;Status\n"
               f"Anna Schmidt;{arrival};{departure};Gartenhaus Salix;2;confirmed\n")
        return svc.beds24_stage(csv, "x.csv").rows.get()

    def test_verfuegbarkeit_frei_und_belegt(self):
        # Zeitraum zunächst frei.
        row = self._stage_one("2026-06-01", "2026-06-08")
        checks = svc.beds24_row_checks(row.batch)
        self.assertTrue(checks[row.id]["free"])
        # Slot belegen, neuer Import desselben Zeitraums -> belegt.
        Allocation.objects.create(member=self.anna, quarter=self.q,
                                  start=row.arrival, end=row.departure, persons=2,
                                  source="import", provisional=False)
        row2 = self._stage_one("2026-06-01", "2026-06-08")
        checks2 = svc.beds24_row_checks(row2.batch)
        self.assertFalse(checks2[row2.id]["free"])
        self.assertTrue(checks2[row2.id]["conflict"])

    def test_regel_warnung_bei_zu_kurzem_aufenthalt(self):
        row = self._stage_one("2026-06-01", "2026-06-03")   # 2 < 5 Nächte
        checks = svc.beds24_row_checks(row.batch)
        self.assertTrue(checks[row.id]["rule_warning"])     # nur Warnung
        # Verfügbarkeit ist davon unberührt (frei).
        self.assertTrue(checks[row.id]["free"])


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

    def test_deaktivierbar_per_opsconfig(self):
        from booking.models import OpsConfig
        adm = User.objects.create_superuser("adm2", "a2@e.de", "x")
        self.client.force_login(adm)
        cfg = OpsConfig.get_solo()
        cfg.beds24_import_enabled = False
        cfg.save()
        # Auch Admin wird bei deaktiviertem Import aufs Dashboard umgeleitet.
        r = self.client.get(reverse("beds24_import"))
        self.assertRedirects(r, reverse("dashboard"))

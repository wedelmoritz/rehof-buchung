"""Integrationstests für die weiteren Entzerrungs-Funktionen (ADR 0101):
Nachfrage-Heatmap (C), Absprachen + Opt-out (D), Wunsch-Export + Admin-Nachtrag (E).
Wächst mit den einzelnen Batches."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from booking import services as svc
from booking.models import (
    BookingPeriod, EquivalenceClass, Member, Membership, Quarter, Share,
)

NEXT = date.today().year + 1


def _member(name):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


def _period(status=BookingPeriod.WISHES_REVIEW):
    return BookingPeriod.objects.create(
        name="Losung", target_year=NEXT, start=date(NEXT, 1, 1),
        end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
        draw_at=timezone.now() + timedelta(days=3), status=status)


class DemandGridTests(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Hütte", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.period = _period()

    def test_grid_zaehlt_eingereichte_wuensche_je_monat(self):
        a = _member("a")
        b = _member("b")
        # Zwei eingereichte Wünsche im Mai für „Turm“, einer im Juli für „Hütte“.
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.add_wish(b, self.period, self.q, date(NEXT, 5, 20), date(NEXT, 5, 24))
        svc.add_wish(a, self.period, self.q2, date(NEXT, 7, 1), date(NEXT, 7, 5))
        svc.submit_wishlist(a, self.period)
        svc.submit_wishlist(b, self.period)
        grid = svc.wish_demand_grid(self.period)
        self.assertEqual(len(grid["months"]), 12)
        turm = next(r for r in grid["rows"] if r["quarter"] == "Turm")
        huette = next(r for r in grid["rows"] if r["quarter"] == "Hütte")
        self.assertEqual(turm["cells"][4]["count"], 2)   # Mai (Index 4)
        self.assertEqual(huette["cells"][6]["count"], 1)  # Juli (Index 6)
        self.assertEqual(grid["max"], 2)

    def test_nur_eingereichte_zaehlen(self):
        a = _member("a")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        # nicht eingereicht → max 0 → keine Heatmap
        grid = svc.wish_demand_grid(self.period)
        self.assertEqual(grid["max"], 0)

    def test_wishlist_zeigt_heatmap(self):
        a = _member("a")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.submit_wishlist(a, self.period)
        self.client.force_login(a.user)
        html = self.client.get(reverse("wishlist")).content.decode()
        self.assertIn("Nachfrage-Übersicht", html)


class CoordinationTests(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Hütte", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.period = _period()
        self.a = _member("anna")
        self.a.phone = "0170 111"
        self.a.save(update_fields=["phone"])
        self.b = _member("bea")
        self.b.phone = "0170 222"
        self.b.save(update_fields=["phone"])

    def _wish(self, m, q, s, e):
        svc.add_wish(m, self.period, q, s, e)
        svc.submit_wishlist(m, self.period)

    def test_ueberlappende_nachbarn_sichtbar_mit_telefon(self):
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 10))
        self._wish(self.b, self.q, date(NEXT, 5, 8), date(NEXT, 5, 12))  # überlappt
        rows = svc.wish_neighbors(self.period, self.a)
        self.assertEqual(len(rows), 1)
        names = [n["name"] for n in rows[0]["neighbors"]]
        self.assertIn("bea", names)
        self.assertEqual(rows[0]["neighbors"][0]["phone"], "0170 222")

    def test_opt_out_verbirgt(self):
        self.b.coordination_opt_out = True
        self.b.save(update_fields=["coordination_opt_out"])
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 10))
        self._wish(self.b, self.q, date(NEXT, 5, 8), date(NEXT, 5, 12))
        rows = svc.wish_neighbors(self.period, self.a)
        self.assertEqual(rows, [])   # bea ausgeblendet → kein Nachbar

    def test_nicht_ueberlappend_kein_nachbar(self):
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 6))
        self._wish(self.b, self.q, date(NEXT, 5, 20), date(NEXT, 5, 24))  # disjunkt
        self.assertEqual(svc.wish_neighbors(self.period, self.a), [])

    def test_anderes_quartier_kein_nachbar(self):
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 10))
        self._wish(self.b, self.q2, date(NEXT, 5, 8), date(NEXT, 5, 12))
        self.assertEqual(svc.wish_neighbors(self.period, self.a), [])

    def test_profil_opt_out_umschalten(self):
        self.client.force_login(self.a.user)
        # Häkchen NICHT gesetzt → opt_out = True (nicht sichtbar)
        self.client.post(reverse("profile"), {"action": "notify_prefs"})
        self.a.refresh_from_db()
        self.assertTrue(self.a.coordination_opt_out)
        # Häkchen gesetzt → wieder sichtbar
        self.client.post(reverse("profile"),
                         {"action": "notify_prefs", "coordination_visible": "on"})
        self.a.refresh_from_db()
        self.assertFalse(self.a.coordination_opt_out)


class WishExportAndNachtragTests(TestCase):
    def setUp(self):
        call_command("sync_roles", verbosity=0)
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.period = _period()
        self.a = _member("anna")
        svc.add_wish(self.a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.submit_wishlist(self.a, self.period)

    def _login(self, role):
        u = User.objects.create_user(f"u_{role}", password="x" * 12)
        u.groups.add(Group.objects.get(name=role))
        self.client.force_login(u)
        return User.objects.get(pk=u.pk)

    # --- Export (export_wishes) ------------------------------------------ #
    def test_export_csv_und_xlsx(self):
        self._login("Buchungs-Verwaltung")
        r = self.client.get(reverse("verw_wuensche") + "?export=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        self.assertIn(b"anna", r.content)
        r2 = self.client.get(reverse("verw_wuensche") + "?export=xlsx")
        self.assertEqual(r2.status_code, 200)

    def test_export_gegated_403(self):
        self._login("Rechnungs-Verwaltung")     # kein export_wishes
        self.assertEqual(self.client.get(reverse("verw_wuensche")).status_code, 403)

    def test_seite_ohne_add_form_fuer_basis_rolle(self):
        self._login("Buchungs-Verwaltung")       # kein add_wish_for_member
        html = self.client.get(reverse("verw_wuensche")).content.decode()
        self.assertNotIn("Wunsch für ein Mitglied nachtragen", html)

    # --- Admin-Nachtrag (add_wish_for_member) ---------------------------- #
    def test_add_wish_for_member_service_auditiert(self):
        actor = User.objects.create_user("bl", password="x" * 12)
        actor.groups.add(Group.objects.get(name="Buchungs-Verwaltung-Erweitert"))
        actor = User.objects.get(pk=actor.pk)
        bob = _member("bob")
        w, err = svc.add_wish_for_member(actor, bob, self.period, self.q,
                                         date(NEXT, 6, 1), date(NEXT, 6, 4))
        self.assertIsNotNone(w, err)
        self.assertTrue(w.submitted)
        self.assertEqual(w.created_by_id, actor.id)

    def test_add_wish_for_member_defense_in_depth(self):
        nobody = User.objects.create_user("x", password="x" * 12)
        with self.assertRaises(PermissionDenied):
            svc.add_wish_for_member(nobody, self.a, self.period, self.q,
                                    date(NEXT, 6, 1), date(NEXT, 6, 4))

    def test_erweitert_view_kann_nachtragen(self):
        self._login("Buchungs-Verwaltung-Erweitert")
        bob = _member("bob")
        html = self.client.get(reverse("verw_wuensche")).content.decode()
        self.assertIn("Wunsch für ein Mitglied nachtragen", html)
        r = self.client.post(reverse("verw_wuensche"), {
            "member_id": bob.id, "quarter_id": self.q.id,
            "start": date(NEXT, 6, 1).isoformat(), "end": date(NEXT, 6, 4).isoformat()})
        self.assertEqual(r.status_code, 302)
        from booking.models import Wish
        self.assertTrue(Wish.objects.filter(member=bob, submitted=True).exists())


class HelpPageTests(TestCase):
    def test_hilfe_zeigt_entzerrungsphase_und_zeitleiste(self):
        m = _member("hilde")
        self.client.force_login(m.user)
        html = self.client.get(reverse("help")).content.decode()
        self.assertIn("Entzerrungsphase vor der Losung", html)   # Abschnittstitel
        self.assertIn("phase-flow", html)                        # HTML/CSS-Zeitleiste
        self.assertIn("Einreiche-Frist", html)
        self.assertIn("Freeze", html)


class SnapshotTests(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.a = _member("anna")

    def _period_draw_in(self, **kw):
        p = BookingPeriod.objects.create(
            name="P", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), wishlist_open=date.today(),
            status=BookingPeriod.WISHES_REVIEW,
            draw_at=timezone.now() + timedelta(**kw))
        svc.add_wish(self.a, p, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.submit_wishlist(self.a, p)
        return p

    def test_freeze_und_vor_snapshot_werden_gespeichert(self):
        p = self._period_draw_in(hours=10)     # < 24 h → eingefroren; review_open lange her
        changed = svc.capture_wish_snapshots(p, timezone.now())
        self.assertTrue(changed)
        p.refresh_from_db()
        self.assertIn("frozen", p.demand_snapshot)
        self.assertIn("review_open", p.demand_snapshot)
        self.assertEqual(p.demand_snapshot["frozen"]["grid"]["max"], 1)
        self.assertTrue(p.demand_snapshot["review_open"]["rows"])   # Wunschzeilen

    def test_idempotent(self):
        p = self._period_draw_in(hours=10)
        svc.capture_wish_snapshots(p, timezone.now())
        # Ein zweiter Wunsch danach ändert den bereits eingefrorenen Stand NICHT.
        b = _member("bea")
        svc.add_wish(b, p, self.q, date(NEXT, 5, 4), date(NEXT, 5, 8))
        svc.submit_wishlist(b, p)
        self.assertFalse(svc.capture_wish_snapshots(p, timezone.now()))
        p.refresh_from_db()
        self.assertEqual(p.demand_snapshot["frozen"]["grid"]["max"], 1)  # unverändert

    def test_kein_freeze_wenn_weit_vor_losung(self):
        # Losung in 5 Tagen: review_open (draw − 7 T) ist schon vorbei, der Freeze
        # (draw − 24 h) aber noch nicht → nur der „vor"-Stand, keine eingefrorene Anzeige.
        p = self._period_draw_in(days=5)
        svc.capture_wish_snapshots(p, timezone.now())
        p.refresh_from_db()
        self.assertNotIn("frozen", p.demand_snapshot)
        self.assertIn("review_open", p.demand_snapshot)

    def test_wishlist_zeigt_eingefrorene_anzeige(self):
        p = self._period_draw_in(hours=10)
        svc.capture_wish_snapshots(p, timezone.now())
        # Nach dem Snapshot ändert sich die Live-Nachfrage, die Anzeige bleibt aber fix.
        b = _member("bea")
        svc.add_wish(b, p, self.q, date(NEXT, 5, 4), date(NEXT, 5, 8))
        svc.submit_wishlist(b, p)
        self.client.force_login(self.a.user)
        r = self.client.get(reverse("wishlist"))
        # display_frozen → Heatmap kommt aus dem Snapshot (max 1), nicht live (max 2).
        self.assertEqual(r.context["demand_grid"]["max"], 1)

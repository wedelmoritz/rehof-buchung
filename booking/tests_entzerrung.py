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
    BookingPeriod, EquivalenceClass, Member, Membership, Quarter, Share, Wish,
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

    def test_grid_zaehlt_eingetragene_wuensche_je_monat(self):
        a = _member("a")
        b = _member("b")
        # Zwei eingetragene Wünsche im Mai für „Turm“, einer im Juli für „Hütte“.
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.add_wish(b, self.period, self.q, date(NEXT, 5, 20), date(NEXT, 5, 24))
        svc.add_wish(a, self.period, self.q2, date(NEXT, 7, 1), date(NEXT, 7, 5))
        grid = svc.wish_demand_grid(self.period)
        self.assertEqual(len(grid["months"]), 12)
        turm = next(r for r in grid["rows"] if r["quarter"] == "Turm")
        huette = next(r for r in grid["rows"] if r["quarter"] == "Hütte")
        self.assertEqual(turm["cells"][4]["count"], 2)   # Mai (Index 4)
        self.assertEqual(huette["cells"][6]["count"], 1)  # Juli (Index 6)
        self.assertEqual(grid["max"], 2)

    def test_eingetragener_wunsch_zaehlt_sofort(self):
        # Seit ADR 0101 nimmt jeder eingetragene Wunsch teil (kein Einreichen mehr) –
        # er zählt daher sofort in die Nachfrage-Heatmap.
        a = _member("a")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        grid = svc.wish_demand_grid(self.period)
        self.assertEqual(grid["max"], 1)

    def test_wishlist_zeigt_heatmap(self):
        # Die Heatmap liegt auf dem Reiter „Nachfrage & Heatmap" (?view=nachfrage).
        a = _member("a")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        self.client.force_login(a.user)
        html = self.client.get(reverse("wishlist") + "?view=nachfrage").content.decode()
        self.assertIn("Nachfrage-Heatmap", html)
        self.assertIn("Beliebteste Unterkünfte", html)   # Ranglisten (Feedback e)

    def test_wuensche_reiter_hat_keine_heatmap(self):
        # Default-Reiter „Meine Wünsche" zeigt die Heatmap NICHT (aufgeräumt, Feedback d).
        a = _member("a")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        self.client.force_login(a.user)
        html = self.client.get(reverse("wishlist")).content.decode()
        self.assertNotIn('<table class="heat">', html)   # Heatmap-Tabelle nur im Nachfrage-Reiter
        self.assertIn("Meine Wünsche", html)

    def test_demand_ranking_listet_top(self):
        a = _member("a"); b = _member("b")
        svc.add_wish(a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        svc.add_wish(b, self.period, self.q, date(NEXT, 5, 10), date(NEXT, 5, 14))
        svc.add_wish(a, self.period, self.q2, date(NEXT, 7, 1), date(NEXT, 7, 5))
        rank = svc.wish_demand_ranking(self.period)
        self.assertEqual(rank["quarters"][0]["name"], "Turm")   # meiste Wünsche
        self.assertEqual(rank["quarters"][0]["count"], 2)
        self.assertTrue(rank["slots"])


class WishUxTests(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(name="Hütte", eq_class=self.cls,
                                         min_occupancy=1, max_occupancy=4)
        self.period = _period()
        self.a = _member("anna")

    def test_demand_band_stufen(self):
        self.assertEqual(svc.wish_demand_band(0)["key"], "none")
        self.assertEqual(svc.wish_demand_band(1)["key"], "few")
        self.assertEqual(svc.wish_demand_band(3)["key"], "popular")
        self.assertEqual(svc.wish_demand_band(9)["key"], "hot")

    def test_adjust_wish_aendert_zeit_und_quartier_behaelt_prio(self):
        w1, _ = svc.add_wish(self.a, self.period, self.q,
                             date(NEXT, 5, 3), date(NEXT, 5, 7))
        w2, _ = svc.add_wish(self.a, self.period, self.q2,
                             date(NEXT, 6, 3), date(NEXT, 6, 7))
        self.assertEqual(w2.priority, 2)
        out, err = svc.adjust_wish(self.a, self.period, w2.id, self.q,
                                   date(NEXT, 8, 1), date(NEXT, 8, 5))
        self.assertIsNone(err, err)
        out.refresh_from_db()
        self.assertEqual(out.quarter_id, self.q.id)
        self.assertEqual(out.start, date(NEXT, 8, 1))
        self.assertEqual(out.priority, 2)   # Priorität bleibt

    def test_adjust_wish_blockt_exakte_doppelung(self):
        svc.add_wish(self.a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))
        w2, _ = svc.add_wish(self.a, self.period, self.q2,
                             date(NEXT, 6, 3), date(NEXT, 6, 7))
        # w2 auf denselben Wunsch wie w1 ändern → abgelehnt.
        out, err = svc.adjust_wish(self.a, self.period, w2.id, self.q,
                                   date(NEXT, 5, 3), date(NEXT, 5, 7))
        self.assertIsNone(out)
        self.assertIn("schon eingetragen", err)

    def test_adjust_wish_via_view(self):
        w, _ = svc.add_wish(self.a, self.period, self.q,
                            date(NEXT, 5, 3), date(NEXT, 5, 7))
        self.client.force_login(self.a.user)
        r = self.client.post(reverse("wishlist"), {
            "action": "adjust_wish", "wish_id": w.id, "quarter": self.q2.id,
            "start": date(NEXT, 5, 10).isoformat(), "end": date(NEXT, 5, 14).isoformat()})
        self.assertEqual(r.status_code, 302)
        w.refresh_from_db()
        self.assertEqual(w.quarter_id, self.q2.id)


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

    def _mine(self, m):
        return list(Wish.objects.filter(period=self.period, member=m)
                    .order_by("priority", "id"))

    def test_ueberlappende_nachbarn_sichtbar_mit_kontakt(self):
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 10))
        self._wish(self.b, self.q, date(NEXT, 5, 8), date(NEXT, 5, 12))  # überlappt
        coord = svc.wish_coordination(self.period, self.a)
        wid = self._mine(self.a)[0].id
        self.assertIn(wid, coord)
        self.assertEqual(coord[wid]["overlap_count"], 1)
        neigh = coord[wid]["neighbors"][0]
        self.assertEqual(neigh["name"], "bea")
        self.assertEqual(neigh["phone"], "0170 222")

    def test_pro_kanal_opt_out_verbirgt_kontakt_nicht_namen(self):
        # Telefon verborgen, E-Mail sichtbar: der Name bleibt sichtbar (Begegnung).
        self.b.coordination_hide_phone = True
        self.b.user.email = "bea@example.org"
        self.b.user.save(update_fields=["email"])
        self.b.save(update_fields=["coordination_hide_phone"])
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 10))
        self._wish(self.b, self.q, date(NEXT, 5, 8), date(NEXT, 5, 12))
        coord = svc.wish_coordination(self.period, self.a)
        neigh = coord[self._mine(self.a)[0].id]["neighbors"][0]
        self.assertEqual(neigh["name"], "bea")     # Name immer sichtbar
        self.assertEqual(neigh["phone"], "")       # Telefon verborgen
        self.assertEqual(neigh["email"], "bea@example.org")  # E-Mail sichtbar

    def test_nicht_ueberlappend_kein_nachbar(self):
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 6))
        self._wish(self.b, self.q, date(NEXT, 5, 20), date(NEXT, 5, 24))  # disjunkt
        self.assertEqual(svc.wish_coordination(self.period, self.a), {})

    def test_anderes_quartier_kein_nachbar(self):
        self._wish(self.a, self.q, date(NEXT, 5, 3), date(NEXT, 5, 10))
        self._wish(self.b, self.q2, date(NEXT, 5, 8), date(NEXT, 5, 12))
        self.assertEqual(svc.wish_coordination(self.period, self.a), {})

    def test_profil_pro_kanal_umschalten(self):
        self.client.force_login(self.a.user)
        # Kein Häkchen → beide Kanäle verborgen (Name bleibt sichtbar).
        self.client.post(reverse("profile"), {"action": "notify_prefs"})
        self.a.refresh_from_db()
        self.assertTrue(self.a.coordination_hide_phone)
        self.assertTrue(self.a.coordination_hide_email)
        # Beide Häkchen → beide Kanäle sichtbar.
        self.client.post(reverse("profile"), {
            "action": "notify_prefs",
            "coordination_show_phone": "on", "coordination_show_email": "on"})
        self.a.refresh_from_db()
        self.assertFalse(self.a.coordination_hide_phone)
        self.assertFalse(self.a.coordination_hide_email)


class WishExportAndNachtragTests(TestCase):
    def setUp(self):
        call_command("sync_roles", verbosity=0)
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.period = _period()
        self.a = _member("anna")
        svc.add_wish(self.a, self.period, self.q, date(NEXT, 5, 3), date(NEXT, 5, 7))

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
        self.assertIsNotNone(w.added_at)
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
        self.assertTrue(Wish.objects.filter(member=bob).exists())


class HelpPageTests(TestCase):
    def test_hilfe_zeigt_entzerrung_im_losungsabschnitt(self):
        # Die Entzerrungsphase ist in „Wunschliste & Auslosung" eingegliedert
        # (ADR 0101 Batch 4): Zeitleiste + Anzeige-Stopp, kein eigener Abschnitt mehr.
        m = _member("hilde")
        self.client.force_login(m.user)
        html = self.client.get(reverse("help")).content.decode()
        self.assertIn("Entzerrungsphase", html)                  # im Losungsabschnitt
        self.assertIn("flow-timeline", html)                     # HTML/CSS-Zeitleiste (Stepper)
        self.assertIn("Frist zum Eintragen", html)               # neue Frist-Marke
        self.assertIn("Anzeige-Stopp", html)                     # statt „Freeze"
        self.assertNotIn('id="entzerrung"', html)                # kein eigener Abschnitt


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
        self.client.force_login(self.a.user)
        r = self.client.get(reverse("wishlist"))
        # display_frozen → Heatmap kommt aus dem Snapshot (max 1), nicht live (max 2).
        self.assertEqual(r.context["demand_grid"]["max"], 1)

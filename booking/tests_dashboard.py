"""Tests für das Verwaltungs-Dashboard: Endreinigung-Verknüpfung, Reinigungs-/
Buchungslisten, Export, Mailversand, Rechnungs-Erinnerung."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from booking.models import (
    Allocation, EquivalenceClass, Member, Membership, OpsConfig, OutboxEmail,
    Quarter, Share,
)
from booking import services as svc
from shop import services as shop_svc
from shop.models import Invoice, LineItem, Product, ProductGroup, ShopConfig


def make_member(name, staff=False, email=""):
    u = User.objects.create_user(username=name, password="x" * 12, email=email)
    if staff:
        # „Verwaltung"-Rolle = Gruppe, nicht mehr das is_staff-Flag.
        from booking.permissions import ensure_verwaltung_group
        u.groups.add(ensure_verwaltung_group())
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50,
                         wish_night_budget=25)
    return m


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class DashboardTests(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Hütte", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        self.member = make_member("Anna", email="anna@example.org")
        self.staff = make_member("Chef", staff=True, email="chef@example.org")
        grp = ProductGroup.objects.create(name="Dienste")
        self.cleaning = Product.objects.create(
            group=grp, name="Endreinigung", price=Decimal("45.00"),
            unit="portion", vat_rate=19, kind="dienstleistung",
            book_with_stay=True, counts_as_cleaning=True, needs_date=True)
        # Eine Buchung im Folgemonat, Endreinigung mitgebucht.
        ny, nm = svc.next_month()
        self.m_from, self.m_to = svc.month_bounds(ny, nm)
        self.alloc = Allocation.objects.create(
            member=self.member, quarter=self.q, start=self.m_from,
            end=self.m_from + timedelta(days=3), persons=2, source="spontaneous")
        shop_svc.purchase_service(self.member, self.cleaning, 1,
                                  service_date=self.alloc.end, allocation=self.alloc)
        OutboxEmail.objects.all().delete()
        mail.outbox = []

    # --- Verknüpfung & Abfrage -------------------------------------------- #
    def test_endreinigung_wird_markiert(self):
        deps = list(svc.departures_in_range(self.m_from, self.m_to))
        self.assertEqual(len(deps), 1)
        self.assertTrue(deps[0].has_cleaning)

    def test_buchung_ohne_endreinigung_nicht_markiert(self):
        other = Allocation.objects.create(
            member=self.member, quarter=self.q,
            start=self.m_from + timedelta(days=10),
            end=self.m_from + timedelta(days=12), persons=1, source="spontaneous")
        deps = {a.id: a.has_cleaning
                for a in svc.departures_in_range(self.m_from, self.m_to)}
        self.assertTrue(deps[self.alloc.id])
        self.assertFalse(deps[other.id])

    # --- Zugriffsschutz ---------------------------------------------------- #
    def test_dashboard_nur_fuer_staff(self):
        self.client.force_login(self.member.user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        self.client.force_login(self.staff.user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    # --- Export ------------------------------------------------------------ #
    def test_export_reinigung_csv_und_xlsx(self):
        self.client.force_login(self.staff.user)
        url = reverse("dashboard_export", args=["reinigung", "csv"])
        r = self.client.get(f"{url}?year={self.m_from.year}&month={self.m_from.month}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        self.assertIn(b"Endreinigung", r.content)
        url = reverse("dashboard_export", args=["buchungen", "xlsx"])
        r = self.client.get(f"{url}?year={self.m_from.year}&month={self.m_from.month}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])

    # --- Versand ----------------------------------------------------------- #
    def test_putzliste_an_team_senden(self):
        OpsConfig.objects.create(admin_emails="verwaltung@example.org",
                                 cleaning_emails="putz@example.org")
        self.client.force_login(self.staff.user)
        self.client.post(reverse("dashboard"), {
            "action": "send_cleaning", "year": self.m_from.year,
            "month": self.m_from.month})
        self.assertTrue(OutboxEmail.objects.filter(to_email="putz@example.org").exists())

    def test_cleaning_faellt_auf_admin_zurueck(self):
        cfg = OpsConfig.objects.create(admin_emails="verwaltung@example.org")
        self.assertEqual(cfg.cleaning_list(), ["verwaltung@example.org"])

    def test_monats_mail_an_verwaltung(self):
        OpsConfig.objects.create(admin_emails="a@example.org, b@example.org")
        n = svc.notify_admins_upcoming(force=True)
        self.assertEqual(n, 2)
        self.assertEqual(OutboxEmail.objects.filter(sent_at__isnull=True).count(), 2)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvoiceReminderTests(TestCase):
    def setUp(self):
        ShopConfig.objects.create(payment_term_days=14)
        self.member = make_member("Bea", email="bea@example.org")
        grp = ProductGroup.objects.create(name="Obst")
        self.apple = Product.objects.create(group=grp, name="Apfel",
                                            price=Decimal("2.00"), unit="kg", vat_rate=7)
        shop_svc.add_item(self.member, self.apple, "1")
        shop_svc.checkout(self.member)
        self.inv, _ = shop_svc.generate_invoice_now(self.member)
        OutboxEmail.objects.all().delete()

    def test_faelligkeit_gesetzt(self):
        self.assertIsNotNone(self.inv.due_date)

    def test_ueberfaellig_und_erinnerung_idempotent(self):
        self.inv.due_date = date.today() - timedelta(days=1)
        self.inv.save(update_fields=["due_date"])
        self.assertTrue(self.inv.is_overdue)
        self.assertIn(self.inv, list(shop_svc.overdue_invoices()))
        self.assertTrue(shop_svc.send_payment_reminder(self.inv))
        self.assertEqual(OutboxEmail.objects.filter(
            to_email="bea@example.org").count(), 1)
        # zweiter Versuch am selben Tag: kein Doppel-Mahnen
        self.assertFalse(shop_svc.send_payment_reminder(self.inv))
        self.assertEqual(OutboxEmail.objects.filter(
            to_email="bea@example.org").count(), 1)

    def test_remind_overdue_bulk(self):
        self.inv.due_date = date.today() - timedelta(days=1)
        self.inv.save(update_fields=["due_date"])
        self.assertEqual(shop_svc.remind_overdue(), 1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvoiceDashboardTests(TestCase):
    def setUp(self):
        ShopConfig.objects.create(payment_term_days=14)
        self.member = make_member("Mia", email="mia@example.org")
        self.staff = make_member("Chefin", staff=True, email="chefin@example.org")
        grp = ProductGroup.objects.create(name="Obst")
        apple = Product.objects.create(group=grp, name="Apfel",
                                       price=Decimal("3.00"), unit="kg", vat_rate=7)
        shop_svc.add_item(self.member, apple, "2")
        shop_svc.checkout(self.member)
        self.overdue_inv, _ = shop_svc.generate_invoice_now(self.member)
        self.overdue_inv.due_date = date.today() - timedelta(days=3)
        self.overdue_inv.save(update_fields=["due_date"])
        shop_svc.add_item(self.member, apple, "1")
        shop_svc.checkout(self.member)
        self.confirmed_inv, _ = shop_svc.generate_invoice_now(self.member)
        self.confirmed_inv.status = Invoice.CONFIRMED
        self.confirmed_inv.save(update_fields=["status"])

    def test_export_nur_fuer_staff(self):
        url = reverse("dashboard_export", args=["rechnungen", "csv"]) + "?status=all"
        self.client.force_login(self.member.user)
        self.assertEqual(self.client.get(url).status_code, 302)   # abgewiesen
        self.client.force_login(self.staff.user)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])

    def test_rechnungsfilter(self):
        self.client.force_login(self.staff.user)
        over = self.client.get(reverse("dashboard") + "?inv=overdue").content.decode()
        self.assertIn(self.overdue_inv.number, over)
        self.assertNotIn(self.confirmed_inv.number, over)
        alle = self.client.get(reverse("dashboard") + "?inv=all").content.decode()
        self.assertIn(self.confirmed_inv.number, alle)
        self.assertIn(self.overdue_inv.number, alle)

    def test_ueberfaellige_per_knopf_erinnern(self):
        OutboxEmail.objects.all().delete()
        self.client.force_login(self.staff.user)
        self.client.post(reverse("dashboard"), {"action": "remind_overdue",
                                                 "year": date.today().year, "month": 1})
        self.assertTrue(OutboxEmail.objects.filter(
            to_email="mia@example.org", subject__contains="Zahlungserinnerung").exists())
        self.overdue_inv.refresh_from_db()
        self.assertIsNotNone(self.overdue_inv.reminded_at)

    def test_dashboard_queries_skalieren_nicht_mit_rechnungen(self):
        """N+1-Wächter: das Dashboard darf nicht pro Rechnung neue Queries feuern
        (total_gross summiert items → ohne prefetch O(n))."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        grp = ProductGroup.objects.get(name="Obst")
        apple = Product.objects.get(name="Apfel")
        for _ in range(15):
            shop_svc.add_item(self.member, apple, "1")
            shop_svc.checkout(self.member)
            shop_svc.generate_invoice_now(self.member)
        self.client.force_login(self.staff.user)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("dashboard") + "?inv=all")
        self.assertLess(len(ctx.captured_queries), 40,
                        f"zu viele Queries: {len(ctx.captured_queries)}")


class DashboardStatsTests(TestCase):
    def test_kennzahlen_und_auslastung(self):
        ec = EquivalenceClass.objects.create(name="E")
        q = Quarter.objects.create(name="Q", eq_class=ec, min_occupancy=1,
                                   max_occupancy=4)
        u = User.objects.create_user("a", password="x" * 12)
        m = Member.objects.create(user=u, display_name="A")
        s = date.today().replace(day=1)
        Allocation.objects.create(member=m, quarter=q, start=s,
                                  end=s + timedelta(days=3), persons=1,
                                  source="spontaneous", provisional=False)
        st = svc.dashboard_stats()
        self.assertEqual(st["n_members"], 1)
        self.assertGreaterEqual(st["n_users"], 1)
        self.assertEqual(st["occ_current"]["booked"], 3)
        self.assertGreater(st["occ_current"]["possible"], 0)
        self.assertIsNone(st["last_lottery"])


class ExportHardeningTests(TestCase):
    """Exporte entschärfen CSV-/Formel-Injektion (führendes ' vor =,+,-,@)."""

    def test_csv_formel_injektion_entschaerft(self):
        from booking import exports
        resp = exports.csv_response("x", ["Name", "Betrag"],
                                    [["=1+2", "10"], ["@cmd", "-5"]])
        body = resp.content.decode("utf-8")
        self.assertIn("'=1+2", body)     # Formel-Zelle bekommt ein '
        self.assertIn("'@cmd", body)
        self.assertIn("'-5", body)
        self.assertNotIn(";=1+2", body)  # nicht ungeschützt

    def test_xlsx_formel_injektion_entschaerft(self):
        import io
        import openpyxl
        from booking import exports
        resp = exports.xlsx_response("x", "T", ["Name"], [["=HYPERLINK(1)"]])
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        self.assertEqual(wb.active["A2"].value, "'=HYPERLINK(1)")

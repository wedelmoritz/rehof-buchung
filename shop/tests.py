"""Tests des Hofladens: Preis-Snapshot, Rechnungserzeugung, Zugriffsrechte."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from booking.models import Member
from shop.models import Invoice, LineItem, Product, ProductGroup, ShopConfig
from shop import services as svc


def make_member(name):
    u = User.objects.create_user(username=name, password="x" * 12)
    return Member.objects.create(user=u, display_name=name)


class ShopBase(TestCase):
    def setUp(self):
        self.group = ProductGroup.objects.create(name="Obst", emoji="🍎")
        self.apple = Product.objects.create(
            group=self.group, name="Äpfel", price=Decimal("3.20"),
            unit="kg", vat_rate=7)
        self.juice = Product.objects.create(
            group=self.group, name="Saft", price=Decimal("2.00"),
            unit="liter", vat_rate=19)
        self.sauna = Product.objects.create(
            group=self.group, name="Sauna", price=Decimal("8.00"),
            unit="portion", vat_rate=19, kind="dienstleistung", needs_date=True)
        self.alice = make_member("alice")
        self.bob = make_member("bob")


class PriceSnapshotTests(ShopBase):
    def test_preis_snapshot_bleibt_bei_aenderung(self):
        item, err = svc.add_item(self.alice, self.apple, "2.5")
        self.assertIsNotNone(item, err)
        self.assertEqual(item.unit_price, Decimal("3.20"))
        self.assertEqual(item.gross, Decimal("8.00"))
        # Produktpreis ändern – Snapshot bleibt
        self.apple.price = Decimal("9.99")
        self.apple.save()
        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("3.20"))

    def test_menge_muss_positiv_sein(self):
        item, err = svc.add_item(self.alice, self.apple, "0")
        self.assertIsNone(item)
        self.assertIn("größer als 0", err)

    def test_dienstleistung_braucht_datum(self):
        item, err = svc.add_item(self.alice, self.sauna, "1")
        self.assertIsNone(item)
        self.assertIn("Datum", err)
        item, err = svc.add_item(self.alice, self.sauna, "1",
                                 service_date=date(2026, 7, 1))
        self.assertIsNotNone(item, err)
        self.assertEqual(item.service_date, date(2026, 7, 1))


class InvoiceTests(ShopBase):
    def test_monatsrechnung_fasst_zusammen(self):
        svc.add_item(self.alice, self.apple, "2")    # 6.40 (7%)
        svc.add_item(self.alice, self.juice, "1")    # 2.00 (19%)
        svc.add_item(self.bob, self.apple, "1")      # 3.20
        invoices = svc.generate_monthly_invoices(date.today().year, date.today().month)
        self.assertEqual(len(invoices), 2)
        inv_a = Invoice.objects.get(member=self.alice)
        self.assertEqual(inv_a.total_gross, Decimal("8.40"))
        # Steuer-Aufschlüsselung je Satz
        rates = {b["rate"]: b for b in inv_a.vat_breakdown()}
        self.assertIn(7, rates)
        self.assertIn(19, rates)
        # Positionen sind der Rechnung zugeordnet (nicht mehr „offen“)
        self.assertEqual(svc.open_items(self.alice).count(), 0)
        self.assertTrue(inv_a.number.startswith("HL-"))

    def test_status_offen_bezahlt_bestaetigt(self):
        svc.add_item(self.alice, self.apple, "2")
        inv = svc.generate_monthly_invoices(date.today().year, date.today().month)[0]
        self.assertEqual(inv.status, Invoice.OPEN)
        ok, err = svc.mark_paid(self.alice, inv.id)
        self.assertTrue(ok, err)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.PAID)
        svc.confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertTrue(inv.archived)


class AccessTests(ShopBase):
    def test_nur_eigene_rechnung_sichtbar(self):
        svc.add_item(self.alice, self.apple, "2")
        inv = svc.generate_monthly_invoices(date.today().year, date.today().month)[0]
        self.client.force_login(self.bob.user)
        self.assertEqual(self.client.get(f"/hofladen/rechnung/{inv.id}/").status_code, 404)
        self.client.force_login(self.alice.user)
        self.assertEqual(self.client.get(f"/hofladen/rechnung/{inv.id}/").status_code, 200)

    def test_fremde_rechnung_nicht_als_bezahlt_meldbar(self):
        svc.add_item(self.alice, self.apple, "2")
        inv = svc.generate_monthly_invoices(date.today().year, date.today().month)[0]
        ok, err = svc.mark_paid(self.bob, inv.id)
        self.assertFalse(ok)

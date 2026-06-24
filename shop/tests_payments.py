"""Tests für die Online-Bezahlung (Mollie, eingebauter Sandbox-Modus)."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking.models import Member
from shop import payments, services as svc
from shop.models import Invoice, LineItem, Payment, ShopConfig


def _member_invoice(member, number="HL-2026-06-001"):
    inv = Invoice.objects.create(member=member, number=number, year=2026, month=6)
    LineItem.objects.create(member=member, invoice=inv, name="Kaffee", unit="stueck",
                            unit_price=Decimal("6.50"), vat_rate=7, quantity=Decimal("2"))
    return inv


class PaymentSandboxTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("m", password="pw12345")
        self.member = Member.objects.create(user=self.user, display_name="M")
        ShopConfig.get_solo()

    def test_sandbox_modus_ohne_key(self):
        inv = _member_invoice(self.member)
        pay = payments.start_payment(inv)
        self.assertTrue(pay.is_sandbox)
        self.assertIn(str(pay.token), pay.checkout_url)

    def test_settle_markiert_rechnung_online_bezahlt(self):
        inv = _member_invoice(self.member)
        pay = payments.start_payment(inv)
        payments.settle_payment(pay)
        inv.refresh_from_db(); pay.refresh_from_db()
        self.assertEqual(pay.status, Payment.PAID)
        self.assertEqual(inv.status, Invoice.CONFIRMED)
        self.assertEqual(inv.payment_method, "mollie")
        self.assertTrue(inv.paid_online)
        self.assertIsNotNone(inv.paid_online_at)
        # Mitglied wird benachrichtigt
        self.assertEqual(self.member.notifications.count(), 1)

    def test_settle_ist_idempotent(self):
        inv = _member_invoice(self.member)
        pay = payments.start_payment(inv)
        payments.settle_payment(pay)
        payments.settle_payment(pay)  # darf nichts kaputt machen
        self.assertEqual(self.member.notifications.count(), 1)

    def test_http_flow_mitglied(self):
        inv = _member_invoice(self.member)
        self.client.force_login(self.user)
        r = self.client.get(reverse("pay_invoice", args=[inv.id]))
        self.assertEqual(r.status_code, 302)
        pay = Payment.objects.get(invoice=inv)
        # Sandbox-Seite bezahlen
        r2 = self.client.post(reverse("payment_sandbox", args=[pay.token]),
                              {"action": "pay"})
        self.assertEqual(r2.status_code, 302)
        inv.refresh_from_db()
        self.assertTrue(inv.paid_online)

    def test_abbrechen_laesst_rechnung_offen(self):
        inv = _member_invoice(self.member)
        pay = payments.start_payment(inv)
        self.client.post(reverse("payment_sandbox", args=[pay.token]),
                         {"action": "cancel"})
        inv.refresh_from_db(); pay.refresh_from_db()
        self.assertEqual(pay.status, Payment.CANCELED)
        self.assertEqual(inv.status, Invoice.OPEN)
        self.assertFalse(inv.paid_online)

    def test_payments_deaktiviert(self):
        cfg = ShopConfig.get_solo(); cfg.payments_active = False; cfg.save()
        inv = _member_invoice(self.member)
        self.client.force_login(self.user)
        r = self.client.get(reverse("pay_invoice", args=[inv.id]))
        self.assertRedirects(r, reverse("shop_invoice", args=[inv.id]))
        self.assertFalse(Payment.objects.exists())

    def test_echtbetrieb_ohne_key_blockiert(self):
        # Sicherheitslücke (alt): aktiv + kein Key fiel still in den Sandbox-Modus.
        cfg = ShopConfig.get_solo()
        cfg.payments_active = True; cfg.payments_test_mode = False
        cfg.mollie_api_key = ""; cfg.save()
        self.assertFalse(payments.payments_enabled())
        inv = _member_invoice(self.member)
        with self.assertRaises(payments.PaymentUnavailable):
            payments.start_payment(inv)
        self.client.force_login(self.user)
        r = self.client.get(reverse("pay_invoice", args=[inv.id]))
        self.assertRedirects(r, reverse("shop_invoice", args=[inv.id]))
        self.assertFalse(Payment.objects.exists())

    def test_testmodus_simuliert_auch_ohne_key(self):
        cfg = ShopConfig.get_solo()
        cfg.payments_active = True; cfg.payments_test_mode = True; cfg.save()
        self.assertTrue(payments.payments_enabled())
        pay = payments.start_payment(_member_invoice(self.member))
        self.assertTrue(pay.is_sandbox)

    def test_gast_rechnung_online_bezahlen(self):
        from booking.models import Guest
        g = Guest.objects.create(name="Gast", email="g@example.org")
        inv = Invoice.objects.create(guest=g, number="HL-2026-06-099",
                                     year=2026, month=6)
        LineItem.objects.create(guest=g, invoice=inv, name="Nacht", unit="Nacht",
                                unit_price=Decimal("80.00"), vat_rate=7,
                                quantity=Decimal("2"))
        payments.settle_payment(payments.start_payment(inv))
        inv.refresh_from_db()
        self.assertTrue(inv.paid_online)
        self.assertEqual(inv.status, Invoice.CONFIRMED)

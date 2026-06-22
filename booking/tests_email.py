"""Tests für das E-Mail-Fundament: Outbox, Versand, Opt-out, Ereignis-Hooks."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from booking.models import Member, OutboxEmail
from booking import services as svc


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailOutboxTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("e", "e@example.org", "x" * 12)
        self.m = Member.objects.create(user=self.u, display_name="Erna")
        OutboxEmail.objects.all().delete()  # evtl. Aktivierungs-Mail vom Signal weg
        mail.outbox = []

    def test_email_member_opt_out_und_fehlende_adresse(self):
        self.m.email_opt_in = False
        self.m.save()
        self.assertIsNone(svc.email_member(self.m, "S", "B"))
        self.m.email_opt_in = True
        self.m.save()
        self.u.email = ""
        self.u.save()
        self.assertIsNone(svc.email_member(self.m, "S", "B"))
        self.u.email = "e@example.org"
        self.u.save()
        self.assertIsNotNone(svc.email_member(self.m, "S", "B"))
        self.assertEqual(OutboxEmail.objects.filter(sent_at__isnull=True).count(), 1)

    def test_send_outbox_versendet_und_ist_idempotent(self):
        svc.queue_email("x@example.org", "Betreff", "Text")
        call_command("send_outbox")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Betreff")
        self.assertIsNotNone(OutboxEmail.objects.get(to_email="x@example.org").sent_at)
        call_command("send_outbox")  # nicht erneut senden
        self.assertEqual(len(mail.outbox), 1)

    def test_aktivierung_reiht_mail_ein(self):
        u2 = User.objects.create_user("a", "a@example.org", "x" * 12)
        Member.objects.create(user=u2, display_name="Anton")  # Signal → Mail
        self.assertTrue(OutboxEmail.objects.filter(to_email="a@example.org").exists())

    def test_rechnung_reiht_mail_ein(self):
        from decimal import Decimal
        from shop.models import Product, ProductGroup
        from shop import services as shop_svc
        g = ProductGroup.objects.create(name="Obst")
        apple = Product.objects.create(group=g, name="Äpfel", price=Decimal("3.20"),
                                       unit="kg", vat_rate=7)
        shop_svc.add_item(self.m, apple, "2")
        shop_svc.checkout(self.m)
        inv, _ = shop_svc.generate_invoice_now(self.m)
        self.assertTrue(
            OutboxEmail.objects.filter(to_email="e@example.org",
                                       subject__contains=inv.number).exists())

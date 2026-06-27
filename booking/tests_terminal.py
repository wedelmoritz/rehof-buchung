"""Tests für das Hofladen-Terminal (ADR 0053): Token-Gate, Roster-Datensparsamkeit,
idempotenter Sync auf die Monatsrechnung, PIN."""
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import Member, TerminalConfig
from shop.models import LineItem, Product, ProductGroup, Purchase


class TerminalBase(TestCase):
    def setUp(self):
        self.cfg = TerminalConfig.get_solo()
        self.cfg.enabled = True
        self.cfg.token = "geheim-token-123"
        self.cfg.save()
        u = User.objects.create_user("gast1", password="x")
        self.m = Member.objects.create(user=u, display_name="Gast Eins",
                                       is_external=True, terminal_enabled=True)
        self.m.set_terminal_pin("123456")
        self.m.save()
        g = ProductGroup.objects.create(name="Eier & Milch", emoji="🥚")
        self.p = Product.objects.create(group=g, name="Eier 6er", unit="Schachtel",
                                        price=Decimal("3.00"), vat_rate=Decimal("7"),
                                        active=True)

    def _post(self, name, body):
        return self.client.post(reverse(name), data=json.dumps(body),
                                content_type="application/json")


class TerminalTokenTests(TerminalBase):
    def test_wrong_token_forbidden(self):
        self.assertEqual(self._post("terminal_data", {"token": "falsch"}).status_code, 403)
        self.assertEqual(self._post("terminal_data", {}).status_code, 403)

    def test_disabled_forbidden_even_with_token(self):
        self.cfg.enabled = False
        self.cfg.save()
        self.assertEqual(
            self._post("terminal_data", {"token": "geheim-token-123"}).status_code, 403)

    def test_data_payload_minimal_no_pii(self):
        r = self._post("terminal_data", {"token": "geheim-token-123"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        # genau ein terminalfähiges Konto, nur u/n/p – keine PII-Schlüssel
        self.assertEqual(len(d["roster"]), 1)
        entry = d["roster"][0]
        self.assertEqual(set(entry.keys()), {"u", "n", "p"})
        self.assertEqual(entry["u"], "gast1")
        self.assertTrue(entry["p"].startswith("pbkdf2_sha256$"))
        self.assertNotIn("iban", json.dumps(d))
        self.assertEqual(len(d["products"]), 1)

    def test_member_without_pin_not_in_roster(self):
        u = User.objects.create_user("gast2", password="x")
        Member.objects.create(user=u, display_name="Ohne PIN",
                              terminal_enabled=True)   # keine PIN gesetzt
        d = self._post("terminal_data", {"token": "geheim-token-123"}).json()
        self.assertEqual(len(d["roster"]), 1)   # nur gast1


class TerminalSyncTests(TerminalBase):
    def _txn(self, ref, qty=2, username="gast1"):
        return {"token": "geheim-token-123", "transactions": [
            {"ref": ref, "username": username, "items": [{"id": self.p.id, "qty": qty}]}]}

    def test_sync_creates_purchase_on_monthly_tab(self):
        r = self._post("terminal_sync", self._txn("ref-1", qty=2))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["accepted"], ["ref-1"])
        pur = Purchase.objects.get(terminal_ref="ref-1")
        self.assertEqual(pur.member, self.m)
        li = LineItem.objects.get(purchase=pur)
        self.assertEqual(li.quantity, Decimal("2"))
        self.assertEqual(li.unit_price, Decimal("3.00"))
        self.assertIsNone(li.invoice_id)   # offen -> Monatsrechnung

    def test_sync_idempotent(self):
        self._post("terminal_sync", self._txn("ref-x"))
        self._post("terminal_sync", self._txn("ref-x"))   # erneut (Nachsync)
        self.assertEqual(Purchase.objects.filter(terminal_ref="ref-x").count(), 1)
        self.assertEqual(LineItem.objects.count(), 1)

    def test_sync_rejects_non_terminal_member(self):
        u = User.objects.create_user("fremd", password="x")
        Member.objects.create(user=u, display_name="Fremd")   # nicht terminalfähig
        r = self._post("terminal_sync", self._txn("ref-2", username="fremd"))
        self.assertEqual(r.json()["rejected"], ["ref-2"])
        self.assertEqual(Purchase.objects.count(), 0)

    def test_sync_wrong_token_forbidden(self):
        body = self._txn("ref-3"); body["token"] = "falsch"
        self.assertEqual(self._post("terminal_sync", body).status_code, 403)


class TerminalPinTests(TestCase):
    def test_set_and_check_pin(self):
        u = User.objects.create_user("p", password="x")
        m = Member.objects.create(user=u, display_name="P", terminal_enabled=True)
        m.set_terminal_pin("654321")
        self.assertTrue(m.check_terminal_pin("654321"))
        self.assertFalse(m.check_terminal_pin("000000"))
        self.assertTrue(m.terminal_ready)

    def test_profile_sets_pin(self):
        u = User.objects.create_user("q", email="q@e.de", password="x")
        m = Member.objects.create(user=u, display_name="Q", terminal_enabled=True)
        self.client.force_login(u)
        self.client.post(reverse("profile"),
                         {"action": "set_terminal_pin", "pin": "246810"})
        m.refresh_from_db()
        self.assertTrue(m.check_terminal_pin("246810"))

    def test_profile_rejects_short_pin(self):
        u = User.objects.create_user("r", email="r@e.de", password="x")
        m = Member.objects.create(user=u, display_name="R", terminal_enabled=True)
        self.client.force_login(u)
        self.client.post(reverse("profile"),
                         {"action": "set_terminal_pin", "pin": "123"})
        m.refresh_from_db()
        self.assertFalse(m.terminal_pin)

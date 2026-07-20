"""Security-Regressionstests (Voll-App-Review, Fix-Batch A):
* `_verw_post` erzwingt Least-Privilege je Aktion (granulare Rolle darf nicht alles).
* `payment_sandbox` schließt echte (Nicht-Sandbox-)Zahlungen aus.
* `member_search` liefert keine E-Mail-Adressen (username) mehr aus.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from booking.models import Member
from shop.models import Invoice, Payment, Product, ProductGroup


def _perm(codename):
    return Permission.objects.get(codename=codename,
                                  content_type__app_label="booking")


def _verw_user(name, *codenames):
    u = User.objects.create_user(username=name, password="x" * 12)
    for c in codenames:
        u.user_permissions.add(_perm(c))
    return User.objects.get(pk=u.pk)          # frischer Perm-Cache


class VerwPostRbacTests(TestCase):
    def test_hofladen_rolle_darf_keinen_bankimport(self):
        # Nur „Hofladen"-Recht → erreicht zwar das Dashboard (Bereichs-Gate), darf aber
        # KEINE Rechnungs-Aktion (import_bank) auslösen.
        self.client.force_login(_verw_user("shopper", "access_hofladen"))
        r = self.client.post(reverse("dashboard"), {"action": "import_bank"})
        self.assertEqual(r.status_code, 403)

    def test_hofladen_rolle_darf_keine_sperrzeit_loeschen(self):
        self.client.force_login(_verw_user("shopper2", "access_hofladen"))
        r = self.client.post(reverse("dashboard"),
                             {"action": "delete_block", "block_id": 1})
        self.assertEqual(r.status_code, 403)

    def test_rechnungs_rolle_darf_bankimport(self):
        # Mit dem passenden Recht kein 403 (ohne Datei nur Fehlermeldung + Redirect).
        self.client.force_login(_verw_user("fin", "access_rechnungen"))
        r = self.client.post(reverse("dashboard"), {"action": "import_bank"})
        self.assertNotEqual(r.status_code, 403)

    def test_superuser_darf_alles(self):
        su = User.objects.create_superuser("root", "root@e.org", "x" * 12)
        self.client.force_login(su)
        r = self.client.post(reverse("dashboard"), {"action": "import_bank"})
        self.assertNotEqual(r.status_code, 403)


class PaymentSandboxGuardTests(TestCase):
    def setUp(self):
        u = User.objects.create_user("gina", password="x" * 12)
        self.member = Member.objects.create(user=u, display_name="Gina")
        self.inv = Invoice.objects.create(member=self.member, year=2026, month=1,
                                          number="HL-2026-01-001")
        self.pay = Payment.objects.create(invoice=self.inv, amount=Decimal("5.00"),
                                          is_sandbox=False)     # ECHT-Modus

    def test_echte_zahlung_nicht_ueber_sandbox_bezahlbar(self):
        url = reverse("payment_sandbox", args=[self.pay.token])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.post(url, {"action": "pay"}).status_code, 404)
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.status, Payment.OPEN)         # unverändert

    def test_sandbox_zahlung_weiterhin_erreichbar(self):
        self.pay.is_sandbox = True
        self.pay.save(update_fields=["is_sandbox"])
        url = reverse("payment_sandbox", args=[self.pay.token])
        self.assertEqual(self.client.get(url).status_code, 200)


class MemberSearchPrivacyTests(TestCase):
    def setUp(self):
        vu = User.objects.create_user("viewer", password="x" * 12,
                                      email="viewer@e.org")
        self.viewer = Member.objects.create(user=vu, display_name="Viewer")
        # Fremdes Mitglied, dessen Benutzername die E-Mail ist (Regelfall).
        ou = User.objects.create_user("berta@example.org", password="x" * 12,
                                      email="berta@example.org")
        Member.objects.create(user=ou, display_name="Berta")

    def test_suche_liefert_keine_email(self):
        self.client.force_login(self.viewer.user)
        data = self.client.get(reverse("member_search") + "?q=ber").json()
        self.assertTrue(data["results"])                       # Berta wird gefunden
        for row in data["results"]:
            self.assertNotIn("username", row)                  # kein E-Mail-Feld
            self.assertNotIn("@", "".join(str(v) for v in row.values()))

"""Tests für die Rollentrennung Admin (Backend) vs. Verwaltung (Dashboard)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking.permissions import ensure_verwaltung_group, is_admin, is_verwaltung
from shop.models import Product, ProductGroup


class RoleHelperTests(TestCase):
    def test_flags(self):
        g = ensure_verwaltung_group()
        verw = User.objects.create_user("verw", password="pw12345")
        verw.groups.add(g)
        adm = User.objects.create_superuser("adm", "a@example.org", "pw12345")
        normal = User.objects.create_user("n", password="pw12345")
        self.assertTrue(is_verwaltung(verw))
        self.assertFalse(is_admin(verw))
        self.assertTrue(is_admin(adm))
        self.assertTrue(is_verwaltung(adm))
        self.assertFalse(is_verwaltung(normal))

    def test_reines_staff_flag_ist_keine_verwaltung(self):
        # Ein bloßes is_staff (für ein enges Backend-Recht) darf NICHT das
        # ganze Verwaltungs-Dashboard freischalten.
        staff = User.objects.create_user("s", password="pw12345")
        staff.is_staff = True; staff.save()
        self.assertFalse(is_verwaltung(staff))
        self.assertFalse(is_admin(staff))


class VerwaltungAccessTests(TestCase):
    def setUp(self):
        self.verw = User.objects.create_user("verw", password="pw12345")
        self.verw.groups.add(ensure_verwaltung_group())
        ProductGroup.objects.create(name="Obst")

    def test_dashboard_und_produkte_erreichbar(self):
        self.client.force_login(self.verw)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("dashboard_products")).status_code, 200)

    def test_kein_backend(self):
        # Verwaltung (kein is_staff) darf NICHT ins Django-Backend.
        self.client.force_login(self.verw)
        r = self.client.get("/admin/", follow=False)
        self.assertIn(r.status_code, (302, 403))  # Login-Redirect bzw. verboten

    def test_kann_produkt_anlegen(self):
        self.client.force_login(self.verw)
        grp = ProductGroup.objects.first()
        r = self.client.post(reverse("dashboard_products"), {
            "action": "add_product", "group": grp.id, "name": "Birnen",
            "price": "2,40", "unit": "kg", "vat_rate": "7", "kind": "ware"})
        self.assertEqual(r.status_code, 302)
        p = Product.objects.get(name="Birnen")
        self.assertEqual(str(p.price), "2.40")


class NormalMemberBlockedTests(TestCase):
    def test_mitglied_kein_dashboard(self):
        from booking.models import Member
        u = User.objects.create_user("u", password="pw12345")
        Member.objects.create(user=u, display_name="U")
        self.client.force_login(u)
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, reverse("overview"))

"""B8/ADR 0094: Buchungen durch die Verwaltung im Namen aktiver Mitglieder –
Audit (`created_by`) + Benachrichtigung + Hinweis in „Meine Buchungen“."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib import admin as djadmin
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings

from booking.admin import AllocationAdmin
from booking.models import (
    Allocation, EquivalenceClass, Member, Membership, Notification,
    OpsConfig, OutboxEmail, Quarter, Share,
)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class StaffBookingTests(TestCase):
    def setUp(self):
        OpsConfig.objects.all().delete()
        OpsConfig.objects.create(admin_emails="office@example.org")
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="K1", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        u = User.objects.create_user("mara", "mara@example.org", "x" * 12)
        self.m = Member.objects.create(user=u, display_name="Mara")
        ms = Membership.objects.create(eg_number="EG-1", label="Mara",
                                       annual_night_budget=50, wish_night_budget=25)
        Share.objects.create(membership=ms, member=self.m, night_budget=50,
                             wish_night_budget=25)
        self.staff = User.objects.create_user("chef", "chef@example.org", "x" * 12,
                                              is_staff=True, is_superuser=True)
        self.admin = AllocationAdmin(Allocation, djadmin.site)

    def _req(self):
        r = RequestFactory().post("/admin/")
        r.user = self.staff
        return r

    def _alloc(self, **kw):
        d = date.today() + timedelta(days=20)
        kw.setdefault("source", "spontaneous")
        return Allocation(member=self.m, quarter=self.q, start=d,
                          end=d + timedelta(days=3), persons=2, **kw)

    def test_anlegen_setzt_created_by_und_meldet(self):
        a = self._alloc()
        self.admin.save_model(self._req(), a, form=None, change=False)
        a.refresh_from_db()
        self.assertEqual(a.created_by_id, self.staff.id)
        self.assertTrue(a.by_management)
        self.assertTrue(Notification.objects.filter(
            member=self.m, message__icontains="angelegt").exists())
        self.assertTrue(OutboxEmail.objects.filter(
            to_email="mara@example.org").exists())

    def test_storno_meldet_und_loescht(self):
        a = self._alloc()
        a.created_by = self.staff
        a.save()
        OutboxEmail.objects.all().delete()
        Notification.objects.all().delete()
        self.admin.delete_model(self._req(), a)
        self.assertFalse(Allocation.objects.filter(pk=a.pk).exists())
        self.assertTrue(Notification.objects.filter(
            member=self.m, message__icontains="storniert").exists())

    def test_losung_wird_nicht_gemeldet(self):
        a = self._alloc(source="lottery")
        self.admin.save_model(self._req(), a, form=None, change=False)
        # Losung hat eigene Benachrichtigung → save_model meldet NICHT zusätzlich.
        self.assertFalse(Notification.objects.filter(member=self.m).exists())

    def test_eigene_buchung_ist_nicht_by_management(self):
        # Mitglied bucht selbst (created_by = eigener User) → kein Hinweis.
        a = self._alloc(created_by=self.m.user)
        a.save()
        self.assertFalse(a.by_management)

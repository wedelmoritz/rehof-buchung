"""Tests fürs Benachrichtigungs-Framework (ADR 0089): Katalog-Rendering (SSTI-frei),
Dispatcher, geplante Status-Vorwarnung."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from booking.models import (
    Member, NotificationSetting, Notification, OpsConfig, OutboxEmail,
)
from booking.notify_catalog import render
from booking import services as svc


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationFrameworkTests(TestCase):
    def setUp(self):
        OpsConfig.objects.all().delete()
        OpsConfig.objects.create(admin_emails="office@example.org")

    def _member(self, name, **kw):
        u = User.objects.create_user(name, f"{name}@example.org", "x" * 12)
        return Member.objects.create(user=u, display_name=name, **kw)

    def test_render_ist_ssti_frei(self):
        # $-Ausdrücke im Kontext werden NICHT als Vorlage interpretiert (nur Daten).
        subj, body = render("announcement",
                             {"subject": "Hallo", "body": "Wert=$geheim"})
        self.assertIn("Hallo", subj)
        self.assertIn("Wert=$geheim", body)   # unverändert eingesetzt, nicht ausgewertet

    def test_dispatch_ops_geht_an_verwaltung(self):
        OutboxEmail.objects.all().delete()
        svc.dispatch_event("overdue_overview", {"body": "Rechnung HL-1"})
        self.assertTrue(OutboxEmail.objects.filter(
            to_email="office@example.org", subject__icontains="Überfällige").exists())

    def test_dispatch_respektiert_aus_schalter(self):
        OutboxEmail.objects.all().delete()
        s = NotificationSetting.for_event("overdue_overview")
        s.enabled = False
        s.save(update_fields=["enabled"])
        self.assertIsNone(svc.dispatch_event("overdue_overview", {"body": "x"}))
        self.assertFalse(OutboxEmail.objects.exists())

    def test_status_vorwarnung(self):
        OutboxEmail.objects.all().delete()
        today = date.today()
        m = self._member("Vera")
        m.passive_from = today + timedelta(days=3)      # innerhalb Vorlauf (14)
        m.save(update_fields=["passive_from"])
        far = self._member("Fern")
        far.excluded_from = today + timedelta(days=90)  # außerhalb Vorlauf
        far.save(update_fields=["excluded_from"])
        n = svc.send_status_warnings(today)
        self.assertEqual(n, 1)                          # nur Vera
        mail = OutboxEmail.objects.filter(subject__icontains="Statuswechsel").first()
        self.assertIsNotNone(mail)
        self.assertIn("Vera", mail.body)
        self.assertNotIn("Fern", mail.body)
        # Idempotent: am selben Tag kein zweiter Versand.
        self.assertEqual(svc.send_status_warnings(today), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BLNotificationTests(TestCase):
    def setUp(self):
        from booking.models import EquivalenceClass, Quarter, Membership, Share
        OpsConfig.objects.all().delete()
        OpsConfig.objects.create(admin_emails="office@example.org")
        self.cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="K1", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        u = User.objects.create_user("mia", "mia@example.org", "x" * 12)
        self.m = Member.objects.create(user=u, display_name="Mia")
        ms = Membership.objects.create(eg_number="EG-1", label="Mia",
                                       annual_night_budget=50, wish_night_budget=25)
        Share.objects.create(membership=ms, member=self.m, night_budget=50,
                             wish_night_budget=25)

    def _daily(self, key):
        s = NotificationSetting.for_event(key)
        s.frequency = NotificationSetting.DAILY
        s.save(update_fields=["frequency"])
        return s

    def test_kurzfristige_buchung_meldet_verwaltung_sofort(self):
        from booking.models import Allocation
        OutboxEmail.objects.all().delete()
        today = date.today()
        a = Allocation.objects.create(
            member=self.m, quarter=self.q, start=today + timedelta(days=3),
            end=today + timedelta(days=6), persons=2, source="spontaneous")
        svc.notify_booking_activity(a, action="new")
        self.assertTrue(OutboxEmail.objects.filter(
            to_email="office@example.org", subject__icontains="Kurzfristig").exists())

    def test_langfristige_buchung_keine_sofortmeldung(self):
        from booking.models import Allocation
        OutboxEmail.objects.all().delete()
        today = date.today()
        a = Allocation.objects.create(
            member=self.m, quarter=self.q, start=today + timedelta(days=40),
            end=today + timedelta(days=43), persons=2, source="spontaneous")
        svc.notify_booking_activity(a, action="new")
        self.assertFalse(OutboxEmail.objects.exists())

    def test_overdue_overview_wenn_faellig(self):
        OutboxEmail.objects.all().delete()
        self._daily("overdue_overview")
        n = svc.send_overdue_overview(date.today())
        self.assertTrue(OutboxEmail.objects.filter(
            subject__icontains="Überfällige").exists())

    def test_lottery_reminder_einmal_je_periode(self):
        from booking.models import BookingPeriod
        OutboxEmail.objects.all().delete()
        today = date.today()
        p = BookingPeriod.objects.create(
            name="Losung", target_year=today.year + 1,
            start=date(today.year + 1, 1, 1), end=date(today.year + 2, 1, 1),
            draw_at=today + timedelta(days=5))
        self.assertEqual(svc.send_lottery_reminder(today), 1)
        p.refresh_from_db()
        self.assertIsNotNone(p.bl_reminder_at)
        self.assertEqual(svc.send_lottery_reminder(today), 0)   # nicht doppelt

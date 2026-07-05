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

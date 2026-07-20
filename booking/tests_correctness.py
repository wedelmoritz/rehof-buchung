"""Korrektheits-Regressionstests (Voll-App-Review, Fix-Batch B):
* Externe Stornierung entwertet die noch unbezahlte Rechnung (kein Falsch-Mahnen).
* Doppelbuchungs-Schutz: adjust_allocation/create_external_booking prüfen unter der
  Quartier-Zeilensperre; die Frei-Prüfung lehnt belegte Zeiträume weiter ab
  (die Sperre selbst wirkt gegen Nebenläufigkeit – unter SQLite ein No-Op).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from booking import services as svc
from booking.models import (
    Allocation, EquivalenceClass, ExternalBooking, Guest, Member, Membership,
    Quarter, Share,
)
from shop import services as shop_svc
from shop.models import Invoice

TODAY = date.today()


def _member(name):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


class ExternalCancelInvoiceTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4,
                                        external_bookable=True)
        self.guest = Guest.objects.create(name="Gast", email="gast@e.org")
        self.inv = Invoice.objects.create(
            guest=self.guest, year=TODAY.year, month=TODAY.month,
            number="HL-EXT-001", due_date=TODAY - timedelta(days=5))  # überfällig, wenn offen
        self.booking = ExternalBooking.objects.create(
            guest=self.guest, quarter=self.q, start=TODAY + timedelta(days=30),
            end=TODAY + timedelta(days=34), persons=2,
            status=ExternalBooking.CONFIRMED, total_gross=Decimal("200.00"),
            invoice=self.inv)

    def test_storno_entwertet_unbezahlte_rechnung(self):
        svc.cancel_external_booking(self.booking)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.CANCELLED)
        # Fällt aus dem Mahnlauf (überfällige offene Rechnungen).
        self.assertNotIn(self.inv, list(shop_svc.overdue_invoices()))

    def test_storno_laesst_bezahlte_rechnung_unangetastet(self):
        self.inv.status = Invoice.CONFIRMED
        self.inv.save(update_fields=["status"])
        svc.cancel_external_booking(self.booking)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.CONFIRMED)


class DoubleBookingGuardTests(TestCase):
    def setUp(self):
        cls = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Turm", eq_class=cls,
                                        min_occupancy=1, max_occupancy=4,
                                        external_bookable=True)
        self.q2 = Quarter.objects.create(name="Hütte", eq_class=cls,
                                         min_occupancy=1, max_occupancy=4)
        self.alice = _member("alice")
        self.s = TODAY + timedelta(days=40)
        self.e = self.s + timedelta(days=4)
        # Belegung im q durch eine bestehende Buchung.
        Allocation.objects.create(member=_member("occupant"), quarter=self.q,
                                  start=self.s, end=self.e, source="spontaneous",
                                  provisional=False)

    def test_adjust_auf_belegtes_quartier_abgelehnt(self):
        a = Allocation.objects.create(member=self.alice, quarter=self.q2,
                                      start=self.s, end=self.e,
                                      source="spontaneous", provisional=False)
        ok, err = svc.adjust_allocation(self.alice, a.id, self.s, self.e,
                                        new_quarter=self.q)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_extern_auf_belegtes_quartier_abgelehnt(self):
        booking, err = svc.create_external_booking(
            self.q, self.s, self.e, 2, name="Gast Zwei", email="g2@e.org")
        self.assertIsNone(booking)
        self.assertIsNotNone(err)

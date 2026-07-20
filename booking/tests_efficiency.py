"""Effizienz-Regressionstests (Voll-App-Review, Fix-Batch C, ADR 0111).

Wacht über die beseitigten N+1-Muster in den Hot-Paths:
* `free_quarters_for` lädt Freigabe-Perioden + Belegung EINMAL vorab und darf
  daher NICHT je Quartier zusätzliche Abfragen feuern (Abfragezahl unabhängig
  von der Quartier-Anzahl).
* Die Rechnungsliste (`shop_invoices`) summiert je Rechnung `total_gross` über
  die Positionen – mit `prefetch_related("items")` bleibt die Abfragezahl
  konstant statt je Rechnung eine weitere zu feuern.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from booking import services as svc
from booking.models import (
    BookingPeriod, EquivalenceClass, Member, Membership, Quarter, Share,
)
from shop.models import Invoice, LineItem

NEXT = date.today().year + 1


def _member(name):
    u = User.objects.create_user(name, password="x" * 12, email=f"{name}@e.org")
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50, wish_night_budget=25)
    return m


def _quarters(n, cls, prefix="Q"):
    for i in range(n):
        Quarter.objects.create(name=f"{prefix}{i}", eq_class=cls,
                               min_occupancy=1, max_occupancy=4)


def _count(fn) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


class FreeQuartersForQueryTests(TestCase):
    """`free_quarters_for` darf NICHT je Quartier eine Abfrage feuern (ADR 0111)."""

    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="K")
        BookingPeriod.objects.create(
            name=f"global {NEXT}", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), status=BookingPeriod.FREE_BOOKING)
        self.start = date(NEXT, 5, 1)
        self.end = self.start + timedelta(days=4)

    def test_abfragen_unabhaengig_von_quartier_anzahl(self):
        _quarters(3, self.cls, prefix="A")
        few = _count(lambda: svc.free_quarters_for(self.start, self.end, 2))
        _quarters(12, self.cls, prefix="B")   # jetzt 15 Quartiere
        many = _count(lambda: svc.free_quarters_for(self.start, self.end, 2))
        # Gleiche Abfragezahl trotz 5× so vieler Quartiere = kein N+1.
        self.assertEqual(few, many)
        # Und der Inhalt stimmt weiterhin (alle frei/freigeschaltet).
        self.assertEqual(len(svc.free_quarters_for(self.start, self.end, 2)), 15)

    def test_belegtes_quartier_faellt_raus(self):
        _quarters(2, self.cls)
        q0 = Quarter.objects.get(name="Q0")
        svc.book_spontaneous(_member("occ"), q0, self.start, self.end)
        free = svc.free_quarters_for(self.start, self.end, 2)
        self.assertNotIn(q0, free)
        self.assertEqual(len(free), 1)


class ShopInvoicesPrefetchQueryTests(TestCase):
    """Die Rechnungsliste summiert `total_gross` je Rechnung über die Positionen;
    mit Prefetch bleibt die Abfragezahl unabhängig von der Rechnungs-Anzahl."""

    def setUp(self):
        self.m = _member("kunde")

    def _make_invoices(self, n):
        base = Invoice.objects.count()
        for i in range(base, base + n):
            inv = Invoice.objects.create(
                member=self.m, year=NEXT, month=1, number=f"HL-{NEXT}-01-{i:03d}",
                due_date=date(NEXT, 2, 1))
            for _ in range(2):
                LineItem.objects.create(
                    member=self.m, invoice=inv, name="Ware", quantity=1,
                    unit_price=Decimal("5.00"), vat_rate=7)

    def test_liste_mit_prefetch_konstante_abfragen(self):
        self._make_invoices(2)

        def render():
            invs = list(self.m.invoices.prefetch_related("items"))
            return [inv.total_gross for inv in invs]

        few = _count(render)
        self._make_invoices(8)   # jetzt 10 Rechnungen
        many = _count(render)
        self.assertEqual(few, many)

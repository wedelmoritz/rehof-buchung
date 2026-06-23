"""Reine Logik für externe Gäste (ohne Django/DB): Erstattungs-Staffel."""
from datetime import date
from decimal import Decimal

from booking.external import cancellation_refund


def test_volle_erstattung_bei_genug_vorlauf():
    refund, pct, label = cancellation_refund(
        Decimal("300.00"), arrival=date(2026, 7, 1), today=date(2026, 5, 1),
        free_days=30, partial_days=7, partial_percent=50)
    assert pct == 100
    assert refund == Decimal("300.00")


def test_teil_erstattung_im_mittleren_fenster():
    refund, pct, label = cancellation_refund(
        Decimal("300.00"), arrival=date(2026, 7, 1), today=date(2026, 6, 20),
        free_days=30, partial_days=7, partial_percent=50)
    assert pct == 50
    assert refund == Decimal("150.00")


def test_keine_erstattung_kurzfristig():
    refund, pct, label = cancellation_refund(
        Decimal("300.00"), arrival=date(2026, 7, 1), today=date(2026, 6, 29),
        free_days=30, partial_days=7, partial_percent=50)
    assert pct == 0
    assert refund == Decimal("0.00")

"""Tests für externe Gäste: Verfügbarkeitsregeln, Buchung (Rechnung wie Hofladen),
Verfügbarkeits-Blockade, Kontoabgleich, öffentliche Seite."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from booking.external import external_allowed
from booking.models import (
    EquivalenceClass, ExternalBooking, ExternalConfig, Guest, Quarter,
    QuarterPrice, SeasonRule,
)
from booking import services as svc
from shop.models import Invoice, ShopConfig
from shop import reconcile


def _next_monday(after=None):
    d = (after or date.today()) + timedelta(days=1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


class ExternalPolicyTests(TestCase):
    """Reine Regel-Logik (ohne DB)."""

    def setUp(self):
        self.today = date(2026, 6, 1)  # Montag

    def test_wochentage_mo_do(self):
        wd = {0, 1, 2, 3}
        mon = _next_monday(self.today)
        ok, _ = external_allowed(mon, mon + timedelta(days=3), today=self.today,
                                 allowed_weekdays=wd, min_nights=1)
        self.assertTrue(ok)
        # Stay über das Wochenende (enthält Fr/Sa-Nacht) -> abgelehnt
        ok2, msg = external_allowed(mon, mon + timedelta(days=6), today=self.today,
                                    allowed_weekdays=wd, min_nights=1)
        self.assertFalse(ok2)

    def test_min_max_lead(self):
        mon = _next_monday(self.today)
        ok, msg = external_allowed(mon, mon + timedelta(days=1), today=self.today,
                                   min_nights=2)
        self.assertFalse(ok)  # zu kurz
        ok2, _ = external_allowed(mon, mon + timedelta(days=2), today=self.today,
                                  min_nights=2, max_nights=5)
        self.assertTrue(ok2)
        # Vorlauf: Anreise heute, aber lead_days=3
        ok3, _ = external_allowed(self.today, self.today + timedelta(days=2),
                                  today=self.today, lead_days=3)
        self.assertFalse(ok3)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ExternalBookingTests(TestCase):
    def setUp(self):
        ShopConfig.objects.create(iban="DE111", invoice_prefix="HL")
        self.cfg = ExternalConfig.objects.create(
            active=True, allowed_weekdays="0,1,2,3", min_nights=2,
            cleaning_fee=Decimal("50.00"), lead_days=0)
        self.ec = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(
            name="Gartenhaus", eq_class=self.ec, min_occupancy=1, max_occupancy=4,
            external_bookable=True, price_per_night=Decimal("80.00"))
        self.mon = _next_monday()
        self.wed = self.mon + timedelta(days=3)   # 3 Nächte Mo,Di,Mi

    def test_quote_und_verfuegbarkeit(self):
        offers = svc.external_available_quarters(self.mon, self.wed)
        self.assertEqual(len(offers), 1)
        q, quote = offers[0]
        self.assertEqual(quote["nights"], 3)
        self.assertEqual(quote["total_gross"], Decimal("290.00"))  # 3*80 + 50

    def test_buchung_erstellt_rechnung_und_blockiert(self):
        from booking.models import OutboxEmail
        b, err = svc.create_external_booking(
            self.q, self.mon, self.wed, 2, name="Max Extern",
            email="max@example.org", street="Weg 1", zip_code="12345", city="Dorf")
        self.assertIsNotNone(b, err)
        self.assertEqual(b.status, ExternalBooking.CONFIRMED)
        self.assertEqual(b.invoice.total_gross, Decimal("290.00"))
        self.assertEqual(b.invoice.recipient_label, "Max Extern")
        self.assertIsNone(b.invoice.member_id)
        self.assertFalse(svc.quarter_is_free(self.q, self.mon, self.wed))
        # Bestätigungs-Mail an den Gast
        self.assertTrue(OutboxEmail.objects.filter(to_email="max@example.org").exists())

    def test_wochenende_und_inaktiv_abgelehnt(self):
        sat = self.mon + timedelta(days=5)
        b, err = svc.create_external_booking(self.q, sat, sat + timedelta(days=2),
                                             2, name="X", email="x@example.org")
        self.assertIsNone(b)
        self.cfg.active = False
        self.cfg.save()
        b2, err2 = svc.create_external_booking(self.q, self.mon, self.wed, 2,
                                               name="Y", email="y@example.org")
        self.assertIsNone(b2)

    def test_nicht_externes_quartier_abgelehnt(self):
        self.q.external_bookable = False
        self.q.save()
        b, err = svc.create_external_booking(self.q, self.mon, self.wed, 2,
                                             name="Z", email="z@example.org")
        self.assertIsNone(b)

    def test_doppelbuchung_verhindert(self):
        svc.create_external_booking(self.q, self.mon, self.wed, 2,
                                    name="A", email="a@example.org")
        b2, err = svc.create_external_booking(self.q, self.mon, self.wed, 2,
                                              name="B", email="b@example.org")
        self.assertIsNone(b2)
        self.assertIn("belegt", err)

    def test_kontoabgleich_zahlt_gastrechnung(self):
        from booking.models import OutboxEmail
        b, _ = svc.create_external_booking(self.q, self.mon, self.wed, 2,
                                           name="Max", email="max@example.org")
        OutboxEmail.objects.all().delete()
        inv = b.invoice
        csv = (f"Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;"
               f"Kontonummer/IBAN;Betrag\n"
               f"15.06.2026;Max;Zahlung {inv.number};DE9;290,00\n").encode()
        batch = reconcile.import_bank_statement(csv, "csv", "a.csv")
        self.assertEqual(batch.n_matched, 1)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.CONFIRMED)
        self.assertTrue(OutboxEmail.objects.filter(to_email="max@example.org").exists())


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ExternalPublicViewTests(TestCase):
    def setUp(self):
        ShopConfig.objects.create(iban="DE111")
        ExternalConfig.objects.create(active=True, allowed_weekdays="0,1,2,3",
                                      min_nights=2, lead_days=0)
        ec = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(name="Gartenhaus", eq_class=ec,
                                        min_occupancy=1, max_occupancy=4,
                                        external_bookable=True,
                                        price_per_night=Decimal("80.00"))
        self.mon = _next_monday()
        self.wed = self.mon + timedelta(days=3)

    def test_oeffentliche_seite_ohne_login(self):
        # Kein Login nötig (anonym)
        r = self.client.get(reverse("external_home"))
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get(reverse("external_home"),
                             {"start": self.mon.isoformat(),
                              "end": self.wed.isoformat(), "persons": 2})
        self.assertContains(r2, "Gartenhaus")
        # Auswahl verlinkt auf die Bestätigungsseite (nicht sofort buchen)
        self.assertContains(r2, reverse("external_book"))

    def test_embed_widget_einbettbar_zeigt_angebote(self):
        # Ohne Zeitraum: Kalender + Hinweis zur Buchungsseite
        r = self.client.get(reverse("external_embed"))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("X-Frame-Options", r)  # per iframe einbettbar
        self.assertContains(r, reverse("external_home"))
        # Mit Zeitraum: freie Unterkünfte direkt im Widget + Buchen-Link
        r2 = self.client.get(reverse("external_embed"),
                             {"start": self.mon.isoformat(),
                              "end": self.wed.isoformat(), "persons": 2})
        self.assertContains(r2, "Gartenhaus")
        self.assertContains(r2, reverse("external_book"))

    def test_bestaetigungsseite_und_buchen(self):
        # Schritt 1: Review-Seite (GET) zeigt Quartier + Daten-Formular
        r = self.client.get(reverse("external_book"), {
            "quarter": self.q.id, "start": self.mon.isoformat(),
            "end": self.wed.isoformat(), "persons": 2})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gartenhaus")
        self.assertContains(r, "Verbindlich buchen")
        self.assertEqual(ExternalBooking.objects.count(), 0)  # noch nichts gebucht
        # Schritt 2: verbindlich buchen
        r2 = self.client.post(reverse("external_book"), {
            "action": "book", "quarter": self.q.id,
            "start": self.mon.isoformat(), "end": self.wed.isoformat(),
            "persons": 2, "name": "Gast Extern", "email": "gast@example.org"})
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "Danke")
        self.assertTrue(Guest.objects.filter(email="gast@example.org").exists())
        self.assertEqual(ExternalBooking.objects.count(), 1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SeasonPriceTests(TestCase):
    def setUp(self):
        ShopConfig.objects.create(iban="DE111")
        self.cfg = ExternalConfig.objects.create(
            active=True, allowed_weekdays="", min_nights=1, lead_days=0,
            cleaning_fee=Decimal("0.00"))
        ec = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(
            name="Gartenhaus", eq_class=ec, min_occupancy=1, max_occupancy=4,
            external_bookable=True, price_per_night=Decimal("80.00"))
        # Hochsaison im Juli: 120 €/Nacht
        QuarterPrice.objects.create(quarter=self.q, label="Hochsaison",
                                    start_month=7, start_day=1, end_month=8, end_day=31,
                                    price_per_night=Decimal("120.00"))

    def test_saisonpreis_greift_pro_nacht(self):
        # 3 Nächte im Juli -> 3*120
        start, end = date(2026, 7, 6), date(2026, 7, 9)
        quote = svc.external_quote(self.q, start, end, self.cfg)
        self.assertEqual(quote["total_gross"], Decimal("360.00"))
        self.assertFalse(quote["seasonal_price"])

    def test_basispreis_ausserhalb_saison(self):
        start, end = date(2026, 6, 8), date(2026, 6, 11)  # Juni -> Basis 80
        quote = svc.external_quote(self.q, start, end, self.cfg)
        self.assertEqual(quote["total_gross"], Decimal("240.00"))

    def test_anzahlung_und_storno_in_quote(self):
        self.cfg.deposit_percent = 20
        self.cfg.save()
        quote = svc.external_quote(self.q, date(2026, 6, 8), date(2026, 6, 11), self.cfg)
        self.assertEqual(quote["deposit_gross"], Decimal("48.00"))  # 20% von 240
        self.assertTrue(quote["cancellation_text"])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MagicLinkAndCalendarTests(TestCase):
    def setUp(self):
        ShopConfig.objects.create(iban="DE111")
        self.cfg = ExternalConfig.objects.create(
            active=True, allowed_weekdays="0,1,2,3", min_nights=2, lead_days=0,
            free_cancel_days=30, partial_cancel_days=7, partial_refund_percent=50)
        ec = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(
            name="Gartenhaus", eq_class=ec, min_occupancy=1, max_occupancy=4,
            external_bookable=True, price_per_night=Decimal("80.00"))
        self.mon = _next_monday()
        self.wed = self.mon + timedelta(days=3)

    def test_externe_im_gemeinschaftskalender(self):
        svc.create_external_booking(self.q, self.mon, self.wed, 2,
                                    name="Max", email="max@example.org")
        cal = svc.build_community_calendar(None, self.mon.year, self.mon.month)
        self.assertTrue(cal["any_external"])
        whos = [b["who"] for week in cal["weeks"] for d in week for b in d["bookings"]]
        self.assertIn("extern", whos)

    def test_magic_link_und_storno(self):
        b, _ = svc.create_external_booking(self.q, self.mon, self.wed, 2,
                                           name="Max", email="max@example.org")
        url = reverse("external_manage", args=[b.guest.token])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gartenhaus")
        # Storno per Magic-Link
        r2 = self.client.post(url, {"action": "cancel", "booking": b.id})
        self.assertEqual(r2.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.status, ExternalBooking.CANCELLED)
        # Slot wieder frei
        self.assertTrue(svc.quarter_is_free(self.q, self.mon, self.wed))

    def test_unbekannter_token_404(self):
        import uuid
        r = self.client.get(reverse("external_manage", args=[uuid.uuid4()]))
        self.assertEqual(r.status_code, 404)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ExternalSeasonMinNightsTests(TestCase):
    """Konfigurierte Saison-Mindestnächte (SeasonRule) gelten auch für externe
    Gäste – zusätzlich zu deren eigenem Mindestaufenthalt; das strengere zählt."""

    def setUp(self):
        ShopConfig.objects.create(iban="DE111", invoice_prefix="HL")
        self.cfg = ExternalConfig.objects.create(
            active=True, allowed_weekdays="", min_nights=2, lead_days=0,
            cleaning_fee=Decimal("0.00"))
        ec = EquivalenceClass.objects.create(name="K")
        self.q = Quarter.objects.create(
            name="Gartenhaus", eq_class=ec, min_occupancy=1, max_occupancy=4,
            external_bookable=True, price_per_night=Decimal("80.00"))
        # Buchung sicher in der Zukunft; Saison-Fenster aus dem Datum ableiten,
        # damit der Test unabhängig vom Lauf-Datum stabil ist.
        self.start = date.today() + timedelta(days=10)
        lo = self.start - timedelta(days=2)
        hi = self.start + timedelta(days=12)
        SeasonRule.objects.create(
            name="Mindestnächte-Test", start_month=lo.month, start_day=lo.day,
            end_month=hi.month, end_day=hi.day, min_nights=7, active=True)

    def test_zu_kurz_wird_abgelehnt(self):
        b, err = svc.create_external_booking(
            self.q, self.start, self.start + timedelta(days=3), 2,
            name="Max", email="max@example.org")
        self.assertIsNone(b)
        self.assertIn("7 Nächte", err or "")

    def test_keine_angebote_unter_saison_mindestnaechte(self):
        offers = svc.external_available_quarters(
            self.start, self.start + timedelta(days=3))
        self.assertEqual(offers, [])

    def test_ausreichend_lang_ok(self):
        b, err = svc.create_external_booking(
            self.q, self.start, self.start + timedelta(days=7), 2,
            name="Max", email="max@example.org")
        self.assertIsNotNone(b, err)

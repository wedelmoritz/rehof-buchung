"""Tests des Hofladens: Preis-Snapshot, Rechnungserzeugung, Zugriffsrechte."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from unittest import skipUnless

from django.test import TestCase
from django.urls import reverse

from booking.models import Member
from shop.models import Invoice, LineItem, Product, ProductGroup, ShopConfig
from shop import services as svc


def make_member(name):
    u = User.objects.create_user(username=name, password="x" * 12)
    return Member.objects.create(user=u, display_name=name)


class ShopBase(TestCase):
    def setUp(self):
        self.group = ProductGroup.objects.create(name="Obst", emoji="🍎")
        self.apple = Product.objects.create(
            group=self.group, name="Äpfel", price=Decimal("3.20"),
            unit="kg", vat_rate=7)
        self.juice = Product.objects.create(
            group=self.group, name="Saft", price=Decimal("2.00"),
            unit="liter", vat_rate=19)
        self.sauna = Product.objects.create(
            group=self.group, name="Sauna", price=Decimal("8.00"),
            unit="portion", vat_rate=19, kind="dienstleistung", needs_date=True)
        self.alice = make_member("alice")
        self.bob = make_member("bob")


class PriceSnapshotTests(ShopBase):
    def test_preis_snapshot_bleibt_bei_aenderung(self):
        item, err = svc.add_item(self.alice, self.apple, "2.5")
        self.assertIsNotNone(item, err)
        self.assertEqual(item.unit_price, Decimal("3.20"))
        self.assertEqual(item.gross, Decimal("8.00"))
        # Produktpreis ändern – Snapshot bleibt
        self.apple.price = Decimal("9.99")
        self.apple.save()
        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("3.20"))

    def test_menge_muss_positiv_sein(self):
        item, err = svc.add_item(self.alice, self.apple, "0")
        self.assertIsNone(item)
        self.assertIn("größer als 0", err)


class MengenRasterTests(ShopBase):
    def test_kg_in_zehntel_schritten_erlaubt(self):
        item, err = svc.add_item(self.alice, self.apple, "0.1")
        self.assertIsNotNone(item, err)
        item, err = svc.add_item(self.alice, self.apple, "1.3")
        self.assertIsNotNone(item, err)

    def test_kg_kleiner_als_zehntel_abgelehnt(self):
        item, err = svc.add_item(self.alice, self.apple, "0.15")
        self.assertIsNone(item)
        self.assertIn("0,1-Schritten", err)

    def test_liter_nur_ganzzahlig(self):
        item, err = svc.add_item(self.alice, self.juice, "2")
        self.assertIsNotNone(item, err)
        item, err = svc.add_item(self.alice, self.juice, "1.5")
        self.assertIsNone(item)
        self.assertIn("ganzen Schritten", err)

    def test_stueck_nur_ganzzahlig(self):
        piece = Product.objects.create(
            group=self.group, name="Ei", price=Decimal("0.40"),
            unit="stueck", vat_rate=7)
        item, err = svc.add_item(self.alice, piece, "1.5")
        self.assertIsNone(item)
        self.assertIn("ganzen Schritten", err)


class WochentagSperreTests(ShopBase):
    def test_dienstleistung_an_gesperrtem_wochentag_abgelehnt(self):
        clean = Product.objects.create(
            group=self.group, name="Endreinigung", price=Decimal("45.00"),
            unit="portion", vat_rate=19, kind="dienstleistung",
            needs_date=True, unavailable_weekdays="6")  # Sonntag gesperrt
        sunday = date(2024, 1, 7)   # weekday() == 6
        monday = date(2024, 1, 8)   # weekday() == 0
        item, err = svc.add_item(self.alice, clean, "1", service_date=sunday)
        self.assertIsNone(item)
        self.assertIn("Sonntag", err)
        item2, err2 = svc.add_item(self.alice, clean, "1", service_date=monday)
        self.assertIsNotNone(item2, err2)

    def test_dienstleistung_braucht_datum(self):
        item, err = svc.add_item(self.alice, self.sauna, "1")
        self.assertIsNone(item)
        self.assertIn("Datum", err)
        item, err = svc.add_item(self.alice, self.sauna, "1",
                                 service_date=date(2026, 7, 1))
        self.assertIsNotNone(item, err)
        self.assertEqual(item.service_date, date(2026, 7, 1))


class CheckoutUndEinkaufTests(ShopBase):
    def test_gleiche_artikel_werden_zusammengefasst(self):
        svc.add_item(self.alice, self.apple, "2")
        svc.add_item(self.alice, self.apple, "1.5")
        items = list(svc.open_items(self.alice))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].quantity, Decimal("3.5"))

    def test_menge_aendern_und_entfernen(self):
        svc.add_item(self.alice, self.apple, "2")
        it = svc.open_items(self.alice).first()
        ok, err = svc.set_cart_quantity(self.alice, it.id, "0.5")
        self.assertTrue(ok, err)
        it.refresh_from_db()
        self.assertEqual(it.quantity, Decimal("0.5"))
        ok, _ = svc.set_cart_quantity(self.alice, it.id, "0")  # 0 entfernt
        self.assertTrue(ok)
        self.assertEqual(svc.open_items(self.alice).count(), 0)

    def test_checkout_bestaetigt_und_sperrt_warenkorb(self):
        svc.add_item(self.alice, self.apple, "2")
        p, err = svc.checkout(self.alice)
        self.assertIsNotNone(p, err)
        self.assertEqual(svc.open_items(self.alice).count(), 0)
        self.assertEqual(p.items.count(), 1)
        p2, _ = svc.checkout(self.alice)  # leerer Korb
        self.assertIsNone(p2)

    def test_warenkorb_ohne_checkout_wird_nicht_abgerechnet(self):
        svc.add_item(self.alice, self.apple, "2")
        invs = svc.generate_monthly_invoices(date.today().year, date.today().month)
        self.assertEqual(invs, [])

    def test_sofort_rechnung(self):
        svc.add_item(self.alice, self.apple, "2")
        svc.checkout(self.alice)
        inv, err = svc.generate_invoice_now(self.alice)
        self.assertIsNotNone(inv, err)
        self.assertEqual(inv.total_gross, Decimal("6.40"))
        inv2, _ = svc.generate_invoice_now(self.alice)  # nichts mehr offen
        self.assertIsNone(inv2)


class InvoiceTests(ShopBase):
    def test_monatsrechnung_fasst_zusammen(self):
        svc.add_item(self.alice, self.apple, "2")    # 6.40 (7%)
        svc.add_item(self.alice, self.juice, "1")    # 2.00 (19%)
        svc.add_item(self.bob, self.apple, "1")      # 3.20
        svc.checkout(self.alice)                     # Warenkorb bestätigen
        svc.checkout(self.bob)
        invoices = svc.generate_monthly_invoices(date.today().year, date.today().month)
        self.assertEqual(len(invoices), 2)
        inv_a = Invoice.objects.get(member=self.alice)
        self.assertEqual(inv_a.total_gross, Decimal("8.40"))
        # Steuer-Aufschlüsselung je Satz
        rates = {b["rate"]: b for b in inv_a.vat_breakdown()}
        self.assertIn(7, rates)
        self.assertIn(19, rates)
        # Positionen sind der Rechnung zugeordnet (nicht mehr „offen“)
        self.assertEqual(svc.open_items(self.alice).count(), 0)
        self.assertTrue(inv_a.number.startswith("HL-"))

    def test_rechnungsnummern_eindeutig_und_fortlaufend(self):
        # Zwei Rechnungen im selben Monat bekommen unterschiedliche, fortlaufende
        # Nummern (die Nummernvergabe ist gegen gleichzeitigen Checkout gesperrt).
        svc.add_item(self.alice, self.apple, "1"); svc.checkout(self.alice)
        svc.add_item(self.bob, self.apple, "1"); svc.checkout(self.bob)
        inv_a, _ = svc.generate_invoice_now(self.alice)
        inv_b, _ = svc.generate_invoice_now(self.bob)
        self.assertNotEqual(inv_a.number, inv_b.number)
        self.assertEqual(Invoice.objects.values("number").distinct().count(),
                         Invoice.objects.count())

    def test_run_monthly_invoices_command_idempotent(self):
        from django.core.management import call_command
        svc.add_item(self.alice, self.apple, "2")
        svc.checkout(self.alice)
        today = date.today()
        call_command("run_monthly_invoices", year=today.year, month=today.month)
        self.assertEqual(Invoice.objects.filter(member=self.alice).count(), 1)
        # Zweiter Lauf erzeugt keine Doppel-Rechnung
        call_command("run_monthly_invoices", year=today.year, month=today.month)
        self.assertEqual(Invoice.objects.filter(member=self.alice).count(), 1)

    def test_status_offen_bezahlt_bestaetigt(self):
        svc.add_item(self.alice, self.apple, "2")
        svc.checkout(self.alice)
        inv = svc.generate_monthly_invoices(date.today().year, date.today().month)[0]
        self.assertEqual(inv.status, Invoice.OPEN)
        ok, err = svc.mark_paid(self.alice, inv.id)
        self.assertTrue(ok, err)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.PAID)
        svc.confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertTrue(inv.archived)


class AccessTests(ShopBase):
    def test_nur_eigene_rechnung_sichtbar(self):
        svc.add_item(self.alice, self.apple, "2")
        svc.checkout(self.alice)
        inv = svc.generate_monthly_invoices(date.today().year, date.today().month)[0]
        self.client.force_login(self.bob.user)
        self.assertEqual(self.client.get(f"/hofladen/rechnung/{inv.id}/").status_code, 404)
        self.client.force_login(self.alice.user)
        self.assertEqual(self.client.get(f"/hofladen/rechnung/{inv.id}/").status_code, 200)

    def test_fremde_rechnung_nicht_als_bezahlt_meldbar(self):
        svc.add_item(self.alice, self.apple, "2")
        svc.checkout(self.alice)
        inv = svc.generate_monthly_invoices(date.today().year, date.today().month)[0]
        ok, err = svc.mark_paid(self.bob, inv.id)
        self.assertFalse(ok)


class InvoicePdfTests(ShopBase):
    """Rechnungs-PDF: HTML-Erzeugung, Endpoint-Zugriff, E-Mail-Anhang."""

    def setUp(self):
        super().setUp()
        ShopConfig.objects.create(payment_term_days=14)
        self.alice.user.email = "alice@example.org"
        self.alice.user.save(update_fields=["email"])
        svc.add_item(self.alice, self.apple, "2")
        svc.checkout(self.alice)
        from booking.models import OutboxEmail
        OutboxEmail.objects.all().delete()
        self.inv, _ = svc.generate_invoice_now(self.alice)

    def test_invoice_html_enthaelt_kernfelder(self):
        from shop import pdf
        html = pdf.invoice_html(self.inv)
        self.assertIn(self.inv.number, html)
        self.assertIn(self.alice.display_name, html)  # recipient_name default
        self.assertIn("Gesamtbetrag", html)

    def test_pdf_endpoint_zugriff(self):
        from shop import pdf
        self.client.force_login(self.alice.user)
        r = self.client.get(reverse("shop_invoice_pdf", args=[self.inv.id]))
        if pdf.weasyprint_available():
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r.content.startswith(b"%PDF"))
        else:
            self.assertEqual(r.status_code, 503)
        # fremde Rechnung ist für Nicht-Staff nicht erreichbar
        self.client.force_login(self.bob.user)
        self.assertEqual(
            self.client.get(reverse("shop_invoice_pdf", args=[self.inv.id])).status_code,
            404)

    @skipUnless(__import__("shop.pdf", fromlist=["x"]).weasyprint_available(),
                "WeasyPrint/native Libs nicht verfügbar")
    def test_pdf_bytes_und_email_anhang(self):
        from shop import pdf
        from booking.models import OutboxEmail
        self.assertTrue(pdf.invoice_pdf_bytes(self.inv).startswith(b"%PDF"))
        em = OutboxEmail.objects.get(to_email="alice@example.org")
        self.assertEqual(em.attachment_name, f"{self.inv.number}.pdf")
        self.assertEqual(em.attachment_mime, "application/pdf")
        self.assertTrue(bytes(em.attachment).startswith(b"%PDF"))


class KontoabgleichTests(ShopBase):
    """Kontoauszug-Import: Parsen (CSV/CAMT), automatischer Abgleich, Dedup."""

    def setUp(self):
        super().setUp()
        ShopConfig.objects.create(payment_term_days=14)
        self.alice.user.email = "alice@example.org"
        self.alice.user.save(update_fields=["email"])
        svc.add_item(self.alice, self.apple, "2")   # 2 × 3,20 = 6,40 brutto
        svc.checkout(self.alice)
        from booking.models import OutboxEmail
        OutboxEmail.objects.all().delete()
        self.inv, _ = svc.generate_invoice_now(self.alice)
        self.assertEqual(self.inv.total_gross, Decimal("6.40"))

    def _csv(self, number, betrag="6,40"):
        return (
            "Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;"
            "Kontonummer/IBAN;Betrag\n"
            f"15.04.2026;Anna Beispiel;Zahlung Rechnung {number};DE12;{betrag}\n"
        ).encode("utf-8")

    def test_csv_parsen_nur_eingaenge(self):
        from shop import bankimport
        data = (self._csv(self.inv.number).decode()
                + "16.04.2026;Laden;Einkauf;DE9;-20,00\n").encode("utf-8")
        txns = bankimport.parse_csv(data)
        self.assertEqual(len(txns), 1)               # Belastung ignoriert
        self.assertEqual(txns[0].amount, Decimal("6.40"))

    def test_import_verbucht_und_benachrichtigt(self):
        from shop import reconcile
        from booking.models import Notification, OutboxEmail
        batch = reconcile.import_bank_statement(
            self._csv(self.inv.number), "csv", "auszug.csv")
        self.assertEqual(batch.n_imported, 1)
        self.assertEqual(batch.n_matched, 1)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.CONFIRMED)
        self.assertTrue(Notification.objects.filter(
            member=self.alice, message__contains=self.inv.number).exists())
        self.assertTrue(OutboxEmail.objects.filter(
            to_email="alice@example.org").exists())

    def test_falscher_betrag_bleibt_offen(self):
        from shop import reconcile
        batch = reconcile.import_bank_statement(
            self._csv(self.inv.number, betrag="5,00"), "csv", "a.csv")
        self.assertEqual(batch.n_matched, 0)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.OPEN)

    def test_doppelimport_wird_dedupliziert(self):
        from shop import reconcile
        data = self._csv(self.inv.number)
        reconcile.import_bank_statement(data, "csv", "a.csv")
        batch2 = reconcile.import_bank_statement(data, "csv", "a.csv")
        self.assertEqual(batch2.n_imported, 0)       # nichts Neues

    def test_camt_parsen_und_abgleich(self):
        from shop import reconcile
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">'
            '<BkToCstmrStmt><Stmt><Ntry>'
            '<Amt Ccy="EUR">6.40</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
            '<BookgDt><Dt>2026-04-15</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            '<RltdPties><Dbtr><Nm>Anna</Nm></Dbtr>'
            '<DbtrAcct><Id><IBAN>DE12</IBAN></Id></DbtrAcct></RltdPties>'
            f'<RmtInf><Ustrd>Rechnung {self.inv.number}</Ustrd></RmtInf>'
            '</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode("utf-8")
        batch = reconcile.import_bank_statement(xml, "camt", "auszug.xml")
        self.assertEqual(batch.n_matched, 1)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.CONFIRMED)


class KleinunternehmerInvoiceTests(ShopBase):
    """§19-Modus: Rechnung ohne MwSt-Ausweis, mit §19-Hinweis (ADR 0041)."""

    def test_paragraph19_rechnung_ohne_mwst(self):
        from shop.models import ShopConfig
        from shop.pdf import invoice_html
        cfg = ShopConfig.get_solo()
        cfg.small_business = True
        cfg.small_business_note = "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet."
        cfg.save()
        svc.add_item(self.alice, self.apple, "2")
        svc.checkout(self.alice)
        inv, _ = svc.generate_invoice_now(self.alice)
        self.assertTrue(inv.small_business)
        self.assertIn("§ 19", inv.tax_note)
        html = invoice_html(inv)
        self.assertIn("§ 19", html)
        self.assertNotIn("zzgl. MwSt", html)   # kein Steuerausweis

    def test_regelbesteuerung_weiterhin_mit_mwst(self):
        from shop.models import ShopConfig
        from shop.pdf import invoice_html
        cfg = ShopConfig.get_solo()
        cfg.small_business = False
        cfg.save()
        svc.add_item(self.bob, self.apple, "1")
        svc.checkout(self.bob)
        inv, _ = svc.generate_invoice_now(self.bob)
        self.assertFalse(inv.small_business)
        self.assertIn("zzgl. MwSt", invoice_html(inv))


class ConfigAdminTests(TestCase):
    """Singleton-Einstellungen: der Admin springt direkt aufs Objekt (keine
    Zwischen-Liste „… zur Änderung auswählen“)."""

    def test_changelist_redirects_to_object(self):
        from django.contrib.auth.models import User
        admin = User.objects.create_superuser("admin9", "admin9@example.org", "x" * 12)
        self.client.force_login(admin)
        r = self.client.get("/admin/shop/shopconfig/")
        self.assertEqual(r.status_code, 302)
        self.assertRegex(r["Location"], r"/admin/shop/shopconfig/\d+/change/")

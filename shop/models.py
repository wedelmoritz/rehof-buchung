"""Datenmodelle des Hofladens: Produktkatalog, Einkaufspositionen (mit
Preis-Snapshot) und monatliche Sammelrechnungen.

Geldlogik: Preise sind BRUTTO. Netto/Steuer werden je Position aus dem
gespeicherten MwSt-Satz gerechnet (Snapshot zum Kaufzeitpunkt). Alles über das
Django-ORM; keine rohen SQL-Abfragen.
"""
from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.db import models

from booking.models import Member

CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class ShopConfig(models.Model):
    """Stammdaten der Genossenschaft für die Rechnung (Singleton)."""
    coop_name = models.CharField("Genossenschaft", max_length=160,
                                 default="Re:Hof eG")
    coop_address = models.TextField("Anschrift", blank=True)
    contact_email = models.EmailField(
        "Kontakt-E-Mail", blank=True,
        help_text="Erscheint auf Rechnungen und im Hilfebereich für externe Gäste.")
    board = models.CharField(
        "Vorstand", max_length=200, blank=True,
        help_text="z. B. Namen des Vorstands (für Rechnung/Impressum).")
    tax_number = models.CharField("Steuernummer/USt-IdNr.", max_length=40, blank=True)
    iban = models.CharField("IBAN (Zahlungsempfang)", max_length=34, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)
    invoice_prefix = models.CharField("Rechnungs-Präfix", max_length=8, default="HL")
    payment_term_days = models.PositiveSmallIntegerField(
        "Zahlungsziel (Tage)", default=14,
        help_text="Nach so vielen Tagen ohne Zahlungseingang gilt eine Rechnung "
                  "als überfällig (für die Zahlungserinnerung).")
    # Online-Bezahlung (Mollie) – EIN System für Hofladen UND externe Gäste.
    payments_active = models.BooleanField(
        "Online-Bezahlung aktiv", default=True,
        help_text="Schaltet die Online-Bezahlung (Mollie) für Hofladen-Rechnungen "
                  "UND externe Gäste frei.")
    mollie_api_key = models.CharField(
        "Mollie API-Key", max_length=64, blank=True,
        help_text="LEER = eingebauter TEST-Modus (simuliert, ohne Konto/Gebühren). "
                  "Ein „test_…“-Key nutzt Mollies Testumgebung (ebenfalls kostenlos), "
                  "ein „live_…“-Key die echte Bezahlung.")

    class Meta:
        verbose_name = "Hofladen-Einstellungen"
        verbose_name_plural = "Hofladen-Einstellungen"

    def __str__(self) -> str:
        return "Hofladen-Einstellungen"

    @classmethod
    def get_solo(cls) -> "ShopConfig":
        obj = cls.objects.first()
        return obj or cls.objects.create()


class ProductGroup(models.Model):
    """Produktgruppe/Kategorie (z.B. Obst/Gemüse, Dienstleistungen)."""
    name = models.CharField("Name", max_length=80, unique=True)
    emoji = models.CharField("Symbol (Emoji)", max_length=8, blank=True)
    sort_order = models.PositiveIntegerField("Sortierung", default=100)
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Produktgruppe"
        verbose_name_plural = "Produktgruppen"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    """Ein Artikel oder eine Dienstleistung im Hofladen."""
    WARE, DIENSTLEISTUNG = "ware", "dienstleistung"
    KIND = [(WARE, "Ware"), (DIENSTLEISTUNG, "Dienstleistung")]
    UNITS = [
        ("stueck", "Stück"), ("kg", "kg"), ("liter", "Liter"),
        ("bund", "Bund"), ("glas", "Glas"), ("portion", "Portion"),
    ]
    VAT_CHOICES = [(0, "0 %"), (7, "7 %"), (19, "19 %")]

    group = models.ForeignKey(
        ProductGroup, on_delete=models.PROTECT, related_name="products",
        verbose_name="Gruppe")
    name = models.CharField("Name", max_length=160)
    description = models.CharField("Kurzbeschreibung", max_length=200, blank=True)
    price = models.DecimalField("Preis (brutto)", max_digits=8, decimal_places=2)
    unit = models.CharField("Einheit", max_length=10, choices=UNITS, default="stueck")
    vat_rate = models.PositiveSmallIntegerField("MwSt", choices=VAT_CHOICES, default=7)
    kind = models.CharField("Art", max_length=14, choices=KIND, default=WARE)
    needs_date = models.BooleanField(
        "Termin nötig", default=False,
        help_text="z.B. Sauna: Mitglied gibt beim Kauf ein Datum an.")
    book_with_stay = models.BooleanField(
        "Beim Buchen einer Unterkunft anbieten", default=False,
        help_text="z.B. Endreinigung: erscheint im Bestätigungsschritt der Buchung "
                  "und kann gleich mitgebucht werden.")
    counts_as_cleaning = models.BooleanField(
        "Zählt als Endreinigung", default=False,
        help_text="Wenn aktiv, gilt diese Dienstleistung als Endreinigung und "
                  "erscheint in der Reinigungsliste fürs Team (Markierung an der "
                  "betroffenen Buchung).")
    unavailable_weekdays = models.CharField(
        "Nicht möglich an Wochentagen", max_length=20, blank=True, default="",
        help_text="Komma-getrennt 0=Mo … 6=So. An diesen Wochentagen (Abreisetag) "
                  "ist die Dienstleistung nicht buchbar – z.B. Endreinigung am "
                  "Wochenende.")
    sort_order = models.PositiveIntegerField("Sortierung", default=100)
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Produkt / Dienstleistung"
        verbose_name_plural = "Produkte & Dienstleistungen"
        ordering = ["group__sort_order", "sort_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.price} € / {self.get_unit_display()})"

    @property
    def unavailable_weekday_set(self) -> set[int]:
        return {int(x) for x in self.unavailable_weekdays.split(",")
                if x.strip().isdigit()}

    def available_on(self, day) -> bool:
        """Ist die Dienstleistung am `day` (Wochentag) gewährleistbar?"""
        return day.weekday() not in self.unavailable_weekday_set

    # Einheiten, die in Zehntel-Schritten zählbar sind (z.B. 0,1 kg). Alle
    # anderen (Stück, Liter, Bund, Glas, Portion) werden nur in ganzen Schritten
    # gezählt.
    FRACTIONAL_UNITS = {"kg"}

    @property
    def quantity_step(self) -> Decimal:
        """Kleinste erlaubte Mengen-Schrittweite für dieses Produkt."""
        return Decimal("0.1") if self.unit in self.FRACTIONAL_UNITS else Decimal("1")


class Purchase(models.Model):
    """Ein **bestätigter Einkauf** (Checkout). Fasst die beim Bestätigen im
    Warenkorb liegenden Positionen zu einem Vorgang mit Datum zusammen. Nach der
    Bestätigung ist er in der Verwaltung sichtbar und nicht mehr änderbar."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="purchases",
        verbose_name="Mitglied")
    confirmed_at = models.DateTimeField("Eingekauft am", auto_now_add=True)

    class Meta:
        verbose_name = "Einkauf"
        verbose_name_plural = "Einkäufe (bestätigt)"
        ordering = ["-confirmed_at"]

    def __str__(self) -> str:
        return f"Einkauf {self.member} – {self.confirmed_at:%d.%m.%Y %H:%M}"

    @property
    def gross(self) -> Decimal:
        return _q(sum((i.gross for i in self.items.all()), Decimal(0)))


class LineItem(models.Model):
    """Eine Einkaufsposition eines Mitglieds. Preis/MwSt/Name werden als
    Snapshot zum Kaufzeitpunkt gespeichert (Produktänderungen wirken nicht
    rückwirkend). Lebenszyklus über die Verknüpfungen:
      * `purchase` leer + `invoice` leer  → im **Warenkorb** (änderbar),
      * `purchase` gesetzt + `invoice` leer → **bestätigter Einkauf** (gesperrt),
      * `invoice` gesetzt                  → **abgerechnet**."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="shop_items",
        verbose_name="Mitglied", null=True, blank=True)
    guest = models.ForeignKey(
        "booking.Guest", on_delete=models.CASCADE, related_name="shop_items",
        verbose_name="Externer Gast", null=True, blank=True)
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="line_items", verbose_name="Produkt")
    purchase = models.ForeignKey(
        "Purchase", on_delete=models.CASCADE, null=True, blank=True,
        related_name="items", verbose_name="Einkauf")
    allocation = models.ForeignKey(
        "booking.Allocation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="service_items", verbose_name="Zugehörige Buchung",
        help_text="Gesetzt, wenn die Dienstleistung beim Buchen mitgebucht wurde "
                  "(z.B. Endreinigung) – verknüpft sie mit Quartier und Abreisetag.")
    name = models.CharField("Bezeichnung", max_length=160)
    unit = models.CharField("Einheit", max_length=10)
    unit_price = models.DecimalField("Einzelpreis (brutto)", max_digits=8,
                                     decimal_places=2)
    vat_rate = models.PositiveSmallIntegerField("MwSt")
    quantity = models.DecimalField("Menge", max_digits=8, decimal_places=3)
    service_date = models.DateField("Termin", null=True, blank=True)
    created_at = models.DateTimeField("Erfasst", auto_now_add=True)
    invoice = models.ForeignKey(
        "Invoice", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="items", verbose_name="Rechnung")

    class Meta:
        verbose_name = "Einkaufsposition"
        verbose_name_plural = "Einkaufspositionen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.quantity}× {self.name} ({self.member})"

    @property
    def gross(self) -> Decimal:
        return _q(self.unit_price * self.quantity)

    @property
    def net(self) -> Decimal:
        return _q(self.gross / (Decimal(1) + Decimal(self.vat_rate) / 100))

    @property
    def vat(self) -> Decimal:
        return _q(self.gross - self.net)


class Invoice(models.Model):
    """Monatliche Sammelrechnung eines Mitglieds. Fasst die offenen Positionen
    eines Monats zusammen; trägt fortlaufende Nummer und Status."""
    OPEN, PAID, CONFIRMED = "open", "paid", "confirmed"
    STATUS = [
        (OPEN, "Offen"),
        (PAID, "Als bezahlt gemeldet"),
        (CONFIRMED, "Bestätigt (archiviert)"),
    ]
    member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="invoices",
        verbose_name="Mitglied", null=True, blank=True)
    guest = models.ForeignKey(
        "booking.Guest", on_delete=models.PROTECT, related_name="invoices",
        verbose_name="Externer Gast", null=True, blank=True)
    number = models.CharField("Rechnungsnummer", max_length=30, unique=True)
    year = models.PositiveIntegerField("Jahr")
    month = models.PositiveSmallIntegerField("Monat")
    status = models.CharField("Status", max_length=10, choices=STATUS, default=OPEN)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    due_date = models.DateField("Fällig am", null=True, blank=True)
    paid_reported_at = models.DateTimeField("Bezahlt gemeldet am", null=True, blank=True)
    confirmed_at = models.DateTimeField("Bestätigt am", null=True, blank=True)
    reminded_at = models.DateTimeField("Zuletzt erinnert am", null=True, blank=True)
    # Snapshots (Empfänger + Genossenschaft) für §14 UStG
    recipient_name = models.CharField("Empfänger", max_length=160, blank=True)
    recipient_address = models.TextField("Empfänger-Anschrift", blank=True)
    coop_name = models.CharField("Genossenschaft", max_length=160, blank=True)
    coop_address = models.TextField("Anschrift", blank=True)
    tax_number = models.CharField("Steuernummer", max_length=40, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)
    # Online-Bezahlung (Mollie): leer = per Überweisung beglichen.
    payment_method = models.CharField(
        "Bezahlt über", max_length=20, blank=True,
        help_text="Leer = Überweisung; sonst Online-Zahldienst (z. B. „mollie“).")
    paid_online_at = models.DateTimeField("Online bezahlt am", null=True, blank=True)

    class Meta:
        verbose_name = "Rechnung"
        verbose_name_plural = "Rechnungen"
        ordering = ["-year", "-month", "number"]

    def __str__(self) -> str:
        return f"{self.number} ({self.recipient_label})"

    @property
    def recipient_label(self) -> str:
        """Empfänger-Anzeige – Mitglied ODER externer Gast."""
        if self.member_id:
            return self.member.display_name
        if self.guest_id:
            return self.guest.name
        return self.recipient_name or "—"

    @property
    def archived(self) -> bool:
        return self.status == self.CONFIRMED

    @property
    def paid_online(self) -> bool:
        """Wurde über den Online-Zahldienst (Mollie) beglichen?"""
        return bool(self.payment_method)

    @property
    def is_payable(self) -> bool:
        """Online bezahlbar, solange nicht schon online beglichen/bestätigt."""
        return self.status in (self.OPEN, self.PAID) and not self.paid_online

    @property
    def is_overdue(self) -> bool:
        """Offen UND Zahlungsziel überschritten (für die Erinnerung)."""
        from datetime import date as _date
        return (self.status == self.OPEN and self.due_date is not None
                and self.due_date < _date.today())

    @property
    def total_gross(self) -> Decimal:
        return _q(sum((i.gross for i in self.items.all()), Decimal(0)))

    @property
    def total_net(self) -> Decimal:
        return _q(sum((i.net for i in self.items.all()), Decimal(0)))

    @property
    def total_vat(self) -> Decimal:
        return _q(sum((i.vat for i in self.items.all()), Decimal(0)))

    def vat_breakdown(self) -> list[dict]:
        """Netto/Steuer/Brutto je Steuersatz (für §14-konforme Ausweisung)."""
        rates: dict[int, dict] = {}
        for i in self.items.all():
            r = rates.setdefault(i.vat_rate, {
                "rate": i.vat_rate, "net": Decimal(0),
                "vat": Decimal(0), "gross": Decimal(0)})
            r["net"] += i.net
            r["vat"] += i.vat
            r["gross"] += i.gross
        for r in rates.values():
            r["net"], r["vat"], r["gross"] = _q(r["net"]), _q(r["vat"]), _q(r["gross"])
        return [rates[k] for k in sorted(rates)]

    def purchase_groups(self) -> list[dict]:
        """Positionen nach Einkauf gruppiert (Datum der Bestätigung + die
        eingekauften Waren/Dienstleistungen darunter)."""
        groups: dict = {}
        for it in self.items.select_related("purchase").all():
            key = it.purchase_id
            g = groups.setdefault(key, {"purchase": it.purchase, "items": [],
                                        "gross": Decimal(0)})
            g["items"].append(it)
            g["gross"] += it.gross
        for g in groups.values():
            g["gross"] = _q(g["gross"])
        return sorted(
            groups.values(),
            key=lambda g: g["purchase"].confirmed_at if g["purchase"] else self.created_at,
        )


class Payment(models.Model):
    """Eine Online-Bezahlung (Mollie) zu einer Rechnung – für Mitglieder UND
    externe Gäste, da beide eine `Invoice` haben. `token` ist die fälschungs-
    sichere Kennung für die (login-freien) Bezahl-/Rückkehr-URLs. Ohne Mollie-
    API-Key läuft alles im eingebauten TEST-Modus (`is_sandbox`)."""
    OPEN, PAID, FAILED, EXPIRED, CANCELED = (
        "open", "paid", "failed", "expired", "canceled")
    STATUS = [
        (OPEN, "Offen"),
        (PAID, "Bezahlt"),
        (FAILED, "Fehlgeschlagen"),
        (EXPIRED, "Abgelaufen"),
        (CANCELED, "Abgebrochen"),
    ]
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="payments",
        verbose_name="Rechnung")
    token = models.UUIDField("Token", default=uuid.uuid4, unique=True,
                             editable=False)
    provider = models.CharField("Anbieter", max_length=20, default="mollie")
    provider_id = models.CharField("Anbieter-Zahlungs-ID", max_length=64, blank=True)
    amount = models.DecimalField("Betrag", max_digits=9, decimal_places=2)
    currency = models.CharField("Währung", max_length=3, default="EUR")
    status = models.CharField("Status", max_length=10, choices=STATUS, default=OPEN)
    description = models.CharField("Verwendungszweck", max_length=140, blank=True)
    checkout_url = models.URLField("Bezahlseite", max_length=500, blank=True)
    is_sandbox = models.BooleanField("Test-Modus", default=False)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    paid_at = models.DateTimeField("Bezahlt am", null=True, blank=True)

    class Meta:
        verbose_name = "Online-Zahlung"
        verbose_name_plural = "Online-Zahlungen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.provider} {self.amount} {self.currency} – {self.get_status_display()}"


class BankImport(models.Model):
    """Ein Import eines Kontoauszugs (für den Abgleich offener Rechnungen).
    Hält nur Eckdaten fürs Protokoll – die Zeilen stehen in BankTransaction."""
    created_at = models.DateTimeField("Importiert am", auto_now_add=True)
    filename = models.CharField("Datei", max_length=200, blank=True)
    fmt = models.CharField("Format", max_length=16, default="csv")
    n_total = models.PositiveIntegerField("Zeilen gesamt", default=0)
    n_imported = models.PositiveIntegerField("Neu übernommen", default=0)
    n_matched = models.PositiveIntegerField("Automatisch zugeordnet", default=0)

    class Meta:
        verbose_name = "Kontoauszug-Import"
        verbose_name_plural = "Kontoauszug-Importe"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Import {self.filename or self.fmt} – {self.created_at:%d.%m.%Y %H:%M}"


class BankTransaction(models.Model):
    """Eine eingegangene Zahlung aus einem Kontoauszug. Wird – wenn eindeutig –
    automatisch einer Rechnung zugeordnet (Betrag + Rechnungsnummer im
    Verwendungszweck) und verbucht."""
    batch = models.ForeignKey(
        BankImport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transactions", verbose_name="Import")
    booked_on = models.DateField("Buchungstag", null=True, blank=True)
    amount = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    purpose = models.TextField("Verwendungszweck", blank=True)
    counterparty_name = models.CharField("Zahlungsbeteiligte:r", max_length=200, blank=True)
    counterparty_iban = models.CharField("IBAN", max_length=40, blank=True)
    # Fingerabdruck (Datum+Betrag+Zweck+Konto) gegen Doppel-Import desselben Auszugs.
    fingerprint = models.CharField("Fingerabdruck", max_length=64, unique=True)
    raw = models.TextField("Rohzeile", blank=True)
    imported_at = models.DateTimeField("Übernommen am", auto_now_add=True)
    matched_invoice = models.ForeignKey(
        "Invoice", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bank_transactions", verbose_name="Zugeordnete Rechnung")
    matched_at = models.DateTimeField("Zugeordnet am", null=True, blank=True)
    note = models.CharField("Hinweis", max_length=200, blank=True)

    class Meta:
        verbose_name = "Zahlungseingang"
        verbose_name_plural = "Zahlungseingänge (Kontoauszug)"
        ordering = ["-booked_on", "-imported_at"]
        indexes = [models.Index(fields=["matched_invoice"])]

    def __str__(self) -> str:
        return f"{self.booked_on} {self.amount} € {self.counterparty_name}".strip()

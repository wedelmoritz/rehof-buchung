"""Datenmodelle des Hofladens: Produktkatalog, Einkaufspositionen (mit
Preis-Snapshot) und monatliche Sammelrechnungen.

Geldlogik: Preise sind BRUTTO. Netto/Steuer werden je Position aus dem
gespeicherten MwSt-Satz gerechnet (Snapshot zum Kaufzeitpunkt). Alles über das
Django-ORM; keine rohen SQL-Abfragen.
"""
from __future__ import annotations

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
    tax_number = models.CharField("Steuernummer/USt-IdNr.", max_length=40, blank=True)
    iban = models.CharField("IBAN (Zahlungsempfang)", max_length=34, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)
    invoice_prefix = models.CharField("Rechnungs-Präfix", max_length=8, default="HL")

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
    sort_order = models.PositiveIntegerField("Sortierung", default=100)
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Produkt / Dienstleistung"
        verbose_name_plural = "Produkte & Dienstleistungen"
        ordering = ["group__sort_order", "sort_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.price} € / {self.get_unit_display()})"


class LineItem(models.Model):
    """Eine Einkaufsposition eines Mitglieds. Preis/MwSt/Name werden als
    Snapshot zum Kaufzeitpunkt gespeichert (Produktänderungen wirken nicht
    rückwirkend). Solange `invoice` leer ist, ist die Position „offen“."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="shop_items",
        verbose_name="Mitglied")
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="line_items", verbose_name="Produkt")
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
        verbose_name="Mitglied")
    number = models.CharField("Rechnungsnummer", max_length=30, unique=True)
    year = models.PositiveIntegerField("Jahr")
    month = models.PositiveSmallIntegerField("Monat")
    status = models.CharField("Status", max_length=10, choices=STATUS, default=OPEN)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    paid_reported_at = models.DateTimeField("Bezahlt gemeldet am", null=True, blank=True)
    confirmed_at = models.DateTimeField("Bestätigt am", null=True, blank=True)
    # Snapshots (Empfänger + Genossenschaft) für §14 UStG
    recipient_name = models.CharField("Empfänger", max_length=160, blank=True)
    recipient_address = models.TextField("Empfänger-Anschrift", blank=True)
    coop_name = models.CharField("Genossenschaft", max_length=160, blank=True)
    coop_address = models.TextField("Anschrift", blank=True)
    tax_number = models.CharField("Steuernummer", max_length=40, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)

    class Meta:
        verbose_name = "Rechnung"
        verbose_name_plural = "Rechnungen"
        ordering = ["-year", "-month", "number"]

    def __str__(self) -> str:
        return f"{self.number} ({self.member})"

    @property
    def archived(self) -> bool:
        return self.status == self.CONFIRMED

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

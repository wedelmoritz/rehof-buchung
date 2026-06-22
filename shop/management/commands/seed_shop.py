"""Demo-Stammdaten für den Hofladen: Einstellungen, Gruppen und Produkte
(inkl. einer terminierten Dienstleistung „Sauna“). Idempotent."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from shop.models import Product, ProductGroup, ShopConfig

GROUPS = [
    # name, emoji, sort
    ("Obst & Gemüse", "🥕", 10),
    ("Kühlprodukte", "🧀", 20),
    ("Getränke", "🧃", 30),
    ("Vorrat & Trockenwaren", "🍝", 40),
    ("Snacks", "🍪", 50),
    ("Dienstleistungen", "🧖", 90),
]

PRODUCTS = [
    # group, name, price, unit, vat, kind, needs_date
    ("Obst & Gemüse", "Äpfel", "3.20", "kg", 7, "ware", False),
    ("Obst & Gemüse", "Möhren (Bund)", "1.50", "bund", 7, "ware", False),
    ("Kühlprodukte", "Bergkäse", "4.80", "stueck", 7, "ware", False),
    ("Kühlprodukte", "Joghurt 500g", "1.40", "glas", 7, "ware", False),
    ("Getränke", "Apfelsaft 1L", "2.60", "liter", 19, "ware", False),
    ("Vorrat & Trockenwaren", "Nudeln 500g", "2.10", "stueck", 7, "ware", False),
    ("Vorrat & Trockenwaren", "Kaffee 250g", "6.50", "stueck", 7, "ware", False),
    ("Snacks", "Müsliriegel", "0.90", "stueck", 7, "ware", False),
    ("Dienstleistungen", "Sauna (Tag)", "8.00", "portion", 19, "dienstleistung", True),
    ("Dienstleistungen", "Endreinigung", "45.00", "portion", 19, "dienstleistung", False),
]


class Command(BaseCommand):
    help = "Legt Demo-Daten für den Hofladen an (Gruppen, Produkte, Einstellungen)."

    @transaction.atomic
    def handle(self, *args, **opts):
        cfg = ShopConfig.get_solo()
        if not cfg.coop_address:
            cfg.coop_name = "Re:Hof eG"
            cfg.coop_address = "Hofweg 1\n16278 Beispieldorf"
            cfg.tax_number = "DE123456789"
            cfg.iban = "DE02120300000000202051"
            cfg.bic = "BYLADEM1001"
            cfg.save()

        groups = {}
        for name, emoji, sort in GROUPS:
            g, _ = ProductGroup.objects.get_or_create(
                name=name, defaults=dict(emoji=emoji, sort_order=sort))
            groups[name] = g
        for gname, name, price, unit, vat, kind, needs in PRODUCTS:
            Product.objects.get_or_create(
                group=groups[gname], name=name,
                defaults=dict(price=price, unit=unit, vat_rate=vat, kind=kind,
                              needs_date=needs))
        self.stdout.write(self.style.SUCCESS(
            f"{len(GROUPS)} Gruppen, {len(PRODUCTS)} Produkte angelegt."))

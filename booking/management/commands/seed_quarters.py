"""Legt die echten Quartiere und ihre Äquivalenzklassen an (Produktiv-Konfig).

Anders als `seed_demo` erzeugt dieses Kommando KEINE Demo-Mitglieder, Wünsche
oder Perioden – nur die 10 Quartiere mit der bestätigten Klassen-Einteilung,
alle aktiv geschaltet. Idempotent: mehrfaches Ausführen aktualisiert die Werte.

Aufruf:  python manage.py seed_quarters
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from booking.models import EquivalenceClass, Quarter

# name, m², min. Personen, max. Personen, Äquivalenzklasse
QUARTERS = [
    ("Scheunen Studio",    52, 2, 5, "Mittel"),
    ("Stallgebäude Nord",  65, 2, 5, "Mittel"),
    ("Stallgebäude Süd",   44, 2, 4, "Klein-Stall"),
    ("Stallgebäude West",  40, 2, 3, "Klein-Stall"),
    ("Gartenhaus Salix",   46, 2, 3, "Gartenhaus"),
    ("Gartenhaus Lupulus", 33, 2, 3, "Gartenhaus"),
    ("Gartenhaus Spinosa", 40, 2, 3, "Gartenhaus"),
    ("Pfarrhaus Nord",     74, 4, 6, "Pfarrhaus"),
    ("Pfarrhaus Süd",      68, 4, 6, "Pfarrhaus"),
    ("Hofgebäude",         54, 2, 4, "Mittel"),
]


class Command(BaseCommand):
    help = "Legt die echten Quartiere und Äquivalenzklassen an (aktiv)."

    @transaction.atomic
    def handle(self, *args, **opts):
        classes: dict[str, EquivalenceClass] = {}
        for *_rest, cls_name in QUARTERS:
            if cls_name not in classes:
                classes[cls_name], _ = EquivalenceClass.objects.get_or_create(
                    name=cls_name,
                )

        created = updated = 0
        for name, sqm, mn, mx, cls_name in QUARTERS:
            q, was_created = Quarter.objects.update_or_create(
                name=name,
                defaults=dict(
                    size_sqm=sqm, min_occupancy=mn, max_occupancy=mx,
                    eq_class=classes[cls_name], active=True,
                ),
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(
            f"{len(QUARTERS)} Quartiere in {len(classes)} Klassen gesetzt "
            f"({created} neu, {updated} aktualisiert): "
            + ", ".join(sorted(classes))
        ))

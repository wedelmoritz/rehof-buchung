"""Altbestände: für jede bereits abgerechnete Rechnung einen Einkauf nachtragen,
damit die Positionen auch rückwirkend nach Einkauf gruppiert werden können.
Offene Warenkorb-Positionen (noch nicht abgerechnet) bleiben unangetastet.

Eigene (Daten-)Migration, getrennt von der Schema-Migration 0003 – kein DDL hier.
"""
from django.db import migrations


def backfill_purchases(apps, schema_editor):
    Invoice = apps.get_model("shop", "Invoice")
    LineItem = apps.get_model("shop", "LineItem")
    Purchase = apps.get_model("shop", "Purchase")
    for inv in Invoice.objects.all():
        items = list(LineItem.objects.filter(invoice=inv, purchase__isnull=True))
        if not items:
            continue
        p = Purchase.objects.create(member_id=inv.member_id)
        # confirmed_at ist auto_now_add → nachträglich auf das Rechnungsdatum setzen.
        Purchase.objects.filter(pk=p.pk).update(confirmed_at=inv.created_at)
        LineItem.objects.filter(id__in=[i.id for i in items]).update(purchase=p)


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0003_purchase_lineitem_purchase"),
    ]

    operations = [
        migrations.RunPython(backfill_purchases, migrations.RunPython.noop),
    ]

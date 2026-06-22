"""Bestehende „beim Buchen anbietbare“ Dienstleistungen (bisher nur die
Endreinigung) als Endreinigung markieren, damit die Reinigungsliste sie ohne
manuelles Nacharbeiten erfasst. Neue Produkte setzen das Flag bewusst selbst."""
from django.db import migrations


def mark_cleaning(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    Product.objects.filter(book_with_stay=True).update(counts_as_cleaning=True)


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0005_invoice_due_date_invoice_reminded_at_and_more"),
    ]
    operations = [
        migrations.RunPython(mark_cleaning, migrations.RunPython.noop),
    ]

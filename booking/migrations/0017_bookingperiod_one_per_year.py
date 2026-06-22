"""Schemaänderung der Buchungsperiode: genau eine pro Jahr, ohne Quartier-Auswahl.

Läuft NACH der Datenbereinigung (0016) in eigener Transaktion, damit keine
„pending trigger events“ aus den Löschungen den ALTER TABLE blockieren.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0016_dedup_bookingperiod_target_year"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="bookingperiod",
            options={
                "ordering": ["-target_year"],
                "verbose_name": "Buchungsperiode (Jahr)",
                "verbose_name_plural": "Buchungsperioden (je Jahr eine)",
            },
        ),
        migrations.RemoveField(
            model_name="bookingperiod",
            name="applies_to_all",
        ),
        migrations.RemoveField(
            model_name="bookingperiod",
            name="quarters",
        ),
        migrations.AlterField(
            model_name="bookingperiod",
            name="start",
            field=models.DateField(
                help_text="Ab wann der Zeitraum frei bebuchbar ist (darf vor dem 1.1. des Buchungsjahres liegen).",
                verbose_name="Zeitraum buchbar ab",
            ),
        ),
        migrations.AlterField(
            model_name="bookingperiod",
            name="target_year",
            field=models.PositiveIntegerField(unique=True, verbose_name="Buchungsjahr"),
        ),
        migrations.AlterField(
            model_name="bookingperiod",
            name="wishlist_close",
            field=models.DateField(blank=True, null=True, verbose_name="Wünsche bis"),
        ),
        migrations.AlterField(
            model_name="bookingperiod",
            name="wishlist_open",
            field=models.DateField(blank=True, null=True, verbose_name="Wünsche ab"),
        ),
    ]

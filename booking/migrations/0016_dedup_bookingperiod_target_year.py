"""Datenbereinigung VOR der Schemaänderung: pro Jahr nur EINE Buchungsperiode.

Bewusst eine eigene (Daten-)Migration, getrennt von der folgenden Schema-
Migration 0017. Grund: Das Löschen von Perioden erzeugt (über Cascade auf
Wünsche etc.) „pending trigger events“; PostgreSQL verbietet dann im selben
Transaktionsschritt ein ALTER TABLE. Durch die Trennung committet die
Löschung zuerst, danach läuft die Schemaänderung sauber.
"""
from django.db import migrations


def dedup_target_year(apps, schema_editor):
    """Ältere Bestände hatten teils mehrere Perioden je Jahr (globale +
    quartiersspezifische). Behalte je Jahr bevorzugt die zur freien Buchung
    freigegebene Periode, sonst die älteste; der Rest wird entfernt. Ohne
    Duplikate ist das ein No-Op."""
    BookingPeriod = apps.get_model("booking", "BookingPeriod")
    by_year = {}
    for p in BookingPeriod.objects.order_by("id"):
        by_year.setdefault(p.target_year, []).append(p)
    for periods in by_year.values():
        if len(periods) < 2:
            continue
        keep = next((p for p in periods if p.status == "free_booking"), periods[0])
        for p in periods:
            if p.pk != keep.pk:
                p.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0015_notification_detail"),
    ]

    operations = [
        migrations.RunPython(dedup_target_year, migrations.RunPython.noop),
    ]

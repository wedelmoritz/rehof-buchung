"""Legt die Gruppe „Verwaltung" an (Dashboard-Rolle ohne Django-Backend)."""
from django.db import migrations


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Verwaltung")


def remove_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="Verwaltung").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0026_fairnesssimconfig"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(create_group, remove_group)]

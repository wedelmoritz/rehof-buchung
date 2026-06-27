"""App-Config, die die Standard-Admin-Site durch die fachlich gegliederte
ersetzt (ADR 0049). In INSTALLED_APPS statt „django.contrib.admin" eintragen:
``booking.admin_apps.RehofAdminConfig``.

Bewusst ein eigenes Modul (nicht booking/apps.py), damit die App-Discovery von
„booking" nicht zwei AppConfigs sieht.
"""
from django.contrib.admin.apps import AdminConfig


class RehofAdminConfig(AdminConfig):
    default_site = "booking.admin_site.RehofAdminSite"

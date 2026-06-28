"""App-Config, die die Standard-Admin-Site durch die fachlich gegliederte
ersetzt (ADR 0049). In INSTALLED_APPS statt „django.contrib.admin" eintragen:
``booking.admin_apps.RehofAdminConfig``.

Bewusst ein eigenes Modul (nicht booking/apps.py), damit die App-Discovery von
„booking" nicht zwei AppConfigs sieht.
"""
from django.contrib.admin.apps import AdminConfig


class RehofAdminConfig(AdminConfig):
    default_site = "booking.admin_site.RehofAdminSite"

    def ready(self):
        super().ready()   # autodiscover aller admin-Module (inkl. django_otp)
        # „Static devices" (OTP-Einmal-Backup-Codes) nutzen wir nicht – nur TOTP.
        # Aus dem Backend entfernen, damit dort kein verwirrender (englischer)
        # Eintrag steht (ADR 0061).
        from django.contrib import admin
        try:
            from django_otp.plugins.otp_static.models import StaticDevice
            admin.site.unregister(StaticDevice)
        except Exception:
            pass

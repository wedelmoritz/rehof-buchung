from django.apps import AppConfig


class BookingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "booking"
    verbose_name = "Quartier-Buchung"

    def ready(self):
        from . import signals  # noqa: F401  (Signal-Handler registrieren)

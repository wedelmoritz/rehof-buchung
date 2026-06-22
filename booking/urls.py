"""URLs der Buchungs-App."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("wuensche/", views.wishlist, name="wishlist"),
    path("kalender/", views.calendar, name="calendar"),
    path("tage-uebertragen/", views.transfer, name="transfer"),
    path("ergebnis/<int:period_id>/", views.period_result, name="period_result"),
]

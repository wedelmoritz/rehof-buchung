"""URLs der Buchungs-App."""
from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("offline/", TemplateView.as_view(
        template_name="booking/offline.html"), name="offline"),
    path("", views.overview, name="overview"),
    path("buchen/", views.book, name="book"),
    path("buchen/bestaetigen/", views.book_confirm, name="book_confirm"),
    path("wunschliste/", views.wishlist, name="wishlist"),
    path("meine-buchungen/", views.my_bookings, name="my_bookings"),
    path("tage-uebertragen/", views.transfer, name="transfer"),
    path("profil/", views.profile, name="profile"),
    path("hilfe/", views.help_page, name="help"),
    path("registrieren/", views.register, name="register"),
    path("freischaltung/", views.pending, name="pending"),
    path("ergebnis/<int:period_id>/", views.period_result, name="period_result"),
    path("verwaltung/", views.dashboard, name="dashboard"),
    path("verwaltung/export/<str:kind>.<str:fmt>", views.dashboard_export,
         name="dashboard_export"),
]

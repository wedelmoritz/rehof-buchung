"""URLs der Buchungs-App."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.overview, name="overview"),
    path("buchen/", views.book, name="book"),
    path("wunschliste/", views.wishlist, name="wishlist"),
    path("meine-buchungen/", views.my_bookings, name="my_bookings"),
    path("tage-uebertragen/", views.transfer, name="transfer"),
    path("profil/", views.profile, name="profile"),
    path("ergebnis/<int:period_id>/", views.period_result, name="period_result"),
]

"""URLs des Hofladens (eingebunden unter /hofladen/)."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.shop_index, name="shop_index"),
    path("kasse/", views.checkout, name="shop_checkout"),
    path("rechnungen/", views.invoices, name="shop_invoices"),
    path("rechnung/<int:invoice_id>/", views.invoice_detail, name="shop_invoice"),
]

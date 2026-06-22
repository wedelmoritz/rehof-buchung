"""Haupt-URL-Konfiguration."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(
        template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Service Worker MUSS im Root-Scope ("/") liegen, um die ganze App zu steuern.
    path("sw.js", TemplateView.as_view(
        template_name="booking/sw.js",
        content_type="application/javascript"), name="sw"),
    path("hofladen/", include("shop.urls")),
    path("", include("booking.urls")),
]

"""Haupt-URL-Konfiguration."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(
        template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Passwort selbst setzen – EIN Token-Mechanismus für beides: die Einladung neuer
    # Konten (services.send_account_invite) UND „Passwort vergessen". Standard-
    # Django-Reset-Views/-Namen, nur mit deutschen Pfaden + eigenen Templates.
    path("passwort-vergessen/", auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        email_template_name="registration/password_reset_email.txt",
        subject_template_name="registration/password_reset_subject.txt",
        success_url=reverse_lazy("password_reset_done")), name="password_reset"),
    path("passwort-vergessen/gesendet/", auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html"),
        name="password_reset_done"),
    path("passwort-setzen/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_set_confirm.html",
        success_url=reverse_lazy("password_reset_complete")),
        name="password_reset_confirm"),
    path("passwort-gesetzt/", auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_set_done.html"),
        name="password_reset_complete"),
    # Service Worker MUSS im Root-Scope ("/") liegen, um die ganze App zu steuern.
    path("sw.js", TemplateView.as_view(
        template_name="booking/sw.js",
        content_type="application/javascript"), name="sw"),
    path("hofladen/", include("shop.urls")),
    path("", include("booking.urls")),
]

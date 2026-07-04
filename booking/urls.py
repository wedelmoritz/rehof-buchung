"""URLs der Buchungs-App."""
from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("offline/", TemplateView.as_view(
        template_name="booking/offline.html"), name="offline"),
    path("healthz/", views.healthz, name="healthz"),
    path("", views.overview, name="overview"),
    path("buchen/", views.book, name="book"),
    path("buchen/bestaetigen/", views.book_confirm, name="book_confirm"),
    path("wunschliste/", views.wishlist, name="wishlist"),
    path("meine-buchungen/", views.my_bookings, name="my_bookings"),
    path("tage-uebertragen/", views.transfer, name="transfer"),
    path("tage-uebertragen/suche/", views.member_search, name="member_search"),
    path("profil/", views.profile, name="profile"),
    path("push/abo/", views.push_subscribe, name="push_subscribe"),
    path("push/abmelden/", views.push_unsubscribe, name="push_unsubscribe"),
    # Hofladen-Terminal vor Ort (offline-fähig, token-authentifiziert; ADR 0053)
    path("terminal/", views.terminal_page, name="terminal"),
    path("terminal/daten/", views.terminal_data, name="terminal_data"),
    path("terminal/sync/", views.terminal_sync, name="terminal_sync"),
    path("hilfe/", views.help_page, name="help"),
    path("losung-fairness/", views.lottery_fairness, name="lottery_fairness"),
    path("gemeinschaft/", views.community, name="community"),
    path("registrieren/", views.register, name="register"),
    path("freischaltung/", views.pending, name="pending"),
    path("impressum/", views.imprint, name="imprint"),
    path("datenschutz/", views.privacy, name="privacy"),
    path("agb/", views.terms, name="terms"),
    path("ergebnis/<int:period_id>/", views.period_result, name="period_result"),
    path("extern/", views.external_home, name="external_home"),
    path("extern/buchen/", views.external_book, name="external_book"),
    path("extern/verwalten/<uuid:token>/", views.external_manage,
         name="external_manage"),
    path("extern/bezahlen/<uuid:token>/", views.external_pay, name="external_pay"),
    path("extern/widget/", views.external_embed, name="external_embed"),
    path("verwaltung/", views.dashboard, name="dashboard"),
    path("verwaltung/buchungen/", views.verw_buchungen, name="verw_buchungen"),
    path("verwaltung/reinigung/", views.verw_reinigung, name="verw_reinigung"),
    path("verwaltung/rechnungen/", views.verw_rechnungen, name="verw_rechnungen"),
    path("verwaltung/kontoabgleich/", views.verw_konto, name="verw_konto"),
    path("verwaltung/auslastung/", views.verw_auslastung, name="verw_auslastung"),
    path("verwaltung/mitglieder/", views.verw_mitglieder, name="verw_mitglieder"),
    path("verwaltung/produkte/", views.dashboard_products, name="dashboard_products"),
    path("verwaltung/beds24-import/", views.beds24_import, name="beds24_import"),
    path("verwaltung/export/<str:kind>.<str:fmt>", views.dashboard_export,
         name="dashboard_export"),
    path("verwaltung/belegungsplan.pdf", views.plan_pdf, name="plan_pdf"),
]

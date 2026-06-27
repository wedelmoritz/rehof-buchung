"""Admin – liefert das Mitgliedermanagement und die Verwaltung quasi geschenkt."""
from __future__ import annotations

import random
from datetime import date

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse

from .models import (
    Allocation, Beds24Import, Beds24ImportRow, BookingPeriod, BookingPolicy,
    EquivalenceClass, ExternalBooking,
    ExternalConfig, FairnessSimConfig, Guest, LotteryRun, Member, Membership,
    NightTransfer,
    Notification, OpsConfig, OutboxEmail, Quarter, QuarterPrice, SchoolHoliday,
    SeasonRule, Share, SwapRequest, UpcomingAllocation, WaitlistEntry, Wish,
)
from .services import confirm_lottery, rollback_lottery, run_period_lottery


class Beds24ImportRowInline(admin.TabularInline):
    model = Beds24ImportRow
    extra = 0
    can_delete = False
    fields = ("guest_name", "arrival", "departure", "unit", "persons",
              "suggested_member", "suggested_score", "chosen_member",
              "chosen_quarter", "status", "note")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Beds24Import)
class Beds24ImportAdmin(admin.ModelAdmin):
    """Beds24-Migrations-Läufe (Audit). Der eigentliche Abgleich läuft über den
    Assistenten unter /verwaltung/beds24-import/ (nur Admin)."""
    list_display = ("created_at", "filename", "n_rows", "n_imported")
    inlines = [Beds24ImportRowInline]
    readonly_fields = ("created_at", "filename", "n_rows", "n_imported")

    def has_add_permission(self, request):
        return False

# Branding der Verwaltung
admin.site.site_header = "ReHof-Verwaltung"
admin.site.site_title = "ReHof-Verwaltung"
admin.site.index_title = "Verwaltung"
# Erklär-Panel „Was kannst du hier tun?“ auf der Backend-Startseite.
admin.site.index_template = "admin/custom_index.html"


@admin.register(EquivalenceClass)
class EquivalenceClassAdmin(admin.ModelAdmin):
    list_display = ("name",)


class QuarterPriceInline(admin.TabularInline):
    """Saisonale Übernachtungspreise (jährlich wiederkehrend). Greift keine Regel,
    gilt der Basispreis/Nacht."""
    model = QuarterPrice
    extra = 0


@admin.register(Quarter)
class QuarterAdmin(admin.ModelAdmin):
    inlines = [QuarterPriceInline]
    list_display = ("name", "eq_class", "size_sqm", "min_occupancy",
                    "max_occupancy", "accessible", "active")
    list_filter = ("eq_class", "active", "accessible")
    list_editable = ("accessible",)
    search_fields = ("name",)
    fieldsets = (
        (None, {
            "fields": ("name", "eq_class", "description", "active"),
            "description": (
                "Ein buchbares Quartier. Die <b>Äquivalenzklasse</b> gruppiert "
                "gleichwertige Quartiere – die Losung darf innerhalb einer Klasse "
                "auf ein freies Quartier ausweichen. „Aktiv“ aus = nicht buchbar."),
        }),
        ("Belegung & Merkmale", {
            "fields": ("size_sqm", "min_occupancy", "max_occupancy", "accessible"),
            "description": "Min./Max.-Personen steuern, welche Quartiere beim "
                           "Buchen je nach Personenzahl als passend angezeigt werden.",
        }),
        ("Buchbarkeitszeitraum (jährlich, ohne Jahr – leer = ganzjährig)", {
            "fields": ("season_start_month", "season_start_day",
                       "season_end_month", "season_end_day"),
            "description": "Manche Quartiere sind nicht das ganze Jahr buchbar. "
                           "Beispiel: 1.4. bis 31.10.",
        }),
        ("Externe Gäste", {
            "fields": ("external_bookable", "price_per_night"),
            "description": "Wenn „für externe Gäste buchbar“ aktiv ist, können "
                           "Externe (im Rahmen der Externe-Gäste-Einstellungen) "
                           "dieses Quartier buchen. „Preis/Nacht“ ist der Basispreis; "
                           "saisonale Abweichungen unten als <b>Saisonpreise</b>.",
        }),
    )


# --------------------------------------------------------------------------- #
# Benutzer (Person + Login + Mitglieds-Profil in EINEM Formular)
# --------------------------------------------------------------------------- #

class MemberProfileInline(admin.StackedInline):
    """Das Mitglieds-Profil dieses Benutzers: Anzeigename, Ausgleichsfaktor und
    die Rechnungsdaten. Ohne ausgefülltes Profil kann die Person nicht buchen
    (reine Verwaltungs-Konten brauchen es nicht)."""
    model = Member
    can_delete = False
    extra = 1
    max_num = 1
    verbose_name = "Mitglieds-Profil"
    verbose_name_plural = "Mitglieds-Profil (zum Buchen nötig)"
    fieldsets = (
        ("Buchungs-Profil", {
            "fields": ("display_name", "factor", "is_external"),
            "description": (
                "<b>Mitglied = Buchungs-Profil dieses Benutzers (1:1).</b> Ohne "
                "Profil kann die Person nicht buchen. Die <b>Tage</b> kommen NICHT "
                "von hier, sondern vom <b>Mitglieds-Anteil</b> – dort die Person mit "
                "ihrem Tage-Anteil zuordnen. Der Ausgleichsfaktor (Karma) wird von "
                "der Losung automatisch gepflegt – im Normalfall nicht ändern."),
        }),
        ("Rechnungsdaten (Hofladen)", {
            "fields": ("legal_name", "street", "zip_code", "city", "iban"),
        }),
    )


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Ein Benutzer = eine Person mit Login UND Buchungs-/Rechnungsprofil.
    Tage-Anteile (welche eG-Anteile die Person hält) werden beim jeweiligen
    „Mitglieds-Anteil“ zugeordnet."""
    inlines = [MemberProfileInline]


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    """Wird nicht eigenständig angezeigt (Profil steckt im Benutzer). Bleibt nur
    für die Such-/Auswahl-Funktion bei der Anteils-Zuordnung registriert."""
    search_fields = ("display_name", "user__username", "user__email")

    def get_model_perms(self, request):
        return {}  # aus der Verwaltungs-Übersicht ausblenden


class ShareInline(admin.TabularInline):
    """Die diesem Anteil zugeordneten Nutzer mit ihrem festen Tage-Anteil.
    Voll-Mitglied = ein Nutzer (voller Anteil); Teil/Tandem = mehrere Nutzer,
    deren Tage-Anteile zusammen das Gesamtbudget ergeben. Leer gelassene Anteile
    (0) werden beim Speichern gleichmäßig (abgerundet) vorgeschlagen."""
    model = Share
    extra = 1
    autocomplete_fields = ("member",)
    fields = ("member", "night_budget", "wish_night_budget")
    verbose_name = "Zugeordneter Nutzer (Tage-Anteil)"
    verbose_name_plural = "Zugeordnete Nutzer (je fester Tage-Anteil)"


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("__str__", "eg_number", "kind", "annual_night_budget",
                    "allocated_display", "is_tandem_display", "created_on")
    list_filter = ("kind",)
    search_fields = ("eg_number", "label", "shares__member__display_name")
    inlines = [ShareInline]
    fieldsets = (
        (None, {
            "fields": ("eg_number", "label", "kind", "annual_night_budget",
                       "wish_night_budget", "created_on"),
            "description": (
                "Ein <b>Mitglieds-Anteil</b> = eine Vielleben-eG-Nummer mit einem "
                "Jahres-Tagebudget (Standard 50). <b>Voll-Mitglied</b> = ein Nutzer "
                "hält den ganzen Anteil; <b>Teil-Mitglied (Tandem)</b> = mehrere "
                "Nutzer teilen sich den Anteil. Unten ordnest du die <b>Nutzer</b> "
                "(= Benutzer mit Mitglieds-Profil) mit ihrem festen Tage-Anteil zu. "
                "Ein Nutzer kann mehreren Anteilen angehören – sein Budget ist die "
                "Summe. Bei Anlage mitten im Jahr ist das Budget bereits anteilig "
                "vorgeschlagen; leer gelassene Tage-Anteile (0) werden beim "
                "Speichern gleichmäßig abgerundet aufgeteilt."),
        }),
    )

    @admin.display(description="vergeben")
    def allocated_display(self, obj):
        return f"{obj.allocated_budget}/{obj.annual_night_budget}"

    @admin.display(boolean=True, description="Tandem")
    def is_tandem_display(self, obj):
        return obj.is_tandem

    def get_changeform_initial_data(self, request):
        return {"annual_night_budget": Membership.suggest_budget()}

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Vorschlag: noch nicht gesetzte Tage-Anteile (0) gleichmäßig abrunden.
        obj = form.instance
        shares = list(obj.shares.all())
        if not shares:
            return
        per = obj.annual_night_budget // len(shares)
        per_wish = obj.wish_night_budget // len(shares)
        for s in shares:
            changed = False
            if s.night_budget == 0:
                s.night_budget, changed = per, True
            if s.wish_night_budget == 0:
                s.wish_night_budget, changed = per_wish, True
            if changed:
                s.save()


class WishInline(admin.TabularInline):
    model = Wish
    extra = 0


@admin.register(BookingPeriod)
class BookingPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "target_year", "status", "start", "end",
                    "wishlist_open", "wishlist_close", "draw_at")
    list_filter = ("status", "target_year")
    actions = ["action_run_lottery"]
    fieldsets = (
        (None, {
            "fields": ("name", "target_year", "status"),
            "description": (
                "Pro Buchungsjahr gibt es <b>genau eine</b> Periode. Der "
                "<b>Status</b> ergibt sich normalerweise automatisch aus den "
                "unten eingestellten Terminen (Entwurf → Wünsche offen → "
                "Auslosung → frei buchbar → beendet) und wird per Cron "
                "(<code>run_due_lotteries</code>) vorwärts geschaltet – inkl. der "
                "fälligen Auslosung. Hier von Hand nur eingreifen, um z. B. auf "
                "<b>„Unterbrochen“</b> zu setzen (pausiert die Automatik)."),
        }),
        ("Termine (steuern den Ablauf)", {
            "fields": ("wishlist_open", "wishlist_close", "draw_at",
                       "start", "end", "seed"),
            "description": (
                "Zeitlicher Ablauf eines Buchungsjahres: <b>Wünsche ab/bis</b> = "
                "Anmeldefenster für die Wunschliste; <b>Losung am</b> = Termin der "
                "automatischen Auslosung; <b>buchbar ab/bis</b> = Zeitraum der "
                "freien Bebuchbarkeit (Ende exklusiv; „buchbar ab“ darf vor dem "
                "1.1. liegen). Übliche Reihenfolge: Wünsche → Losung → buchbar. "
                "Der Seed macht die Auslosung reproduzierbar (leer = zufällig)."
            ),
        }),
    )

    @admin.action(description="Losung für gewählte Periode(n) durchführen")
    def action_run_lottery(self, request, queryset):
        for period in queryset:
            seed = period.seed or random.randint(1, 2_000_000_000)
            try:
                run = run_period_lottery(period, seed=seed)
            except ValueError as exc:
                self.message_user(request, f"{period}: {exc}", level=messages.ERROR)
                continue
            self.message_user(
                request,
                f"{period}: {run.summary}. Ergebnis ist UNBESTÄTIGT (für "
                f"Mitglieder unsichtbar) – unter „Losdurchläufe“ bestätigen oder "
                f"zurücknehmen.",
                level=messages.WARNING,
            )


@admin.register(Wish)
class WishAdmin(admin.ModelAdmin):
    list_display = ("member", "period", "priority", "quarter", "start", "end",
                    "submitted")
    list_filter = ("period", "quarter", "submitted")
    search_fields = ("member__display_name",)


@admin.register(Allocation)
class AllocationAdmin(admin.ModelAdmin):
    list_display = ("member", "quarter", "start", "end", "persons", "source",
                    "via_substitution", "contested")
    list_filter = ("source", "quarter", "contested")
    search_fields = ("member__display_name",)


@admin.action(description="Excel-Export der ausgewählten Buchungen")
def export_bookings_xlsx(modeladmin, request, queryset):
    from . import exports, services as svc
    return exports.xlsx_response(
        "buchungen", "Buchungen", svc.BOOKING_COLUMNS,
        svc.booking_rows(svc._annotate_cleaning(queryset)
                         .select_related("quarter", "member")))


@admin.register(UpcomingAllocation)
class UpcomingAllocationAdmin(admin.ModelAdmin):
    """Anstehende Buchungen – für die Vorbereitung der Verwaltung. Zeigt nur
    Buchungen mit Abreise ab heute, chronologisch nach Anreise. Für die
    monatliche Reinigungs-/Buchungsübersicht das <b>Verwaltungs-Dashboard</b>
    nutzen (Filter, Versand, Export)."""
    list_display = ("start", "end", "quarter", "member", "persons",
                    "nights_display", "cleaning_display", "source")
    list_filter = ("quarter", "source")
    search_fields = ("member__display_name", "quarter__name")
    date_hierarchy = "start"
    ordering = ("start",)
    actions = [export_bookings_xlsx]

    @admin.display(description="Nächte")
    def nights_display(self, obj):
        return obj.nights

    @admin.display(boolean=True, description="Endreinigung")
    def cleaning_display(self, obj):
        return bool(getattr(obj, "has_cleaning", False))

    def get_queryset(self, request):
        from .services import _annotate_cleaning
        return (
            _annotate_cleaning(super().get_queryset(request))
            .filter(end__gte=date.today())
            .select_related("quarter", "member")
        )

    def has_add_permission(self, request):
        return False


@admin.register(LotteryRun)
class LotteryRunAdmin(admin.ModelAdmin):
    """Losdurchläufe. Ein Lauf ist zunächst <b>unbestätigt</b> (Ergebnis für
    Mitglieder unsichtbar). Über die Aktionen <b>bestätigen</b> (veröffentlicht +
    benachrichtigt; danach kein Zurück) oder <b>zurücknehmen</b> (löscht die
    vorläufigen Zuteilungen, stellt das Karma wieder her)."""
    list_display = ("period", "executed_at", "seed", "confirmed", "confirmed_at",
                    "summary")
    list_filter = ("confirmed",)
    readonly_fields = ("period", "executed_at", "seed", "summary", "log_text",
                       "confirmed", "confirmed_at")
    actions = ["action_confirm", "action_rollback"]
    exclude = ("karma_snapshot", "notices")

    def has_add_permission(self, request):
        # Losdurchläufe sind Audit-Einträge, die der Dienst bei der Auslosung
        # erzeugt – manuelles Anlegen ergibt keinen Sinn. Auslösen über die
        # Aktion an der Buchungsperiode.
        return False

    def _confirm_page(self, request, queryset, action, title, intro, button):
        from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
        from django.template.response import TemplateResponse
        return TemplateResponse(request, "admin/lottery_action_confirm.html", {
            "title": title, "intro": intro, "button_label": button,
            "action": action, "runs": queryset,
            "checkbox_name": ACTION_CHECKBOX_NAME,
            "opts": self.model._meta,
        })

    @admin.action(description="Auslosung bestätigen & veröffentlichen")
    def action_confirm(self, request, queryset):
        if request.POST.get("confirm"):
            n = 0
            for run in queryset:
                if not run.confirmed:
                    confirm_lottery(run)
                    n += 1
            self.message_user(
                request, f"{n} Auslosung(en) bestätigt und veröffentlicht.",
                level=messages.SUCCESS)
            return None
        return self._confirm_page(
            request, queryset, "action_confirm",
            "Auslosung wirklich bestätigen?",
            "Die folgende(n) Auslosung(en) werden veröffentlicht und alle "
            "Teilnehmer benachrichtigt. Danach ist KEIN Zurücknehmen mehr möglich:",
            "Ja, verbindlich bestätigen")

    @admin.action(description="Auslosung zurücknehmen (nur unbestätigte)")
    def action_rollback(self, request, queryset):
        if request.POST.get("confirm"):
            ok_n = 0
            for run in queryset:
                done, err = rollback_lottery(run)
                if done:
                    ok_n += 1
                else:
                    self.message_user(request, f"{run.period}: {err}",
                                      level=messages.ERROR)
            if ok_n:
                self.message_user(
                    request, f"{ok_n} Auslosung(en) zurückgenommen "
                    "(Zuteilungen entfernt, Karma wiederhergestellt).",
                    level=messages.SUCCESS)
            return None
        return self._confirm_page(
            request, queryset, "action_rollback",
            "Auslosung wirklich zurücknehmen?",
            "Die vorläufigen Zuteilungen werden gelöscht und das Karma auf den "
            "Stand vor dem Lauf zurückgesetzt. Nur unbestätigte Läufe:",
            "Ja, zurücknehmen")


@admin.register(NightTransfer)
class NightTransferAdmin(admin.ModelAdmin):
    list_display = ("year", "from_member", "to_member", "nights", "created_at")
    list_filter = ("year",)
    search_fields = ("from_member__display_name", "to_member__display_name")


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("quarter", "start", "end", "persons", "member",
                    "fulfilled", "created_at")
    list_filter = ("fulfilled", "quarter")
    search_fields = ("member__display_name", "quarter__name")
    date_hierarchy = "start"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("member", "message", "read", "created_at")
    list_filter = ("read",)
    search_fields = ("member__display_name", "message")


@admin.register(SwapRequest)
class SwapRequestAdmin(admin.ModelAdmin):
    list_display = ("from_member", "to_member", "from_allocation",
                    "to_allocation", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("from_member__display_name", "to_member__display_name")


@admin.register(OpsConfig)
class OpsConfigAdmin(admin.ModelAdmin):
    """Betriebs-Einstellungen (Singleton): Empfänger der Verwaltungs-Mails und
    der Reinigungsliste. Im Verwaltungs-Dashboard genutzt."""
    fieldsets = (
        ("Empfänger der Verwaltungs-Mails", {
            "fields": ("admin_emails", "cleaning_emails"),
            "description": "Komma-getrennte E-Mail-Adressen. „Reinigungsteam“ "
                           "leer = es gilt die Verwaltungs-Adresse."}),
        ("Automatische Monats-Mail", {
            "fields": ("notify_day",),
            "description": "An diesem Tag des Monats geht die Übersicht der "
                           "Buchungen des Folgemonats automatisch an die Verwaltung "
                           "(per Cron/Scheduler)."}),
        ("Beds24-Migration", {
            "fields": ("beds24_import_enabled",),
            "description": "Der Beds24-Import wird i. d. R. nur einmalig beim Umzug "
                           "gebraucht. Danach hier ausschalten – dann ist der "
                           "Assistent im Dashboard ausgeblendet und gesperrt."}),
    )

    def has_add_permission(self, request):
        return not OpsConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = OpsConfig.get_solo()
        return redirect(reverse("admin:booking_opsconfig_change", args=[obj.id]))


@admin.register(OutboxEmail)
class OutboxEmailAdmin(admin.ModelAdmin):
    """Einsicht in die E-Mail-Warteschlange (versendet der Scheduler via
    send_outbox). Read-only – Inhalte werden vom System erzeugt."""
    list_display = ("to_email", "subject", "created_at", "sent_at", "attempts")
    list_filter = ("sent_at",)
    search_fields = ("to_email", "subject")
    date_hierarchy = "created_at"
    readonly_fields = ("to_email", "subject", "body", "html_body", "member",
                       "created_at", "sent_at", "attempts", "last_error")

    def has_add_permission(self, request):
        return False


class SeasonRuleInline(admin.TabularInline):
    """Saison-/Sonderzeiträume mit verschärften Regeln – Teil der Buchungsregeln.

    Beispiele: Juli/August → Mindestnächte 7. Schulferien/Feiertage → max. 2
    gleichzeitige Wohneinheiten. BB-Sommerferien → zusätzlich Deckel 14 Nächte.
    Leere Felder = die jeweilige Regel greift nicht.
    """
    model = SeasonRule
    extra = 0
    ordering = ("start_month", "start_day")
    fields = ("name", "start_month", "start_day", "end_month", "end_day",
              "min_nights", "max_parallel_units", "max_stay_nights", "active")
    verbose_name = "Saison-Regel (gilt jedes Jahr)"
    verbose_name_plural = "Saison-Regeln (gelten jedes Jahr, verschärfen die globalen Regeln)"


class SchoolHolidayInline(admin.TabularInline):
    """Schulferien – jährlich wiederkehrend. Anzeige im Kalender; gesetzte
    Regelfelder werden im Zeitraum durchgesetzt (leer = nur Anzeige)."""
    model = SchoolHoliday
    extra = 0
    ordering = ("start_month", "start_day")
    fields = ("name", "start_month", "start_day", "end_month", "end_day",
              "region", "min_nights", "max_parallel_units", "max_stay_nights",
              "active")
    verbose_name = "Schulferien (gilt jedes Jahr)"
    verbose_name_plural = "Schulferien (gelten jedes Jahr; Regelfelder optional)"


@admin.register(BookingPolicy)
class BookingPolicyAdmin(admin.ModelAdmin):
    """Eine gemeinsame Einstellungsseite für alle Buchungsregeln: globale
    Mindestnächte, beliebig viele Saison-Regeln und die Schulferien."""
    inlines = [SeasonRuleInline, SchoolHolidayInline]
    fieldsets = (
        ("Globale Regeln", {"fields": ("default_min_nights",)}),
    )

    def has_add_permission(self, request):
        # Es gibt genau ein Regelwerk.
        return not BookingPolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Direkt auf die eine Einstellungsseite springen (statt Listenansicht).
        obj = BookingPolicy.get_solo()
        return redirect(
            reverse("admin:booking_bookingpolicy_change", args=[obj.id])
        )


# --------------------------------------------------------------------------- #
# Externe Gäste (siehe docs/EXTERNE-GAESTE.md)
# --------------------------------------------------------------------------- #

@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    """Externe Gäste (kein Login). Werden beim öffentlichen Buchen angelegt."""
    list_display = ("name", "email", "city", "created_at")
    search_fields = ("name", "email", "city")
    date_hierarchy = "created_at"
    readonly_fields = ("token", "created_at")


@admin.register(ExternalConfig)
class ExternalConfigAdmin(admin.ModelAdmin):
    """Regeln & Konditionen für externe Gäste (Singleton)."""
    fieldsets = (
        ("Freigabe", {
            "fields": ("active",),
            "description": "Globaler Schalter für die externe Buchung."}),
        ("Wann dürfen Externe buchen?", {
            "fields": ("allowed_weekdays", "min_nights_follow_internal",
                       "min_nights", "max_nights", "lead_days", "horizon_days"),
            "description": "„Erlaubte Übernachtungs-Wochentage“ z. B. 0,1,2,3 = Mo–Do "
                           "(Wochenenden bleiben Mitgliedern). Leer = alle Tage. "
                           "Mindestaufenthalt: standardmäßig „wie intern“ (inkl. "
                           "Saison-Mindestnächte); zum Abweichen den Haken entfernen "
                           "und den eigenen Wert setzen. Unabhängig von der "
                           "tatsächlichen Belegung."}),
        ("Preise & Zahlung", {
            "fields": ("cleaning_fee", "cleaning_vat", "stay_vat", "payment_term_days"),
            "description": "Preis/Nacht steht je Quartier (inkl. Saisonpreise). "
                           "Endreinigung als Pauschale; USt getrennt "
                           "(Beherbergung 7 %, Reinigung 19 %)."}),
        ("Anzahlung, Storno & Säumnis", {
            "fields": ("deposit_percent", "free_cancel_days", "partial_cancel_days",
                       "partial_refund_percent", "late_fee", "terms"),
            "description": "Anzahlung (%, 0 = keine), Erstattungs-Staffel nach Vorlauf "
                           "zur Anreise und Säumniszuschlag. Diese Werte sind als Naht "
                           "für den Online-Bezahlprozess vorbereitet; heute werden sie "
                           "den Gästen informativ angezeigt (Erstattung manuell)."}),
    )

    def has_add_permission(self, request):
        return not ExternalConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = ExternalConfig.get_solo()
        return redirect(reverse("admin:booking_externalconfig_change", args=[obj.id]))


@admin.action(description="Ausgewählte Buchungen stornieren")
def cancel_external(modeladmin, request, queryset):
    from .services import cancel_external_booking
    n = sum(1 for b in queryset if b.status != ExternalBooking.CANCELLED
            and cancel_external_booking(b))
    messages.success(request, f"{n} externe Buchung(en) storniert.")


@admin.register(ExternalBooking)
class ExternalBookingAdmin(admin.ModelAdmin):
    """Buchungen externer Gäste. Blockieren (wenn bestätigt) die Verfügbarkeit;
    abgerechnet über die verknüpfte Rechnung (Hofladen-Workflow)."""
    list_display = ("start", "end", "quarter", "guest", "persons", "status",
                    "total_gross", "invoice")
    list_filter = ("status", "quarter")
    search_fields = ("guest__name", "guest__email", "quarter__name")
    date_hierarchy = "start"
    actions = [cancel_external]
    autocomplete_fields = ("guest", "quarter", "invoice")
    readonly_fields = ("created_at", "confirmed_at", "cancelled_at", "total_gross")

    def has_add_permission(self, request):
        return False


@admin.register(FairnessSimConfig)
class FairnessSimConfigAdmin(admin.ModelAdmin):
    """Statistischer Fairness-Nachweis (Singleton): Parameter einstellen und die
    Monte-Carlo-Simulation per Knopf starten. Das Ergebnis erscheint mit Grafen
    auf der Login-Seite /losung-fairness/ (verlinkt unter der Hilfe)."""
    fields = ("n_users", "n_items", "n_runs", "last_run_at")
    readonly_fields = ("last_run_at",)
    change_form_template = "admin/fairness_change_form.html"

    def has_add_permission(self, request):
        return not FairnessSimConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = FairnessSimConfig.get_solo()
        return redirect(
            reverse("admin:booking_fairnesssimconfig_change", args=[obj.id]))

    def response_change(self, request, obj):
        # Beim Klick auf „Simulation berechnen“ werden zuerst die (ggf. geänderten)
        # Parameter gespeichert, dann wird die Simulation ausgeführt.
        if "_run_sim" in request.POST:
            from .services import run_fairness_simulation
            eq = run_fairness_simulation(obj)["equal"]
            messages.success(
                request,
                f"Fairness-Simulation berechnet: {eq['n_runs']} Ziehungen, "
                f"χ²-p-Wert {eq['p_value']:.3f} "
                f"({'fair ✓' if eq['uniform_ok'] else 'siehe Seite'}). "
                "Ergebnis unter „/losung-fairness/“.")
            return redirect(request.path)
        return super().response_change(request, obj)

"""Admin – liefert das Mitgliedermanagement und die Verwaltung quasi geschenkt."""
from __future__ import annotations

import random
from datetime import date

from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse

from .models import (
    Allocation, BookingPeriod, BookingPolicy, EquivalenceClass,
    LotteryRun, Member, Membership, NightTransfer, Notification, Quarter,
    SchoolHoliday, SeasonRule, SwapRequest, UpcomingAllocation, WaitlistEntry,
    Wish,
)
from .services import run_period_lottery

# Branding der Verwaltung
admin.site.site_header = "ReHof-Verwaltung"
admin.site.site_title = "ReHof-Verwaltung"
admin.site.index_title = "Verwaltung"


@admin.register(EquivalenceClass)
class EquivalenceClassAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Quarter)
class QuarterAdmin(admin.ModelAdmin):
    list_display = ("name", "eq_class", "size_sqm", "min_occupancy",
                    "max_occupancy", "accessible", "active")
    list_filter = ("eq_class", "active", "accessible")
    list_editable = ("accessible",)
    search_fields = ("name",)
    fieldsets = (
        (None, {"fields": ("name", "eq_class", "description", "active")}),
        ("Belegung & Merkmale", {
            "fields": ("size_sqm", "min_occupancy", "max_occupancy", "accessible"),
        }),
        ("Buchbarkeitszeitraum (jährlich, ohne Jahr – leer = ganzjährig)", {
            "fields": ("season_start_month", "season_start_day",
                       "season_end_month", "season_end_day"),
            "description": "Manche Quartiere sind nicht das ganze Jahr buchbar. "
                           "Beispiel: 1.4. bis 31.10.",
        }),
    )


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "membership", "factor",
                    "annual_night_budget", "wish_night_budget", "is_external")
    list_filter = ("is_external", "membership")
    search_fields = ("display_name", "user__username", "user__email",
                     "membership__eg_number")
    list_editable = ("factor",)
    list_select_related = ("user", "membership")


class MemberInline(admin.TabularInline):
    """Die einem Anteil zugeordneten Nutzer mit ihrem festen Tage-Anteil.
    Voll-Mitglied = ein Nutzer (voller Anteil); Tandem = mehrere Nutzer, deren
    Tage-Anteile zusammen das Gesamtbudget ergeben."""
    model = Member
    extra = 0
    fields = ("user", "display_name", "annual_night_budget", "wish_night_budget",
              "factor", "is_external")
    autocomplete_fields = ("user",)
    verbose_name = "Nutzer (Tage-Anteil)"
    verbose_name_plural = "Zugeordnete Nutzer (je fester Tage-Anteil)"


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("__str__", "eg_number", "annual_night_budget",
                    "allocated_display", "is_tandem", "created_on")
    search_fields = ("eg_number", "label", "members__display_name")
    inlines = [MemberInline]
    fieldsets = (
        (None, {
            "fields": ("eg_number", "label", "annual_night_budget", "created_on"),
            "description": "Bei Anlage mitten im Jahr ist das Gesamtbudget bereits "
                           "anteilig vorgeschlagen (Rest des Kalenderjahres).",
        }),
    )

    @admin.display(description="vergeben")
    def allocated_display(self, obj):
        return f"{obj.allocated_budget}/{obj.annual_night_budget}"

    @admin.display(boolean=True, description="Tandem")
    def is_tandem(self, obj):
        return obj.is_tandem

    def get_changeform_initial_data(self, request):
        # Beim Anlegen das anteilige Tagebudget vorschlagen.
        return {"annual_night_budget": Membership.suggest_budget()}


class WishInline(admin.TabularInline):
    model = Wish
    extra = 0


@admin.register(BookingPeriod)
class BookingPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "target_year", "status", "start", "end",
                    "wishlist_open", "wishlist_close")
    list_filter = ("status", "target_year")
    filter_horizontal = ("quarters",)
    actions = ["action_run_lottery"]
    fieldsets = (
        (None, {"fields": ("name", "target_year", "status")}),
        ("Zeitraum (buchbarer Bereich)", {
            "fields": ("start", "end"),
            "description": (
                "Der Zeitraum, der im Status „Freie Bebuchbarkeit“ zur normalen "
                "Buchung freigeschaltet ist (Abreise/Ende exklusiv). Üblich: das "
                "ganze Buchungsjahr."
            ),
        }),
        ("Wunsch- & Losphase", {
            "fields": ("wishlist_open", "wishlist_close", "seed"),
            "description": (
                "Anmeldezeitraum für die Wunschliste (relevant im Status „Für "
                "Wunsch-Einträge freigegeben“). Der Seed macht die Auslosung "
                "reproduzierbar; leer = zufällig bei Durchführung."
            ),
        }),
        ("Geltungsbereich der freien Bebuchbarkeit", {
            "fields": ("applies_to_all", "quarters"),
            "description": (
                "Standard: der Zeitraum gilt für alle aktiven Quartiere. Haken "
                "entfernen und Quartiere wählen, um die freie Buchbarkeit auf "
                "einzelne Quartiere zu beschränken."
            ),
        }),
    )

    @admin.action(description="Losung für gewählte Periode(n) durchführen")
    def action_run_lottery(self, request, queryset):
        for period in queryset:
            seed = period.seed or random.randint(1, 2_000_000_000)
            run = run_period_lottery(period, seed=seed)
            self.message_user(
                request, f"{period}: {run.summary}", level=messages.SUCCESS,
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


@admin.register(UpcomingAllocation)
class UpcomingAllocationAdmin(admin.ModelAdmin):
    """Anstehende Buchungen – für die Vorbereitung der Verwaltung. Zeigt nur
    Buchungen mit Abreise ab heute, chronologisch nach Anreise."""
    list_display = ("start", "end", "quarter", "member", "persons",
                    "nights_display", "source")
    list_filter = ("quarter", "source")
    search_fields = ("member__display_name", "quarter__name")
    date_hierarchy = "start"
    ordering = ("start",)

    @admin.display(description="Nächte")
    def nights_display(self, obj):
        return obj.nights

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .filter(end__gte=date.today())
            .select_related("quarter", "member")
        )

    def has_add_permission(self, request):
        return False


@admin.register(LotteryRun)
class LotteryRunAdmin(admin.ModelAdmin):
    list_display = ("period", "executed_at", "seed", "summary")
    readonly_fields = ("executed_at", "seed", "summary", "log_text")


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

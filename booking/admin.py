"""Admin – liefert das Mitgliedermanagement und die Verwaltung quasi geschenkt."""
from __future__ import annotations

import random

from django.contrib import admin, messages

from .models import (
    Allocation, BookingPeriod, BookingPolicy, BookingWindow, EquivalenceClass,
    LotteryRun, Member, NightTransfer, Quarter, SchoolHoliday, SeasonRule, Wish,
)
from .services import run_period_lottery


@admin.register(EquivalenceClass)
class EquivalenceClassAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Quarter)
class QuarterAdmin(admin.ModelAdmin):
    list_display = ("name", "eq_class", "size_sqm", "min_occupancy",
                    "max_occupancy", "active")
    list_filter = ("eq_class", "active")
    search_fields = ("name",)


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "factor", "annual_night_budget",
                    "wish_night_budget", "is_external")
    list_filter = ("is_external",)
    search_fields = ("display_name", "user__username", "user__email")
    list_editable = ("factor",)


class WishInline(admin.TabularInline):
    model = Wish
    extra = 0


@admin.register(BookingPeriod)
class BookingPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "target_year", "status", "wishlist_open",
                    "wishlist_close", "seed")
    list_filter = ("status", "target_year")
    actions = ["action_run_lottery"]

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
    list_display = ("member", "quarter", "start", "end", "source",
                    "via_substitution", "contested")
    list_filter = ("source", "quarter", "contested")
    search_fields = ("member__display_name",)


@admin.register(LotteryRun)
class LotteryRunAdmin(admin.ModelAdmin):
    list_display = ("period", "executed_at", "seed", "summary")
    readonly_fields = ("executed_at", "seed", "summary", "log_text")


@admin.register(BookingWindow)
class BookingWindowAdmin(admin.ModelAdmin):
    list_display = ("name", "start", "end", "applies_to_all", "active")
    list_filter = ("active", "applies_to_all")
    list_editable = ("active",)
    filter_horizontal = ("quarters",)
    fieldsets = (
        (None, {"fields": ("name", "active")}),
        ("Zeitraum", {"fields": ("start", "end")}),
        ("Geltungsbereich", {
            "fields": ("applies_to_all", "quarters"),
            "description": (
                "Globale Fenster (Haken bei „Gilt für alle Quartiere“) geben "
                "die Grundfreigabe. Ein nicht-globales Fenster schränkt die "
                "Buchbarkeit für die gewählten Quartiere weiter ein – buchbar "
                "ist dann nur, was sowohl global als auch hier freigegeben ist."
            ),
        }),
    )


@admin.register(NightTransfer)
class NightTransferAdmin(admin.ModelAdmin):
    list_display = ("year", "from_member", "to_member", "nights", "created_at")
    list_filter = ("year",)
    search_fields = ("from_member__display_name", "to_member__display_name")


@admin.register(BookingPolicy)
class BookingPolicyAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

    def has_add_permission(self, request):
        # Nur eine globale Regel-Zeile zulassen
        return not BookingPolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SeasonRule)
class SeasonRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "start", "end", "min_nights",
                    "max_parallel_units", "max_stay_nights", "active")
    list_filter = ("active",)
    list_editable = ("active",)
    ordering = ("start",)
    fieldsets = (
        (None, {"fields": ("name", "active")}),
        ("Zeitraum", {"fields": ("start", "end")}),
        ("Regeln (leer = Regel greift nicht)", {
            "fields": ("min_nights", "max_parallel_units", "max_stay_nights"),
            "description": (
                "Beispiele: Juli/August → Mindestnächte 7. Schulferien/Feiertage "
                "→ max. 2 gleichzeitige Wohneinheiten. BB-Sommerferien → "
                "zusätzlich Deckel 14 Nächte je Partei."
            ),
        }),
    )


@admin.register(SchoolHoliday)
class SchoolHolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "start", "end", "region", "active")
    list_filter = ("region", "active")
    list_editable = ("active",)
    ordering = ("start",)

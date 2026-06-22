"""Verwaltung des Hofladens: Produkte/Gruppen (CRUD), Einstellungen,
Rechnungsübersicht mit Zahlungs-Bestätigung und Excel-Export."""
from __future__ import annotations

from django.contrib import admin, messages
from django.http import HttpResponse

from . import services as svc
from .models import Invoice, LineItem, Product, ProductGroup, ShopConfig


@admin.register(ShopConfig)
class ShopConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Genossenschaft (für die Rechnung)", {
            "fields": ("coop_name", "coop_address", "tax_number"),
            "description": "Diese Angaben erscheinen als Absender auf jeder "
                           "Hofladen-Rechnung (§14 UStG). Einmalig pflegen."}),
        ("Zahlung", {
            "fields": ("iban", "bic", "invoice_prefix"),
            "description": "IBAN/BIC, auf die Mitglieder überweisen. Das Präfix "
                           "bildet die Rechnungsnummer (z. B. HL-2026-04-001)."}),
    )

    def has_add_permission(self, request):
        return not ShopConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "emoji", "sort_order", "active")
    list_editable = ("emoji", "sort_order", "active")
    fieldsets = ((None, {
        "fields": ("name", "emoji", "sort_order", "active"),
        "description": "Kategorie/Kachel im Hofladen (z. B. Obst & Gemüse, "
                       "Dienstleistungen). „Sortierung“ bestimmt die Reihenfolge.",
    }),)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "kind", "price", "unit", "vat_rate",
                    "needs_date", "active")
    list_filter = ("group", "kind", "active", "vat_rate")
    list_editable = ("price", "active")
    search_fields = ("name",)
    fieldsets = (
        (None, {
            "fields": ("group", "name", "description", "active", "sort_order"),
            "description": "Ein Artikel ODER eine Dienstleistung im Hofladen."}),
        ("Preis & Steuer", {
            "fields": ("price", "unit", "vat_rate"),
            "description": "Preis ist <b>brutto</b>; Netto/Steuer rechnet die App "
                           "aus dem MwSt-Satz. Der Preis wird beim Kauf als Snapshot "
                           "gespeichert – spätere Änderungen wirken nicht rückwirkend."}),
        ("Art", {
            "fields": ("kind", "needs_date"),
            "description": "„Dienstleistung“ (z. B. Sauna) wird wie eine Ware "
                           "abgerechnet. „Termin nötig“ = Mitglied gibt beim Kauf "
                           "ein Datum an."}),
    )


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 0
    fields = ("name", "quantity", "unit", "unit_price", "vat_rate",
              "service_date", "gross")
    readonly_fields = ("gross",)
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.action(description="Zahlungseingang bestätigen (archivieren)")
def confirm_payment(modeladmin, request, queryset):
    n = 0
    for inv in queryset:
        svc.confirm_invoice(inv)
        n += 1
    messages.success(request, f"{n} Rechnung(en) bestätigt und archiviert.")


@admin.action(description="Excel-Export der ausgewählten Rechnungen")
def export_excel(modeladmin, request, queryset):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rechnungen"
    ws.append(["Nummer", "Mitglied", "Jahr", "Monat", "Status",
               "Netto", "MwSt", "Brutto", "IBAN-Mitglied"])
    for inv in queryset.select_related("member"):
        ws.append([
            inv.number, inv.member.display_name, inv.year, inv.month,
            inv.get_status_display(),
            float(inv.total_net), float(inv.total_vat), float(inv.total_gross),
            inv.member.iban,
        ])
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = "attachment; filename=rechnungen.xlsx"
    wb.save(resp)
    return resp


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "member", "year", "month", "status",
                    "total_gross", "created_at")
    list_filter = ("status", "year", "month")
    search_fields = ("number", "member__display_name")
    date_hierarchy = "created_at"
    inlines = [LineItemInline]
    actions = [confirm_payment, export_excel]
    readonly_fields = ("number", "year", "month", "created_at", "paid_reported_at",
                       "confirmed_at", "recipient_name", "recipient_address",
                       "coop_name", "coop_address", "tax_number", "iban", "bic",
                       "total_net", "total_vat", "total_gross")
    fieldsets = (
        (None, {
            "fields": ("number", "member", "year", "month", "status"),
            "description": (
                "Sammelrechnungen entstehen <b>automatisch monatlich</b> "
                "(Kommando <code>generate_monthly_invoices</code>, per Cron). "
                "Ablauf: <b>offen</b> → das Mitglied meldet „bezahlt“ → hier mit "
                "der Aktion <b>„Zahlungseingang bestätigen“</b> bestätigen "
                "(→ archiviert). Mit der Aktion <b>„Excel-Export“</b> lassen sich "
                "ausgewählte Rechnungen exportieren."),
        }),
        ("Beträge", {"fields": ("total_net", "total_vat", "total_gross")}),
        ("Zeitstempel", {"fields": ("created_at", "paid_reported_at", "confirmed_at")}),
        ("Rechnungs-Snapshots (§14 UStG)", {
            "classes": ("collapse",),
            "fields": ("recipient_name", "recipient_address", "coop_name",
                       "coop_address", "tax_number", "iban", "bic")}),
    )

    @admin.display(description="Brutto")
    def total_gross(self, obj):
        return f"{obj.total_gross} €"


@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ("name", "member", "quantity", "unit", "unit_price",
                    "gross", "invoice", "created_at")
    list_filter = ("invoice__status", "vat_rate")
    search_fields = ("name", "member__display_name")
    date_hierarchy = "created_at"

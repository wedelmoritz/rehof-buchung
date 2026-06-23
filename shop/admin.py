"""Verwaltung des Hofladens: Produkte/Gruppen (CRUD), Einstellungen,
Rechnungsübersicht mit Zahlungs-Bestätigung und Excel-Export."""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages

from . import reconcile, services as svc
from .models import (
    BankImport, BankTransaction, Invoice, LineItem, Product, ProductGroup,
    Purchase, ShopConfig)

WEEKDAYS = [("0", "Montag"), ("1", "Dienstag"), ("2", "Mittwoch"),
            ("3", "Donnerstag"), ("4", "Freitag"), ("5", "Samstag"),
            ("6", "Sonntag")]


class ProductAdminForm(forms.ModelForm):
    """Wochentage als Checkboxen statt als roher Komma-String."""
    unavailable_weekdays = forms.MultipleChoiceField(
        choices=WEEKDAYS, required=False, widget=forms.CheckboxSelectMultiple,
        label="Nicht möglich an Wochentagen",
        help_text="Geprüft wird der Abreisetag der Buchung – z. B. Endreinigung "
                  "am Wochenende nicht möglich.")

    class Meta:
        model = Product
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        raw = getattr(self.instance, "unavailable_weekdays", "") or ""
        self.initial["unavailable_weekdays"] = [x for x in raw.split(",") if x.strip()]

    def clean_unavailable_weekdays(self):
        return ",".join(self.cleaned_data["unavailable_weekdays"])


@admin.register(ShopConfig)
class ShopConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Genossenschaft (für die Rechnung)", {
            "fields": ("coop_name", "coop_address", "tax_number"),
            "description": "Diese Angaben erscheinen als Absender auf jeder "
                           "Hofladen-Rechnung (§14 UStG). Einmalig pflegen."}),
        ("Zahlung", {
            "fields": ("iban", "bic", "invoice_prefix", "payment_term_days"),
            "description": "IBAN/BIC, auf die Mitglieder überweisen. Das Präfix "
                           "bildet die Rechnungsnummer (z. B. HL-2026-04-001). Das "
                           "Zahlungsziel bestimmt, ab wann eine Rechnung als "
                           "überfällig gilt (für die Zahlungserinnerung)."}),
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
    form = ProductAdminForm
    list_display = ("name", "group", "kind", "price", "unit", "vat_rate",
                    "needs_date", "book_with_stay", "active")
    list_filter = ("group", "kind", "active", "book_with_stay", "vat_rate")
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
        ("Beim Buchen anbieten (z. B. Endreinigung)", {
            "fields": ("book_with_stay", "counts_as_cleaning", "unavailable_weekdays"),
            "description": "Ist „Beim Buchen anbieten“ aktiv, erscheint die "
                           "Dienstleistung im Bestätigungsschritt der Unterkunfts-"
                           "Buchung und kann gleich mitgebucht werden. „Zählt als "
                           "Endreinigung“ markiert die betroffenen Buchungen in der "
                           "Reinigungsliste fürs Team. Über die Wochentage lässt sich "
                           "steuern, an welchen Abreisetagen die Leistung NICHT "
                           "gewährleistet werden kann."}),
    )


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 0
    # Positionen sind nach der Bestätigung des Einkaufs fix – alles schreibgeschützt.
    fields = ("name", "quantity", "unit", "unit_price", "vat_rate",
              "service_date", "gross")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    """Bestätigte Einkäufe (Checkout). Read-only – ein Einkauf ist nach der
    Bestätigung durch das Mitglied nicht mehr änderbar."""
    list_display = ("id", "member", "confirmed_at", "gross_display", "invoiced")
    list_filter = ("confirmed_at",)
    search_fields = ("member__display_name",)
    date_hierarchy = "confirmed_at"
    inlines = [LineItemInline]
    readonly_fields = ("member", "confirmed_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Betrag")
    def gross_display(self, obj):
        return f"{obj.gross} €"

    @admin.display(boolean=True, description="abgerechnet")
    def invoiced(self, obj):
        return obj.items.filter(invoice__isnull=False).exists()


@admin.action(description="Zahlungseingang bestätigen (archivieren)")
def confirm_payment(modeladmin, request, queryset):
    n = 0
    for inv in queryset:
        svc.confirm_invoice(inv)
        n += 1
    messages.success(request, f"{n} Rechnung(en) bestätigt und archiviert.")


@admin.action(description="Excel-Export der ausgewählten Rechnungen")
def export_excel(modeladmin, request, queryset):
    from booking import exports
    return exports.xlsx_response(
        "rechnungen", "Rechnungen", svc.INVOICE_COLUMNS,
        svc.invoice_export_rows(queryset))


@admin.action(description="CSV-Export der ausgewählten Rechnungen")
def export_csv(modeladmin, request, queryset):
    from booking import exports
    return exports.csv_response(
        "rechnungen", svc.INVOICE_COLUMNS, svc.invoice_export_rows(queryset))


@admin.action(description="Zahlungserinnerung senden (nur offene/überfällige)")
def send_reminders(modeladmin, request, queryset):
    n = sum(1 for inv in queryset if svc.send_payment_reminder(inv))
    messages.success(request, f"{n} Zahlungserinnerung(en) verschickt.")


class OverdueFilter(admin.SimpleListFilter):
    """Filter „überfällig“: offene Rechnungen mit überschrittenem Zahlungsziel."""
    title = "Fälligkeit"
    parameter_name = "overdue"

    def lookups(self, request, model_admin):
        return [("1", "überfällig (offen)"), ("open", "offen")]

    def queryset(self, request, queryset):
        from datetime import date as _date
        if self.value() == "1":
            return queryset.filter(status=Invoice.OPEN, due_date__lt=_date.today())
        if self.value() == "open":
            return queryset.filter(status=Invoice.OPEN)
        return queryset


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "recipient", "year", "month", "status",
                    "total_gross", "due_date", "overdue_display", "reminded_at")
    list_filter = (OverdueFilter, "status", "year", "month")
    search_fields = ("number", "member__display_name", "guest__name")
    date_hierarchy = "created_at"
    inlines = [LineItemInline]
    actions = [confirm_payment, send_reminders, export_excel, export_csv]
    readonly_fields = ("number", "year", "month", "created_at", "due_date",
                       "paid_reported_at", "confirmed_at", "reminded_at",
                       "recipient_name", "recipient_address",
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
                "(→ archiviert). Überfällige offene Rechnungen lassen sich mit "
                "<b>„Zahlungserinnerung senden“</b> anmahnen; Export als "
                "<b>Excel/CSV</b>. Den schnellen Überblick gibt das "
                "<b>Verwaltungs-Dashboard</b>."),
        }),
        ("Beträge", {"fields": ("total_net", "total_vat", "total_gross")}),
        ("Zeitstempel", {"fields": ("created_at", "due_date", "paid_reported_at",
                                    "confirmed_at", "reminded_at")}),
        ("Rechnungs-Snapshots (§14 UStG)", {
            "classes": ("collapse",),
            "fields": ("recipient_name", "recipient_address", "coop_name",
                       "coop_address", "tax_number", "iban", "bic")}),
    )

    @admin.display(description="Empfänger")
    def recipient(self, obj):
        return obj.recipient_label

    @admin.display(description="Brutto")
    def total_gross(self, obj):
        return f"{obj.total_gross} €"

    @admin.display(boolean=True, description="überfällig")
    def overdue_display(self, obj):
        return obj.is_overdue


@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ("name", "member", "quantity", "unit", "unit_price",
                    "gross", "invoice", "created_at")
    list_filter = ("invoice__status", "vat_rate")
    search_fields = ("name", "member__display_name")
    date_hierarchy = "created_at"


class MatchedFilter(admin.SimpleListFilter):
    """Filter: zugeordnet / nicht zugeordnet."""
    title = "Zuordnung"
    parameter_name = "matched"

    def lookups(self, request, model_admin):
        return [("yes", "zugeordnet"), ("no", "nicht zugeordnet")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(matched_invoice__isnull=False)
        if self.value() == "no":
            return queryset.filter(matched_invoice__isnull=True, amount__gt=0)
        return queryset


@admin.action(description="Automatisch abgleichen (offene zuordnen)")
def reconcile_action(modeladmin, request, queryset):
    n = reconcile.reconcile_unmatched(queryset)
    messages.success(request, f"{n} Zahlung(en) automatisch verbucht.")


@admin.action(description="Verknüpfte Rechnung als bezahlt verbuchen")
def book_linked(modeladmin, request, queryset):
    n = 0
    for txn in queryset:
        if txn.matched_invoice and not txn.matched_at:
            reconcile.book_payment(txn, txn.matched_invoice, note="manuell zugeordnet")
            n += 1
    messages.success(request, f"{n} Zahlung(en) verbucht.")


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    """Zahlungseingänge aus Kontoauszügen. Eindeutige (Betrag + Rechnungsnummer
    im Verwendungszweck) werden automatisch verbucht; den Rest hier von Hand
    einer Rechnung zuordnen (Feld „Zugeordnete Rechnung“) und „verbuchen“."""
    list_display = ("booked_on", "amount", "counterparty_name", "short_purpose",
                    "matched_invoice", "matched_at")
    list_filter = (MatchedFilter, "booked_on")
    search_fields = ("purpose", "counterparty_name", "counterparty_iban",
                     "matched_invoice__number")
    date_hierarchy = "booked_on"
    autocomplete_fields = ("matched_invoice",)
    actions = [reconcile_action, book_linked]
    readonly_fields = ("batch", "booked_on", "amount", "purpose",
                       "counterparty_name", "counterparty_iban", "fingerprint",
                       "raw", "imported_at", "matched_at", "note")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Verwendungszweck")
    def short_purpose(self, obj):
        return (obj.purpose[:60] + "…") if len(obj.purpose) > 60 else obj.purpose


@admin.register(BankImport)
class BankImportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "filename", "fmt", "n_total", "n_imported",
                    "n_matched")
    readonly_fields = ("created_at", "filename", "fmt", "n_total", "n_imported",
                       "n_matched")

    def has_add_permission(self, request):
        return False

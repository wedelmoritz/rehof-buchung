"""Admin – liefert das Mitgliedermanagement und die Verwaltung quasi geschenkt."""
from __future__ import annotations

import random
from datetime import date

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .models import (
    Allocation, Beds24Import, Beds24ImportRow, BookingPeriod, BookingPolicy,
    EquivalenceClass, ExternalBooking,
    ExternalConfig, FairnessSimConfig, Guest, LotteryRun, Member, Membership,
    NightTransfer, DayPoolEntry,
    Notification, OpsConfig, OutboxEmail, PendingUser, Quarter, QuarterPrice,
    SchoolHoliday,
    SeasonRule, Share, SwapRequest, TerminalConfig, UpcomingAllocation,
    WaitlistEntry, Wish,
)
from .services import (confirm_lottery, ensure_seed_commit, rollback_lottery,
                       run_period_lottery)

# --- Versionierte Historie + Wiederherstellen (ADR 0070) -------------------- #
# Die Identitäts-Daten Benutzer/Mitglied/Anteil/Tage-Anteil werden versioniert,
# damit starke Backend-Aktionen (Löschen, Tage ändern, Anteil wechseln) im Backend
# rückgängig gemacht werden können. EXPLIZIT registriert (genau EINMAL je Modell),
# damit der follow-Graph stimmt: ein Benutzer-Stand snapshottet auch sein Mitglied
# und dessen Tage-Anteile, ein Anteil-Stand seine Tage-Anteile. Reihenfolge egal,
# weil VersionAdmin bereits registrierte Modelle respektiert (is_registered).
import reversion as _reversion

for _model, _follow in (
    (Share, ()),
    (Member, ("shares",)),       # Mitglied-Stand umfasst seine Tage-Anteile
    (Membership, ("shares",)),   # Anteil-Stand umfasst seine Tage-Anteile
    (User, ("member",)),         # Benutzer-Stand umfasst sein Mitglieds-Profil
):
    if not _reversion.is_registered(_model):
        _reversion.register(_model, follow=_follow)

from reversion.admin import VersionAdmin


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
    readonly_fields = ("anteile_uebersicht",)
    fieldsets = (
        ("Buchungs-Profil", {
            "fields": ("display_name", "factor", "is_external", "anteile_uebersicht"),
            "description": (
                "<b>Mitglied = Buchungs-Profil dieses Benutzers (1:1).</b> Beim "
                "Speichern wird – wenn noch keiner besteht – <b>automatisch ein "
                "voller Mitglieds-Anteil (50 Tage) angelegt</b> und der Person "
                "zugeordnet; sie kann dann sofort buchen. Ein <b>Tandem</b> (geteilter "
                "Anteil) entsteht, indem man unter „Mitglieds-Anteile“ am selben "
                "Anteil weitere Nutzer ergänzt. Der Ausgleichsfaktor (Karma) wird von "
                "der Losung automatisch gepflegt – im Normalfall nicht ändern."),
        }),
        ("Rechnungsdaten (Hofladen)", {
            "fields": ("legal_name", "street", "zip_code", "city", "iban"),
        }),
        ("Hofladen-Terminal vor Ort", {
            "fields": ("terminal_enabled",),
            "description": (
                "Standardmäßig an: die Person darf am Vor-Ort-Terminal (PIN) auf die "
                "Monatsrechnung einkaufen. Die <b>PIN</b> setzt die Person selbst im "
                "Profil; ohne PIN erscheint sie nicht am Terminal. Die Person kann das "
                "auch selbst im Profil ausschalten."),
        }),
    )

    @admin.display(description="Mitglieds-Anteil(e)")
    def anteile_uebersicht(self, obj):
        """Zeigt direkt im Benutzer-Formular, welche(n) Mitglieds-Anteil(e) die
        Person hält (mit Tage-Anteil + Link) – so stehen Mitglied und Anteil
        zueinander. Bei einem neuen/anteillosen Mitglied der Hinweis aufs
        automatische Anlegen."""
        if obj is None or obj.pk is None:
            return mark_safe("<i>— wird beim Speichern automatisch als voller "
                             "Anteil (50 Tage) angelegt.</i>")
        if obj.is_external:
            return mark_safe("<i>Hofladen-Gast – kein Buchungs-Anteil.</i>")
        shares = list(obj.shares.select_related("membership"))
        if not shares:
            return mark_safe("<i>— noch keiner; wird beim Speichern automatisch "
                             "angelegt.</i>")
        rows = format_html_join(
            mark_safe("<br>"),
            '<a href="{}">{}</a> – {} Tage (davon {} über die Wunschliste){}',
            ((reverse("admin:booking_membership_change", args=[s.membership_id]),
              str(s.membership), s.night_budget, s.wish_night_budget,
              " · Tandem" if s.membership.is_tandem else "")
             for s in shares))
        edit_url = reverse("admin:booking_member_change", args=[obj.pk])
        return format_html(
            "{}<br><span style=\"color:#6b6259\">Gesamt-Tagebudget: "
            "{} Tage/Jahr.</span> &nbsp;<a href=\"{}\"><b>Anteile bearbeiten / "
            "Tandem aufteilen →</b></a>",
            rows, obj.annual_night_budget, edit_url)


admin.site.unregister(User)


from django import forms


class AdminUserInviteForm(forms.ModelForm):
    """Benutzer anlegen **ohne** Passwort: die E-Mail ist Pflicht, denn der neue
    Nutzer setzt sein Passwort selbst über einen Einladungs-Link (Admins vergeben
    kein Passwort)."""
    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            raise forms.ValidationError(
                "E-Mail ist nötig – darüber bekommt die Person den Link zum "
                "Passwort-Setzen.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Mit dieser E-Mail gibt es bereits ein Konto.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()   # der Nutzer vergibt es selbst per Einladung
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(VersionAdmin, DjangoUserAdmin):
    """Ein Benutzer = eine Person mit Login UND Buchungs-/Rechnungsprofil.
    Tage-Anteile (welche eG-Anteile die Person hält) werden beim jeweiligen
    „Mitglieds-Anteil“ zugeordnet. **Anlegen ohne Passwort:** beim Speichern geht
    automatisch eine „Passwort setzen"-Einladung an die E-Mail des Kontos."""
    inlines = [MemberProfileInline]
    actions = ["send_invite_selected", "anonymize_selected"]
    # E-Mail in der Liste zeigen; beim Anlegen abfragen (Pflicht, ohne Passwort).
    list_display = ("username", "email", "first_name", "last_name", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    add_form = AdminUserInviteForm
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "description": "Kein Passwort nötig – der neue Nutzer bekommt per "
                           "E-Mail einen Link, um es selbst zu setzen.",
            "fields": ("username", "email"),
        }),
    )

    def save_related(self, request, form, formsets, change):
        """Nachdem das Mitglieds-Profil (Inline) gespeichert ist: hat ein
        buchendes Mitglied noch keinen Mitglieds-Anteil, automatisch einen vollen
        anlegen – so ist „Mitglied" immer mit einem „Mitglieds-Anteil" verknüpft
        (Tandems entstehen durch Aufteilen, ADR 0068)."""
        super().save_related(request, form, formsets, change)
        from .services import ensure_personal_membership
        member = Member.objects.filter(user=form.instance).first()
        share = ensure_personal_membership(member)
        if share:
            self.message_user(
                request,
                f"Voller Mitglieds-Anteil ({share.night_budget} Tage) automatisch "
                f"angelegt und {member.display_name} zugeordnet – die Person kann "
                f"jetzt buchen. Für ein Tandem den Anteil unter „Mitglieds-Anteile“ "
                f"aufteilen; die eG-Nummer dort nachtragen.", level=messages.SUCCESS)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            from .services import send_account_invite
            if send_account_invite(obj):
                self.message_user(
                    request,
                    f"Konto angelegt. Einladung zum Passwort-Setzen an "
                    f"{obj.email} gesendet.", level=messages.SUCCESS)
            else:
                self.message_user(
                    request,
                    "Konto angelegt, aber ohne E-Mail – es konnte keine Einladung "
                    "verschickt werden. E-Mail nachtragen und Einladung erneut "
                    "senden.", level=messages.WARNING)

    @admin.action(description="Einladung zum Passwort-Setzen (erneut) senden")
    def send_invite_selected(self, request, queryset):
        from .services import send_account_invite
        n = sum(1 for user in queryset if send_account_invite(user))
        self.message_user(
            request,
            f"{n} Einladung(en) gesendet (Konten ohne E-Mail wurden übersprungen).",
            level=messages.SUCCESS)

    @admin.action(description="Mitglied anonymisieren (Recht auf Löschung, DSGVO)")
    def anonymize_selected(self, request, queryset):
        from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
        from django.template.response import TemplateResponse
        from .services import anonymize_member
        if request.POST.get("confirm"):
            n = 0
            for user in queryset:
                member = getattr(user, "member", None)
                if member is not None:
                    anonymize_member(member)
                    n += 1
            self.message_user(
                request,
                f"{n} Mitglied(er) anonymisiert. Rechnungen bleiben (10 Jahre) "
                "erhalten, die Login-Konten sind deaktiviert.",
                level=messages.SUCCESS)
            return None
        # Anzahl erhaltener Rechnungen je Nutzer für die Rückfrage anzeigen.
        from shop.models import Invoice
        users = list(queryset)
        for u in users:
            m = getattr(u, "member", None)
            u.invoice_count = Invoice.objects.filter(member=m).count() if m else 0
        return TemplateResponse(request, "admin/anonymize_confirm.html", {
            "title": "Mitglied(er) wirklich anonymisieren?",
            "intro": "Die personenbezogenen Daten der folgenden Konten werden "
            "unwiderruflich entfernt (Profil, Begleit-/Notiztexte, "
            "Benachrichtigungen, Wünsche) und das Login deaktiviert. Die "
            "gesetzlich aufzubewahrenden Rechnungen bleiben mit ihren "
            "Snapshot-Daten erhalten:",
            "button_label": "Ja, unwiderruflich anonymisieren",
            "users": users,
            "checkbox_name": ACTION_CHECKBOX_NAME,
            "opts": self.model._meta,
        })


@admin.register(PendingUser)
class PendingUserAdmin(admin.ModelAdmin):
    """Geführtes Onboarding (ADR 0056): zeigt nur Konten OHNE Mitglieds-Anteil und
    ordnet sie mit wenigen Klicks zu – als Mitglied (Anteil), als Hofladen-/
    Terminal-Gast, oder (unbekannt) deaktivieren/löschen. Eigene Seite statt der
    Standard-Liste."""
    list_display = ("username", "email")
    search_fields = ("username", "email", "first_name", "last_name")

    def has_add_permission(self, request):
        return False  # neue Konten entstehen durch Selbstregistrierung/Einladung

    def changelist_view(self, request, extra_context=None):
        from django.template.response import TemplateResponse
        from . import services as svc
        if request.method == "POST":
            return self._handle(request, svc)
        pending = list(svc.users_without_membership().select_related("member"))
        for u in pending:
            u.suggested_name = (u.get_full_name() or u.username).strip()
        # Anteile mit „noch frei" anreichern (für die Tandem-Wahl nachvollziehbar).
        memberships = list(Membership.objects.order_by("label", "eg_number")
                           .prefetch_related("shares"))
        for ms in memberships:
            ms.free_nights = ms.annual_night_budget - ms.allocated_budget
        ctx = {
            **self.admin_site.each_context(request),
            "title": "Neue Benutzer zuordnen",
            "opts": self.model._meta,
            "pending": pending,
            "memberships": memberships,
            "default_budget": (db := Membership.suggest_budget()),
            "default_wish": min(25, db),
        }
        return TemplateResponse(request, "admin/onboarding.html", ctx)

    def _handle(self, request, svc):
        action = request.POST.get("action")
        user = User.objects.filter(pk=request.POST.get("user_id")).first()
        if not user:
            self.message_user(request, "Benutzer nicht gefunden.", level=messages.ERROR)
            return redirect(request.path)
        name = (user.get_full_name() or user.username).strip()
        display_name = (request.POST.get("display_name") or "").strip() or user.username
        try:
            if action == "member":
                mid = request.POST.get("membership") or ""
                membership_id = mid if mid and mid != "new" else None
                svc.onboard_as_member(
                    user, display_name=display_name,
                    night_budget=request.POST.get("night_budget") or 0,
                    wish_night_budget=request.POST.get("wish_night_budget") or 0,
                    membership_id=membership_id,
                    new_label=(request.POST.get("new_label") or "").strip())
                self.message_user(
                    request, f"{name} wurde als Mitglied zugeordnet und kann jetzt "
                    "buchen.", level=messages.SUCCESS)
            elif action == "terminal":
                svc.onboard_as_terminal(user, display_name=display_name)
                self.message_user(
                    request, f"{name} ist jetzt Hofladen-/Terminal-Gast. Die PIN "
                    "setzt die Person selbst im Profil.", level=messages.SUCCESS)
            elif action == "deactivate":
                svc.deactivate_account(user)
                self.message_user(request, f"Konto {name} deaktiviert (Login "
                                  "gesperrt; reversibel im Benutzer-Formular).",
                                  level=messages.SUCCESS)
            elif action == "delete":
                user.delete()
                self.message_user(request, f"Konto {name} gelöscht.",
                                  level=messages.SUCCESS)
            else:
                self.message_user(request, "Unbekannte Aktion.", level=messages.ERROR)
        except Membership.DoesNotExist:
            self.message_user(request, "Der gewählte Anteil existiert nicht (mehr).",
                              level=messages.ERROR)
        except (ValueError, TypeError) as e:
            self.message_user(request, f"Eingabe ungültig: {e}", level=messages.ERROR)
        return redirect(request.path)


class ShareMemberInline(admin.TabularInline):
    """Die Mitglieds-Anteile DIESES Mitglieds – hier lässt sich der Anteil eines
    Mitglieds direkt bearbeiten: Anteil wählen/wechseln, Tage-Anteil ändern oder das
    Mitglied über „Löschen?“ aus EINEM Anteil entfernen (entfernt nur die Zuordnung,
    NICHT den Anteil oder das Mitglied)."""
    model = Share
    fk_name = "member"
    extra = 0
    autocomplete_fields = ("membership",)
    fields = ("membership", "night_budget", "wish_night_budget")
    verbose_name = "Mitglieds-Anteil dieses Mitglieds"
    verbose_name_plural = ("Mitglieds-Anteile dieses Mitglieds  —  „Löschen?“ "
                           "entfernt NUR die Zuordnung zu DIESEM Anteil (Anteil & "
                           "Mitglied bleiben)")


@admin.register(Member)
class MemberAdmin(VersionAdmin):
    """Das Mitglied (Buchungs-Profil eines Benutzers) MIT seinen Mitglieds-Anteilen.
    Hier ordnest du dem Mitglied einen vollen oder Tandem-Teil-Anteil zu, änderst den
    Tage-Anteil oder entfernst eine Zuordnung. Profil/Login bearbeitest du am
    Benutzer; Anlegen läuft übers geführte Onboarding. Versionen siehe „GESCHICHTE“."""
    list_display = ("display_name", "user_link", "anteile_kurz", "budget_kurz",
                    "is_external")
    list_filter = ("is_external",)
    search_fields = ("display_name", "user__username", "user__email")
    readonly_fields = ("user_link", "factor")
    fields = ("user_link", "display_name", "is_external", "factor")
    inlines = [ShareMemberInline]
    list_select_related = ("user",)

    def has_add_permission(self, request):
        return False  # Mitglieder entstehen am Benutzer / im geführten Onboarding

    def has_delete_permission(self, request, obj=None):
        # Kein hartes Löschen (würde Buchungen mitlöschen) – zum „Recht auf Löschung“
        # die Aktion „Mitglied anonymisieren“ am Benutzer nutzen.
        return False

    @admin.display(description="Benutzer (Login)")
    def user_link(self, obj):
        if not obj or not obj.user_id:
            return "—"
        url = reverse("admin:auth_user_change", args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_username())

    @admin.display(description="Anteile")
    def anteile_kurz(self, obj):
        shares = list(obj.shares.select_related("membership"))
        if not shares:
            return "—"
        return ", ".join(f"{s.membership} ({s.night_budget} T"
                         f"{', Tandem' if s.membership.is_tandem else ''})"
                         for s in shares)

    @admin.display(description="Tage gesamt")
    def budget_kurz(self, obj):
        return f"{obj.annual_night_budget} (davon {obj.wish_night_budget} Wunsch)"


class ShareInline(admin.TabularInline):
    """Die diesem Anteil zugeordneten Nutzer mit ihrem festen Tage-Anteil.
    Voll-Mitglied = ein Nutzer (voller Anteil); Teil/Tandem = mehrere Nutzer,
    deren Tage-Anteile zusammen das Gesamtbudget ergeben. Leer gelassene Anteile
    (0) werden beim Speichern gleichmäßig (abgerundet) vorgeschlagen."""
    model = Share
    extra = 1
    autocomplete_fields = ("member",)
    fields = ("member", "night_budget", "wish_night_budget")
    verbose_name = "Mitglied mit Tage-Anteil"
    verbose_name_plural = ("Mitglieder & Tage-Anteil  —  EIN Mitglied mit 50 = "
                           "Voll-Mitglied; MEHRERE, deren Tage zusammen 50 ergeben "
                           "(z. B. 25 + 25) = Tandem")


@admin.register(Membership)
class MembershipAdmin(VersionAdmin):
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
                "Jahres-Tagebudget (Standard <b>50 Tage</b>). Unten ordnest du die "
                "<b>Mitglieder</b> (Personen mit Buchungs-Profil) mit ihrem festen "
                "Tage-Anteil zu:<br>"
                "&nbsp;&bull; <b>Voll-Mitglied</b> = <b>ein</b> Mitglied bekommt die "
                "<b>vollen 50 Tage</b>.<br>"
                "&nbsp;&bull; <b>Tandem (Teil-Anteil)</b> = <b>mehrere</b> Mitglieder "
                "teilen den Anteil, ihre Tage-Anteile ergeben zusammen 50 "
                "(z. B. 25&nbsp;+&nbsp;25). Die Spalte „vergeben / frei“ zeigt, wie "
                "viele Tage noch frei sind.<br>"
                "Ein Mitglied kann auch <b>mehreren</b> Anteilen angehören (mehrere "
                "Tandems) – sein Budget ist dann die <b>Summe</b> der Tage-Anteile. "
                "Bei Anlage mitten im Jahr ist das Budget anteilig vorgeschlagen; "
                "leer gelassene Tage-Anteile (0) werden beim Speichern gleichmäßig "
                "abgerundet aufgeteilt."),
        }),
    )

    def get_queryset(self, request):
        # N+1 vermeiden: Anteile je Zeile vorladen + Anzahl annotieren, statt pro
        # Zeile allocated_budget (Summe) und is_tandem (count) einzeln abzufragen.
        from django.db.models import Count
        return (super().get_queryset(request)
                .prefetch_related("shares").annotate(_n_shares=Count("shares")))

    @admin.display(description="vergeben / frei")
    def allocated_display(self, obj):
        used = sum(s.night_budget for s in obj.shares.all())
        free = obj.annual_night_budget - used
        if free > 0:
            return f"{used}/{obj.annual_night_budget} · {free} frei (für Tandem-Partner)"
        if free < 0:
            return f"{used}/{obj.annual_night_budget} · {-free} zu viel (überbelegt!)"
        return f"{used}/{obj.annual_night_budget} · voll vergeben"

    @admin.display(boolean=True, description="Tandem")
    def is_tandem_display(self, obj):
        return obj._n_shares > 1

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
    # Seed + Commit werden vom Commit-Reveal verwaltet (ADR 0062) und dürfen NICHT
    # von Hand geändert werden – sonst passte der veröffentlichte Hash nicht mehr.
    readonly_fields = ("seed", "seed_commit", "seed_committed_at")
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
                       "start", "end"),
            "description": (
                "Zeitlicher Ablauf eines Buchungsjahres: <b>Wünsche ab/bis</b> = "
                "Anmeldefenster für die Wunschliste; <b>Losung am</b> = Termin der "
                "automatischen Auslosung; <b>buchbar ab/bis</b> = Zeitraum der "
                "freien Bebuchbarkeit (Ende exklusiv; „buchbar ab“ darf vor dem "
                "1.1. liegen). Übliche Reihenfolge: Wünsche → Losung → buchbar."
            ),
        }),
        ("Verifizierbarkeit (Commit-Reveal, ADR 0062)", {
            "fields": ("seed", "seed_commit", "seed_committed_at"),
            "classes": ("collapse",),
            "description": (
                "Wird automatisch verwaltet: Sobald die Wünsche öffnen, wird der "
                "geheime <b>Seed</b> erzeugt und seine <b>Prüfsumme</b> "
                "veröffentlicht; nach der bestätigten Ziehung ist der Seed "
                "offengelegt. Per <code>manage.py verify_lottery &lt;id&gt;</code> "
                "prüfbar. <b>Nicht von Hand ändern.</b>"
            ),
        }),
    )

    def save_model(self, request, obj, form, change):
        """Sobald eine Periode (im Backend) in „Wünsche offen" oder weiter steht,
        die Seed-Prüfsumme festlegen/veröffentlichen – damit der Seed VOR den
        Einträgen feststeht, auch ohne Cron (Commit-Reveal, ADR 0062)."""
        super().save_model(request, obj, form, change)
        open_rank = BookingPeriod.LIFECYCLE.index(BookingPeriod.WISHES_OPEN)
        if not obj.seed_commit and obj.status_rank >= open_rank:
            ensure_seed_commit(obj)

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
    list_display = ("member", "membership", "period", "priority", "quarter",
                    "start", "end", "submitted")
    list_filter = ("period", "quarter", "submitted")
    search_fields = ("member__display_name", "member__user__username",
                     "quarter__name")
    date_hierarchy = "start"
    autocomplete_fields = ("membership",)
    list_select_related = ("member", "membership", "quarter", "period")


@admin.register(Allocation)
class AllocationAdmin(admin.ModelAdmin):
    """Buchungen/Zuteilungen. <b>Domänenregeln greifen auch hier</b>
    (<code>Allocation.clean</code>): gültiger Zeitraum, Personenzahl im
    Quartiers-Rahmen und <b>keine Überschneidung</b> mit einer anderen Zuteilung
    oder bestätigten externen Buchung im selben Quartier – eine Doppelbuchung
    wird beim Speichern abgewiesen."""
    list_display = ("start", "end", "nights_display", "quarter", "member",
                    "membership", "persons", "source", "via_substitution",
                    "contested")
    list_filter = ("source", "quarter", "contested")
    search_fields = ("member__display_name", "member__user__username",
                     "quarter__name")
    date_hierarchy = "start"
    ordering = ("-start",)
    autocomplete_fields = ("membership",)
    list_select_related = ("quarter", "member", "membership")

    @admin.display(description="Nächte")
    def nights_display(self, obj):
        return obj.nights


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


@admin.register(DayPoolEntry)
class DayPoolEntryAdmin(admin.ModelAdmin):
    list_display = ("year", "kind", "member", "nights", "created_at")
    list_filter = ("year", "kind")
    search_fields = ("member__display_name",)


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
    date_hierarchy = "created_at"
    list_select_related = ("member",)


@admin.register(SwapRequest)
class SwapRequestAdmin(admin.ModelAdmin):
    list_display = ("from_member", "to_member", "from_allocation",
                    "to_allocation", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("from_member__display_name", "to_member__display_name")
    date_hierarchy = "created_at"


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


@admin.register(TerminalConfig)
class TerminalConfigAdmin(admin.ModelAdmin):
    """Hofladen-Terminal vor Ort (Singleton). Das **Token** richtet ein Gerät ein;
    bei Verlust/Diebstahl hier **neu erzeugen** – dann ist das alte sofort ungültig."""
    fieldsets = (
        ("Terminal", {
            "fields": ("enabled", "token", "idle_timeout_seconds", "max_pin_attempts"),
            "description": (
                "Das <b>Token</b> wird einmalig im Terminal-Gerät hinterlegt "
                "(Seite <code>/terminal/</code> → „Einrichten“). Es ist das einzige "
                "Geräte-Gate – sorgfältig behandeln. Bei Verlust unten neu erzeugen. "
                "Das Gerät muss zusätzlich betrieblich gehärtet sein (Kiosk-Modus, "
                "Verschlüsselung) – siehe ADR 0053.")}),
    )
    actions = ["regenerate_token"]

    @admin.action(description="Neues Token erzeugen (altes wird ungültig)")
    def regenerate_token(self, request, queryset):
        cfg = TerminalConfig.get_solo()
        cfg.regenerate()
        self.message_user(
            request, "Neues Geräte-Token erzeugt. Bestehende Terminals müssen neu "
            "eingerichtet werden; das alte Token ist ab sofort ungültig.",
            level=messages.WARNING)

    def has_add_permission(self, request):
        return not TerminalConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = TerminalConfig.get_solo()
        if not obj.token:
            obj.regenerate()
        return redirect(reverse("admin:booking_terminalconfig_change", args=[obj.id]))


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

    def get_queryset(self, request):
        # Große Felder (Mailtext/HTML/Anhang-Blob) NICHT in die Liste laden – sie
        # stehen nicht in list_display; im Detail werden sie bei Bedarf nachgeladen.
        return super().get_queryset(request).defer("body", "html_body", "attachment")

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
